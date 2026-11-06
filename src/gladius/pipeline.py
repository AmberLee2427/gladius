"""Dependency-aware, exposure-first execution with named revisions."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import yaml
from filelock import FileLock

from . import __version__
from .cache import copy_files, fingerprint, implementation, load_record, publish, valid_files
from .config import RunConfig
from .core import OffDetectorError, check_correction_matches_parent, make_cutout, validate_wcs
from .inputs import discover, selected, staged
from .io import atomic_json, read_correction, read_cutout, read_exposure, sha256, write_cutout
from .quality import assess
from .stacks import build_stacks


def _versions():
    result = {}
    for name in (
        "numpy",
        "astropy",
        "asdf",
        "gwcs",
        "roman_datamodels",
        "rad",
        "asdf-astropy",
        "scipy",
        "pillow",
        "astroquery",
    ):
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = None
    return result


def _read_cache_json(path):
    try:
        record = json.loads(path.read_text())
        data = record["payload"]
        return data if fingerprint(data) == record["sha256"] else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_cache_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(path, {"payload": data, "sha256": fingerprint(data)})


def _file_identity(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _stable_hash(path):
    before = path.stat()
    digest = sha256(path)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ino,
    ):
        raise ValueError("Input changed while hashing; retry with stable inputs")
    return digest


def _row_dict(row):
    result = {}
    for name in row.colnames if hasattr(row, "colnames") else row:
        value = row[name]
        if hasattr(value, "item"):
            value = value.item()
        if isinstance(value, bytes):
            value = value.decode()
        result[name] = (
            value if isinstance(value, (str, int, float, bool, type(None))) else str(value)
        )
    return result


def _archive_identity(source, config):
    for field in ("dataURI", "dataUri", "data_uri", "product_id"):
        if source.get(field):
            return fingerprint({"mission": "roman", field: str(source[field])})
    dataset = (
        source.get("fileSetName")
        or source.get("parent_id")
        or config.inputs.mast_criteria.get("fileSetName")
    )
    return fingerprint(
        {"mission": "roman", "dataset": dataset, "filename": str(source["filename"])}
    )


def _validator(source):
    """Only a digest supplied by the archive is an identity validator; size is not."""
    for name in ("sha256", "md5", "checksum"):
        value = str(source.get(name, "")).lower().strip()
        value = value.removeprefix("sha256:").removeprefix("md5:")
        if len(value) in (32, 64) and all(c in "0123456789abcdef" for c in value):
            return ("sha256" if len(value) == 64 else "md5", value)
    return None


def _latest(folder):
    revisions = sorted(
        (p for p in folder.glob("r[0-9]*/manifest.json") if p.parent.name[1:].isdigit()),
        key=lambda p: int(p.parent.name[1:]),
    )
    if not revisions:
        return None
    try:
        return revisions[-1], json.loads(revisions[-1].read_text())
    except (ValueError, OSError):
        return None


def _revision_intact(manifest, directory):
    if not all(
        e["status"] != "complete" or valid_files(e, directory) for e in manifest["entries"].values()
    ):
        return False
    options = manifest["configuration"]["stacks"]
    if any(options[k] for k in ("enabled", "gif_enabled", "rgb_enabled")):
        try:
            display = json.loads((directory / "stack-manifest.json").read_text())
            for kind in ("products", "animations", "composites"):
                for product in display[kind]:
                    path = directory / product["path"]
                    if not path.is_file() or sha256(path) != product["sha256"]:
                        return False
        except (OSError, ValueError, KeyError):
            return False
    return True


def _discovery_signature(config):
    return fingerprint(
        {
            "inputs": config.inputs.model_dump(mode="json"),
            "selection": config.selection.model_dump(mode="json"),
            "positions": sorted({(t.ra, t.dec) for t in config.targets if t.ra is not None}),
            "implementation": implementation("inputs.py"),
        }
    )


def _native_identity(config, target, parent_digest, correction_digest, versions):
    return fingerprint(
        {
            "source": parent_digest,
            "target": target.model_dump(mode="json"),
            "extraction": config.extraction.model_dump(mode="json"),
            "astrometry": {
                "source": "corrected" if config.astrometry.mode == "corrected" else "original",
                "correction": correction_digest,
            },
            "implementation": implementation("core.py", "io.py"),
            "native_stage": fingerprint(inspect.getsource(_native)),
            "dependencies": {
                name: value
                for name, value in versions.items()
                if name not in {"scipy", "pillow", "astroquery"}
            },
        }
    )


@contextmanager
def _parent(record, missions, work, retained):
    """Use an already verified retained parent, otherwise stage one remote image."""
    path = retained.get(record.get("digest"))
    if path and Path(path).is_file() and _stable_hash(Path(path)) == record["digest"]:
        yield Path(path)
    elif record.get("local"):
        yield Path(record["source"])
    else:
        if missions is None:
            from astroquery.mast import MastMissions

            missions = MastMissions(mission="roman")
            if os.environ.get("MAST_API_TOKEN"):
                missions.login(token=os.environ["MAST_API_TOKEN"], store_token=False)
        with staged(record["source"], missions, work) as path:
            yield path


def _retain(path, digest, output):
    destination = output / "parents" / digest / path.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.is_file() or sha256(destination) != digest:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
            temporary = Path(stream.name)
        try:
            shutil.copyfile(path, temporary)
            if sha256(temporary) != digest:
                raise ValueError("Parent changed while copying retained image")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    return str(destination)


def _native(
    config, target, path, exposure, digest, correction, native_directory, versions, settings
):
    wcs = correction["applied_parent_wcs"] if correction else exposure.wcs
    cutout = make_cutout(
        exposure.arrays,
        wcs,
        target,
        extraction=config.extraction,
        parent_wcs=exposure.wcs,
        parent_metadata=exposure.parent_metadata,
        ancillary_arrays=exposure.ancillary_arrays,
        provenance={
            "parent_filename": path.name,
            "parent_sha256": digest,
            "source": str(path) if config.inputs.mode == "directory" else path.name,
            "exposure": exposure.summary,
            "astrometry_mode": config.astrometry.mode,
            "astrometry_validation": {
                "check": "recorded_in_revision_manifest",
                "absolute_astrometry_validated": False,
            },
            "correction": correction,
            "configuration": settings,
            "dependencies": versions,
            "implementation_sha256": fingerprint(implementation("core.py", "io.py")),
            "centering": "floor(position)-(size-1)//2",
            "ancillary_padding": "floating:NaN; integer:0; dq/pixeldq:DO_NOT_USE",
            "provenance_scope": "creation record; current quality and settings are in the revision manifest",
        },
    )
    return publish(
        native_directory,
        lambda folder: [p.name for p in write_cutout(cutout, folder, ["asdf"])],
        {"mapping": cutout.mapping},
    )


def _assess_astrometry(canonical, native, config, cache, versions, fresh):
    """Changing a numerical check does not change the pixels or selected WCS."""
    identity = fingerprint(
        {
            "native": native["files"],
            "policy": "use" if config.astrometry.mode == "use" else "validate",
            "tolerance": config.astrometry.roundtrip_tolerance_pixels,
            "implementation": implementation("core.py"),
            "dependencies": {k: versions[k] for k in ("numpy", "astropy", "gwcs")},
        }
    )
    path = cache / "validation" / f"{identity}.json"
    result = None if fresh else _read_cache_json(path)
    if result is not None:
        return result
    result = {"check": "not_requested", "absolute_astrometry_validated": False}
    if config.astrometry.mode != "use":
        cutout = read_cutout(canonical)
        correction = cutout.provenance.get("correction")
        parent = correction["applied_parent_wcs"] if correction else cutout.parent_wcs
        result = validate_wcs(
            parent,
            cutout.mapping["parent_shape_yx"],
            config.astrometry.roundtrip_tolerance_pixels,
            points=[cutout.provenance["predicted_parent_xy"]],
        )
        validate_wcs(
            cutout.wcs, cutout.arrays["data"].shape, config.astrometry.roundtrip_tolerance_pixels
        )
    _write_cache_json(path, result)
    return result


def _display(entries, directory, config, cache, versions, fresh, progress):
    combined = {
        "products": [],
        "animations": [],
        "composites": [],
        "composite_skips": [],
        "excluded": [
            {"input": key, "quality": e["quality"]}
            for key, e in sorted(entries.items())
            if e["status"] == "complete"
            and config.quality.exclude_from_stacks
            and not e["quality"]["accepted"]
        ],
        "note": "Display products; native cutouts unchanged. No photometric or PSF matching.",
    }
    eligible = {
        key: entry
        for key, entry in sorted(entries.items())
        if entry["status"] == "complete"
        and (not config.quality.exclude_from_stacks or entry["quality"]["accepted"])
    }
    groups = sorted({(e["target_id"], e["filter"]) for e in eligible.values()})
    requests = []
    for target, band in groups:
        if config.stacks.enabled:
            requests.append(("median", target, band))
        if config.stacks.gif_enabled:
            requests.append(("gif", target, band))
    if config.stacks.rgb_enabled:
        requests.extend(("rgb", target, None) for target in sorted({t for t, _ in groups}))
    for kind, target, band in requests:
        channels = {config.stacks.red_filter, config.stacks.green_filter, config.stacks.blue_filter}
        inputs = {
            key: deepcopy(entry)
            for key, entry in eligible.items()
            if entry["target_id"] == target
            and (entry["filter"] == band if kind != "rgb" else entry["filter"] in channels)
        }
        # Keep an unrelated eligible band only to let the renderer report missing RGB
        # channels for this target. It is never included in the composite itself.
        if kind == "rgb" and not inputs:
            inputs = {
                key: deepcopy(entry)
                for key, entry in eligible.items()
                if entry["target_id"] == target
            }
        members = {
            key: {"native": e["identity"], "canonical_sha256": e["native_sha256"]}
            for key, e in inputs.items()
        }
        options = {
            "max_exposures": config.stacks.max_exposures,
            "max_memory_mb": config.stacks.max_memory_mb,
        }
        if kind == "gif":
            options["frame_ms"] = config.stacks.gif_frame_ms
        elif kind == "median":
            options["fits_tolerance"] = config.astrometry.fits_tolerance_pixels
        else:
            options["filters"] = [
                config.stacks.red_filter,
                config.stacks.green_filter,
                config.stacks.blue_filter,
            ]
        identity = fingerprint(
            {
                "kind": kind,
                "target": target,
                "filter": band,
                "members": members,
                "options": options,
                "implementation": implementation("stacks.py"),
                "dependencies": {
                    k: versions[k]
                    for k in (
                        ("numpy", "scipy", "astropy")
                        if kind == "median"
                        else ("numpy", "scipy", "astropy", "pillow")
                    )
                },
            }
        )
        folder = cache / "display" / identity
        record = None if fresh else load_record(folder)
        if record is None:
            progress(f"Building {kind} display: {target}" + (f" / {band}" if band else ""))
            data = config.model_dump(mode="json")
            data["stacks"].update(
                enabled=kind == "median", gif_enabled=kind == "gif", rgb_enabled=kind == "rgb"
            )
            subset = RunConfig.model_validate(data)
            for entry in inputs.values():
                entry["files"] = {
                    str((directory / name).resolve()): digest
                    for name, digest in entry["files"].items()
                }
            record = publish(
                folder,
                lambda temporary, inputs=inputs, subset=subset: build_stacks(
                    inputs, temporary, subset
                ),
            )
        else:
            progress(f"Reusing {kind} display: {target}" + (f" / {band}" if band else ""))
        # Category manifests are combined below; copying them would clobber the
        # current revision's membership if rendering stops partway through.
        product_record = {
            **record,
            "files": {
                name: digest
                for name, digest in record["files"].items()
                if name != "stack-manifest.json"
            },
        }
        copy_files(product_record, folder, directory)
        for field in ("products", "animations", "composites", "composite_skips"):
            combined[field].extend(record["result"][field])
    atomic_json(directory / "stack-manifest.json", combined)


def run(config: RunConfig, *, progress=print, fresh=False, refresh_inputs=False) -> Path:
    """Run selected inputs, reusing verified stage products in named revisions.

    MAST discovery is pinned until its settings change or refresh_inputs=True.
    A refresh trusts stable archive product identities; fresh=True forces downloads.
    fresh=True (or execution.resume=False) bypasses all reuse and starts a revision.
    """
    config = config.resolved(Path.cwd())
    settings = config.model_dump(mode="json")
    output = config.storage.output_directory
    output.mkdir(parents=True, exist_ok=True)
    with FileLock(str(output / ".pipeline.lock"), timeout=config.execution.lock_timeout_seconds):
        return _run_locked(
            config, settings, progress, fresh or not config.execution.resume, refresh_inputs
        )


def _run_locked(config, settings, progress, fresh, refresh_inputs):
    output = config.storage.output_directory
    cache = output / ".cache"
    cache.mkdir(exist_ok=True)
    versions = _versions()
    folder = output / "runs" / config.run.name
    folder.mkdir(parents=True, exist_ok=True)
    previous = _latest(folder)
    discovery_id = _discovery_signature(config)
    snapshot_path = cache / "discovery" / f"{discovery_id}.json"
    pinned = None
    if (
        config.inputs.mode == "mast"
        and not fresh
        and not refresh_inputs
        and snapshot_path.is_file()
    ):
        pinned = _read_cache_json(snapshot_path)
    retained = {}
    if previous and not fresh:
        retained.update(previous[1].get("retained_parents", {}))
    manifest = {
        "schema_version": 2,
        "package_version": __version__,
        "dependencies": versions,
        "configuration": settings,
        "run_name": config.run.name,
        "started_utc": datetime.now(UTC).isoformat(),
        "status": "running",
        "entries": {},
        "errors": [],
        "selection_rejections": [],
        "retained_parents": {},
        "sources": [],
        "discovery_signature": discovery_id,
        "input_freshness": "pinned_verified_snapshot" if pinned else "refreshed",
        "archive_reuse_policy": "trust stable MAST product identity; original parent SHA256 is retained; --fresh downloads again",
        "discovery_snapshot_created_utc": pinned.get("created_utc") if pinned else None,
        "stage_counts": {
            "extracted": 0,
            "native_reused": 0,
            "quality_measured": 0,
            "quality_reused": 0,
            "serialized": 0,
        },
    }
    failure = None
    with tempfile.TemporaryDirectory(prefix="work-", dir=cache) as work_name:
        work = Path(work_name)
        try:
            if pinned:
                sources = deepcopy(pinned["sources"])
                missions = None
                progress("Using pinned MAST source snapshot; use --refresh-inputs to query again")
            else:
                missions, raw_sources = discover(config)
                sources = [
                    {
                        "source": str(source) if missions is None else _row_dict(source),
                        "local": missions is None,
                    }
                    for source in raw_sources
                ]
            manifest["plan_identity"] = fingerprint(
                {
                    "settings": settings,
                    "sources": [record["source"] for record in sources],
                    "implementation": implementation(
                        "pipeline.py", "cache.py", "core.py", "io.py", "quality.py", "stacks.py"
                    ),
                    "dependencies": versions,
                }
            )
            old_remote = {}
            for path in (cache / "discovery").glob("*.json"):
                try:
                    saved = _read_cache_json(path)
                    for record in saved["sources"] if saved else []:
                        if not record["local"] and record.get("digest") and record.get("summary"):
                            old_remote[record["archive_identity"]] = record
                except (ValueError, OSError, KeyError):
                    continue
            for source_record in sources:
                source = source_record["source"]
                if not source_record["local"]:
                    source_record.setdefault("archive_identity", _archive_identity(source, config))
                prior = old_remote.get(source_record.get("archive_identity"))
                # A changed archive checksum means different bytes behind the same identity.
                if prior and _validator(prior["source"]) != _validator(source):
                    prior = None
                if prior and not fresh and not pinned:
                    source_record.update(
                        digest=prior["digest"],
                        summary=prior["summary"],
                        summary_reader=prior.get("summary_reader"),
                    )
                    source_record["verification"] = "trusted_archive_product_identity"
                elif pinned:
                    source_record["verification"] = "pinned_verified_bytes"
                elif source_record["local"]:
                    source_record["digest"] = _stable_hash(Path(source))
                    source_record["verification"] = "local_sha256"
                try:
                    with _process_parent(
                        source_record,
                        missions,
                        work,
                        retained,
                        cache,
                        config,
                        versions,
                        settings,
                        progress,
                        fresh,
                        manifest,
                    ) as record:
                        if record is not None:
                            manifest["sources"].append(record)
                except Exception as exc:
                    source_record["error"] = f"{type(exc).__name__}: {exc}"
                    manifest["sources"].append(source_record)
                    manifest["errors"].append(
                        {"source": str(source), "error": source_record["error"]}
                    )
                    if not config.execution.continue_on_error:
                        raise
            if not manifest["sources"]:
                raise ValueError("No parent exposures passed the selection")
            if config.inputs.mode == "mast" and not pinned and not manifest["errors"]:
                snapshot_path.parent.mkdir(parents=True, exist_ok=True)
                created = datetime.now(UTC).isoformat()
                _write_cache_json(
                    snapshot_path, {"created_utc": created, "sources": manifest["sources"]}
                )
                manifest["discovery_snapshot_created_utc"] = created
        except BaseException as exc:
            failure = exc
            manifest["errors"].append({"error": f"{type(exc).__name__}: {exc}"})
    identity = fingerprint(
        {
            "settings": settings,
            "sources": [
                {k: s.get(k) for k in ("source", "digest", "correction_digest")}
                for s in manifest["sources"]
            ],
            "dependencies": versions,
            "quality": implementation("quality.py"),
            "pipeline": implementation("pipeline.py", "cache.py", "core.py", "io.py"),
            "display": implementation("stacks.py"),
            "display_dependencies": {
                k: versions[k] for k in ("numpy", "scipy", "astropy", "pillow")
            }
            if any((config.stacks.enabled, config.stacks.gif_enabled, config.stacks.rgb_enabled))
            else {},
        }
    )
    directory = None
    if previous and not fresh and previous[1].get("revision_identity") == identity:
        old_path, old = previous
        intact = _revision_intact(old, old_path.parent)
        if old.get("status") != "complete" or intact:
            directory = old_path.parent
    if previous and not fresh and previous[1].get("status") != "complete":
        old_path, old = previous
        current_sources = {fingerprint(s["source"]): s for s in manifest["sources"]}
        known_inputs_match = all(
            fingerprint(source["source"]) in current_sources
            and all(
                not source.get(field)
                or source[field] == current_sources[fingerprint(source["source"])].get(field)
                for field in ("digest", "correction_digest")
            )
            for source in old.get("sources", [])
        )
        if (
            manifest.get("plan_identity")
            and old.get("plan_identity") == manifest["plan_identity"]
            and known_inputs_match
        ):
            directory = old_path.parent
    if directory is None:
        numbers = [int(p.name[1:]) for p in folder.glob("r[0-9]*") if p.name[1:].isdigit()]
        directory = folder / f"r{max(numbers, default=0) + 1:04d}"
        directory.mkdir()
    manifest_path = directory / "manifest.json"
    # Completed, verified identical revisions are left byte-for-byte untouched.
    if (
        previous
        and manifest_path == previous[0]
        and previous[1].get("status") == "complete"
        and failure is None
    ):
        progress(f"Reusing complete revision {config.run.name}/{directory.name}")
        return manifest_path
    manifest.update(
        run_id=f"{config.run.name}/{directory.name}",
        revision=directory.name,
        revision_identity=identity,
    )
    (directory / "resolved-config.yaml").write_text(yaml.safe_dump(settings, sort_keys=False))
    try:
        for entry in manifest["entries"].values():
            if entry["status"] != "complete":
                continue
            files = entry.pop("cache_files")
            entry["files"] = {}
            for path, digest in files.items():
                source = Path(path)
                name = Path("cutouts") / entry["target_id"] / entry["identity"][:20] / source.name
                destination = directory / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                if sha256(destination) != digest:
                    raise ValueError("Cutout copy failed checksum verification")
                entry["files"][str(name)] = digest
        atomic_json(manifest_path, manifest)
        if failure:
            raise failure
        if config.stacks.enabled or config.stacks.gif_enabled or config.stacks.rgb_enabled:
            _display(manifest["entries"], directory, config, cache, versions, fresh, progress)
        manifest["status"] = "failed" if manifest["errors"] else "complete"
    except BaseException as exc:
        manifest["status"] = "failed"
        manifest["fatal_error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        manifest["finished_utc"] = datetime.now(UTC).isoformat()
        atomic_json(manifest_path, manifest)
    return manifest_path


@contextmanager
def _process_parent(
    record, missions, work, retained, cache, config, versions, settings, progress, fresh, manifest
):
    """At most one parent array is loaded; cached products avoid opening it at all."""
    source = record["source"]
    label = source if record["local"] else str(source["filename"])
    path_name = Path(label)
    correction = None
    correction_digest = None
    if config.astrometry.mode == "corrected":
        path = config.astrometry.corrected_directory / config.astrometry.corrected_pattern.format(
            stem=path_name.stem, filename=path_name.name
        )
        correction_digest = _stable_hash(path)
        record["correction_digest"] = correction_digest
    reader_identity = fingerprint(
        {
            "implementation": implementation("io.py"),
            "dependencies": {
                k: v for k, v in versions.items() if k not in {"scipy", "pillow", "astroquery"}
            },
        }
    )
    if record.get("summary_reader") != reader_identity:
        record.pop("summary", None)
    summary_id = fingerprint({"digest": record.get("digest"), "reader": reader_identity})
    summary_path = cache / "summaries" / f"{summary_id}.json"
    if "summary" not in record:
        summary = _read_cache_json(summary_path)
        if summary:
            record.update(summary=summary, summary_reader=reader_identity)
    with _lazy_parent(record, missions, work, retained) as load:
        verified = []

        def obtain():
            # Verify and hash the parent once; later targets reuse the result.
            if verified:
                return verified[0]
            path, exposure = load()
            digest = _stable_hash(path)
            if _file_identity(path) != load.before_read:
                raise ValueError("Parent changed while reading/hashing; retry with stable inputs")
            if record.get("digest") and digest != record["digest"]:
                raise ValueError(
                    "Source bytes no longer match the selected source snapshot; refresh inputs"
                )
            validator = _validator(source) if not record["local"] else None
            if validator:
                with path.open("rb") as stream:
                    actual = hashlib.file_digest(stream, validator[0]).hexdigest()
                if actual != validator[1]:
                    raise ValueError("Downloaded parent does not match the archive digest")
            record.update(digest=digest, summary=exposure.summary, summary_reader=reader_identity)
            record.setdefault("verification", "downloaded_sha256")
            summaries = cache / "summaries"
            summaries.mkdir(exist_ok=True)
            summary_id = fingerprint({"digest": digest, "reader": reader_identity})
            _write_cache_json(summaries / f"{summary_id}.json", exposure.summary)
            verified.append((path, exposure))
            return verified[0]

        if "digest" not in record or "summary" not in record:
            obtain()
        if not selected(record["summary"], config.selection):
            manifest["selection_rejections"].append(label)
            yield None
            return
        digest = record["digest"]
        if config.storage.retain_full_images:
            existing = retained.get(digest)
            if existing and Path(existing).is_file() and _stable_hash(Path(existing)) == digest:
                manifest["retained_parents"][digest] = existing
            else:
                path, _ = obtain()
                manifest["retained_parents"][digest] = _retain(
                    path, digest, config.storage.output_directory
                )
        source_id = fingerprint({"source": label, "sha256": digest})[:16]
        for target in config.targets:
            key = f"{target.id}/{source_id}"
            identity = _native_identity(config, target, digest, correction_digest, versions)
            native_directory = cache / "native" / identity
            native = None if fresh else load_record(native_directory)
            try:
                if native is None:
                    path, exposure = obtain()
                    if correction_digest:
                        correction_path = (
                            config.astrometry.corrected_directory
                            / config.astrometry.corrected_pattern.format(
                                stem=path.stem, filename=path.name
                            )
                        )
                        wcs, metadata, shape = read_correction(correction_path)
                        if _stable_hash(correction_path) != correction_digest:
                            raise ValueError("Correction changed while reading")
                        check_correction_matches_parent(
                            wcs, shape, exposure.wcs, exposure.arrays["data"].shape
                        )
                        correction = {
                            "path": str(correction_path),
                            "sha256": correction_digest,
                            "parent_metadata": metadata,
                            "applied_parent_wcs": wcs,
                        }
                    progress(f"Extracting {target.id}: {path_name.name}")
                    native = _native(
                        config,
                        target,
                        path,
                        exposure,
                        digest,
                        correction,
                        native_directory,
                        versions,
                        settings,
                    )
                    manifest["stage_counts"]["extracted"] += 1
                else:
                    progress(f"Reusing native cutout {target.id}: {path_name.name}")
                    manifest["stage_counts"]["native_reused"] += 1
                canonical = native_directory / "cutout.asdf"
                validation = _assess_astrometry(canonical, native, config, cache, versions, fresh)
                cutout = None
                quality_settings = config.quality.model_dump(
                    mode="json", exclude={"exclude_from_stacks"}
                )
                quality_id = fingerprint(
                    {
                        "native": identity,
                        "bytes": native["files"],
                        "settings": quality_settings,
                        "implementation": implementation("quality.py"),
                        "dependencies": {k: versions[k] for k in ("numpy", "scipy")},
                    }
                )
                assessment_path = cache / "quality" / f"{quality_id}.json"
                quality = None if fresh else _read_cache_json(assessment_path)
                if quality is not None:
                    manifest["stage_counts"]["quality_reused"] += 1
                else:
                    cutout = read_cutout(canonical)
                    quality = assess(cutout.arrays["data"], cutout.arrays["dq"], config.quality)
                    _write_cache_json(assessment_path, quality)
                    manifest["stage_counts"]["quality_measured"] += 1
                outputs = {}
                for format_name in config.storage.formats:
                    if format_name == "asdf":
                        outputs[str(canonical)] = native["files"]["cutout.asdf"]
                    else:
                        serialization_id = fingerprint(
                            {
                                "native": identity,
                                "bytes": native["files"],
                                "format": "fits",
                                "tolerance": config.astrometry.fits_tolerance_pixels,
                                "implementation": implementation("io.py"),
                            }
                        )
                        serialization_directory = cache / "serialized" / serialization_id
                        serialized = None if fresh else load_record(serialization_directory)
                        if serialized is None:
                            if cutout is None:
                                cutout = read_cutout(canonical)
                            serialized = publish(
                                serialization_directory,
                                lambda temporary, cutout=cutout: [
                                    p.name
                                    for p in write_cutout(
                                        cutout,
                                        temporary,
                                        ["fits"],
                                        tolerance=config.astrometry.fits_tolerance_pixels,
                                    )
                                ],
                            )
                            manifest["stage_counts"]["serialized"] += 1
                        outputs.update(
                            {
                                str(serialization_directory / name): value
                                for name, value in serialized["files"].items()
                            }
                        )
                manifest["entries"][key] = {
                    "status": "complete",
                    "identity": identity,
                    "quality_identity": quality_id,
                    "native_sha256": native["files"]["cutout.asdf"],
                    "target_id": target.id,
                    "source": label,
                    "parent_sha256": digest,
                    "filter": record["summary"]["filter"],
                    "data_units": record["summary"]["data_units"],
                    "quality": quality,
                    "astrometry_validation": validation,
                    "mapping": native["mapping"],
                    "cache_files": outputs,
                    "provenance_scope": "files preserve creation provenance; this manifest records current quality and configuration",
                }
            except OffDetectorError:
                manifest["entries"][key] = {
                    "status": "skipped",
                    "reason": "target_off_detector",
                    "identity": identity,
                    "target_id": target.id,
                    "source": label,
                }
            except Exception as exc:
                manifest["entries"][key] = {
                    "status": "failed",
                    "error": str(exc),
                    "identity": identity,
                    "target_id": target.id,
                    "source": label,
                }
                if not config.execution.continue_on_error:
                    raise
                manifest["errors"].append(
                    {"target": target.id, "source": label, "error": f"{type(exc).__name__}: {exc}"}
                )
        yield record


@contextmanager
def _lazy_parent(record, missions, work, retained):
    with_context = None
    loaded = None
    try:

        def load():
            nonlocal with_context, loaded
            if loaded is None:
                with_context = _parent(record, missions, work, retained)
                path = with_context.__enter__()
                load.before_read = _file_identity(path)
                loaded = path, read_exposure(path)
            return loaded

        yield load
    finally:
        if with_context is not None:
            with_context.__exit__(None, None, None)
