"""Portable, restartable exposure-first execution without publishing side effects."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import yaml
from filelock import FileLock

from . import __version__
from .config import RunConfig
from .core import NoOverlapError, make_cutout, validate_wcs
from .inputs import discover, selected, staged
from .io import atomic_json, read_correction, read_exposure, sha256, write_cutout
from .quality import assess
from .stacks import build_stacks


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _file_identity(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _complete(entry, directory, identity):
    return (
        entry.get("status") == "complete"
        and entry.get("identity") == identity
        and bool(entry.get("files"))
        and all(
            (directory / name).is_file() and sha256(directory / name) == digest
            for name, digest in entry["files"].items()
        )
    )


def run(config: RunConfig, *, progress=print) -> Path:
    """Execute a validated configuration and return its durable run manifest path.

    Failures are recorded before being raised. continue_on_error allows later
    inputs to run but leaves the final manifest status failed (and CLI nonzero).
    """
    config = config.resolved(Path.cwd())
    settings = config.model_dump(mode="json")
    versions = {name: version(name) for name in ("numpy", "astropy", "asdf", "gwcs")}
    for name in ("roman_datamodels", "rad", "asdf-astropy", "scipy", "astroquery"):
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            versions[name] = None
    implementation = _fingerprint(
        {p.name: sha256(p) for p in sorted(Path(__file__).parent.glob("*.py"))}
    )
    run_id = _fingerprint(
        {
            "configuration": settings,
            "package": __version__,
            "dependencies": versions,
            "implementation_sha256": implementation,
        }
    )[:20]
    directory = config.storage.output_directory / "runs" / run_id
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    with FileLock(str(directory / ".run.lock"), timeout=config.execution.lock_timeout_seconds):
        (directory / "resolved-config.yaml").write_text(yaml.safe_dump(settings, sort_keys=False))
        previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        manifest = {
            "schema_version": 1,
            "package_version": __version__,
            "dependencies": versions,
            "implementation_sha256": implementation,
            "run_id": run_id,
            "configuration": settings,
            "started_utc": datetime.now(UTC).isoformat(),
            "status": "running",
            "entries": previous.get("entries", {}),
            "errors": [],
            "selection_rejections": [],
            "retained_parents": {},
        }
        atomic_json(manifest_path, manifest)
        work = directory / ".work"
        work.mkdir(exist_ok=True)
        try:
            missions, sources = discover(config)
            active = set()
            parents_selected = 0
            for source in sources:
                label = str(source) if missions is None else str(source["filename"])
                try:
                    with staged(source, missions, work) as path:
                        before = _file_identity(path)
                        exposure = read_exposure(path)
                        if not selected(exposure.summary, config.selection):
                            manifest["selection_rejections"].append(label)
                            continue
                        parents_selected += 1
                        digest = sha256(path)
                        if before != _file_identity(path):
                            raise ValueError(
                                "Parent changed while reading/hashing; retry with stable inputs"
                            )
                        source_id = _fingerprint({"source": label, "sha256": digest})[:16]
                        wcs = exposure.wcs
                        correction = None
                        if config.astrometry.mode == "corrected":
                            correction_path = (
                                config.astrometry.corrected_directory
                                / config.astrometry.corrected_pattern.format(
                                    stem=path.stem, filename=path.name
                                )
                            )
                            before_correction = _file_identity(correction_path)
                            wcs, metadata = read_correction(correction_path)
                            correction_digest = sha256(correction_path)
                            if before_correction != _file_identity(correction_path):
                                raise ValueError("Correction changed while reading/hashing")
                            correction = {
                                "path": str(correction_path),
                                "sha256": correction_digest,
                                "parent_metadata": metadata,
                                "applied_parent_wcs": wcs,
                            }
                        validation = {
                            "check": "not_requested",
                            "absolute_astrometry_validated": False,
                        }
                        if config.astrometry.mode != "use":
                            validation = validate_wcs(
                                wcs,
                                exposure.arrays["data"].shape,
                                config.astrometry.roundtrip_tolerance_pixels,
                            )
                        if config.storage.retain_full_images:
                            retained = (
                                config.storage.output_directory / "parents" / digest / path.name
                            )
                            retained.parent.mkdir(parents=True, exist_ok=True)
                            if not retained.exists() or sha256(retained) != digest:
                                with tempfile.NamedTemporaryFile(
                                    dir=retained.parent, delete=False
                                ) as stream:
                                    temp = Path(stream.name)
                                try:
                                    shutil.copyfile(path, temp)
                                    if sha256(temp) != digest:
                                        raise ValueError(
                                            "Parent changed while copying its retained image"
                                        )
                                    temp.replace(retained)
                                finally:
                                    temp.unlink(missing_ok=True)
                            manifest["retained_parents"][digest] = str(retained)
                        for target in config.targets:
                            key = f"{target.id}/{source_id}"
                            active.add(key)
                            identity = _fingerprint(
                                {
                                    "source": digest,
                                    "run": run_id,
                                    "target": target.model_dump(),
                                    "correction": correction["sha256"] if correction else None,
                                }
                            )
                            old = manifest["entries"].get(key, {})
                            if config.execution.resume and _complete(old, directory, identity):
                                progress(f"Reusing {target.id}: {path.name}")
                                continue
                            progress(f"Extracting {target.id}: {path.name}")
                            try:
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
                                        "source": label,
                                        "exposure": exposure.summary,
                                        "astrometry_mode": config.astrometry.mode,
                                        "astrometry_validation": validation,
                                        "correction": correction,
                                        "configuration": settings,
                                        "dependencies": versions,
                                        "implementation_sha256": implementation,
                                        "centering": "floor(position)-(size-1)//2",
                                        "ancillary_padding": "floating:NaN; integer:0; dq/pixeldq:DO_NOT_USE",
                                    },
                                )
                                quality = assess(
                                    cutout.arrays["data"], cutout.arrays["dq"], config.quality
                                )
                                cutout.provenance["quality"] = quality
                                if config.astrometry.mode != "use":
                                    validate_wcs(
                                        cutout.wcs,
                                        cutout.arrays["data"].shape,
                                        config.astrometry.roundtrip_tolerance_pixels,
                                    )
                                # Content-specific directories make changed corrections immutable variants.
                                destination = directory / "cutouts" / target.id / identity[:20]
                                with tempfile.TemporaryDirectory(prefix="cutout-", dir=work) as td:
                                    temporary = Path(td)
                                    files = write_cutout(
                                        cutout,
                                        temporary,
                                        config.storage.formats,
                                        tolerance=config.astrometry.fits_tolerance_pixels,
                                    )
                                    checks = {name.name: sha256(name) for name in files}
                                    if destination.exists():
                                        # A corrupted/incomplete previous variant is replaced file by file;
                                        # manifest publication below remains the commit point.
                                        for name in checks:
                                            (temporary / name).replace(destination / name)
                                    else:
                                        destination.parent.mkdir(parents=True, exist_ok=True)
                                        temporary.rename(destination)
                                manifest["entries"][key] = {
                                    "status": "complete",
                                    "identity": identity,
                                    "target_id": target.id,
                                    "source": label,
                                    "parent_sha256": digest,
                                    "filter": exposure.summary["filter"],
                                    "data_units": exposure.summary["data_units"],
                                    "quality": quality,
                                    "mapping": cutout.mapping,
                                    "files": {
                                        str((destination / name).relative_to(directory)): value
                                        for name, value in checks.items()
                                    },
                                }
                            except NoOverlapError:
                                if config.extraction.no_overlap != "skip":
                                    raise
                                manifest["entries"][key] = {
                                    "status": "skipped",
                                    "reason": "no_overlap",
                                    "identity": identity,
                                }
                            except Exception as exc:
                                manifest["entries"][key] = {
                                    "status": "failed",
                                    "error": str(exc),
                                    "identity": identity,
                                }
                                if not config.execution.continue_on_error:
                                    raise
                                manifest["errors"].append(
                                    {
                                        "target": target.id,
                                        "source": label,
                                        "error": f"{type(exc).__name__}: {exc}",
                                    }
                                )
                            finally:
                                atomic_json(manifest_path, manifest)
                except Exception as exc:
                    manifest["errors"].append(
                        {"source": label, "error": f"{type(exc).__name__}: {exc}"}
                    )
                    if not config.execution.continue_on_error:
                        raise
                finally:
                    atomic_json(manifest_path, manifest)
            # Files removed from the input set do not silently remain stack contributors on resume.
            manifest["entries"] = {
                key: value for key, value in manifest["entries"].items() if key in active
            }
            if parents_selected == 0:
                raise ValueError("No parent exposures passed the selection")
            if config.stacks.enabled:
                build_stacks(manifest["entries"], directory, config)
            manifest["status"] = "failed" if manifest["errors"] else "complete"
        except BaseException as exc:
            manifest["status"] = "failed"
            manifest["fatal_error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            manifest["finished_utc"] = datetime.now(UTC).isoformat()
            atomic_json(manifest_path, manifest)
    return manifest_path
