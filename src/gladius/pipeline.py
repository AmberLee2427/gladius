"""Dependency-aware, exposure-first execution with named revisions."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import shutil
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import yaml
from filelock import FileLock

from . import __version__
from .cache import (
    copy_files,
    fingerprint,
    implementation,
    load_record,
    place_file,
    publish,
    valid_files,
)
from .config import RunConfig
from .core import (
    OffDetectorError,
    WcsRoundTripError,
    check_correction_matches_parent,
    make_cutout,
    validate_wcs,
)
from .inputs import discover, selected, staged
from .io import (
    FRAME_FILENAME,
    atomic_json,
    omit_arrays,
    read_correction,
    read_cutout,
    read_exposure,
    sha256,
    write_cutout,
    write_parent_frame,
)
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
            "content": config.storage.model_dump(
                mode="json",
                include={"ancillary_arrays", "parent_metadata_arrays", "asdf_compression"},
            ),
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
    storage = config.storage
    content = {}
    if not storage.ancillary_arrays:
        content["omitted_ancillary_arrays"] = {
            name: {"parent_shape": list(a.shape), "dtype": str(a.dtype)}
            for name, a in exposure.ancillary_arrays.items()
        }
    if not storage.parent_metadata_arrays:
        content["parent_metadata_arrays"] = "omitted; shape, dtype and SHA256 descriptors kept"
    cutout = make_cutout(
        exposure.arrays,
        wcs,
        target,
        extraction=config.extraction,
        parent_wcs=exposure.wcs,
        parent_metadata=exposure.parent_metadata
        if storage.parent_metadata_arrays
        else omit_arrays(exposure.parent_metadata),
        ancillary_arrays=exposure.ancillary_arrays if storage.ancillary_arrays else {},
        provenance={
            **content,
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
        lambda folder: [
            p.name
            for p in write_cutout(cutout, folder, ["asdf"], compression=storage.asdf_compression)
        ],
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
        copy_files(product_record, folder, directory, config.storage.output_links == "hardlink")
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


class RepeatedFailureError(RuntimeError):
    """The first parents all failed for one reason; continuing would repeat it."""


def _error_class(exc, label=""):
    """Group failures that differ only by file names, quoted values or numbers."""
    text = f"{type(exc).__name__}: {exc}"
    if label:
        text = text.replace(str(label), "<parent>").replace(Path(str(label)).name, "<parent>")
    text = re.sub(r"'[^']*'|\"[^\"]*\"", "'…'", text)
    return re.sub(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", "#", text)[:300]


def _reader_identity(versions):
    return fingerprint(
        {
            "implementation": implementation("io.py"),
            "dependencies": {
                k: v for k, v in versions.items() if k not in {"scipy", "pillow", "astroquery"}
            },
        }
    )


def _resolve_summary(record, cache, reader_identity):
    """Reuse a cached parent summary written by this reader; drop a stale one."""
    if record.get("summary_reader") != reader_identity:
        record.pop("summary", None)
    if "summary" not in record and record.get("digest"):
        summary_id = fingerprint({"digest": record["digest"], "reader": reader_identity})
        summary = _read_cache_json(cache / "summaries" / f"{summary_id}.json")
        if summary:
            record.update(summary=summary, summary_reader=reader_identity)


def _label(record):
    return record["source"] if record["local"] else str(record["source"]["filename"])


def _correction_path(config, name):
    name = Path(name)
    return config.astrometry.corrected_directory / config.astrometry.corrected_pattern.format(
        stem=name.stem, filename=name.name
    )


def _frame_identity(identity, native, config, versions):
    return fingerprint(
        {
            "native": identity,
            "bytes": native["files"],
            "compression": config.storage.asdf_compression,
            "implementation": implementation("io.py"),
            "dependencies": {k: versions[k] for k in ("numpy", "asdf", "roman_datamodels")},
        }
    )


def _needs_parent(record, config, cache, versions, retained, fresh):
    """Predict whether processing will open this archive parent (for look-ahead only).

    A wrong guess costs one early download or one wait; it never changes results.
    """
    try:
        if record["local"]:
            return False
        if fresh or "digest" not in record or "summary" not in record:
            return True
        if not selected(record["summary"], config.selection):
            return False
        digest = record["digest"]
        if retained.get(digest) and Path(retained[digest]).is_file():
            return False
        if config.storage.retain_full_images:
            return True
        correction = record.get("correction_digest")
        for target in config.targets:
            identity = _native_identity(config, target, digest, correction, versions)
            if (cache / "off_detector" / f"{identity}.json").is_file():
                continue
            try:
                # Unverified read: checksums are verified when the parent is processed.
                native = json.loads((cache / "native" / identity / "record.json").read_text())
            except (OSError, ValueError):
                return True
            if "roman_frame" in config.storage.formats:
                frame = _frame_identity(identity, native, config, versions)
                if not (cache / "frames" / frame / "record.json").is_file():
                    return True
        return False
    except Exception:
        return False


def _mast_client():
    from astroquery.mast import MastMissions

    missions = MastMissions(mission="roman")
    if os.environ.get("MAST_API_TOKEN"):
        missions.login(token=os.environ["MAST_API_TOKEN"], store_token=False)
    return missions


class _Downloads:
    """Stage archive parents with bounded look-ahead; extraction stays one at a time.

    Up to ``workers`` downloads run while the current parent is processed. A parent
    whose processing fails, or a look-ahead download that was never used, is kept in
    ``store`` so the next run does not download it again; the kept copy is removed
    once that parent is processed without errors.
    """

    def __init__(self, missions, work, store, workers):
        self.missions = missions
        self.work = Path(work)
        self.store = Path(store)
        self.workers = workers
        self.executor = None
        self.pending = {}
        self.active = {}
        self.lock = threading.Lock()

    def _client(self):
        with self.lock:
            if self.missions is None:
                self.missions = _mast_client()
            return self.missions

    def _stage(self, source, client):
        context = staged(source, client, self.work)
        path = context.__enter__()
        return context, path

    def _kept(self, key):
        folder = self.store / key
        if not folder.is_dir():
            return None
        files = [p for p in folder.iterdir() if p.is_file()]
        return files[0] if len(files) == 1 else None

    def prefetch(self, key, source):
        if self.workers <= 1 or key in self.pending or key in self.active or self._kept(key):
            return
        if self.executor is None:
            self.executor = ThreadPoolExecutor(self.workers, thread_name_prefix="gladius-download")
        self.pending[key] = self.executor.submit(self._stage, source, self._client())

    def acquire(self, key, source):
        if key in self.active:
            return self.active[key][2]
        kept = self._kept(key)
        if kept is not None:
            self.active[key] = ("kept", None, kept)
            return kept
        future = self.pending.pop(key, None)
        context, path = future.result() if future else self._stage(source, self._client())
        self.active[key] = ("staged", context, path)
        return path

    def _keep(self, key, path):
        if not Path(path).resolve().is_relative_to(self.work.resolve()):
            return  # not a download this run owns (for example a supplied file)
        destination = self.store / key / Path(path).name
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(path, destination)

    def release(self, key, keep):
        kind, context, path = self.active.pop(key, (None, None, None))
        if kind == "kept" and not keep:
            shutil.rmtree(path.parent, ignore_errors=True)
        elif kind == "staged":
            try:
                if keep:
                    self._keep(key, path)
            finally:
                context.__exit__(None, None, None)

    def close(self):
        for future in self.pending.values():
            future.cancel()
        if self.executor is not None:
            self.executor.shutdown(wait=True)
        for key, future in self.pending.items():
            if future.cancelled() or future.exception() is not None:
                continue
            context, path = future.result()
            try:
                self._keep(key, path)
            except OSError:
                pass
            finally:
                context.__exit__(None, None, None)
        self.pending.clear()


def _run_locked(config, settings, progress, fresh, refresh_inputs):
    output = config.storage.output_directory
    cache = output / ".cache"
    cache.mkdir(exist_ok=True)
    store = cache / "downloads"
    if fresh:
        shutil.rmtree(store, ignore_errors=True)
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
            "off_detector_reused": 0,
            "quality_measured": 0,
            "quality_reused": 0,
            "serialized": 0,
            "frames_written": 0,
            "published": 0,
        },
        "stage_count_definitions": {
            "serialized": "FITS files newly converted from native cutouts",
            "published": "cutout files placed in this revision (all formats)",
        },
    }
    failure = None
    with tempfile.TemporaryDirectory(prefix="work-", dir=cache) as work_name:
        work = Path(work_name)
        downloads = None
        try:
            if pinned:
                sources = deepcopy(pinned["sources"])
                missions = None
                progress("Using pinned MAST source snapshot; use --refresh-inputs to query again")
            else:
                stats = {}
                missions, raw_sources = discover(config, stats=stats)
                if stats:
                    manifest["discovery"] = stats
                if stats.get("footprint_rejected"):
                    progress(
                        f"Footprint check: skipped {stats['footprint_rejected']} of "
                        f"{stats['candidate_observations']} MAST candidates containing no target"
                    )
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
            reader_identity = _reader_identity(versions)
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
                _resolve_summary(source_record, cache, reader_identity)
            downloads = _Downloads(missions, work, store, config.execution.download_workers)
            total = len(sources)
            considered = set()
            failed_classes = []
            succeeded = False
            for index, source_record in enumerate(sources):
                for ahead in range(
                    index, min(total, index + config.execution.download_workers + 1)
                ):
                    upcoming = sources[ahead]
                    if ahead not in considered and not upcoming["local"]:
                        considered.add(ahead)
                        if _needs_parent(upcoming, config, cache, versions, retained, fresh):
                            downloads.prefetch(upcoming["archive_identity"], upcoming["source"])
                label = _label(source_record)
                progress(f"[{index + 1}/{total}] {Path(label).name}")
                outcome = {"state": None, "complete": 0, "skipped": 0, "failed": 0, "class": None}
                try:
                    with _process_parent(
                        source_record,
                        downloads,
                        retained,
                        cache,
                        config,
                        versions,
                        settings,
                        progress,
                        fresh,
                        manifest,
                        outcome,
                    ) as record:
                        if record is not None:
                            manifest["sources"].append(record)
                except Exception as exc:
                    source_record["error"] = f"{type(exc).__name__}: {exc}"
                    manifest["sources"].append(source_record)
                    manifest["errors"].append(
                        {"source": str(source_record["source"]), "error": source_record["error"]}
                    )
                    progress(f"  failed: {source_record['error']}")
                    if not config.execution.continue_on_error:
                        raise
                    outcome["class"] = _error_class(exc, label)
                if outcome["state"] == "rejected":
                    progress("  not selected")
                elif outcome["state"] == "processed":
                    done = outcome["complete"]
                    progress(
                        f"  {done} cutout{'' if done == 1 else 's'}, "
                        f"{outcome['skipped']} off detector, {outcome['failed']} failed"
                    )
                if outcome["class"]:
                    failed_classes.append(outcome["class"])
                elif outcome["state"] == "processed":
                    succeeded = True
                limit = config.execution.abort_after_repeated_failures
                if (
                    limit
                    and not succeeded
                    and len(failed_classes) == limit
                    and len(set(failed_classes)) == 1
                ):
                    raise RepeatedFailureError(
                        f"Stopped: the first {limit} parent images all failed with the same "
                        f"error ({manifest['errors'][-1]['error']}). This usually means an "
                        "environment or configuration problem; fix it and rerun. Downloaded "
                        "parents are kept in the cache, so a rerun does not download them "
                        "again. Set execution.abort_after_repeated_failures: 0 to disable."
                    )
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
        finally:
            if downloads is not None:
                downloads.close()
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
        shutil.rmtree(store, ignore_errors=True)
        return manifest_path
    manifest.update(
        run_id=f"{config.run.name}/{directory.name}",
        revision=directory.name,
        revision_identity=identity,
    )
    (directory / "resolved-config.yaml").write_text(yaml.safe_dump(settings, sort_keys=False))
    link = config.storage.output_links == "hardlink"
    try:
        for entry in manifest["entries"].values():
            if entry["status"] != "complete":
                continue
            files = entry.pop("cache_files")
            entry["files"] = {}
            for path, digest in files.items():
                source = Path(path)
                name = Path("cutouts") / entry["target_id"] / entry["identity"][:20] / source.name
                place_file(source, directory / name, digest, link)
                manifest["stage_counts"]["published"] += 1
                entry["files"][str(name)] = digest
        atomic_json(manifest_path, manifest)
        if failure:
            raise failure
        if config.stacks.enabled or config.stacks.gif_enabled or config.stacks.rgb_enabled:
            _display(manifest["entries"], directory, config, cache, versions, fresh, progress)
        manifest["status"] = "failed" if manifest["errors"] else "complete"
        if manifest["status"] == "complete":
            # Kept downloads only exist to avoid re-downloading after a failure.
            shutil.rmtree(store, ignore_errors=True)
    except BaseException as exc:
        manifest["status"] = "failed"
        manifest["fatal_error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        manifest["finished_utc"] = datetime.now(UTC).isoformat()
        atomic_json(manifest_path, manifest)
    return manifest_path


def _record_failures(manifest, label, failures):
    """One manifest error per parent and error class, naming the affected targets."""
    groups = {}
    for target, exc in failures:
        groups.setdefault(_error_class(exc, label), []).append((target, exc))
    for members in groups.values():
        first = members[0][1]
        error = f"{type(first).__name__}: {first}"
        worst = [exc for _, exc in members if isinstance(exc, WcsRoundTripError)]
        if len(worst) == len(members) and len(members) > 1:
            error = (
                f"{type(first).__name__}: WCS numerical round-trip error up to "
                f"{max(e.error_pixels for e in worst):g} exceeds {first.tolerance:g} pixels"
            )
        item = {"source": label, "error": error, "targets": [t for t, _ in members]}
        if len(members) == 1:
            item["target"] = members[0][0]
        manifest["errors"].append(item)


@contextmanager
def _process_parent(
    record,
    downloads,
    retained,
    cache,
    config,
    versions,
    settings,
    progress,
    fresh,
    manifest,
    outcome,
):
    """At most one parent array is loaded; cached products avoid opening it at all."""
    source = record["source"]
    label = _label(record)
    path_name = Path(label)
    correction = None
    correction_digest = None
    if config.astrometry.mode == "corrected":
        correction_digest = _stable_hash(_correction_path(config, path_name))
        record["correction_digest"] = correction_digest
    reader_identity = _reader_identity(versions)
    _resolve_summary(record, cache, reader_identity)
    with _lazy_parent(record, downloads, retained) as load:
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
            outcome["state"] = "rejected"
            yield None
            return
        outcome["state"] = "processed"
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
        failures = []
        for target in config.targets:
            key = f"{target.id}/{source_id}"
            identity = _native_identity(config, target, digest, correction_digest, versions)
            native_directory = cache / "native" / identity
            off_detector = cache / "off_detector" / f"{identity}.json"
            native = None if fresh else load_record(native_directory)
            if native is None and not fresh and _read_cache_json(off_detector) is not None:
                # Known from an earlier run: no need to download the parent again.
                manifest["entries"][key] = {
                    "status": "skipped",
                    "reason": "target_off_detector",
                    "identity": identity,
                    "target_id": target.id,
                    "source": label,
                }
                manifest["stage_counts"]["off_detector_reused"] += 1
                outcome["skipped"] += 1
                continue
            try:
                if native is None:
                    path, exposure = obtain()
                    if correction_digest:
                        correction_path = _correction_path(config, path)
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
                    elif format_name == "fits":
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
                if "roman_frame" in config.storage.formats:
                    frame_directory = (
                        cache / "frames" / _frame_identity(identity, native, config, versions)
                    )
                    frame = None if fresh else load_record(frame_directory)
                    if frame is None:
                        path, _ = obtain()
                        frame = publish(
                            frame_directory,
                            lambda temporary, path=path, native=native, target=target: [
                                write_parent_frame(
                                    path,
                                    native["mapping"],
                                    temporary / FRAME_FILENAME,
                                    compression=config.storage.asdf_compression,
                                    provenance={
                                        "parent_filename": path.name,
                                        "parent_sha256": digest,
                                        "target": target.model_dump(mode="json"),
                                        "cutout_sha256": native["files"]["cutout.asdf"],
                                    },
                                ).name
                            ],
                        )
                        manifest["stage_counts"]["frames_written"] += 1
                    outputs[str(frame_directory / FRAME_FILENAME)] = frame["files"][FRAME_FILENAME]
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
                outcome["complete"] += 1
            except OffDetectorError:
                _write_cache_json(off_detector, {"reason": "target_off_detector"})
                manifest["entries"][key] = {
                    "status": "skipped",
                    "reason": "target_off_detector",
                    "identity": identity,
                    "target_id": target.id,
                    "source": label,
                }
                outcome["skipped"] += 1
            except Exception as exc:
                manifest["entries"][key] = {
                    "status": "failed",
                    "error": str(exc),
                    "identity": identity,
                    "target_id": target.id,
                    "source": label,
                }
                outcome["failed"] += 1
                if not config.execution.continue_on_error:
                    raise
                failures.append((target.id, exc))
        _record_failures(manifest, label, failures)
        if failures:
            load.keep = True
            if not outcome["complete"]:
                outcome["class"] = _error_class(failures[0][1], label)
        yield record


def _local_parent(record, retained):
    path = retained.get(record.get("digest"))
    if path and Path(path).is_file() and _stable_hash(Path(path)) == record["digest"]:
        return Path(path)
    if record.get("local"):
        return Path(record["source"])
    return None


@contextmanager
def _lazy_parent(record, downloads, retained):
    """Open the parent on first use; keep a fresh download if processing fails."""
    state = {}

    def load():
        if "loaded" not in state:
            if "path" not in state:
                path = _local_parent(record, retained)
                if path is None:
                    path = downloads.acquire(record["archive_identity"], record["source"])
                    state["key"] = record["archive_identity"]
                state["path"] = path
            load.before_read = _file_identity(state["path"])
            state["loaded"] = state["path"], read_exposure(state["path"])
        return state["loaded"]

    load.keep = False
    try:
        yield load
    except BaseException:
        load.keep = True
        raise
    finally:
        if "key" in state:
            downloads.release(state["key"], keep=load.keep)
