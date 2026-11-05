import datetime as dt
import importlib.util
from pathlib import Path

import pytest
from packaging.version import Version

SPEC = importlib.util.spec_from_file_location(
    "bump_version", Path(__file__).parents[1] / "tools" / "bump_version.py"
)
bump = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bump)


@pytest.mark.parametrize(
    ("current", "kind", "expected"),
    [
        ("0.1.0a3", "pre", "0.1.0a4"),
        ("0.1.0rc1", "pre", "0.1.0rc2"),
        ("0.1.0a3", "release", "0.1.0"),
        ("0.1.0a3", "patch", "0.1.1"),
        ("0.1.4", "minor", "0.2.0"),
        ("0.1.4", "major", "1.0.0"),
        ("0.1.0a3", "0.1.0b1", "0.1.0b1"),
    ],
)
def test_next_version(current, kind, expected):
    assert bump.next_version(Version(current), kind) == Version(expected)


@pytest.mark.parametrize(
    ("current", "kind"),
    [("0.1.0", "pre"), ("0.1.0", "release"), ("0.1.0a3", "0.1.0a3"), ("0.1.0", "nonsense")],
)
def test_next_version_rejects_invalid(current, kind):
    with pytest.raises(ValueError):
        bump.next_version(Version(current), kind)


def make_tree(root, changelog="Unreleased\n==========\n\n* thing\n\n0.1.0a3 (2026-11-01)\n===\n"):
    (root / "src" / "gladius").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.1.0a3"\n')
    (root / "src" / "gladius" / "__init__.py").write_text('"""Doc."""\n\n__version__ = "0.1.0a3"\n')
    (root / "CITATION.cff").write_text("cff-version: 1.2.0\nversion: 0.1.0a2\ntitle: G\n")
    (root / "CHANGES.rst").write_text(changelog)


def test_apply_updates_every_file(tmp_path):
    make_tree(tmp_path)
    assert bump.current_version(tmp_path) == Version("0.1.0a3")
    changed = bump.apply(Version("0.1.0a4"), tmp_path, dt.date(2026, 11, 5))
    assert len(changed) == 4
    assert 'version = "0.1.0a4"' in (tmp_path / "pyproject.toml").read_text()
    assert '__version__ = "0.1.0a4"' in (tmp_path / "src/gladius/__init__.py").read_text()
    citation = (tmp_path / "CITATION.cff").read_text()
    assert "version: 0.1.0a4" in citation and "date-released: 2026-11-05" in citation
    changes = (tmp_path / "CHANGES.rst").read_text()
    assert changes.startswith(
        "Unreleased\n==========\n\n0.1.0a4 (2026-11-05)\n====================\n"
    )
    assert "* thing" in changes
    # Re-running the date stamp replaces rather than duplicates it.
    bump.apply(Version("0.1.0a5"), tmp_path, dt.date(2026, 11, 6))
    assert (tmp_path / "CITATION.cff").read_text().count("date-released") == 1


def test_changelog_requires_unreleased_section(tmp_path):
    make_tree(tmp_path, changelog="0.1.0a3 (2026-11-01)\n===\n")
    with pytest.raises(SystemExit):
        bump.apply(Version("0.1.0a4"), tmp_path)


def test_real_repo_versions_agree():
    root = Path(__file__).parents[1]
    version = bump.current_version(root)
    assert f'__version__ = "{version}"' in (root / "src/gladius/__init__.py").read_text()
    assert f"version: {version}" in (root / "CITATION.cff").read_text()


def test_main_dry_run_prints_version(capsys):
    assert bump.main(["pre", "--dry-run"]) == 0
    assert capsys.readouterr().out.strip() == str(bump.next_version(bump.current_version(), "pre"))
