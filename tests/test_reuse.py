"""Changing downstream choices must not repeat upstream work or mutate history."""

import json
from contextlib import contextmanager

import pytest

from gladius.config import RunConfig, load_config
from gladius.io import read_cutout, sha256
from gladius.pipeline import run


def change(config, **sections):
    data = config.model_dump(mode="json")
    for name, values in sections.items():
        data[name].update(values)
    return RunConfig.model_validate(data)


def saved(path):
    return json.loads(path.read_text())


def forbidden(*args, **kwargs):
    raise AssertionError("This stage must be reused")


def test_quality_reuses_native_and_records_current_assessment(demo, monkeypatch):
    config = load_config(demo)
    first = run(config, progress=lambda _: None)
    contents = {p: sha256(p) for p in first.parent.rglob("*") if p.is_file()}
    monkeypatch.setattr("gladius.pipeline.make_cutout", forbidden)
    monkeypatch.setattr("gladius.pipeline.read_exposure", forbidden)
    changed = run(change(config, quality={"autocorrelation_limit": 2.6}), progress=lambda _: None)
    assert changed != first and changed.parent.name == "r0002"
    assert saved(changed)["stage_counts"]["extracted"] == 0
    assert saved(changed)["stage_counts"]["quality_measured"] == 2
    assert all(e["quality"]["threshold"] == 2.6 for e in saved(changed)["entries"].values())
    for entry in saved(changed)["entries"].values():
        cutout = read_cutout(changed.parent / next(iter(entry["files"])))
        assert cutout.provenance["configuration"]["quality"]["autocorrelation_limit"] is None
        assert "creation" in cutout.provenance["provenance_scope"]
    assert all(sha256(p) == digest for p, digest in contents.items())


def test_format_and_rgb_additions_do_not_reextract_or_rebuild_old_displays(demo, monkeypatch):
    config = change(load_config(demo), storage={"formats": ["asdf"]})
    first = run(config, progress=lambda _: None)
    original = saved(first.parent / "stack-manifest.json")
    import gladius.pipeline as module

    build = module.build_stacks
    built = []

    def record(entries, directory, subset):
        built.append(subset.stacks.model_dump())
        return build(entries, directory, subset)

    monkeypatch.setattr(module, "make_cutout", forbidden)
    monkeypatch.setattr(module, "read_exposure", forbidden)
    monkeypatch.setattr(module, "build_stacks", record)
    second = run(change(config, storage={"formats": ["asdf", "fits"]}), progress=lambda _: None)
    assert saved(second)["stage_counts"]["serialized"] == 2
    assert built == []
    third = run(change(config, stacks={"rgb_enabled": True}), progress=lambda _: None)
    assert len(built) == 1 and built[0]["rgb_enabled"]
    assert not built[0]["enabled"] and not built[0]["gif_enabled"]
    actual = saved(third.parent / "stack-manifest.json")
    assert actual["products"] == original["products"]
    assert actual["animations"] == original["animations"]


def test_gif_speed_changes_only_animation(demo, monkeypatch):
    config = load_config(demo)
    first = run(config, progress=lambda _: None)
    import gladius.pipeline as module

    build = module.build_stacks
    built = []

    def record(entries, directory, subset):
        built.append(subset.stacks)
        return build(entries, directory, subset)

    monkeypatch.setattr(module, "build_stacks", record)
    second = run(change(config, stacks={"gif_frame_ms": 300}), progress=lambda _: None)
    assert len(built) == 1 and built[0].gif_enabled and not built[0].enabled
    assert (
        saved(first.parent / "stack-manifest.json")["products"]
        == saved(second.parent / "stack-manifest.json")["products"]
    )


def test_dates_membership_new_name_and_fresh(demo, monkeypatch):
    config = load_config(demo)
    first = run(config, progress=lambda _: None)
    monkeypatch.setattr("gladius.pipeline.make_cutout", forbidden)
    second = run(
        change(config, selection={"start": "2026-01-02", "end": "2026-01-03"}),
        progress=lambda _: None,
    )
    assert len(saved(second)["entries"]) == 1
    assert len(saved(first)["entries"]) == 2
    other = run(change(config, run={"name": "another-field"}), progress=lambda _: None)
    assert other.parent.parent.name == "another-field"
    assert other.parent.name == "r0001"
    assert saved(other)["stage_counts"]["native_reused"] == 2
    monkeypatch.undo()
    fresh = run(config, fresh=True, progress=lambda _: None)
    assert fresh != first and saved(fresh)["stage_counts"]["extracted"] == 2


def test_add_remove_targets_reuses_existing_target_only(demo, monkeypatch):
    config = load_config(demo)
    first = run(config, progress=lambda _: None)
    data = config.model_dump(mode="json")
    data["targets"].append({"id": "second", "ra": 270, "dec": -29})
    second_config = RunConfig.model_validate(data)
    second = run(second_config, progress=lambda _: None)
    assert saved(second)["stage_counts"]["extracted"] == 2
    assert saved(second)["stage_counts"]["native_reused"] == 2
    monkeypatch.setattr("gladius.pipeline.make_cutout", forbidden)
    third = run(config, progress=lambda _: None)
    assert len(saved(third)["entries"]) == len(saved(first)["entries"]) == 2


def test_parent_byte_change_and_corrupted_cache(demo, modify_parent):
    config = load_config(demo)
    first = run(config, progress=lambda _: None)
    modify_parent(lambda tree: tree["roman"]["data"].__iadd__(1))
    second = run(config, progress=lambda _: None)
    assert second != first and saved(second)["stage_counts"]["extracted"] == 1
    cache = config.storage.output_directory / ".cache/native"
    native = next(cache.glob("*/cutout.asdf"))
    native.write_bytes(b"broken")
    third = run(config, progress=lambda _: None)
    assert saved(third)["status"] == "complete"


def test_cached_products_do_not_bypass_new_resource_limits(demo):
    config = load_config(demo)
    run(config, progress=lambda _: None)
    with pytest.raises(ValueError, match="max_exposures"):
        run(change(config, stacks={"max_exposures": 1}), progress=lambda _: None)


def test_mast_snapshots_refresh_identity_and_fresh_download(demo, monkeypatch):
    import gladius.pipeline as module

    config = change(
        load_config(demo), inputs={"mode": "mast", "mast_criteria": {"fileSetName": "dataset"}}
    )
    paths = list((demo.parent / "images").glob("*.asdf"))
    rows = [{"filename": p.name, "dataURI": f"mast:roman/{p.name}"} for p in paths]
    mission = object()
    calls = {"queries": 0, "downloads": 0}

    def discover(options):
        calls["queries"] += 1
        return mission, rows

    @contextmanager
    def staged(source, missions, work):
        calls["downloads"] += 1
        yield next(p for p in paths if p.name == source["filename"])

    monkeypatch.setattr(module, "discover", discover)
    monkeypatch.setattr(module, "staged", staged)
    first = run(config, progress=lambda _: None)
    assert calls == {"queries": 1, "downloads": 2}
    second = run(change(config, quality={"autocorrelation_limit": 2.6}), progress=lambda _: None)
    assert calls == {"queries": 1, "downloads": 2}
    assert saved(second)["input_freshness"] == "pinned_verified_snapshot"
    third = run(
        change(config, selection={"start": "2026-01-01", "end": "2026-01-03"}),
        progress=lambda _: None,
    )
    assert calls == {"queries": 2, "downloads": 2}
    assert saved(third)["stage_counts"]["extracted"] == 0
    assert all(
        s["verification"] == "trusted_archive_product_identity" for s in saved(third)["sources"]
    )
    run(config, refresh_inputs=True, progress=lambda _: None)
    assert calls == {"queries": 3, "downloads": 2}
    run(config, fresh=True, progress=lambda _: None)
    assert calls == {"queries": 4, "downloads": 4}
    assert first.exists()


def test_retention_after_cutout_creation_needs_no_new_extraction(demo, monkeypatch):
    config = load_config(demo)
    run(config, progress=lambda _: None)
    monkeypatch.setattr("gladius.pipeline.make_cutout", forbidden)
    second = run(change(config, storage={"retain_full_images": True}), progress=lambda _: None)
    assert len(saved(second)["retained_parents"]) == 2


@pytest.mark.parametrize("name", ["../outside", "bad/name", "CON", "nul", "field name", ".hidden"])
def test_run_names_are_portable_and_cannot_escape_output(demo, name):
    with pytest.raises(ValueError):
        change(load_config(demo), run={"name": name})


def test_quality_cache_corruption_is_remeasured_without_extraction(demo, monkeypatch):
    config = load_config(demo)
    first = run(config, progress=lambda _: None)
    assessment = next((config.storage.output_directory / ".cache/quality").glob("*.json"))
    assessment.write_text('{"bad":')
    monkeypatch.setattr("gladius.pipeline.make_cutout", forbidden)
    # A new named result exposes current counters without mutating the first revision.
    second = run(change(config, run={"name": "rechecked"}), progress=lambda _: None)
    assert saved(second)["stage_counts"]["quality_measured"] == 1
    assert first.exists()


def test_fresh_mast_retention_still_downloads(demo, monkeypatch):
    import gladius.pipeline as module

    config = change(
        load_config(demo), inputs={"mode": "mast"}, storage={"retain_full_images": True}
    )
    paths = list((demo.parent / "images").glob("*.asdf"))
    downloads = []
    monkeypatch.setattr(
        module,
        "discover",
        lambda _: (
            object(),
            [{"filename": p.name, "dataURI": f"mast:roman/{p.name}"} for p in paths],
        ),
    )

    @contextmanager
    def staged(source, missions, work):
        downloads.append(source["filename"])
        yield next(p for p in paths if p.name == source["filename"])

    monkeypatch.setattr(module, "staged", staged)
    run(config, progress=lambda _: None)
    run(config, fresh=True, progress=lambda _: None)
    assert len(downloads) == 4


def test_corrupt_display_starts_new_revision_and_restores_from_cache(demo):
    config = load_config(demo)
    first = run(config, progress=lambda _: None)
    display = saved(first.parent / "stack-manifest.json")["products"][0]
    broken = first.parent / display["path"]
    broken.write_bytes(b"corrupt")
    second = run(config, progress=lambda _: None)
    assert first != second
    assert broken.read_bytes() == b"corrupt"
    assert sha256(second.parent / display["path"]) == display["sha256"]


def test_parent_mutation_during_read_is_rejected(demo, monkeypatch):
    import gladius.pipeline as module

    config = load_config(demo)
    read = module.read_exposure

    def unstable(path):
        result = read(path)
        with path.open("ab") as stream:
            stream.write(b"changed during read")
        return result

    monkeypatch.setattr(module, "read_exposure", unstable)
    with pytest.raises(ValueError, match="changed while reading"):
        run(config, progress=lambda _: None)


def test_new_target_reuses_each_existing_display_product(demo, monkeypatch):
    import gladius.pipeline as module

    config = load_config(demo)
    first = run(config, progress=lambda _: None)
    old_display = saved(first.parent / "stack-manifest.json")
    build = module.build_stacks
    targets_built = []

    def record(entries, directory, subset):
        targets_built.append({e["target_id"] for e in entries.values()})
        return build(entries, directory, subset)

    data = config.model_dump(mode="json")
    data["targets"].append({"id": "new-target", "ra": 270, "dec": -29})
    monkeypatch.setattr(module, "build_stacks", record)
    second = run(RunConfig.model_validate(data), progress=lambda _: None)
    assert targets_built == [{"new-target"}, {"new-target"}]
    new_display = saved(second.parent / "stack-manifest.json")
    for kind in ("products", "animations"):
        original_target = [p for p in new_display[kind] if p["target"] == "demo-event"]
        assert original_target == old_display[kind]


def test_display_dependency_change_keeps_native_pixels(demo, monkeypatch):
    import gladius.pipeline as module

    config = load_config(demo)
    first = run(config, progress=lambda _: None)
    versions = module._versions()
    versions["pillow"] = "simulated-new-renderer"
    monkeypatch.setattr(module, "_versions", lambda: versions)
    monkeypatch.setattr(module, "make_cutout", forbidden)
    build = module.build_stacks
    built = []

    def record(entries, directory, subset):
        built.append(subset.stacks)
        return build(entries, directory, subset)

    monkeypatch.setattr(module, "build_stacks", record)
    second = run(config, progress=lambda _: None)
    assert second != first
    assert saved(second)["stage_counts"]["extracted"] == 0
    assert len(built) == 1 and built[0].gif_enabled and not built[0].enabled


def test_cli_name_override_and_fresh_revision(demo):
    from gladius.cli import main

    assert main(["run", str(demo), "--name", "cli-review"]) == 0
    folder = demo.parent / "output/runs/cli-review"
    assert (folder / "r0001/manifest.json").is_file()
    assert main(["run", str(demo), "--name", "cli-review"]) == 0
    assert not (folder / "r0002").exists()
    assert main(["run", str(demo), "--name", "cli-review", "--fresh"]) == 0
    second = saved(folder / "r0002/manifest.json")
    assert second["stage_counts"]["extracted"] == 2


def test_validation_policy_and_tolerance_do_not_reextract_pixels(demo, monkeypatch):
    config = change(load_config(demo), astrometry={"mode": "use"})
    first = run(config, progress=lambda _: None)
    monkeypatch.setattr("gladius.pipeline.make_cutout", forbidden)
    monkeypatch.setattr("gladius.pipeline.read_exposure", forbidden)
    validated = change(config, astrometry={"mode": "validate", "roundtrip_tolerance_pixels": 0.01})
    second = run(validated, progress=lambda _: None)
    assert second != first
    assert saved(second)["stage_counts"]["extracted"] == 0
    assert all(
        e["astrometry_validation"]["check"] != "not_requested"
        for e in saved(second)["entries"].values()
    )
    third = run(
        change(validated, astrometry={"roundtrip_tolerance_pixels": 0.001}), progress=lambda _: None
    )
    assert saved(third)["stage_counts"]["extracted"] == 0


def test_output_lock_protects_shared_cache_across_names(demo):
    from filelock import FileLock, Timeout

    config = load_config(demo)
    first = run(config, progress=lambda _: None)
    original = first.read_bytes()
    with FileLock(str(config.storage.output_directory / ".pipeline.lock")):
        with pytest.raises(Timeout):
            run(change(config, run={"name": "competing-run"}), progress=lambda _: None)
    assert first.read_bytes() == original
    assert not (config.storage.output_directory / "runs/competing-run").exists()


def test_refresh_downloads_only_new_archive_members(demo, monkeypatch):
    from copy import deepcopy

    import asdf

    import gladius.pipeline as module

    config = change(load_config(demo), inputs={"mode": "mast"})
    paths = {p.name: p for p in (demo.parent / "images").glob("*.asdf")}
    rows = [{"filename": name, "dataURI": f"mast:roman/{name}"} for name in sorted(paths)]
    downloads = []
    monkeypatch.setattr(module, "discover", lambda _: (object(), rows))

    @contextmanager
    def staged(source, missions, work):
        downloads.append(source["filename"])
        yield paths[source["filename"]]

    monkeypatch.setattr(module, "staged", staged)
    first = run(config, progress=lambda _: None)
    with asdf.open(next(iter(paths.values())), lazy_load=False, memmap=False) as af:
        tree = deepcopy(dict(af.tree))
    tree["roman"]["data"] *= 3
    extra = demo.parent / "images/new_cal.asdf"
    asdf.AsdfFile(tree).write_to(extra)
    paths[extra.name] = extra
    rows.append({"filename": extra.name, "dataURI": f"mast:roman/{extra.name}"})
    second = run(config, refresh_inputs=True, progress=lambda _: None)
    assert len(downloads) == 3 and downloads[-1] == extra.name
    assert saved(second)["stage_counts"]["extracted"] == 1
    assert saved(second)["stage_counts"]["native_reused"] == 2
    assert len(saved(first)["entries"]) == 2
    assert len(saved(second)["entries"]) == 3


def test_fits_only_to_asdf_does_not_need_parent_or_new_extraction(demo, monkeypatch):
    config = change(load_config(demo), storage={"formats": ["fits"]})
    run(config, progress=lambda _: None)
    monkeypatch.setattr("gladius.pipeline.make_cutout", forbidden)
    monkeypatch.setattr("gladius.pipeline.read_exposure", forbidden)
    second = run(change(config, storage={"formats": ["asdf"]}), progress=lambda _: None)
    assert all(list(e["files"])[0].endswith(".asdf") for e in saved(second)["entries"].values())


def test_retry_transient_serialization_failure_resumes_incomplete_revision(demo, monkeypatch):
    import gladius.pipeline as module

    config = load_config(demo)
    write = module.write_cutout
    failed = False

    def transient(cutout, folder, formats=("asdf", "fits"), **kwargs):
        nonlocal failed
        if list(formats) == ["fits"] and not failed:
            failed = True
            raise RuntimeError("temporary write failure")
        return write(cutout, folder, formats, **kwargs)

    monkeypatch.setattr(module, "write_cutout", transient)
    with pytest.raises(RuntimeError, match="temporary write failure"):
        run(config, progress=lambda _: None)
    original = config.storage.output_directory / "runs/default/r0001/manifest.json"
    assert saved(original)["status"] == "failed"
    resumed = run(config, progress=lambda _: None)
    assert resumed == original
    assert saved(resumed)["status"] == "complete"
    assert saved(resumed)["stage_counts"]["native_reused"] == 1
    assert saved(resumed)["stage_counts"]["extracted"] == 1
