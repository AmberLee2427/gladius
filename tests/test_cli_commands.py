"""Command-line behaviour: argument rules, exit codes and delegation, without real runs."""

import json
import os
from pathlib import Path

import pytest

from gladius import __version__
from gladius.cli import main


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "run.yaml"
    path.write_text("targets: [{id: test, x: 0, y: 0}]\n")
    return path


def fake_run(status="complete", record=None):
    def run(config, **controls):
        if record is not None:
            record.update(controls=controls, name=config.run.name)
        manifest = Path(config.storage.output_directory).parent / "manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({"status": status}))
        return manifest

    return run


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as stop:
        main(["--version"])
    assert stop.value.code == 0
    assert capsys.readouterr().out.strip() == __version__


@pytest.mark.parametrize(
    "argv",
    [[], ["--no-open", "validate", "x.yaml"], ["--tutorial", "validate", "x.yaml"]],
    ids=["nothing", "no-open-without-tutorial", "tutorial-and-subcommand"],
)
def test_conflicting_or_missing_modes_are_usage_errors(argv, capsys):
    with pytest.raises(SystemExit) as stop:
        main(argv)
    assert stop.value.code == 2
    assert "Choose a" in capsys.readouterr().err


def test_tutorial_opens_the_copy_it_just_wrote(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    opened = []
    monkeypatch.setattr(
        "gladius.tutorials.open_tutorial",
        lambda path, nexus=False: opened.append((path, nexus)) or "Starting JupyterLab",
    )
    assert main(["--nexus-tutorial"]) == 0
    out = capsys.readouterr().out
    assert "gladius-nexus-tutorial.ipynb" in out and "Starting JupyterLab" in out
    assert opened[0][1] is True and opened[0][0].parent == tmp_path.resolve()


def test_init_config_and_schema_refuse_to_overwrite(tmp_path, capsys):
    config, schema = tmp_path / "new.yaml", tmp_path / "schema.json"
    assert main(["init-config", str(config)]) == 0
    assert main(["config-schema", str(schema)]) == 0
    assert "targets" in config.read_text()
    assert "properties" in json.loads(schema.read_text())
    capsys.readouterr()
    for argv in (["init-config", str(config)], ["config-schema", str(schema)]):
        assert main(argv) == 1
        assert "FileExistsError" in capsys.readouterr().err


def test_validate_writes_resolved_configuration_without_running(config_file, tmp_path, capsys):
    resolved = tmp_path / "resolved.yaml"
    assert main(["validate", str(config_file), "--resolved", str(resolved)]) == 0
    assert "Configuration is valid" in capsys.readouterr().out
    assert Path(
        __import__("yaml").safe_load(resolved.read_text())["storage"]["output_directory"]
    ).is_absolute()
    assert main(["validate", str(config_file), "--resolved", str(resolved)]) == 1  # no overwrite


def test_validate_reports_invalid_configuration(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("targets: []\nunknown_key: 1\n")
    assert main(["validate", str(bad)]) == 1
    assert "gladius:" in capsys.readouterr().err


def test_run_forwards_name_and_cache_controls(config_file, monkeypatch):
    seen = {}
    monkeypatch.setattr("gladius.cli.run", fake_run(record=seen))
    assert main(["run", str(config_file), "--name", "review", "--fresh", "--refresh-inputs"]) == 0
    assert seen == {"controls": {"fresh": True, "refresh_inputs": True}, "name": "review"}
    seen.clear()
    assert main(["run", str(config_file)]) == 0
    assert seen["controls"] == {} and seen["name"] == "default"


def test_run_exit_code_reflects_manifest_status(config_file, monkeypatch, capsys):
    monkeypatch.setattr("gladius.cli.run", fake_run(status="partial"))
    assert main(["run", str(config_file)]) == 1
    assert "Manifest:" in capsys.readouterr().out


def test_keyboard_interrupt_exits_130(config_file, monkeypatch, capsys):
    def interrupted(config, **controls):
        raise KeyboardInterrupt

    monkeypatch.setattr("gladius.cli.run", interrupted)
    assert main(["run", str(config_file)]) == 130
    assert "KeyboardInterrupt" in capsys.readouterr().err


def test_run_loads_explicit_env_file(config_file, tmp_path, monkeypatch):
    monkeypatch.delenv("GLADIUS_TEST_EXPLICIT", raising=False)
    env = tmp_path / "creds.env"
    env.write_text("GLADIUS_TEST_EXPLICIT=yes\n")
    monkeypatch.setattr("gladius.cli.run", fake_run())
    assert main(["run", str(config_file), "--env-file", str(env)]) == 0
    assert os.environ["GLADIUS_TEST_EXPLICIT"] == "yes"


def test_gui_passes_options_and_loads_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("GLADIUS_TEST_GUI", raising=False)
    env = tmp_path / "gui.env"
    env.write_text("GLADIUS_TEST_GUI=1\n")
    calls = []
    monkeypatch.setattr(
        "gladius.web.serve", lambda workspace, **kwargs: calls.append((workspace, kwargs))
    )
    argv = ["gui", "--workspace", str(tmp_path), "--port", "9000", "--env-file", str(env)]
    assert main(argv + ["--nexus", "--iframe-origin", "self"]) == 0
    assert calls == [
        (
            tmp_path,
            {"port": 9000, "public_url": None, "nexus": True, "iframe_origin": "self"},
        )
    ]
    assert os.environ["GLADIUS_TEST_GUI"] == "1"


def test_token_refuses_symlink_and_missing_directory(tmp_path, capsys):
    target = tmp_path / "real.env"
    target.write_text("")
    link = tmp_path / "link.env"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    assert main(["token", "--env-file", str(link)]) == 1
    assert "symlink" in capsys.readouterr().err
    assert main(["token", "--env-file", str(tmp_path / "nowhere" / ".env")]) == 1
    assert "directory does not exist" in capsys.readouterr().err


def test_force_replaces_existing_token_without_prompting(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("MAST_API_TOKEN=old\n")
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("--force must not prompt"))
    monkeypatch.setattr("gladius.cli.getpass.getpass", lambda _: "test-only-new")
    assert main(["token", "--env-file", str(path), "--force"]) == 0
    assert "test-only-new" in path.read_text()


def test_offline_demo_rejects_mast_only_options(tmp_path, capsys):
    assert main(["demo", str(tmp_path / "demo"), "--max-parent-mib", "10"]) == 1
    assert "apply to demo mast-demo" in capsys.readouterr().err
    assert main(["demo", str(tmp_path / "demo"), "--directory", str(tmp_path)]) == 1


def test_mast_demo_uses_default_directory_and_size_limit(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GLADIUS_TEST_DEMO", raising=False)
    env = tmp_path / "demo.env"
    env.write_text("GLADIUS_TEST_DEMO=1\n")
    created = {}

    def create(directory, max_parent_mib):
        created.update(directory=directory, limit=max_parent_mib)
        path = tmp_path / "mast-demo" / "config.yaml"
        path.parent.mkdir()
        path.write_text("targets: [{id: t, ra: 1.0, dec: 1.0}]\ninputs: {mode: mast}\n")
        return path

    monkeypatch.setattr("gladius.cli.create_mast_demo", create)
    monkeypatch.setattr("gladius.cli.run", fake_run())
    assert main(["demo", "mast-demo", "--env-file", str(env)]) == 0
    assert created == {"directory": Path("mast-demo"), "limit": 512}
    assert os.environ["GLADIUS_TEST_DEMO"] == "1"
    assert "Querying MAST" in capsys.readouterr().out
