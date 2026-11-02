"""Credential persistence and real-demo orchestration without network access."""

import getpass
import os
import warnings
from pathlib import Path

import pytest
from dotenv import dotenv_values

from gladius import RunConfig, load_config
from gladius.cli import main
from gladius.demo import create_mast_demo


def test_hidden_token_preserves_other_settings_and_permissions(tmp_path, monkeypatch, capsys):
    path = tmp_path / ".env"
    path.write_text("# local settings\nOTHER=keep-me\nMAST_API_TOKEN='old'\n")
    secret = "test-only-$literal'quoted"
    monkeypatch.setattr("gladius.cli.getpass.getpass", lambda _: secret)
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    assert main(["token", "--env-file", str(path)]) == 0
    values = dotenv_values(path, interpolate=False)
    assert values == {"OTHER": "keep-me", "MAST_API_TOKEN": secret}
    assert "# local settings" in path.read_text()
    assert secret not in capsys.readouterr().out
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


def test_token_new_file_declined_replace_and_no_echo_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("gladius.cli.getpass.getpass", lambda _: "test-only-sentinel")
    assert main(["token"]) == 0
    original = Path(".env").read_bytes()
    monkeypatch.setattr("builtins.input", lambda _: "no")
    assert main(["token"]) == 0
    assert Path(".env").read_bytes() == original

    def no_terminal(_):
        warnings.warn("Cannot hide input", getpass.GetPassWarning, stacklevel=2)
        pytest.fail("Must not fall back to echoing the token")

    monkeypatch.setattr("gladius.cli.getpass.getpass", no_terminal)
    assert main(["token", "--force"]) == 1
    assert Path(".env").read_bytes() == original


def test_real_demo_loads_explicit_credentials_before_query(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MAST_API_TOKEN", raising=False)
    env_file = tmp_path / "credentials.env"
    env_file.write_text("MAST_API_TOKEN=test-only-sentinel\n")
    destination = tmp_path / "real-demo"

    def selection(base):
        assert base == destination
        assert os.environ["MAST_API_TOKEN"] == "test-only-sentinel"
        config = RunConfig(
            targets=[{"id": "archive", "ra": 270, "dec": -29}],
            inputs={
                "mode": "mast",
                "mast_criteria": {"fileSetName": "real-parent"},
                "product_filename": "parent_cal.asdf",
            },
        ).resolved(base)
        return {"configuration": config.model_dump(mode="json"), "download_bytes": 1024}

    def run(config):
        assert config.inputs.mode == "mast"
        assert config.inputs.product_filename == "parent_cal.asdf"
        assert config.extraction.size == 150
        assert config.astrometry.roundtrip_tolerance_pixels == 0.01
        assert not config.stacks.enabled
        assert config.storage.formats == ["asdf", "fits"]
        manifest = destination / "manifest.json"
        manifest.write_text('{"status": "complete"}')
        return manifest

    monkeypatch.setattr("gladius.inputs.mast_test_configuration", selection)
    monkeypatch.setattr("gladius.cli.run", run)
    assert (
        main(["demo", "mast-demo", "--directory", str(destination), "--env-file", str(env_file)])
        == 0
    )
    assert load_config(destination / "demo.yaml").inputs.mode == "mast"
    assert "test-only-sentinel" not in capsys.readouterr().out


def test_mast_demo_rejects_large_parent_before_writing_or_running(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "gladius.inputs.mast_test_configuration", lambda _: {"download_bytes": 513 * 1024**2}
    )
    destination = tmp_path / "demo"
    with pytest.raises(ValueError, match="No image was downloaded"):
        create_mast_demo(destination)
    assert not destination.exists()
    for cap in [0, -1, float("inf"), float("nan")]:
        with pytest.raises(ValueError, match="finite and positive"):
            create_mast_demo(destination, max_parent_mib=cap)
    destination.mkdir()
    (destination / "keep.txt").write_text("keep")
    with pytest.raises(FileExistsError):
        create_mast_demo(destination)
    assert (destination / "keep.txt").read_text() == "keep"
