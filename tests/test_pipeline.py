import json
from copy import deepcopy

import asdf
import numpy as np
import pytest
import yaml
from astropy.io import fits
from astropy.modeling.models import Shift

from gladius.cli import main
from gladius.config import load_config
from gladius.io import read_cutout, sha256
from gladius.pipeline import run


def configure(demo, **sections):
    data = yaml.safe_load(demo.read_text())
    data.update(sections)
    demo.write_text(yaml.safe_dump(data))
    return load_config(demo)


def test_full_offline_run_resume_and_stack(demo):
    config = load_config(demo)
    manifest = run(config, progress=lambda _: None)
    saved = json.loads(manifest.read_text())
    assert saved["status"] == "complete" and len(saved["entries"]) == 2
    outputs = [manifest.parent / path for e in saved["entries"].values() for path in e["files"]]
    times = [p.stat().st_mtime_ns for p in outputs]
    run(config, progress=lambda _: None)
    assert times == [p.stat().st_mtime_ns for p in outputs]
    stacks = json.loads((manifest.parent / "stack-manifest.json").read_text())
    assert len(stacks["products"]) == 1 and len(stacks["products"][0]["inputs"]) == 2
    with fits.open(manifest.parent / stacks["products"][0]["path"]) as hdul:
        assert hdul[0].header["PREVIEW"] and hdul[0].header["RESAMPLE"]
        coverage = hdul["COVERAGE"].data
        assert coverage.max() == 2
        # The fully valid reference covers its entire own output grid. Tiny WCS
        # roundtrip errors must not punch holes along its boundary.
        assert coverage.min() == 1
        assert np.isfinite(hdul[0].data).all()
        # The other exposure is offset by half a cutout pixel: its genuinely
        # uncovered edge must remain excluded rather than being extrapolated.
        assert np.count_nonzero(coverage == 1) == 64
        assert np.nanmax(hdul[0].data) > 90
    assert not (demo.parent / "output/parents").exists()
    assert len(list((demo.parent / "images").iterdir())) == 2
    # A corrupted file cannot be trusted merely because a manifest says complete.
    bad = outputs[0]
    bad.write_bytes(b"broken")
    run(config, progress=lambda _: None)
    assert sha256(bad) == next(
        e["files"][str(bad.relative_to(manifest.parent))]
        for e in saved["entries"].values()
        if str(bad.relative_to(manifest.parent)) in e["files"]
    )


def test_selection_retention_and_failures(demo):
    config = configure(
        demo,
        selection={"start": "2026-01-02", "end": "2026-01-03", "detectors": [1]},
        storage={"output_directory": "selected", "retain_full_images": True, "formats": ["fits"]},
    )
    path = run(config, progress=lambda _: None)
    manifest = json.loads(path.read_text())
    assert len(manifest["entries"]) == 1 and len(manifest["selection_rejections"]) == 1
    assert len(manifest["retained_parents"]) == 1
    assert next((demo.parent / "selected/parents").rglob("*.asdf")).exists()
    configure(demo, selection={"detectors": [2]})
    with pytest.raises(ValueError, match="No parent"):
        run(load_config(demo), progress=lambda _: None)


def test_correction_changes_identity_and_preserves_parent_wcs(demo):
    corrections = demo.parent / "corrections"
    corrections.mkdir()
    originals = {}
    for image in (demo.parent / "images").glob("*.asdf"):
        with asdf.open(image, lazy_load=False) as af:
            wcs = deepcopy(af.tree["roman"]["meta"]["wcs"])
        originals[image.stem] = wcs
        asdf.AsdfFile({"wcs": wcs, "solution": "test corrected product"}).write_to(
            corrections / f"{image.stem}_gaiawcs.asdf"
        )
    config = configure(demo, astrometry={"mode": "corrected", "corrected_directory": "corrections"})
    path = run(config, progress=lambda _: None)
    first = json.loads(path.read_text())
    change = corrections / "demo0_cal_gaiawcs.asdf"
    wcs = deepcopy(originals["demo0_cal"])
    wcs.insert_transform(wcs.input_frame, Shift(0.2) & Shift(-0.3), after=True)
    change.unlink()
    asdf.AsdfFile({"wcs": wcs, "solution": "changed correction"}).write_to(change)
    run(config, progress=lambda _: None)
    second = json.loads(path.read_text())
    changed = [
        key
        for key in first["entries"]
        if first["entries"][key]["identity"] != second["entries"][key]["identity"]
    ]
    assert len(changed) == 1
    row = second["entries"][changed[0]]
    c = read_cutout(path.parent / next(iter(row["files"])))
    assert c.provenance["correction"]["parent_metadata"]["solution"] == "changed correction"
    np.testing.assert_allclose(c.parent_wcs(48, 48), originals["demo0_cal"](48, 48))
    assert not c.provenance["astrometry_validation"]["absolute_astrometry_validated"]


def test_cli_validation_failure_exit_and_quality_retains_native(demo, tmp_path):
    assert main(["init-config", str(tmp_path / "example.yaml")]) == 0
    assert main(["init-config", str(tmp_path / "example.yaml")]) == 1
    assert main(["validate", str(demo)]) == 0
    assert main(["config-schema", str(tmp_path / "schema.json")]) == 0
    configure(
        demo,
        extraction={"size": 16},
        quality={"autocorrelation_limit": 2.6},
        execution={"continue_on_error": True},
    )
    assert main(["run", str(demo)]) == 0
    # Both products exist even though a 64-pixel screen cannot assess a 16-pixel cutout.
    manifest = next((demo.parent / "output/runs").glob("*/manifest.json"))
    data = json.loads(manifest.read_text())
    assert len(data["entries"]) == 2
    assert all(not e["quality"]["accepted"] for e in data["entries"].values())
    assert json.loads((manifest.parent / "stack-manifest.json").read_text())["products"] == []
    configure(demo, astrometry={"mode": "corrected", "corrected_directory": "missing"})
    assert main(["run", str(demo)]) == 1


def test_unlimited_stacks_and_preserved_cutouts_on_limit_failure(demo):
    config = configure(demo, stacks={"enabled": True, "max_exposures": 0, "max_memory_mb": 0})
    manifest = run(config, progress=lambda _: None)
    assert json.loads(manifest.read_text())["status"] == "complete"
    assert len(json.loads((manifest.parent / "stack-manifest.json").read_text())["products"]) == 1
    for limits, message in [
        ({"max_exposures": 1, "max_memory_mb": 0}, "max_exposures"),
        ({"max_exposures": 0, "max_memory_mb": 1}, "max_memory_mb"),
    ]:
        config = configure(demo, stacks={"enabled": True, **limits}, extraction={"size": 150})
        with pytest.raises(ValueError, match=message):
            run(config, progress=lambda _: None)
        records = list(config.storage.output_directory.glob("runs/*/manifest.json"))
        failed = [
            json.loads(p.read_text())
            for p in records
            if json.loads(p.read_text())["status"] == "failed"
        ]
        assert failed and all(
            entry["status"] == "complete" for entry in failed[-1]["entries"].values()
        )
        assert len(failed[-1]["entries"]) == 2


def test_stack_boundary_roundoff_does_not_extend_real_coverage():
    from gladius.stacks import _snap_to_image_edges

    coordinates = np.array([-0.5, -1e-9, 0.0, 1.5, 63 + 1e-9, 63.5, np.nan])
    snapped = _snap_to_image_edges(coordinates, 64)
    np.testing.assert_allclose(snapped, [-0.5, 0, 0, 1.5, 63, 63.5, np.nan])


def test_animation_only_records_time_order_and_playback(demo):
    from PIL import Image

    config = configure(demo, stacks={"enabled": False, "gif_enabled": True, "gif_frame_ms": 240})
    manifest_path = run(config, progress=lambda _: None)
    saved = json.loads((manifest_path.parent / "stack-manifest.json").read_text())
    assert saved["products"] == []
    (animation,) = saved["animations"]
    assert [f["start_utc"][:10] for f in animation["frames"]] == ["2026-01-01", "2026-01-02"]
    assert animation["display_only"] and animation["resampled"]
    path = manifest_path.parent / animation["path"]
    assert sha256(path) == animation["sha256"]
    with Image.open(path) as gif:
        assert gif.n_frames == 2 and gif.info["loop"] == 0
        first = gif.convert("RGB").copy()
        for index in range(gif.n_frames):
            gif.seek(index)
            assert gif.info["duration"] == 240
        assert np.any(np.asarray(first) != np.asarray(gif.convert("RGB")))
    assert not list(manifest_path.parent.rglob("*.tmp"))


def test_animation_uses_one_stretch_and_marks_missing_pixels(tmp_path):
    from PIL import Image

    from gladius.stacks import _write_animation

    cube = np.array([[[0.0, 1.0, np.nan]], [[0.0, 2.0, np.nan]]])
    path = tmp_path / "preview.gif"
    _write_animation(cube, path, 500, [{"start_utc": None}, {"start_utc": None}])
    with Image.open(path) as gif:
        gif.seek(0)
        first = np.asarray(gif.convert("RGB")).copy()
        gif.seek(1)
        second = np.asarray(gif.convert("RGB"))
        # Header is 34 pixels; each input pixel is repeated four times.
        start = (gif.width - 12) // 2
        assert first[34, start + 4, 0] < second[34, start + 4, 0]
        np.testing.assert_array_equal(first[34, start + 8], [34, 22, 46])


def test_colour_composite_without_stack_or_gif(demo):
    from PIL import Image

    original = demo.parent / "images/demo0_cal.asdf"
    with asdf.open(original, lazy_load=False, memmap=False) as af:
        tree = deepcopy(dict(af.tree))
    for index, band in enumerate(("F062", "F184", "F213")):
        changed = deepcopy(tree)
        changed["roman"]["meta"]["instrument"]["optical_element"] = band
        changed["roman"]["data"] *= index + 1
        # A bad pixel in any one channel must be grey in the combined PNG.
        if band == "F184":
            changed["roman"]["dq"][40, 40] = 1
        asdf.AsdfFile(changed).write_to(demo.parent / f"images/colour{index}_cal.asdf")
    config = configure(demo, stacks={"rgb_enabled": True, "blue_filter": "f062"})
    path = run(config, progress=lambda _: None)
    manifest = json.loads((path.parent / "stack-manifest.json").read_text())
    assert (
        not manifest["products"] and not manifest["animations"] and not manifest["composite_skips"]
    )
    (composite,) = manifest["composites"]
    assert composite["channel_filters"] == {"red": "F213", "green": "F184", "blue": "F062"}
    assert composite["display_only"] and not composite["physical_colours"]
    assert all(len(inputs) == 1 for inputs in composite["inputs_by_filter"].values())
    assert composite["reference"] == composite["inputs_by_filter"]["F062"][0]
    assert composite["zscale_limits"]["F213"][1] > composite["zscale_limits"]["F062"][1]
    assert sha256(path.parent / composite["path"]) == composite["sha256"]
    with Image.open(path.parent / composite["path"]) as png:
        pixels = np.asarray(png)
    # Independent normalization removes a multiplicative difference between bands.
    assert np.abs(pixels[..., 0].astype(int) - pixels[..., 2]).max() <= 1
    assert np.any(np.all(pixels == 64, axis=-1))


def test_colour_missing_filters_are_reported(demo):
    path = run(configure(demo, stacks={"rgb_enabled": True}), progress=lambda _: None)
    manifest = json.loads((path.parent / "stack-manifest.json").read_text())
    assert manifest["composites"] == []
    assert manifest["composite_skips"] == [
        {
            "target": "demo-event",
            "reason": "missing eligible filters",
            "filters": ["F062", "F184", "F213"],
        }
    ]


def test_colour_reprojects_every_filter_on_the_same_reference(demo, monkeypatch):
    import gladius.stacks as module

    path = run(configure(demo, stacks={"enabled": False}), progress=lambda _: None)
    entries = list(json.loads(path.read_text())["entries"].items())
    groups = {
        ("demo-event", band): [entries[i % 2]] for i, band in enumerate(("F062", "F184", "F213"))
    }
    refs = []
    align = module._aligned_exposures

    def record_reference(rows, directory, reference):
        refs.append(reference)
        return align(rows, directory, reference)

    monkeypatch.setattr(module, "_aligned_exposures", record_reference)
    products, skipped = module._build_composites(
        groups, path.parent, configure(demo, stacks={"rgb_enabled": True})
    )
    assert len(products) == 1 and not skipped
    assert len(refs) == 3 and all(ref is refs[0] for ref in refs)
