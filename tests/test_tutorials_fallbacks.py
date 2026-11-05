"""Fallback paths for opening tutorials: no Jupyter, no kernel, unknown server roots."""

import json
import subprocess
from types import SimpleNamespace

import pytest

import gladius.tutorials as module
from gladius.tutorials import open_tutorial, write_tutorial


def test_running_servers_keeps_only_well_formed_server_records(monkeypatch):
    lines = [
        json.dumps({"root_dir": "/a", "base_url": "/"}),
        "not json at all",
        json.dumps({"base_url": "/no-root"}),
        json.dumps(["root_dir"]),
        json.dumps({"root_dir": "/b", "base_url": "/user/x/"}),
        "",
    ]
    seen = {}

    def fake_run(args, **kwargs):
        seen["args"], seen["kwargs"] = args, kwargs
        return SimpleNamespace(stdout="\n".join(lines))

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    servers = module._running_servers("/usr/bin/jupyter")
    assert [s["root_dir"] for s in servers] == ["/a", "/b"]
    assert seen["args"] == ["/usr/bin/jupyter", "server", "list", "--json"]
    assert seen["kwargs"]["timeout"] == 15


def test_kernel_registration_needs_ipykernel(tmp_path, monkeypatch):
    path = write_tutorial(tmp_path)
    before = path.read_text()
    monkeypatch.setattr(module, "find_spec", lambda _: None)
    message = module._register_kernel(path)
    assert "roman-gladius[notebook]" in message
    assert path.read_text() == before


def test_kernel_registration_failure_leaves_notebook_unchanged(tmp_path, monkeypatch):
    path = write_tutorial(tmp_path)
    before = path.read_text()
    monkeypatch.setattr(module, "find_spec", lambda _: object())
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr=""),
    )
    assert "Could not register" in module._register_kernel(path)
    assert path.read_text() == before


def test_unused_filename_search_skips_every_existing_copy(tmp_path):
    first = write_tutorial(tmp_path)
    second = write_tutorial(tmp_path)
    third = write_tutorial(tmp_path, nexus=True)
    assert [p.name for p in (first, second, third)] == [
        "gladius-local-tutorial.ipynb",
        "gladius-local-tutorial-2.ipynb",
        "gladius-nexus-tutorial.ipynb",
    ]


@pytest.mark.parametrize("error", [OSError("no such program"), subprocess.TimeoutExpired("x", 1)])
def test_open_reports_kernel_registration_errors_without_launching(tmp_path, monkeypatch, error):
    path = write_tutorial(tmp_path)
    monkeypatch.setattr(module.shutil, "which", lambda _: "/usr/bin/jupyter")

    def broken(_):
        raise error

    launched = []
    monkeypatch.setattr(module, "_register_kernel", broken)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: launched.append(a))
    assert "Could not register" in open_tutorial(path)
    assert not launched


def test_open_returns_kernel_message_instead_of_starting_jupyter(tmp_path, monkeypatch):
    path = write_tutorial(tmp_path)
    launched = []
    monkeypatch.setattr(module.shutil, "which", lambda _: "/usr/bin/jupyter")
    monkeypatch.setattr(module, "_register_kernel", lambda _: "choose a kernel manually")
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: launched.append(a))
    assert open_tutorial(path) == "choose a kernel manually"
    assert not launched


@pytest.fixture
def nexus(tmp_path, monkeypatch):
    path = write_tutorial(tmp_path, nexus=True)
    monkeypatch.setattr(module.shutil, "which", lambda _: "/usr/bin/jupyter")
    monkeypatch.setattr(module, "_register_kernel", lambda _: None)
    monkeypatch.setenv("JUPYTERHUB_SERVICE_PREFIX", "/user/amber/commissioning/")
    for name in ("JUPYTERHUB_PUBLIC_URL", "NEXUS_SERVER_URL", "JUPYTERHUB_HOST"):
        monkeypatch.delenv(name, raising=False)
    opened = []
    monkeypatch.setattr(module.webbrowser, "open", lambda url: opened.append(url))
    return SimpleNamespace(path=path, root=tmp_path, opened=opened, patch=monkeypatch)


def test_nexus_outside_a_hub_session_asks_user_to_open_manually(nexus):
    nexus.patch.delenv("JUPYTERHUB_SERVICE_PREFIX")
    assert "On Nexus, run this command" in open_tutorial(nexus.path, nexus=True)
    assert not nexus.opened


def test_nexus_server_listing_failure_degrades_to_manual_instructions(nexus):
    def broken(_):
        raise OSError("jupyter vanished")

    nexus.patch.setattr(module, "_running_servers", broken)
    assert "server root could not be determined" in open_tutorial(nexus.path, nexus=True)
    assert not nexus.opened


@pytest.mark.parametrize(
    "server",
    [
        {"root_dir": "/somewhere/else", "base_url": "/user/amber/commissioning/"},
        {"root_dir": "{root}", "base_url": "/user/other/"},
    ],
    ids=["tutorial-outside-server-root", "different-user-server"],
)
def test_nexus_ignores_servers_that_do_not_own_the_notebook(nexus, server):
    server = {**server, "root_dir": server["root_dir"].format(root=nexus.root)}
    nexus.patch.setattr(module, "_running_servers", lambda _: [server])
    assert "server root could not be determined" in open_tutorial(nexus.path, nexus=True)
    assert not nexus.opened
