"""Tutorial files must stay editable, credential-free and safe to launch."""

import ast
import json
from pathlib import Path

from gladius.cli import main
from gladius.tutorials import open_tutorial, write_tutorial


def test_copy_tutorials_does_not_overwrite_user_work(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["--tutorial", "--no-open"]) == 0
    original = tmp_path / "gladius-local-tutorial.ipynb"
    original.write_text("user edits")
    assert main(["--tutorial", "--no-open"]) == 0
    assert original.read_text() == "user edits"
    assert (tmp_path / "gladius-local-tutorial-2.ipynb").is_file()
    assert main(["--nexus-tutorial", "--no-open"]) == 0
    assert (tmp_path / "gladius-nexus-tutorial.ipynb").is_file()


def test_bundled_tutorials_match_sources_and_are_clean(tmp_path):
    for nexus, filename in ((False, "local_cutouts.ipynb"), (True, "nexus_cutouts.ipynb")):
        copied = write_tutorial(tmp_path, nexus=nexus)
        source = Path(__file__).resolve().parents[1] / "notebooks" / Path(filename).stem / filename
        assert copied.read_bytes() == source.read_bytes()
        notebook = json.loads(copied.read_text())
        for cell in notebook["cells"]:
            if cell["cell_type"] == "code":
                assert cell["execution_count"] is None and cell["outputs"] == []
                ast.parse("".join(cell["source"]))


def test_nexus_open_uses_runtime_root_not_home_guess(tmp_path, monkeypatch, capsys):
    import gladius.tutorials as module

    monkeypatch.setattr(module, "_register_kernel", lambda _: None)

    monkeypatch.setenv("JUPYTERHUB_SERVICE_PREFIX", "/user/amber/commissioning/")
    monkeypatch.delenv("JUPYTERHUB_PUBLIC_URL", raising=False)
    monkeypatch.delenv("NEXUS_SERVER_URL", raising=False)
    monkeypatch.delenv("JUPYTERHUB_HOST", raising=False)
    monkeypatch.setattr(module.shutil, "which", lambda _: "/usr/bin/jupyter")
    monkeypatch.setattr(
        module,
        "_running_servers",
        lambda _: [
            {
                "root_dir": str(tmp_path),
                "base_url": "/user/amber/commissioning/",
                "token": "private-runtime-token",
                "url": "http://internal-host:8888/",
            }
        ],
    )
    opened = []
    monkeypatch.setattr(module.webbrowser, "open", lambda url: opened.append(url))
    folder = tmp_path / "folder with spaces"
    folder.mkdir()
    path = write_tutorial(folder, nexus=True)
    message = open_tutorial(path, nexus=True)
    assert opened == [
        "https://roman.science.stsci.edu/user/amber/commissioning/lab/tree/folder%20with%20spaces/gladius-nexus-tutorial.ipynb"
    ]
    assert "private-runtime-token" not in message + capsys.readouterr().out
    assert "internal-host" not in message


def test_local_open_and_missing_jupyter(tmp_path, monkeypatch):
    import gladius.tutorials as module

    monkeypatch.setattr(module, "_register_kernel", lambda _: None)

    path = write_tutorial(tmp_path)
    monkeypatch.setattr(module.shutil, "which", lambda _: None)
    assert "Notebook saved" in open_tutorial(path)
    launched = []
    monkeypatch.setattr(module.shutil, "which", lambda _: "/usr/bin/jupyter")
    monkeypatch.setattr(
        module.subprocess, "Popen", lambda args, **kwargs: launched.append((args, kwargs))
    )
    assert "Starting JupyterLab" in open_tutorial(path)
    assert launched[0][0] == [
        "/usr/bin/jupyter",
        "lab",
        path.name,
        "--ServerApp.root_dir",
        str(tmp_path),
    ]
    assert launched[0][1]["cwd"] == tmp_path


def test_registered_kernel_matches_cli_interpreter(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import gladius.tutorials as module

    path = write_tutorial(tmp_path)
    calls = []
    monkeypatch.setattr(module, "find_spec", lambda _: object())
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda args, **kwargs: calls.append(args) or SimpleNamespace(returncode=0),
    )
    assert module._register_kernel(path) is None
    assert calls[0][:4] == [module.sys.executable, "-m", "ipykernel", "install"]
    name = calls[0][calls[0].index("--name") + 1]
    assert json.loads(path.read_text())["metadata"]["kernelspec"]["name"] == name


def test_tutorial_workflows_differ_only_in_gui_connection():
    root = Path(__file__).resolve().parents[1] / "notebooks"
    local = json.loads((root / "local_cutouts/local_cutouts.ipynb").read_text())
    nexus = json.loads((root / "nexus_cutouts/nexus_cutouts.ipynb").read_text())
    local_code = ["".join(c["source"]) for c in local["cells"] if c["cell_type"] == "code"]
    nexus_code = ["".join(c["source"]) for c in nexus["cells"] if c["cell_type"] == "code"]
    assert len(local_code) == len(nexus_code)
    for left, right in zip(local_code, nexus_code, strict=True):
        left = left.replace(
            "\n# Match the scheme, hostname, and port in your JupyterLab address.\n"
            'NOTEBOOK_ORIGIN = "http://localhost:8888"\n',
            "",
        )
        left = left.replace("iframe_origin=NOTEBOOK_ORIGIN", 'nexus=True, iframe_origin="self"')
        left = left.replace('gui_server.url + "/"', "gui_server.public_url")
        assert left == right


def test_archive_cells_are_optional_without_credentials(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = Path(__file__).resolve().parents[1] / "notebooks"
    for kind in ("local", "nexus"):
        notebook = json.loads((root / f"{kind}_cutouts/{kind}_cutouts.ipynb").read_text())
        namespace = {}
        for cell in notebook["cells"]:
            if cell["cell_type"] != "code":
                continue
            if cell["id"] != "nexus-gui-start":
                exec("".join(cell["source"]), namespace)
        assert namespace["RUN_ARCHIVE_EXAMPLE"] is False
        assert "config" not in namespace
        assert "missions" not in namespace


def test_gui_opens_before_archive_setup_without_config(tmp_path, monkeypatch):
    import threading
    from types import SimpleNamespace

    import IPython.display

    import gladius.web

    calls = []

    class FakeThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

    def server(workspace, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            serve_forever=lambda: None,
            public_url="https://example.invalid/proxy/1234/",
            url="http://localhost:1234",
        )

    monkeypatch.setattr(gladius.web, "GuiServer", server)
    monkeypatch.setattr(threading, "Thread", FakeThread)
    monkeypatch.setattr(IPython.display, "display", lambda *args: None)
    monkeypatch.chdir(tmp_path)
    root = Path(__file__).resolve().parents[1] / "notebooks"
    for kind in ("local", "nexus"):
        notebook = json.loads((root / f"{kind}_cutouts/{kind}_cutouts.ipynb").read_text())
        namespace = {}
        for cell in notebook["cells"]:
            if cell["cell_type"] == "code":
                exec("".join(cell["source"]), namespace)
            if cell["id"] == "nexus-gui-start":
                break
        assert "gui_server" in namespace
        assert namespace["ENV_FILE"] is None
        assert calls[-1]["initial_config"] is None
