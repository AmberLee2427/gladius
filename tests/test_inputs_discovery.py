"""Input discovery: local directories, archive query handling and the MAST load test.

The MAST client is replaced by a small in-memory fake so every branch of query
construction, truncation protection, selection and product identity checking is
exercised without credentials or network access.
"""

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from astropy.table import Table

from gladius.config import RunConfig
from gladius.inputs import discover, mast_test_configuration, staged

OBS_COLUMNS = ["fileSetName", "detector", "optical_element", "exposure_start_time"]


def observations(*rows):
    return Table(rows=list(rows), names=OBS_COLUMNS) if rows else empty_observations()


def empty_observations():
    return Table(names=OBS_COLUMNS, dtype=[str] * 4)


def products_table(*filenames):
    if not filenames:
        return Table(names=["filename"], dtype=[str])
    return Table(rows=[(name,) for name in filenames], names=["filename"])


class FakeMissions:
    """Programmable stand-in for ``astroquery.mast.MastMissions``."""

    def __init__(self, *, responses=(), products=None, dataset_kwds=None, error=None):
        self.dataset_kwds = {"roman": "fileSetName"} if dataset_kwds is None else dataset_kwds
        self.responses = list(responses)
        self.products = products if products is not None else products_table("a_cal.asdf")
        self.error = error
        self.queries = []
        self.login_calls = []
        self.requested_suffix = None

    def login(self, **kwargs):
        self.login_calls.append(kwargs)

    def query_criteria(self, **criteria):
        self.queries.append(criteria)
        if self.error is not None:
            raise self.error
        return self.responses.pop(0) if self.responses else empty_observations()

    def get_unique_product_list(self, selected_observations):
        return self.products

    def filter_products(self, products, **kwargs):
        self.requested_suffix = kwargs.get("file_suffix")
        return products


def install(monkeypatch, fake):
    module = ModuleType("astroquery.mast")
    module.MastMissions = lambda **kwargs: fake
    monkeypatch.setitem(sys.modules, "astroquery.mast", module)
    monkeypatch.delenv("MAST_API_TOKEN", raising=False)
    return fake


def mast_config(**changes):
    data = {
        "targets": [{"id": "a", "ra": 270.0, "dec": -29.0}],
        "inputs": {"mode": "mast", "query_limit": 10},
    }
    for key, value in changes.items():
        data.setdefault(key, {})
        data[key] = {**data[key], **value} if isinstance(value, dict) else value
    return RunConfig.model_validate(data)


# ---------------------------------------------------------------- local directories


def directory_config(directory, **inputs):
    return RunConfig.model_validate(
        {
            "targets": [{"id": "a", "x": 1, "y": 1}],
            "inputs": {"mode": "directory", "directory": str(directory), **inputs},
            "storage": {"output_directory": str(directory / "products")},
        }
    )


def test_directory_discovery_is_sorted_and_skips_generated_products(tmp_path):
    for name in ("b_cal.asdf", "a_cal.asdf", "notes.txt"):
        (tmp_path / name).write_text("x")
    (tmp_path / "products").mkdir()
    (tmp_path / "products" / "generated_cal.asdf").write_text("x")
    missions, paths = discover(directory_config(tmp_path))
    assert missions is None
    assert [p.name for p in paths] == ["a_cal.asdf", "b_cal.asdf"]


def test_directory_recursion_is_opt_in(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "deep_cal.asdf").write_text("x")
    with pytest.raises(ValueError, match="No parent files matched"):
        discover(directory_config(tmp_path))
    _, paths = discover(directory_config(tmp_path, recursive=True))
    assert [p.name for p in paths] == ["deep_cal.asdf"]


def test_missing_directory_is_reported(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        discover(directory_config(tmp_path / "absent"))


def test_staged_local_parent_is_passed_through_untouched(tmp_path):
    parent = tmp_path / "parent_cal.asdf"
    parent.write_text("keep")
    with staged(parent, None, tmp_path) as path:
        assert path == parent
    assert parent.read_text() == "keep"


# ---------------------------------------------------------------- MAST discovery


def test_missing_astroquery_gives_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "astroquery.mast", None)
    with pytest.raises(ImportError, match=r"roman-gladius\[mast\]"):
        discover(mast_config())


def test_old_astroquery_without_roman_support_is_rejected(monkeypatch):
    install(monkeypatch, FakeMissions(dataset_kwds={}))
    with pytest.raises(ImportError, match="0.4.11"):
        discover(mast_config())


def test_token_is_taken_from_environment_only(monkeypatch):
    fake = install(
        monkeypatch, FakeMissions(responses=[observations(("ds1", "WFI01", "F146", "2026-01-01"))])
    )
    monkeypatch.setenv("MAST_API_TOKEN", "test-only-sentinel")
    discover(mast_config())
    assert fake.login_calls == [{"token": "test-only-sentinel"}]


def test_non_authorization_errors_are_not_masked(monkeypatch):
    install(monkeypatch, FakeMissions(error=RuntimeError("archive offline")))
    with pytest.raises(RuntimeError, match="archive offline"):
        discover(mast_config())


def test_query_at_limit_is_treated_as_truncated(monkeypatch):
    rows = [("ds1", "WFI01", "F146", "2026-01-01"), ("ds2", "WFI01", "F146", "2026-01-01")]
    install(monkeypatch, FakeMissions(responses=[observations(*rows)]))
    with pytest.raises(ValueError, match="truncated"):
        discover(mast_config(inputs={"query_limit": 2}))


def test_combined_target_searches_at_limit_are_treated_as_truncated(monkeypatch):
    # Each cone is below the limit by itself; their union reaches it.
    install(
        monkeypatch,
        FakeMissions(
            responses=[
                observations(("ds1", "WFI01", "F146", "2026-01-01")),
                observations(("ds2", "WFI01", "F146", "2026-01-01")),
            ]
        ),
    )
    config = mast_config(
        targets=[{"id": "a", "ra": 270, "dec": -29}, {"id": "b", "ra": 10, "dec": 20}],
        inputs={"query_limit": 2},
    )
    with pytest.raises(ValueError, match="truncated"):
        discover(config)


def test_no_matching_observations(monkeypatch):
    install(monkeypatch, FakeMissions())
    with pytest.raises(ValueError, match="No MAST observations matched"):
        discover(mast_config())


def test_selection_that_excludes_everything_is_reported(monkeypatch):
    install(
        monkeypatch, FakeMissions(responses=[observations(("ds1", "WFI01", "F146", "2026-01-01"))])
    )
    with pytest.raises(ValueError, match="passed selection"):
        discover(mast_config(selection={"filters": ["F158"]}))


def test_selection_keeps_only_matching_observations(monkeypatch):
    fake = install(
        monkeypatch,
        FakeMissions(
            responses=[
                observations(
                    ("ds1", "WFI01", "F146", "2026-01-01"),
                    ("ds2", "WFI02", "F158", "2026-01-01"),
                )
            ]
        ),
    )
    fake.get_unique_product_list = lambda selected: (
        pytest.fail("only one observation should survive selection")
        if len(selected) != 1
        else products_table(f"{selected['fileSetName'][0]}_cal.asdf")
    )
    _, found = discover(mast_config(selection={"filters": ["F158"]}))
    assert [str(row["filename"]) for row in found] == ["ds2_cal.asdf"]
    assert fake.requested_suffix == "_cal"


def test_open_ended_date_selection_builds_query_bounds(monkeypatch):
    from gladius.inputs import mast_queries

    start_only = mast_queries(mast_config(selection={"start": "2026-01-01"}))[0]
    end_only = mast_queries(mast_config(selection={"end": "2026-02-01"}))[0]
    assert start_only["exposure_start_time"] == ">=2026-01-01T00:00:00.000"
    assert end_only["exposure_start_time"] == "<2026-02-01T00:00:00.000"


def test_pixel_only_config_issues_one_unfiltered_query():
    from gladius.inputs import mast_queries

    config = RunConfig.model_validate(
        {
            "targets": [{"id": "p", "x": 1, "y": 1}],
            "inputs": {"mode": "mast", "mast_criteria": {"objectname": "TRAPPIST-1"}},
        }
    )
    assert mast_queries(config) == [{"productLevel": "2", "objectname": "TRAPPIST-1"}]


def test_product_suffix_filter_can_remove_everything(monkeypatch):
    install(
        monkeypatch,
        FakeMissions(
            responses=[observations(("ds1", "WFI01", "F146", "2026-01-01"))],
            products=products_table(),
        ),
    )
    with pytest.raises(ValueError, match="product_suffix"):
        discover(mast_config())


def test_product_filename_pins_a_single_product(monkeypatch):
    responses = [observations(("ds1", "WFI01", "F146", "2026-01-01"))]
    both = products_table("a_cal.asdf", "b_cal.asdf")
    install(monkeypatch, FakeMissions(responses=list(responses), products=both))
    _, found = discover(mast_config(inputs={"product_filename": "b_cal.asdf"}))
    assert [str(row["filename"]) for row in found] == ["b_cal.asdf"]

    install(monkeypatch, FakeMissions(responses=list(responses), products=both))
    with pytest.raises(ValueError, match="no product matching"):
        discover(mast_config(inputs={"product_filename": "missing_cal.asdf"}))


def test_duplicate_archive_filenames_are_ambiguous(monkeypatch):
    install(
        monkeypatch,
        FakeMissions(
            responses=[observations(("ds1", "WFI01", "F146", "2026-01-01"))],
            products=products_table("same_cal.asdf", "same_cal.asdf"),
        ),
    )
    with pytest.raises(ValueError, match="duplicate filenames"):
        discover(mast_config())


# ---------------------------------------------------------------- MAST load test


class SizedMissions(FakeMissions):
    """Returns one product table per sampled dataset, keyed by its file set name."""

    def __init__(self, observations_table, products_by_dataset, **kwargs):
        super().__init__(responses=[observations_table], **kwargs)
        self.products_by_dataset = products_by_dataset

    def get_unique_product_list(self, selected_observations):
        return self.products_by_dataset[str(selected_observations["fileSetName"][0])]


def sample_table(*rows):
    return Table(rows=list(rows), names=["fileSetName", "ra", "dec"])


def sized(*entries):
    return Table(rows=list(entries), names=["filename", "size"])


def test_load_test_picks_smallest_valid_calibrated_image(tmp_path, monkeypatch):
    fake = install(
        monkeypatch,
        SizedMissions(
            sample_table(
                ("big", 10.0, -20.0),
                ("small", 11.0, -21.0),
                ("badsky", 400.0, 0.0),
                ("nosize", 12.0, -22.0),
            ),
            {
                "big": sized(("big_cal.asdf", 5000)),
                "small": sized(("small_cal.asdf", 300), ("small_cal.png", 1)),
                "badsky": sized(("badsky_cal.asdf", 1)),
                "nosize": sized(("fraction_cal.asdf", 2.5), ("zero_cal.asdf", 0)),
            },
        ),
    )
    monkeypatch.setenv("MAST_API_TOKEN", "test-only-sentinel")
    result = mast_test_configuration(tmp_path)
    assert fake.login_calls == [{"token": "test-only-sentinel", "store_token": False}]
    assert result["filename"] == "small_cal.asdf"
    assert result["dataset"] == "small"
    assert result["download_bytes"] == 300
    configuration = result["configuration"]
    assert configuration["inputs"]["product_filename"] == "small_cal.asdf"
    assert configuration["targets"][0]["ra"] == pytest.approx(11.0)
    assert "small_cal.asdf" in result["yaml"]


def test_load_test_requires_astroquery(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "astroquery.mast", None)
    with pytest.raises(ValueError, match=r"roman-gladius\[mast\]"):
        mast_test_configuration(tmp_path)


def test_load_test_rejects_old_astroquery(tmp_path, monkeypatch):
    install(monkeypatch, FakeMissions(dataset_kwds={}))
    with pytest.raises(ValueError, match="0.4.11"):
        mast_test_configuration(tmp_path)


def test_load_test_explains_access_denied(tmp_path, monkeypatch):
    class Denied(Exception):
        response = SimpleNamespace(status_code=403)

    install(monkeypatch, FakeMissions(error=Denied()))
    with pytest.raises(ValueError, match="MAST_API_TOKEN"):
        mast_test_configuration(tmp_path)


def test_load_test_wraps_other_failures(tmp_path, monkeypatch):
    install(monkeypatch, FakeMissions(error=TimeoutError("slow")))
    with pytest.raises(ValueError, match="discovery failed: TimeoutError: slow"):
        mast_test_configuration(tmp_path)


def test_load_test_without_usable_candidates(tmp_path, monkeypatch):
    install(
        monkeypatch,
        SizedMissions(sample_table(("a", 10.0, 10.0)), {"a": sized(("a_cal.txt", 10))}),
    )
    with pytest.raises(ValueError, match="No accessible calibrated image"):
        mast_test_configuration(tmp_path)


def test_load_test_skips_datasets_without_products(tmp_path, monkeypatch):
    class Empty(SizedMissions):
        def get_unique_product_list(self, selected_observations):
            return Table(names=["filename", "size"], dtype=[str, float])

    install(monkeypatch, Empty(sample_table(("a", 10.0, 10.0)), {}))
    with pytest.raises(ValueError, match="No accessible calibrated image"):
        mast_test_configuration(Path(tmp_path))
