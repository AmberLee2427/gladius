import json
from copy import deepcopy

import asdf
import numpy as np
import pytest
import yaml
from astropy.io import fits
from astropy.modeling.models import Shift

from gladius_roman.cli import main
from gladius_roman.config import load_config
from gladius_roman.io import read_cutout, sha256
from gladius_roman.pipeline import run


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
        assert hdul["COVERAGE"].data.max() == 2
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
    for limits, message in [({"max_exposures": 1, "max_memory_mb": 0}, "max_exposures"),
                            ({"max_exposures": 0, "max_memory_mb": 1}, "max_memory_mb")]:
        config = configure(demo, stacks={"enabled": True, **limits}, extraction={"size": 150})
        with pytest.raises(ValueError, match=message):
            run(config, progress=lambda _: None)
        records = list(config.storage.output_directory.glob("runs/*/manifest.json"))
        failed = [json.loads(p.read_text()) for p in records if json.loads(p.read_text())["status"] == "failed"]
        assert failed and all(entry["status"] == "complete" for entry in failed[-1]["entries"].values())
        assert len(failed[-1]["entries"]) == 2
