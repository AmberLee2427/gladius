"""Verified shared products and named run revisions.

Cache keys describe inputs to one stage, rather than the whole user configuration.
The output-directory lock in pipeline serializes publication and revision allocation.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
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
    """Replace cache files by renaming, never by writing into an existing file."""
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
            _make_writable(destination)  # Windows cannot replace read-only files
            (temporary / name).replace(destination)
        atomic_json(directory / "record.json", record)
    return record


def _make_writable(path):
    try:
        mode = path.stat().st_mode
        if not mode & stat.S_IWUSR:
            path.chmod(mode | stat.S_IWUSR)
    except FileNotFoundError:
        pass


def place_file(source, destination, digest, link=True):
    """Put a verified cache file in a revision, as a hard link when possible.

    Cache files are only ever replaced (new inode), never edited in place, so a
    link cannot change under a revision. Linked files are made read-only, so an
    accidental in-place edit of a revision file cannot also change the cache.
    The destination is always unlinked first, so writing never reaches a shared inode.
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and sha256(destination) == digest:
        return
    _make_writable(destination)
    destination.unlink(missing_ok=True)
    linked = False
    if link:
        try:
            os.link(source, destination)
            linked = True
        except OSError:
            pass  # another filesystem, or links unsupported: copy instead
    if linked:
        mode = destination.stat().st_mode
        destination.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    else:
        shutil.copyfile(source, destination)
    if sha256(destination) != digest:
        destination.unlink(missing_ok=True)
        raise ValueError(f"Placed product failed checksum verification: {destination}")


def copy_files(record, source, destination, link=False):
    """Place verified products; ``link`` shares cache inodes instead of copying."""
    for name, digest in record["files"].items():
        place_file(source / name, destination / name, digest, link)
