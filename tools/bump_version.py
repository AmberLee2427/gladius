"""Bump the Gladius version in every file that records it.

Usage::

    python tools/bump_version.py {major,minor,patch,pre,release} | X.Y.Z[aN|bN|rcN]
    python tools/bump_version.py patch --dry-run

* ``pre``     0.1.0a3 -> 0.1.0a4 (same pre-release segment, next number)
* ``release`` 0.1.0a3 -> 0.1.0   (drop the pre-release marker)
* ``patch``/``minor``/``major`` bump the release segment and drop any pre-release marker.
* An explicit PEP 440 version is used verbatim.

Updated: ``pyproject.toml``, ``src/gladius/__init__.py``, ``CITATION.cff`` and the
``Unreleased`` heading in ``CHANGES.rst``. The new version is printed on the last
line of stdout so CI can capture it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parents[1]
KINDS = ("major", "minor", "patch", "pre", "release")

PYPROJECT_RE = re.compile(r'^(version\s*=\s*)"[^"]+"', re.MULTILINE)
INIT_RE = re.compile(r'^(__version__\s*=\s*)"[^"]+"', re.MULTILINE)
CITATION_VERSION_RE = re.compile(r"^(version:\s*).+$", re.MULTILINE)
CITATION_DATE_RE = re.compile(r"^(date-released:\s*).+$", re.MULTILINE)


def current_version(root: Path = ROOT) -> Version:
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = PYPROJECT_RE.search(text)
    if match is None:
        raise SystemExit("Could not find a version in pyproject.toml")
    return Version(text[match.end(1) :].split('"')[1])


def next_version(current: Version, kind: str) -> Version:
    """Return the version produced by applying ``kind`` (or an explicit version string)."""
    major, minor, micro = (list(current.release) + [0, 0, 0])[:3]
    if kind == "major":
        return Version(f"{major + 1}.0.0")
    if kind == "minor":
        return Version(f"{major}.{minor + 1}.0")
    if kind == "patch":
        return Version(f"{major}.{minor}.{micro + 1}")
    if kind == "release":
        if current.pre is None:
            raise ValueError(f"{current} is already a final release")
        return Version(f"{major}.{minor}.{micro}")
    if kind == "pre":
        if current.pre is None:
            raise ValueError(f"{current} has no pre-release segment to increment")
        label, number = current.pre
        return Version(f"{major}.{minor}.{micro}{label}{number + 1}")
    try:
        new = Version(kind)
    except InvalidVersion as error:
        raise ValueError(f"{kind!r} is not a bump kind {KINDS} or a valid version") from error
    if new <= current:
        raise ValueError(f"New version {new} must be greater than {current}")
    return new


def _sub_once(pattern: re.Pattern[str], replacement: str, text: str, label: str) -> str:
    new_text, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise SystemExit(f"Could not find the version field in {label}")
    return new_text


def roll_changelog(text: str, version: Version, today: dt.date) -> str:
    """Turn the ``Unreleased`` heading into ``<version> (<date>)`` and add a fresh one."""
    match = re.search(r"^Unreleased\n=+\n", text, re.MULTILINE)
    if match is None:
        raise SystemExit("CHANGES.rst has no 'Unreleased' section to release")
    heading = f"{version} ({today.isoformat()})"
    return (
        text[: match.start()]
        + "Unreleased\n==========\n\n"
        + f"{heading}\n{'=' * len(heading)}\n"
        + text[match.end() :]
    )


def apply(version: Version, root: Path = ROOT, today: dt.date | None = None) -> list[Path]:
    today = today or dt.date.today()
    changed = []

    def rewrite(relative: str, function) -> None:
        path = root / relative
        old = path.read_text(encoding="utf-8")
        new = function(old)
        if new != old:
            path.write_text(new, encoding="utf-8")
            changed.append(path)

    rewrite(
        "pyproject.toml",
        lambda t: _sub_once(PYPROJECT_RE, rf'\g<1>"{version}"', t, "pyproject.toml"),
    )
    rewrite(
        "src/gladius/__init__.py",
        lambda t: _sub_once(INIT_RE, rf'\g<1>"{version}"', t, "__init__.py"),
    )

    def citation(text: str) -> str:
        text = _sub_once(CITATION_VERSION_RE, rf"\g<1>{version}", text, "CITATION.cff")
        stamp = today.isoformat()
        if CITATION_DATE_RE.search(text):
            return CITATION_DATE_RE.sub(rf"\g<1>{stamp}", text, count=1)
        return text.rstrip("\n") + f"\ndate-released: {stamp}\n"

    rewrite("CITATION.cff", citation)
    rewrite("CHANGES.rst", lambda t: roll_changelog(t, version, today))
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("kind", help=f"one of {', '.join(KINDS)}, or an explicit version")
    parser.add_argument("--dry-run", action="store_true", help="print the new version only")
    args = parser.parse_args(argv)

    try:
        version = next_version(current_version(), args.kind)
    except ValueError as error:
        parser.error(str(error))
    if not args.dry_run:
        for path in apply(version):
            print(f"updated {path.relative_to(ROOT)}", file=sys.stderr)
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
