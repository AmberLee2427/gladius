"""Verified shared products and named run revisions.

Cache keys describe inputs to one stage, rather than the whole user configuration.
The output-directory lock in pipeline serializes publication and revision allocation.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from .io import atomic_json, sha256


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def implementation(*names):
    return {name: sha256(Path(__file__).parent / name) for name in names}


def valid_files(record, directory):
    return bool(record.get("files")) and all(
        (directory / name).is_file() and sha256(directory / name) == digest
        for name, digest in record["files"].items()
    )


def load_record(directory):
    try:
        record = json.loads((directory / "record.json").read_text())
        return record if valid_files(record, directory) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def publish(directory, writer, metadata=None):
    """Replace cache files only; revisions always contain independent copies."""
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="publish-", dir=directory.parent) as folder:
        temporary = Path(folder)
        result = writer(temporary)
        record = {
            **(metadata or {}),
            "result": result,
            "files": {
                str(p.relative_to(temporary)): sha256(p)
                for p in temporary.rglob("*")
                if p.is_file()
            },
        }
        directory.mkdir(exist_ok=True)
        for name in record["files"]:
            destination = directory / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            (temporary / name).replace(destination)
        atomic_json(directory / "record.json", record)
    return record


def copy_files(record, source, destination):
    """Copy verified products without linking mutable cache inodes into history."""
    for name, digest in record["files"].items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and sha256(path) == digest:
            continue
        shutil.copyfile(source / name, path)
        if sha256(path) != digest:
            raise ValueError(f"Copied product failed checksum verification: {path}")
