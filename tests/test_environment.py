import os

from gladius_roman import load_environment
from gladius_roman.cli import main
from gladius_roman.web import GuiServer


def test_explicit_file_precedence_and_literal_values(tmp_path, monkeypatch):
    monkeypatch.delenv("GLADIUS_TEST_TOKEN", raising=False)
    monkeypatch.setenv("GLADIUS_TEST_EXISTING", "shell")
    (tmp_path / ".env").write_text(
        'GLADIUS_TEST_TOKEN="literal-${GLADIUS_TEST_EXISTING}"\n'
        'GLADIUS_TEST_EXISTING=file\n'
    )
    assert load_environment(tmp_path)
    assert os.environ["GLADIUS_TEST_TOKEN"] == "literal-${GLADIUS_TEST_EXISTING}"
    assert os.environ["GLADIUS_TEST_EXISTING"] == "shell"
    child = tmp_path / "child"
    child.mkdir()
    assert not load_environment(child)
    assert not (child / ".env").exists()


def test_cli_uses_yaml_directory_not_launch_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("GLADIUS_TEST_CLI", raising=False)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / ".env").write_text("GLADIUS_TEST_CLI=from-config\n")
    (tmp_path / ".env").write_text("GLADIUS_TEST_CLI=from-launch\n")
    (config_dir / "run.yaml").write_text("targets: [{id: test, x: 0, y: 0}]\n")
    monkeypatch.chdir(tmp_path)
    def fake_run(config):
        assert os.environ["GLADIUS_TEST_CLI"] == "from-config"
        manifest = tmp_path / "manifest.json"
        manifest.write_text('{"status": "complete"}')
        return manifest
    monkeypatch.setattr("gladius_roman.cli.run", fake_run)
    assert main(["run", "config/run.yaml"]) == 0


def test_gui_loads_workspace_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("MAST_API_TOKEN", raising=False)
    (tmp_path / ".env").write_text("MAST_API_TOKEN=test-only-sentinel\n")
    server = GuiServer(tmp_path, port=0)
    try:
        assert os.environ["MAST_API_TOKEN"] == "test-only-sentinel"
    finally:
        server.server_close()
