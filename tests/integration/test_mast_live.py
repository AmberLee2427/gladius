"""Opt-in authenticated Roman downloads; normal pytest runs remain offline."""

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest
from astropy.table import Table

MAX_BYTES = 1024 * 1024 * 1024


def choose_product(products):
    """Choose the smallest known-size calibrated detector image within the byte cap."""
    candidates = []
    for row in products:
        try:
            size = float(row["size"])
        except (KeyError, TypeError, ValueError):
            continue
        if not np.isfinite(size) or size != int(size) or not 0 < size <= MAX_BYTES:
            continue
        filename = str(row["filename"])
        calibrated = filename.lower().endswith("_cal.asdf")
        if not calibrated:
            continue
        candidates.append((int(size), filename, row))
    if not candidates:
        raise ValueError("No eligible calibrated Roman image <=1 GiB; no download was attempted")
    return min(candidates, key=lambda item: item[:2])[2]


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
    """Keep embargoed data and third-party diagnostics out of public CI output."""
    # A process boundary also contains native-library output and uncaught tracebacks.
    # Never attach the worker's stdout/stderr or temporary science files as artifacts.
    worker = (
        "import sys; from pathlib import Path; "
        "sys.path.insert(0, sys.argv[1]); "
        "from test_mast_live import _authenticated_roman_download; "
        "_authenticated_roman_download(Path(sys.argv[2]), lambda *args: None)"
    )
    result = subprocess.run(
        [sys.executable, "-c", worker, str(Path(__file__).parent), str(tmp_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode:
        pytest.fail(
            "Live fidelity check failed; diagnostics withheld to protect embargoed data",
            pytrace=False,
        )
    record_property("live_fidelity", "passed")


def _authenticated_roman_download(tmp_path, record_property):
    from astroquery.mast import MastMissions

    from gladius import RunConfig, Target, make_cutout
    from gladius.inputs import mast_queries, staged
    from gladius.io import read_cutout, read_exposure, write_cutout

    token = os.environ.get("MAST_API_TOKEN")
    assert token, "Live MAST tests require the MAST_API_TOKEN environment variable"
    missions = MastMissions(mission="roman")
    missions.TIMEOUT = 60
    missions.login(token=token, store_token=False)
    assert missions.dataset_kwds.get("roman") == "fileSetName"

    # This intentionally samples up to five datasets; it is not a complete survey.
    # No invented program ID or hard-coded dataset can silently go stale.
    observations = missions.query_criteria(
        productLevel="2",
        exposure_type="WFI_IMAGE",
        limit=5,
        select_cols=[
            "fileSetName",
            "ra",
            "dec",
            "detector",
            "optical_element",
            "exposure_start_time",
        ],
    )
    assert len(observations), "No accessible Roman Level 2 datasets found"

    # Exercise the package's generated cone syntax using an actual archive position.
    position = next(
        (
            row
            for row in observations
            if np.isfinite(float(row["ra"])) and np.isfinite(float(row["dec"]))
        ),
        None,
    )
    assert position is not None, "Sample has no finite Roman archive sky positions"
    config = RunConfig(
        targets=[Target(id="archive-smoke", ra=float(position["ra"]), dec=float(position["dec"]))],
        inputs={"mode": "mast"},
    )
    query = mast_queries(config)[0]
    nearby = missions.query_criteria(
        **query,
        limit=5,
        select_cols=["fileSetName", "detector", "optical_element", "exposure_start_time"],
    )
    assert len(nearby), "Generated target query did not recover any candidate observations"
    products = missions.get_unique_product_list(observations)
    assert len(products), "Sample datasets have no associated products"
    product = choose_product(products)
    advertised = int(product["size"])
    # staged() is the production download/cleanup path, not a separate HTTP client.
    with bounded_files(), staged(product, missions, tmp_path) as path:
        assert path.is_file()
        actual = path.stat().st_size
        assert 0 < actual <= MAX_BYTES
        assert actual == advertised, "Downloaded length differs from archive product size"
        with path.open("rb") as stream:
            prefix = stream.read(512).lstrip().lower()
        assert not prefix.startswith((b"<!doctype html", b"<html")), "Received an HTML error page"
        exposure = read_exposure(path)
        ny, nx = exposure.arrays["data"].shape
        cutout = make_cutout(
            exposure.arrays,
            exposure.wcs,
            Target(id="archive-smoke", x=(nx - 1) / 2, y=(ny - 1) / 2),
            parent_metadata=exposure.parent_metadata,
            ancillary_arrays=exposure.ancillary_arrays,
        )
        assert cutout.arrays["data"].shape == (150, 150)
        assert cutout.parent_metadata
        output = tmp_path / "cutout"
        output.mkdir()
        write_cutout(cutout, output, formats=("asdf",))
        reopened = read_cutout(output / "cutout.asdf")
        np.testing.assert_array_equal(reopened.arrays["data"], cutout.arrays["data"])
        from standalone_fidelity import check_standalone_fidelity

        check_standalone_fidelity(path, tmp_path)

        # Use the downloaded parent for both implementations; no second download.
        # This runs inside the silent worker, so assertion details stay private.
        from package_script_parity import check_package_script_parity

        for size in (50, 51):
            check_package_script_parity(path, tmp_path / f"parity-{size}", size)
        downloaded_path = Path(path)
    assert not downloaded_path.exists(), "Temporary archive parent was not cleaned up"

    # Reports contain no token, raw product metadata, or restricted science data.
    # Public reports deliberately contain only pass/fail, no filenames, catalog IDs,
    # hashes, coordinates, measurements, or restricted parent metadata.
    result = {
        "coverage": "calibrated-image-and-cutout",
        "generated_target_query": "passed",
        "temporary_cleanup": "passed",
        "standalone_pixel_fidelity": "passed",
        "standalone_wcs": "passed",
        "standalone_metadata": "passed",
        "package_script_product_equivalence": "passed",
    }
    report = os.environ.get("GLADIUS_MAST_REPORT")
    if report:
        Path(report).write_text(json.dumps(result, indent=2) + "\n")
    for key, value in result.items():
        record_property(key, value)
    print(json.dumps(result, indent=2))


def test_only_calibrated_images_within_size_limit_are_selected():
    products = Table(
        rows=[("preview.jpg", 100), ("parent_cal.asdf", 1000), ("huge_cal.asdf", MAX_BYTES + 1)],
        names=["filename", "size"],
    )
    assert choose_product(products)["filename"] == "parent_cal.asdf"
    with pytest.raises(ValueError, match="No eligible"):
        choose_product(products[:1])


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
            assert kwargs["exposure_type"] == "WFI_IMAGE"
            self.calls += 1
            if self.calls == 2:
                assert kwargs["coordinates"] == "270.0 -29.0"
                assert kwargs["radius"] == "6.0 arcmin"
            return Table(
                rows=[("demo", 270.0, -29.0, "WFI01", "F146", "2026-01-01")],
                names=[
                    "fileSetName",
                    "ra",
                    "dec",
                    "detector",
                    "optical_element",
                    "exposure_start_time",
                ],
            )

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
    _authenticated_roman_download(tmp_path, lambda *_: None)
    result = json.loads(report.read_text())
    assert result["coverage"] == "calibrated-image-and-cutout"
    assert result["temporary_cleanup"] == "passed"
    assert result["package_script_product_equivalence"] == "passed"
    assert "synthetic-test-token" not in report.read_text()


def test_embargo_boundary_discards_worker_output(tmp_path, monkeypatch):
    """A failed worker cannot expose restricted diagnostics through pytest."""
    from types import SimpleNamespace

    calls = []

    def failed_worker(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(subprocess, "run", failed_worker)
    with pytest.raises(pytest.fail.Exception, match="diagnostics withheld"):
        test_authenticated_roman_download(tmp_path, lambda *_: None)
    assert calls[0]["stdout"] == subprocess.DEVNULL
    assert calls[0]["stderr"] == subprocess.DEVNULL


@pytest.mark.parametrize("search_radius_deg", [None, 0.005])
def test_gaia_reference_with_synthetic_catalog(demo, tmp_path, monkeypatch, search_radius_deg):
    """Exercise catalog selection, epoch propagation, CLI, and image centroid offline."""
    from types import ModuleType, SimpleNamespace

    from gaia_reference import check_gaia_reference

    module = ModuleType("astroquery.gaia")
    catalog = Table(
        rows=[(1, 270.0, -29.0, 0.0, 0.0, 2016.0, 17.0)],
        names=["source_id", "ra", "dec", "pmra", "pmdec", "ref_epoch", "phot_g_mean_mag"],
    )
    module.Gaia = SimpleNamespace(
        launch_job_async=lambda *args, **kwargs: SimpleNamespace(get_results=lambda: catalog)
    )
    monkeypatch.setitem(sys.modules, "astroquery.gaia", module)
    result = check_gaia_reference(
        demo.parent / "images" / "demo0_cal.asdf",
        tmp_path,
        search_radius_deg=search_radius_deg,
    )
    assert result["gaia_centroid_offset_arcsec"] < 0.03
