"""Large archive runs: footprint prefiltering, parallel staging, kept downloads,
fail-fast, smaller products, shared output files and full-frame exports.

These follow the 0.1.0a6 Nexus beta test. The MAST client is replaced by small
fakes, so no credentials, network access or archive data are involved.
"""

import importlib.util
import json
import shutil
import sys
import threading
import warnings
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

import asdf
import numpy as np
import pytest
from astropy.table import Table

from gladius.config import RunConfig, load_config
from gladius.core import DO_NOT_USE, WcsRoundTripError
from gladius.inputs import discover, footprint_contains, parse_s_region
from gladius.io import AsdfPackageVersionWarning, read_cutout, read_exposure
from gladius.pipeline import RepeatedFailureError, run

SQUARE = "POLYGON ICRS 269.99 -29.01 270.01 -29.01 270.01 -28.99 269.99 -28.99"


def change(config, **sections):
    data = config.model_dump(mode="json")
    for name, values in sections.items():
        data[name].update(values)
    return RunConfig.model_validate(data)


def saved(path):
    return json.loads(path.read_text())


def quiet(_):
    return None


# ------------------------------------------------------------- footprint geometry


def test_s_region_parsing_accepts_one_polygon_only():
    ra, dec = parse_s_region(SQUARE)
    assert len(ra) == len(dec) == 4
    assert parse_s_region("POLYGON 1 2 3 4 5 6") is not None
    for text in (None, "", "CIRCLE ICRS 1 2 3", "POLYGON 1 2 3", "POLYGON 1 2 3 4 POLYGON 5 6 7 8"):
        assert parse_s_region(text) is None


def test_footprint_contains_inside_outside_and_margin():
    vertices = parse_s_region(SQUARE)
    assert footprint_contains(vertices, 270.0, -29.0)
    assert not footprint_contains(vertices, 270.5, -29.0)
    # 0.011 deg of RA at dec -29 is ~35 arcsec east of the 270.01 edge.
    assert not footprint_contains(vertices, 270.011 + 0.01 / 3600, -29.0, margin_arcsec=1)
    assert footprint_contains(vertices, 270.0105, -29.0, margin_arcsec=10)
    wrapped = parse_s_region("POLYGON 359.99 0.01 0.01 0.01 0.01 -0.01 359.99 -0.01")
    assert footprint_contains(wrapped, 0.0, 0.0)
    assert footprint_contains(wrapped, 359.995, 0.0)


class FootprintMissions:
    columns = ["fileSetName", "detector", "optical_element", "exposure_start_time", "s_region"]

    def __init__(self, rows):
        self.dataset_kwds = {"roman": "fileSetName"}
        self.rows = rows
        self.selected = None
        self.select_cols = None

    def login(self, **kwargs):
        pass

    def query_criteria(self, **criteria):
        self.select_cols = criteria["select_cols"]
        return Table(rows=self.rows, names=self.columns)

    def get_unique_product_list(self, observations):
        self.selected = [str(name) for name in observations["fileSetName"]]
        return Table(rows=[(f"{n}_cal.asdf",) for n in self.selected], names=["filename"])

    def filter_products(self, products, **kwargs):
        return products


def install(monkeypatch, fake):
    module = ModuleType("astroquery.mast")
    module.MastMissions = lambda **kwargs: fake
    monkeypatch.setitem(sys.modules, "astroquery.mast", module)
    monkeypatch.delenv("MAST_API_TOKEN", raising=False)
    return fake


def footprint_rows():
    far = "POLYGON ICRS 271.0 -29.01 271.02 -29.01 271.02 -28.99 271.0 -28.99"
    return [
        ("hit", "WFI07", "F213", "2026-10-01T00:00:00", SQUARE),
        ("miss", "WFI04", "F213", "2026-10-01T00:00:00", far),
        ("unknown", "WFI05", "F213", "2026-10-01T00:00:00", ""),
    ]


def mast_config(targets=None, **inputs):
    return RunConfig(
        targets=targets or [{"id": "a", "ra": 270.0, "dec": -29.0}],
        inputs={"mode": "mast", **inputs},
    )


def test_discovery_skips_parents_whose_footprint_holds_no_target(monkeypatch):
    fake = install(monkeypatch, FootprintMissions(footprint_rows()))
    stats = {}
    _, products = discover(mast_config(), stats=stats)
    assert "s_region" in fake.select_cols
    assert fake.selected == ["hit", "unknown"]  # an unknown footprint is never skipped
    assert [str(p["filename"]) for p in products] == ["hit_cal.asdf", "unknown_cal.asdf"]
    assert stats == {
        "footprint_prefilter": True,
        "candidate_observations": 3,
        "footprint_rejected": 1,
        "footprint_unknown": 1,
    }


def test_footprint_prefilter_can_be_disabled_and_ignores_pixel_targets(monkeypatch):
    fake = install(monkeypatch, FootprintMissions(footprint_rows()))
    discover(mast_config(prefilter_footprint=False))
    assert fake.selected == ["hit", "miss", "unknown"]
    mixed = [{"id": "a", "ra": 270.0, "dec": -29.0}, {"id": "b", "x": 1.0, "y": 2.0}]
    stats = {}
    discover(mast_config(mixed), stats=stats)
    assert fake.selected == ["hit", "miss", "unknown"]
    assert stats["footprint_prefilter"] is False


def test_all_candidates_outside_footprints_report_the_reason(monkeypatch):
    install(monkeypatch, FootprintMissions(footprint_rows()[1:2]))
    with pytest.raises(ValueError, match="footprint"):
        discover(mast_config(), stats={})


# ---------------------------------------------------- archive staging in the pipeline


def archive(demo, monkeypatch, *, owned=True, delay=None):
    """Serve the demo parents as MAST products; ``owned`` copies into the work folder."""
    import gladius.pipeline as module

    paths = sorted((demo.parent / "images").glob("*.asdf"))
    rows = [{"filename": p.name, "dataURI": f"mast:roman/{p.name}"} for p in paths]
    calls = {"downloads": [], "threads": set()}
    lock = threading.Lock()

    @contextmanager
    def staged(source, missions, work):
        with lock:
            calls["downloads"].append(source["filename"])
            calls["threads"].add(threading.current_thread().name)
        parent = next(p for p in paths if p.name == source["filename"])
        if not owned:
            yield parent
            return
        folder = Path(work) / f"parent-{source['filename']}"
        folder.mkdir()
        shutil.copyfile(parent, folder / parent.name)
        try:
            yield folder / parent.name
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    monkeypatch.setattr(module, "discover", lambda *_, **__: (object(), rows))
    monkeypatch.setattr(module, "staged", staged)
    return calls


def mast_demo(demo, **sections):
    config = change(load_config(demo), inputs={"mode": "mast"})
    return change(config, **sections) if sections else config


def entries(manifest_path):
    return {
        (e["target_id"], e["source"]): e["status"] for e in saved(manifest_path)["entries"].values()
    }


def test_parallel_downloads_match_sequential_results(demo, monkeypatch):
    calls = archive(demo, monkeypatch)
    messages = []
    parallel = run(
        mast_demo(demo, execution={"download_workers": 2}, run={"name": "parallel"}),
        progress=messages.append,
    )
    assert sorted(calls["downloads"]) == ["demo0_cal.asdf", "demo1_cal.asdf"]
    assert any(name.startswith("gladius-download") for name in calls["threads"])
    assert "[1/2] demo0_cal.asdf" in messages and "[2/2] demo1_cal.asdf" in messages
    assert "  1 cutout, 0 off detector, 0 failed" in messages
    calls["downloads"].clear()
    sequential = run(
        mast_demo(demo, execution={"download_workers": 1}, run={"name": "serial"}),
        progress=quiet,
        fresh=True,
    )
    assert sorted(calls["downloads"]) == ["demo0_cal.asdf", "demo1_cal.asdf"]
    assert entries(parallel) == entries(sequential)
    assert saved(parallel)["status"] == saved(sequential)["status"] == "complete"
    work = demo.parent / "output/.cache"
    assert not list(work.glob("work-*")), "temporary download folders must be removed"


def test_systematic_failures_stop_early_and_keep_downloads(demo, monkeypatch):
    import gladius.pipeline as module

    calls = archive(demo, monkeypatch)
    real = module.read_exposure

    def broken(path):
        raise RuntimeError(f"File '{path}' was created with a newer package")

    monkeypatch.setattr(module, "read_exposure", broken)
    config = mast_demo(
        demo,
        execution={"continue_on_error": True, "abort_after_repeated_failures": 2},
    )
    with pytest.raises(RepeatedFailureError, match="first 2 parent images"):
        run(config, progress=quiet)
    store = demo.parent / "output/.cache/downloads"
    kept = sorted(p.name for p in store.glob("*/*"))
    assert kept == ["demo0_cal.asdf", "demo1_cal.asdf"]
    assert len(calls["downloads"]) == 2

    # Once the environment is fixed, the kept parents are used, then cleaned up.
    monkeypatch.setattr(module, "read_exposure", real)
    manifest = run(config, progress=quiet)
    assert saved(manifest)["status"] == "complete"
    assert len(calls["downloads"]) == 2, "kept parents must not be downloaded again"
    assert not store.exists()


def test_fail_fast_needs_one_shared_error_before_any_success(demo, monkeypatch):
    import gladius.pipeline as module

    archive(demo, monkeypatch)
    real = module.read_exposure
    count = {"n": 0}

    def sometimes(path):
        count["n"] += 1
        if count["n"] == 1:
            raise RuntimeError("first parent is damaged")
        return real(path)

    monkeypatch.setattr(module, "read_exposure", sometimes)
    config = mast_demo(
        demo, execution={"continue_on_error": True, "abort_after_repeated_failures": 2}
    )
    manifest = run(config, progress=quiet)
    assert saved(manifest)["status"] == "failed"
    assert len(saved(manifest)["errors"]) == 1
    disabled = mast_demo(
        demo, execution={"continue_on_error": True, "abort_after_repeated_failures": 0}
    )
    monkeypatch.setattr(module, "read_exposure", lambda path: (_ for _ in ()).throw(OSError()))
    assert saved(run(disabled, progress=quiet, fresh=True))["status"] == "failed"


def test_off_detector_results_are_cached_so_reruns_do_not_download(demo, monkeypatch):
    calls = archive(demo, monkeypatch)
    config = mast_demo(demo)
    data = config.model_dump(mode="json")
    data["targets"].append({"id": "elsewhere", "ra": 10.0, "dec": 10.0})
    config = RunConfig.model_validate(data)
    first = run(config, progress=quiet)
    assert saved(first)["status"] == "complete"
    assert len(calls["downloads"]) == 2
    second = run(change(config, quality={"autocorrelation_limit": 2.5}), progress=quiet)
    assert len(calls["downloads"]) == 2
    counts = saved(second)["stage_counts"]
    assert counts["off_detector_reused"] == 2 and counts["extracted"] == 0


def test_wcs_failures_are_reported_once_per_parent(demo, monkeypatch):
    import gladius.pipeline as module

    data = load_config(demo).model_dump(mode="json")
    data["targets"].append({"id": "second", "x": 40.0, "y": 40.0})
    data["execution"]["continue_on_error"] = True
    data["execution"]["abort_after_repeated_failures"] = 0
    data["stacks"].update(enabled=False, gif_enabled=False)
    config = RunConfig.model_validate(data)
    errors = iter([0.0011, 0.0038, 0.002, 0.003])

    def validate(*args, **kwargs):
        raise WcsRoundTripError(next(errors), 0.001)

    monkeypatch.setattr(module, "validate_wcs", validate)
    manifest = saved(run(config, progress=quiet))
    assert len(manifest["errors"]) == 2
    first = manifest["errors"][0]
    assert first["targets"] == ["demo-event", "second"]
    assert "up to 0.0038 exceeds 0.001" in first["error"]
    assert sum(e["status"] == "failed" for e in manifest["entries"].values()) == 4


# -------------------------------------------------------------- products and storage


def test_slim_compressed_cutouts_keep_descriptors(demo):
    config = change(
        load_config(demo),
        storage={
            "ancillary_arrays": False,
            "parent_metadata_arrays": False,
            "asdf_compression": "zlib",
        },
        stacks={"enabled": False, "gif_enabled": False},
    )
    manifest_path = run(config, progress=quiet)
    entry = next(iter(saved(manifest_path)["entries"].values()))
    name = next(n for n in entry["files"] if n.endswith(".asdf"))
    cutout = read_cutout(manifest_path.parent / name)
    assert cutout.ancillary_arrays == {}
    assert "roman/var_poisson" in cutout.provenance["omitted_ancillary_arrays"]
    reference = cutout.parent_metadata["custom_top_level"]["reference"]
    assert reference["omitted_array"] is True and reference["shape"] == [4]
    with asdf.open(manifest_path.parent / name) as af:
        assert af.get_array_compression(af.tree["data"]) == "zlib"
    full = run(change(config, storage={"ancillary_arrays": True}), progress=quiet)
    entry = next(iter(saved(full)["entries"].values()))
    name = next(n for n in entry["files"] if n.endswith(".asdf"))
    assert "roman/var_poisson" in read_cutout(full.parent / name).ancillary_arrays


def test_run_outputs_share_cache_files_unless_copies_requested(demo):
    config = change(load_config(demo), stacks={"enabled": False, "gif_enabled": False})
    linked = run(config, progress=quiet)
    manifest = saved(linked)
    assert manifest["stage_counts"]["published"] == 4  # two parents, ASDF and FITS
    entry = next(iter(manifest["entries"].values()))
    asdf_name = next(n for n in entry["files"] if n.endswith(".asdf"))
    cached = demo.parent / "output/.cache/native" / entry["identity"] / "cutout.asdf"
    assert (linked.parent / asdf_name).stat().st_ino == cached.stat().st_ino
    copied = run(change(config, storage={"output_links": "copy"}), progress=quiet)
    assert (copied.parent / asdf_name).stat().st_ino != cached.stat().st_ino
    assert (copied.parent / asdf_name).read_bytes() == cached.read_bytes()


def test_roman_frame_export_keeps_parent_layout(demo):
    config = change(load_config(demo), storage={"formats": ["asdf", "roman_frame"]})
    manifest_path = run(config, progress=quiet)
    manifest = saved(manifest_path)
    assert manifest["status"] == "complete"  # stacks still read the cutout, not the frame
    assert manifest["stage_counts"]["frames_written"] == 2
    entry = next(e for e in manifest["entries"].values() if e["source"].endswith("demo0_cal.asdf"))
    frame_name = next(n for n in entry["files"] if n.endswith("parent-frame.asdf"))
    x0, y0, x1, y1 = entry["mapping"]["parent_valid_bounds_xyxy"]
    with (
        asdf.open(manifest_path.parent / frame_name) as frame,
        asdf.open(demo.parent / "images/demo0_cal.asdf") as parent,
    ):
        roman, original = frame.tree["roman"], parent.tree["roman"]
        assert roman["data"].shape == original["data"].shape == (96, 96)
        np.testing.assert_array_equal(roman["data"][y0:y1, x0:x1], original["data"][y0:y1, x0:x1])
        np.testing.assert_array_equal(
            roman["var_poisson"][y0:y1, x0:x1], original["var_poisson"][y0:y1, x0:x1]
        )
        outside = np.ones((96, 96), bool)
        outside[y0:y1, x0:x1] = False
        assert np.isnan(roman["data"][outside]).all() and np.isnan(roman["err"][outside]).all()
        assert (roman["dq"][outside] == DO_NOT_USE).all()
        assert (roman["dq"][~outside] == original["dq"][~outside]).all()
        assert roman["meta"]["wcsinfo"]["s_region"] == "original parent footprint"
        assert roman["custom_scalar"] == "retain me"
        assert frame.tree["gladius_frame"]["mapping"] == entry["mapping"]
    with pytest.raises(ValueError, match="roman_frame"):
        change(config, storage={"formats": ["roman_frame"]})


# ----------------------------------------------------- ASDF files from newer packages


def rewrite_history(path, old, new):
    data = path.read_bytes()
    assert len(old) == len(new) and data.count(old) >= 1
    path.write_bytes(data.replace(old, new))


def installed_asdf():
    return f"{{name: asdf, version: {asdf.__version__}}}".encode()


def newer_asdf():
    major, rest = asdf.__version__.split(".", 1)
    return f"{{name: asdf, version: {'9' if major != '9' else '8'}.{rest}}}".encode()


def test_parents_from_newer_asdf_releases_are_read_with_one_warning(demo):
    path = demo.parent / "images/demo0_cal.asdf"
    rewrite_history(path, installed_asdf(), newer_asdf())
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        exposure = read_exposure(path)
    assert exposure.arrays["data"].shape == (96, 96)
    messages = [str(w.message) for w in caught if issubclass(w.category, AsdfPackageVersionWarning)]
    assert messages and all(path.name not in m for m in messages)


def test_parents_needing_missing_extensions_still_fail(demo):
    path = demo.parent / "images/demo0_cal.asdf"
    rewrite_history(path, b"extensions/core-1.6.0", b"extensions/cxre-1.6.0")
    with pytest.raises(RuntimeError, match="not installed"):
        read_exposure(path)


def test_standalone_script_reads_newer_asdf_parents(demo, tmp_path):
    script_path = Path(__file__).resolve().parents[1] / "standalone" / "roman_cutouts.py"
    spec = importlib.util.spec_from_file_location("roman_cutouts_newer_asdf", script_path)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    images = demo.parent / "images"
    rewrite_history(images / "demo0_cal.asdf", installed_asdf(), newer_asdf())
    config = tmp_path / "script.yaml"
    config.write_text(
        json.dumps(
            {
                "inputs": {"directory": str(images)},
                "output": str(tmp_path / "out"),
                "targets": [{"id": "centre", "x": 48, "y": 48}],
            }
        )
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", AsdfPackageVersionWarning)
        assert script.main([str(config)]) == 0
    results = saved(tmp_path / "out/manifest.json")["results"]
    assert [r["status"] for r in results] == ["ok", "ok"]


def test_default_wcs_tolerance_accepts_flight_inverse_precision():
    config = RunConfig(targets=[{"id": "a", "x": 1.0, "y": 1.0}])
    assert config.astrometry.roundtrip_tolerance_pixels == 0.01
