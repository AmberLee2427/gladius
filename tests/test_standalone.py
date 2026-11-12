"""Verify the distributable script without importing Gladius inside it."""

import importlib.util
import json
from pathlib import Path

import asdf
import numpy as np
import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "standalone" / "roman_cutouts.py"
spec = importlib.util.spec_from_file_location("roman_cutouts_standalone", SCRIPT)
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)


@pytest.mark.parametrize("size", [50, 51])
def test_script_native_pixels_wcs_metadata_and_fresh_output(demo, tmp_path, size):
    config = tmp_path / "simple.yaml"
    output = tmp_path / "result"
    config.write_text(
        yaml.safe_dump(
            {
                "inputs": {"directory": str(demo.parent / "images")},
                "output": str(output),
                "size": size,
                "fits": True,
                "targets": [{"id": "edge", "x": 0, "y": 0}, {"id": "off", "x": -100, "y": -100}],
            }
        )
    )
    assert script.main([str(config)]) == 0
    report = json.loads((output / "manifest.json").read_text())["results"]
    assert [r["status"] for r in report] == ["ok", "off_detector"] * 2
    for record in report[::2]:
        with (
            asdf.open(output / record["output"]) as cutout,
            asdf.open(demo.parent / "images" / record["parent"]) as parent,
        ):
            tree = cutout.tree
            x0, y0 = tree["mapping"]["x0"], tree["mapping"]["y0"]
            assert tree["data"].shape == (size, size)
            assert np.isnan(tree["data"][0, 0])
            assert tree["dq"][0, 0] & 1
            np.testing.assert_equal(
                tree["data"][-y0:, -x0:], parent["roman"]["data"][: size + y0, : size + x0]
            )
            np.testing.assert_allclose(
                script.pixel_to_world(tree["wcs"], -x0, -y0),
                script.pixel_to_world(tree["parent_wcs"], 0, 0),
                atol=1e-10,
            )
            assert tree["parent_metadata"]["roman"]["meta"]["instrument"]
            assert (output / record["output"]).with_suffix(".fits").is_file()
    before = (output / "manifest.json").read_bytes()
    with pytest.raises(ValueError, match="must not exist"):
        script.main([str(config)])
    assert (output / "manifest.json").read_bytes() == before


def test_script_records_strict_edge_failure(demo, tmp_path):
    config = tmp_path / "simple.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "inputs": {"directory": str(demo.parent / "images")},
                "output": "strict",
                "edge": "strict",
                "targets": [{"id": "edge", "x": 0, "y": 0}],
            }
        )
    )
    assert script.main([str(config)]) == 1
    report = json.loads((tmp_path / "strict" / "manifest.json").read_text())
    assert all(r["status"] == "failed" for r in report["results"])


def test_script_rejects_external_asdf_array_before_materializing(tmp_path):
    parent = tmp_path / "external.asdf"
    parent.write_text(
        """#ASDF 1.0.0
#ASDF_STANDARD 1.6.0
%YAML 1.1
---
roman:
  data: !<tag:stsci.edu:asdf/core/ndarray-1.1.0>
    source: file:///no-such-gladius-test/standalone.asdf
    datatype: float32
    byteorder: little
    shape: [2, 2]
...
"""
    )

    with pytest.raises(ValueError, match="External ASDF array sources"):
        script.extract_parent(parent, [], {}, tmp_path, 1, [])


def test_script_rejects_external_array_reference(tmp_path):
    parent = tmp_path / "reference.asdf"
    asdf.AsdfFile(
        {
            "roman": {
                "reference": asdf.ExternalArrayReference(
                    "file:///no-such-gladius-test/standalone-reference.fits",
                    0,
                    "float32",
                    (2, 2),
                )
            }
        }
    ).write_to(parent)

    with pytest.raises(ValueError, match="External ASDF array sources"):
        script.extract_parent(parent, [], {}, tmp_path, 1, [])


def test_csv_with_blank_unused_coordinates(tmp_path):
    (tmp_path / "targets.csv").write_text("id,ra,dec,x,y\nevent,270,-29,,\n")
    target = script.targets_from({"targets_csv": "targets.csv"}, tmp_path, None)[0]
    assert "x" not in target and target["ra"] == 270


def test_script_mast_download_and_cleanup(demo, tmp_path, monkeypatch):
    import shutil
    import sys
    from types import ModuleType

    from astropy.table import Table

    parent = demo.parent / "images" / "demo0_cal.asdf"
    downloaded = []

    class Missions:
        def __init__(self, mission):
            assert mission == "roman"

        def login(self, **kwargs):
            assert kwargs == {"token": "test-token", "store_token": False}

        def query_criteria(self, **kwargs):
            assert kwargs["productLevel"] == "2"
            assert kwargs["coordinates"] == "270.0 -29.0"
            return Table(rows=[("demo",)], names=["fileSetName"])

        def get_unique_product_list(self, observations):
            return Table(rows=[(parent.name, "mast:demo")], names=["filename", "dataURI"])

        def download_products(self, products, download_dir):
            assert len(products) == 1
            path = Path(download_dir) / parent.name
            shutil.copyfile(parent, path)
            downloaded.append(path)
            return Table(rows=[(str(path), "COMPLETE")], names=["Local Path", "Status"])

    module = ModuleType("astroquery.mast")
    module.MastMissions = Missions
    monkeypatch.setitem(sys.modules, "astroquery.mast", module)
    monkeypatch.setenv("MAST_API_TOKEN", "test-token")
    config = tmp_path / "simple.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "inputs": {"mode": "mast"},
                "output": "downloaded-cutouts",
                "targets": [{"id": "sky", "ra": 270.0, "dec": -29.0}],
            }
        )
    )
    assert script.main([str(config)]) == 0
    assert downloaded and all(not path.exists() for path in downloaded)
    manifest = (tmp_path / "downloaded-cutouts" / "manifest.json").read_text()
    assert "test-token" not in manifest


@pytest.mark.parametrize("x,y", [(0.1, 0.3), (np.array([0.01, 0.1]), np.array([0.2, 0.3]))])
def test_inverse_refines_supplied_solution_across_ra_wrap(x, y):
    class ApproximateInverse:
        def __call__(self, x, y, **kwargs):
            return (359.95 + x) % 360, 2 * y

        def invert(self, ra, dec, **kwargs):
            return (ra - 359.95) % 360 + 0.02, dec / 2 - 0.01

        def numerical_inverse(self, *args, **kwargs):
            raise AssertionError("This global solver does not support the fixture transform")

    wcs = ApproximateInverse()
    sky = wcs(x, y)
    actual = script.world_to_pixel(wcs, *sky)
    np.testing.assert_allclose(actual[0], x, atol=1e-6, rtol=0)
    np.testing.assert_allclose(actual[1], y, atol=1e-6, rtol=0)


def test_inverse_rejects_singular_transform():
    class SingularInverse:
        def __call__(self, x, y, **kwargs):
            return np.zeros_like(x), np.zeros_like(y)

        def invert(self, ra, dec, **kwargs):
            return 1.0, 1.0

    with pytest.raises(ValueError, match="singular"):
        script.world_to_pixel(SingularInverse(), 1.0, 2.0)


@pytest.mark.parametrize("size", [50, 51])
def test_package_and_script_produce_equivalent_cutouts(demo, tmp_path, size):
    """Exercise the same comparison as live CI, using synthetic parents offline."""
    from tests.integration.package_script_parity import check_package_script_parity

    for parent in sorted((demo.parent / "images").glob("*.asdf")):
        check_package_script_parity(parent, tmp_path / parent.stem, size)
