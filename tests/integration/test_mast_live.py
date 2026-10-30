"""Opt-in authenticated Roman downloads; normal pytest runs remain offline."""

import hashlib
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest
from astropy.table import Table

MAX_BYTES = 20 * 1024 * 1024


def choose_product(products, *, require_calibrated=False):
    """Choose one known-size small product; prefer a calibrated detector image."""
    candidates = []
    for row in products:
        try:
            size = float(row["size"])
        except (KeyError, TypeError, ValueError):
            continue
        if not np.isfinite(size) or size != int(size) or not 0 < size <= MAX_BYTES:
            continue
        filename = str(row["filename"])
        calibrated = filename.lower().endswith(("_cal.asdf", "_cal.fits"))
        if require_calibrated and not calibrated:
            continue
        candidates.append((not calibrated, int(size), filename, row))
    if not candidates:
        raise ValueError("No eligible Roman product <=20 MiB; no download was attempted")
    return min(candidates, key=lambda item: item[:3])[3]


@contextmanager
def bounded_files():
    """Enforce the byte cap during writes as well as checking archive metadata."""
    import resource  # The live workflow runs on Linux.

    previous = resource.getrlimit(resource.RLIMIT_FSIZE)
    ceiling = MAX_BYTES if previous[1] == resource.RLIM_INFINITY else min(MAX_BYTES, previous[1])
    resource.setrlimit(resource.RLIMIT_FSIZE, (ceiling, previous[1]))
    try:
        yield
    finally:
        resource.setrlimit(resource.RLIMIT_FSIZE, previous)


@pytest.mark.live_mast
@pytest.mark.skipif(
    os.environ.get("GLADIUS_LIVE_MAST") != "1",
    reason="Set GLADIUS_LIVE_MAST=1 to enable real authenticated downloads",
)
def test_authenticated_roman_download(tmp_path, record_property):
    from astroquery.mast import MastMissions

    from gladius_roman import RunConfig, Target, make_cutout
    from gladius_roman.inputs import mast_queries, staged
    from gladius_roman.io import read_exposure, write_cutout

    token = os.environ.get("MAST_API_TOKEN")
    assert token, "Live MAST tests require the MAST_API_TOKEN environment variable"
    missions = MastMissions(mission="roman")
    missions.TIMEOUT = 60
    missions.login(token=token, store_token=False)
    assert missions.dataset_kwds.get("roman") == "fileSetName"

    # This intentionally samples up to five datasets; it is not a complete survey.
    # No invented program ID or hard-coded dataset can silently go stale.
    observations = missions.query_criteria(
        productLevel="2", limit=5,
        select_cols=["fileSetName", "ra", "dec", "detector", "optical_element",
                     "exposure_start_time"],
    )
    assert len(observations), "No accessible Roman Level 2 datasets found"

    # Exercise the package's generated cone syntax using an actual archive position.
    position = next((row for row in observations
                     if np.isfinite(float(row["ra"])) and np.isfinite(float(row["dec"]))), None)
    assert position is not None, "Sample has no finite Roman archive sky positions"
    config = RunConfig(
        targets=[Target(id="archive-smoke", ra=float(position["ra"]), dec=float(position["dec"]))],
        inputs={"mode": "mast"},
    )
    query = mast_queries(config)[0]
    nearby = missions.query_criteria(
        **query, limit=5, select_cols=["fileSetName", "detector", "optical_element",
                                      "exposure_start_time"],
    )
    assert len(nearby), "Generated target query did not recover any candidate observations"
    products = missions.get_unique_product_list(observations)
    assert len(products), "Sample datasets have no associated products"
    product = choose_product(
        products, require_calibrated=os.environ.get("GLADIUS_MAST_REQUIRE_CALIBRATED") == "1"
    )
    advertised = int(product["size"])
    calibrated = str(product["filename"]).lower().endswith(("_cal.asdf", "_cal.fits"))
    # staged() is the production download/cleanup path, not a separate HTTP client.
    with bounded_files(), staged(product, missions, tmp_path) as path:
        assert path.is_file()
        actual = path.stat().st_size
        assert 0 < actual <= MAX_BYTES
        assert actual == advertised, "Downloaded length differs from archive product size"
        with path.open("rb") as stream:
            prefix = stream.read(512).lstrip().lower()
        assert not prefix.startswith((b"<!doctype html", b"<html")), "Received an HTML error page"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if calibrated:
            exposure = read_exposure(path)
            ny, nx = exposure.arrays["data"].shape
            cutout = make_cutout(
                exposure.arrays, exposure.wcs,
                Target(id="archive-smoke", x=(nx - 1) / 2, y=(ny - 1) / 2),
                parent_metadata=exposure.parent_metadata,
                ancillary_arrays=exposure.ancillary_arrays,
            )
            assert cutout.arrays["data"].shape == (150, 150)
            assert cutout.parent_metadata
            output = tmp_path / "cutout"
            output.mkdir()
            write_cutout(cutout, output, formats=("asdf",))
            assert (output / "cutout.asdf").is_file()
        downloaded_path = Path(path)
    assert not downloaded_path.exists(), "Temporary archive parent was not cleaned up"

    # Reports contain no token, raw product metadata, or restricted science data.
    result = {"downloaded_bytes": actual, "sha256": digest,
              "coverage": "calibrated-image-and-cutout" if calibrated else "associated-product-download",
              "generated_target_query": "passed", "temporary_cleanup": "passed"}
    report = os.environ.get("GLADIUS_MAST_REPORT")
    if report:
        Path(report).write_text(json.dumps(result, indent=2) + "\n")
    for key, value in result.items():
        record_property(key, value)
    print(json.dumps(result, indent=2))


def test_small_product_selection_and_image_preference():
    products = Table(rows=[("preview.jpg", 100), ("parent_cal.asdf", 1000),
                           ("huge_cal.asdf", MAX_BYTES + 1)], names=["filename", "size"])
    assert choose_product(products)["filename"] == "parent_cal.asdf"
    assert choose_product(products[:1])["filename"] == "preview.jpg"
    with pytest.raises(ValueError, match="No eligible"):
        choose_product(products[:1], require_calibrated=True)


@pytest.mark.parametrize("size", [0, -1, MAX_BYTES + 1, float("nan"), float("inf"), "unknown"])
def test_unknown_or_oversize_downloads_are_rejected(size):
    with pytest.raises(ValueError, match="no download"):
        choose_product(Table(rows=[("file.asdf", size)], names=["filename", "size"]))


@pytest.mark.skipif(sys.platform == "win32", reason="Live workflow uses Linux resource limits")
def test_live_harness_with_synthetic_archive(demo, tmp_path, monkeypatch):
    """Exercise the entire harness offline, including its calibrated-image branch."""
    import shutil
    from types import ModuleType

    source = demo.parent / "images" / "demo0_cal.asdf"
    report = tmp_path / "report.json"

    class Missions:
        dataset_kwds = {"roman": "fileSetName"}
        calls = 0

        def login(self, **kwargs):
            assert kwargs == {"token": "synthetic-test-token", "store_token": False}

        def query_criteria(self, **kwargs):
            self.calls += 1
            if self.calls == 2:
                assert kwargs["coordinates"] == "270.0 -29.0"
                assert kwargs["radius"] == "6.0 arcmin"
            return Table(rows=[("demo", 270., -29., "WFI01", "F146", "2026-01-01")],
                         names=["fileSetName", "ra", "dec", "detector", "optical_element",
                                "exposure_start_time"])

        def get_unique_product_list(self, observations):
            return Table(rows=[(source.name, source.stat().st_size)], names=["filename", "size"])

        def download_products(self, products, download_dir):
            assert len(products) == 1
            target = Path(download_dir) / source.name
            shutil.copyfile(source, target)
            return Table(rows=[(str(target), "COMPLETE")], names=["Local Path", "Status"])

    module = ModuleType("astroquery.mast")
    module.MastMissions = lambda **kwargs: Missions()
    monkeypatch.setitem(sys.modules, "astroquery.mast", module)
    monkeypatch.setenv("MAST_API_TOKEN", "synthetic-test-token")
    monkeypatch.setenv("GLADIUS_MAST_REPORT", str(report))
    test_authenticated_roman_download(tmp_path, lambda *_: None)
    result = json.loads(report.read_text())
    assert result["coverage"] == "calibrated-image-and-cutout"
    assert result["temporary_cleanup"] == "passed"
    assert "synthetic-test-token" not in report.read_text()
