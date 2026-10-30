"""Reject private working material and science files in built distributions."""

import argparse
import tarfile
import zipfile
from pathlib import PurePosixPath


def check(path):
    if path.endswith(".whl"):
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    elif path.endswith(".tar.gz"):
        with tarfile.open(path) as archive:
            names = archive.getnames()
    else:
        raise ValueError(f"Unexpected distribution format: {path}")
    forbidden = {
        ".git", ".agents", ".gladius-gui", ".roman-cutouts-gui",
        "local-snapshot", "nexus-snapshot", "nexus-source-snapshot.zip",
        "commissioning-handoff.md", "cutouts", "downloads",
    }
    bad = []
    for name in names:
        member = PurePosixPath(name)
        if (forbidden.intersection(member.parts)
                or any(part.startswith(".env") and part != ".env.example"
                       for part in member.parts)
                or member.suffix.lower() in {".asdf", ".fits", ".fit", ".fts", ".h5", ".hdf5", ".parquet"}
                or (member.suffix.lower() == ".csv" and member.parts[-2:] != ("examples", "targets.csv"))):
            bad.append(name)
    if bad:
        raise ValueError(f"Excluded material in {path}: {bad}")
    print(f"Distribution content check passed: {path} ({len(names)} entries)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+")
    for filename in parser.parse_args().archives:
        check(filename)
