"""Tutorial files must stay editable, credential-free and safe to launch."""

import ast
import json
from pathlib import Path

import pytest

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
    import textwrap

    for left, right in zip(local_code, nexus_code, strict=True):
        if right.startswith("if RUN_ARCHIVE_EXAMPLE:\n"):
            right = textwrap.dedent(right.split("\n", 1)[1])
        right = right.replace(
            "RUN_ARCHIVE_EXAMPLE = False  # True enables the archive cells on Nexus.\n\n", ""
        )
        left = left.replace(
            "\n# Match the scheme, hostname, and port in your JupyterLab address.\n"
            'NOTEBOOK_ORIGIN = "http://localhost:8888"\n',
            "",
        )
        left = left.replace("iframe_origin=NOTEBOOK_ORIGIN", 'nexus=True, iframe_origin="self"')
        left = left.replace('gui_server.url + "/"', "gui_server.public_url")
        left = left.replace("SHOW_ALADIN_INLINE = True", "SHOW_ALADIN_INLINE = False")
        assert left == right


def test_archive_cells_are_optional_without_credentials(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = Path(__file__).resolve().parents[1] / "notebooks"
    for kind in ("nexus",):
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


def test_notebook_creates_target_csv_and_configuration(tmp_path, monkeypatch):
    from gladius import read_targets_csv

    monkeypatch.chdir(tmp_path)
    root = Path(__file__).resolve().parents[1] / "notebooks"
    for kind in ("local", "nexus"):
        notebook = json.loads((root / f"{kind}_cutouts/{kind}_cutouts.ipynb").read_text())
        cells = {c["id"]: "".join(c["source"]) for c in notebook["cells"]}
        namespace = {}
        exec(cells["ui-settings"], namespace)
        exec(cells["gladius-02"], namespace)
        targets = read_targets_csv(namespace["TARGET_CSV"])
        assert targets[0].id == "sgr-a-star"
        namespace["RUN_ARCHIVE_EXAMPLE"] = True
        exec(cells["nexus-config"], namespace)
        assert namespace["config"].inputs.mode == "mast"
        assert namespace["config"].targets[0].ra == 266.416837


@pytest.mark.parametrize("response", ["valid-test-token", "", "denied-test-token"])
def test_notebook_auth_prompt_retries_once_without_printing_token(
    tmp_path, monkeypatch, capsys, response
):
    import getpass
    import os
    from types import SimpleNamespace

    monkeypatch.delenv("MAST_API_TOKEN", raising=False)
    monkeypatch.setattr(getpass, "getpass", lambda _: response)
    notebook = json.loads(
        (
            Path(__file__).resolve().parents[1] / "notebooks/local_cutouts/local_cutouts.ipynb"
        ).read_text()
    )
    source = "".join(next(c for c in notebook["cells"] if c["id"] == "nexus-run")["source"])
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text('{"stage_counts": {}}')
    calls = []

    def run(config, **kwargs):
        calls.append(os.environ.get("MAST_API_TOKEN"))
        if calls[-1] != "valid-test-token":
            raise PermissionError("test denial")
        return manifest_path

    namespace = {
        "config": SimpleNamespace(inputs=SimpleNamespace(mode="mast")),
        "run": run,
        "json": json,
    }
    exec(source, namespace)
    assert len(calls) == (1 if not response else 2)
    assert namespace["manifest_path"] == (manifest_path if response == "valid-test-token" else None)
    output = capsys.readouterr().out
    if response:
        assert response not in output
    if response != "valid-test-token":
        assert "MAST_API_TOKEN" not in os.environ


def test_local_aladin_view_uses_explicit_coordinates_and_survey(monkeypatch):
    from types import SimpleNamespace
    from urllib.parse import parse_qs, urlsplit

    import IPython.display

    shown = []
    monkeypatch.setattr(IPython.display, "display", shown.append)
    notebook = json.loads(
        (
            Path(__file__).resolve().parents[1] / "notebooks/local_cutouts/local_cutouts.ipynb"
        ).read_text()
    )
    source = "".join(next(c for c in notebook["cells"] if c["id"] == "finding-chart")["source"])
    namespace = {"config": SimpleNamespace(targets=[SimpleNamespace(ra=12.5, dec=-3.0)])}
    exec(source, namespace)
    parameters = parse_qs(urlsplit(namespace["aladin_url"]).query)
    assert parameters["ra"] == ["12.5"]
    assert parameters["dec"] == ["-3.0"]
    assert parameters["hips"] == ["https://irsa.ipac.caltech.edu/data/hips/CDS/2MASS/Color"]
    assert len(shown) == 2
    assert isinstance(shown[0], IPython.display.Markdown)
    from ipyaladin import Aladin

    widget = shown[1]
    assert isinstance(widget, Aladin)
    assert widget.target.ra.deg == pytest.approx(12.5)
    assert widget.target.dec.deg == pytest.approx(-3.0)
    assert widget.fov.deg == pytest.approx(0.1)
    assert widget.survey == "https://irsa.ipac.caltech.edu/data/hips/CDS/2MASS/Color"
