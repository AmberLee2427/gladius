import shutil

import pytest
from astropy.table import Table

from roman_cutouts.config import RunConfig, Selection
from roman_cutouts.inputs import discover, selected, staged
from roman_cutouts.pipeline import run


def test_selection_missing_metadata_and_exclusive_dates():
    summary = {"detector": "SCA02", "filter": "F146", "start_utc": "2026-02-01T00:00:00"}
    assert selected(summary, Selection(detectors=[2], filters=["f146"]))
    assert not selected(summary, Selection(end="2026-02-01"))
    with pytest.raises(ValueError, match="detector"):
        selected({}, Selection(detectors=[2]))
    with pytest.raises(ValueError, match="start"):
        selected({}, Selection(start="2026-01-01"))


def test_archive_selection_staging_and_cleanup(demo, tmp_path, monkeypatch):
    import json
    import sys
    from types import ModuleType

    class FakeMissions:
        dataset_kwds = {"roman": "fileSetName"}

        def __init__(self, mission):
            assert mission == "roman"
            self.downloads = []

        def query_criteria(self, **criteria):
            assert criteria["program"] == 1043
            return Table(
                rows=[("a", "WFI01", "F146", "2026-01-01"), ("b", "WFI02", "F146", "2026-01-01")],
                names=["fileSetName", "detector", "optical_element", "exposure_start_time"],
            )

        def get_unique_product_list(self, observations):
            assert list(observations["fileSetName"]) == ["a"]
            return Table(rows=[("demo0_cal.asdf",)], names=["filename"])

        def filter_products(self, products, **filters):
            assert filters == {"file_suffix": "_cal"}
            return products

        def download_products(self, products, download_dir):
            assert len(products) == 1
            path = demo.parent / "images" / str(products[0]["filename"])
            target = type(path)(download_dir) / path.name
            shutil.copyfile(path, target)
            self.downloads.append(target)
            return Table(rows=[(str(target), "COMPLETE")], names=["Local Path", "Status"])

    module = ModuleType("astroquery.mast")
    instance = FakeMissions("roman")
    module.MastMissions = lambda **kwargs: instance
    parent = ModuleType("astroquery")
    parent.mast = module
    monkeypatch.setitem(sys.modules, "astroquery", parent)
    monkeypatch.setitem(sys.modules, "astroquery.mast", module)
    monkeypatch.delenv("MAST_API_TOKEN", raising=False)
    config = RunConfig.model_validate(
        {
            "targets": [{"id": "e", "x": 48, "y": 48}],
            "inputs": {"mode": "mast", "mast_criteria": {"program": 1043}},
            "selection": {"detectors": [1]},
            "extraction": {"size": 10},
            "storage": {"output_directory": str(tmp_path / "out")},
        }
    )
    manifest = run(config, progress=lambda _: None)
    assert json.loads(manifest.read_text())["status"] == "complete"
    assert len(instance.downloads) == 1
    assert not instance.downloads[0].exists()
    # A response hitting the query limit is never treated as a complete inventory.
    config = config.model_copy(
        update={"inputs": config.inputs.model_copy(update={"query_limit": 2})}
    )
    with pytest.raises(ValueError, match="truncated"):
        discover(config)


def test_archive_download_failure_and_context_cleanup(tmp_path):
    class Broken:
        def download_products(self, products, download_dir):
            (tmp_path / "temporary_path.txt").write_text(download_dir)
            return Table(rows=[("", "ERROR")], names=["Local Path", "Status"])

    product = Table(rows=[("file.asdf",)], names=["filename"])[0]
    with pytest.raises(RuntimeError, match="exactly one"):
        with staged(product, Broken(), tmp_path):
            pytest.fail("Failed archive downloads must never yield a parent")
    from pathlib import Path

    assert not Path((tmp_path / "temporary_path.txt").read_text()).exists()


def test_automatic_mast_queries_and_overrides():
    from roman_cutouts.inputs import mast_queries

    config = RunConfig(
        targets=[{"id": "a", "ra": 359.99, "dec": -29},
                 {"id": "b", "ra": 359.99, "dec": -29},
                 {"id": "c", "ra": 0.01, "dec": -29}],
        inputs={"mode": "mast"},
        selection={"start": "2026-01-01", "end": "2026-02-01",
                   "detectors": [1], "filters": ["f146"]},
    )
    queries = mast_queries(config)
    assert len(queries) == 2
    assert queries[0] == {
        "productLevel": "2", "coordinates": "359.99 -29.0", "radius": "6.0 arcmin",
        "detector": ["WFI01", "SCA01"], "optical_element": ["F146"],
        "exposure_start_time": "2026-01-01T00:00:00.000..2026-02-01T00:00:00.000",
    }
    override = config.model_dump()
    override["inputs"]["mast_criteria"] = {"coordinates": "12 34", "program": 1043}
    assert len(mast_queries(RunConfig.model_validate(override))) == 1
    assert mast_queries(RunConfig.model_validate(override))[0]["coordinates"] == "12 34"
    with pytest.raises(ValueError, match="Pixel-only"):
        RunConfig(targets=[{"id": "p", "x": 1, "y": 2}], inputs={"mode": "mast"})
    with pytest.raises(ValueError, match="managed query"):
        RunConfig(targets=config.targets, inputs={"mode": "mast", "mast_criteria": {"offset": 1}})


def test_overlapping_mast_queries_deduplicate_before_download(monkeypatch):
    import sys
    from types import ModuleType

    class Missions:
        dataset_kwds = {"roman": "fileSetName"}
        queries = []

        def query_criteria(self, **criteria):
            self.queries.append(criteria)
            return Table(rows=[("same", "WFI01", "F146", "2026-01-01")],
                         names=["fileSetName", "detector", "optical_element", "exposure_start_time"])

        def get_unique_product_list(self, observations):
            assert len(observations) == 1
            return Table(rows=[("parent_cal.asdf",)], names=["filename"])

        def filter_products(self, products, **kwargs):
            return products

    instance = Missions()
    module = ModuleType("astroquery.mast")
    module.MastMissions = lambda **kwargs: instance
    monkeypatch.setitem(sys.modules, "astroquery.mast", module)
    monkeypatch.delenv("MAST_API_TOKEN", raising=False)
    config = RunConfig(targets=[{"id": "a", "ra": 270, "dec": -29},
                                {"id": "b", "ra": 270.001, "dec": -29}],
                       inputs={"mode": "mast"})
    _, products = discover(config)
    assert len(instance.queries) == 2 and len(products) == 1


def test_mast_unauthorized_error_is_actionable(monkeypatch):
    import sys
    from types import ModuleType

    from requests import HTTPError, Response

    class Missions:
        dataset_kwds = {"roman": "fileSetName"}

        def query_criteria(self, **criteria):
            response = Response()
            response.status_code = 401
            raise HTTPError(response=response)

    module = ModuleType("astroquery.mast")
    module.MastMissions = lambda **kwargs: Missions()
    monkeypatch.setitem(sys.modules, "astroquery.mast", module)
    monkeypatch.delenv("MAST_API_TOKEN", raising=False)
    config = RunConfig(targets=[{"id": "a", "ra": 270, "dec": -29}], inputs={"mode": "mast"})
    with pytest.raises(PermissionError, match="MAST_API_TOKEN"):
        discover(config)
