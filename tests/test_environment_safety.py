"""Dotenv loading and token storage safety checks."""

import os
from pathlib import Path

import pytest
from dotenv import dotenv_values

from gladius.environment import load_environment, save_mast_token


def test_explicit_env_file_is_loaded_without_overriding_the_shell(tmp_path, monkeypatch):
    monkeypatch.setenv("GLADIUS_TEST_KEPT", "shell")
    monkeypatch.delenv("GLADIUS_TEST_NEW", raising=False)
    explicit = tmp_path / "custom.env"
    explicit.write_text("GLADIUS_TEST_KEPT=file\nGLADIUS_TEST_NEW=file\n")
    (tmp_path / ".env").write_text("GLADIUS_TEST_NEW=wrong-file\n")
    assert load_environment(tmp_path, env_file=explicit)
    assert os.environ["GLADIUS_TEST_KEPT"] == "shell"
    assert os.environ["GLADIUS_TEST_NEW"] == "file"


def test_missing_explicit_env_file_is_an_error_not_a_silent_skip(tmp_path):
    with pytest.raises(FileNotFoundError, match="does not exist"):
        load_environment(tmp_path, env_file=tmp_path / "absent.env")


def test_default_directory_is_the_current_working_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("GLADIUS_TEST_CWD", raising=False)
    (tmp_path / ".env").write_text("GLADIUS_TEST_CWD=here\n")
    monkeypatch.chdir(tmp_path)
    assert load_environment()
    assert os.environ["GLADIUS_TEST_CWD"] == "here"


@pytest.mark.parametrize(
    "token", ["", "   ", "two words", "tab\tinside", "line\nbreak", "bell\x07"]
)
def test_unsafe_tokens_are_rejected_before_touching_the_file(tmp_path, token):
    path = tmp_path / ".env"
    with pytest.raises(ValueError, match="nonempty and contain no whitespace"):
        save_mast_token(token, path)
    assert not path.exists()


def test_token_surrounding_whitespace_is_stripped(tmp_path):
    path = save_mast_token("  test-only-sentinel \n", tmp_path / ".env")
    assert dotenv_values(path, interpolate=False)["MAST_API_TOKEN"] == "test-only-sentinel"


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
def test_token_is_never_written_through_a_symlink(tmp_path):
    target = tmp_path / "elsewhere.env"
    target.write_text("KEEP=1\n")
    link = tmp_path / ".env"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="regular file, not a symlink"):
        save_mast_token("test-only-sentinel", link)
    assert target.read_text() == "KEEP=1\n"


def test_token_destination_must_not_be_a_directory(tmp_path):
    with pytest.raises(ValueError, match="regular file"):
        save_mast_token("test-only-sentinel", tmp_path)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_existing_loose_permissions_are_tightened(tmp_path):
    path = tmp_path / ".env"
    path.write_text("OTHER=1\n")
    path.chmod(0o644)
    save_mast_token("test-only-sentinel", path)
    assert path.stat().st_mode & 0o777 == 0o600
    assert dotenv_values(path)["OTHER"] == "1"


def test_relative_destination_resolves_against_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    saved = save_mast_token("test-only-sentinel", "relative.env")
    assert saved == Path(tmp_path / "relative.env").absolute()
