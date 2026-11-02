import json
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
import yaml

from gladius.config import load_config
from gladius.web import GuiServer


@pytest.fixture
def gui(tmp_path):
    server = GuiServer(tmp_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


def request(gui, path, payload=None, *, token=True, origin=None):
    headers = {"X-Roman-Token": gui.token} if token else {}
    if origin:
        headers["Origin"] = origin
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = Request(gui.url + path, data=data, headers=headers)
    try:
        with urlopen(req, timeout=10) as response:
            raw = response.read()
            return response.status, json.loads(
                raw
            ) if response.headers.get_content_type() == "application/json" else raw
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_gui_home_session_protection_and_validation(gui):
    status, page = request(gui, "/", token=False)
    assert status == 200 and b"Gladius" in page
    assert b"__BOOTSTRAP__" not in page
    assert request(gui, "/api/defaults", token=False)[0] == 403
    assert request(gui, "/api/defaults", origin="https://example.com")[0] == 403
    assert request(gui, "/api/run", {"yaml": "{}"}, token=False)[0] == 403
    assert request(gui, "/api/validate", {"yaml": "invalid: ["})[0] == 400
    assert request(gui, "/api/validate", {"yaml": 42})[0] == 400
    assert request(gui, "/api/targets", {"csv": 42})[0] == 400
    status, csv = request(gui, "/api/targets", {"csv": "id,ra,dec,source\ne,270,-29,cat\n"})
    assert status == 200 and csv["targets"][0]["metadata"]["source"] == "cat"
    status, config = request(
        gui, "/api/validate", {"yaml": yaml.safe_dump({"targets": csv["targets"]})}
    )
    assert status == 200 and config["configuration"]["storage"]["output_directory"] == str(
        gui.workspace / "cutouts"
    )
    assert not (gui.workspace / ".gladius-gui").exists()


def test_real_pipeline_run_from_gui(gui, demo):
    config = load_config(demo)
    status, job = request(gui, "/api/run", {"yaml": yaml.safe_dump(config.model_dump(mode="json"))})
    assert status == 202
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        status, result = request(gui, "/api/jobs/" + job["id"])
        if result["state"] in ("complete", "failed"):
            break
        time.sleep(0.05)
    assert result["state"] == "complete", result
    assert result["summary"]["complete"] == 2
    status, manifest = request(gui, "/api/jobs/" + job["id"] + "/manifest")
    assert status == 200 and json.loads(manifest)["status"] == "complete"
    assert (gui.workspace / ".gladius-gui" / job["id"] / "config.yaml").is_file()
    _, defaults = request(gui, "/api/defaults")
    assert defaults["last_job"]["id"] == job["id"]
    assert defaults["configuration"]["targets"][0]["id"] == "demo-event"


def test_active_run_conflict_and_failed_run_state(gui, demo):
    entered, release = threading.Event(), threading.Event()

    def worker(config, progress):
        entered.set()
        release.wait(timeout=5)
        raise ValueError("intentional test failure")

    gui.jobs.runner = worker
    payload = {"yaml": yaml.safe_dump(load_config(demo).model_dump(mode="json"))}
    _, job = request(gui, "/api/run", payload)
    assert entered.wait(timeout=3)
    try:
        assert request(gui, "/api/run", payload)[0] == 409
    finally:
        release.set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        _, result = request(gui, "/api/jobs/" + job["id"])
        if result["state"] == "failed":
            break
        time.sleep(0.01)
    assert result["state"] == "failed" and "intentional test failure" in result["error"]


def test_bundled_branding_and_license_resources(gui):
    status, page = request(gui, "/", token=False)
    assert status == 200
    assert b"Gladius \xc2\xb7 Roman image cutouts" in page
    assert b'rel="icon"' in page
    assert b'class="header-actions"' in page
    assert b'>Local</div>' not in page
    status, theme_script = request(gui, "/assets/theme.js", token=False)
    assert status == 200 and b"gladius-theme" in theme_script
    status, theme_css = request(gui, "/assets/theme.css", token=False)
    assert status == 200 and b"color-scheme: dark" in theme_css
    for asset in ("family.css", "fonts.css", "family-theme.js", "family-font-0.ttf"):
        status, content = request(gui, f"/assets/family/{asset}", token=False)
        assert status == 200 and content
    assert request(gui, "/assets/family/../../config.py", token=False)[0] == 404
    for url in (
        "https://rges-pit.org/",
        "https://github.com/AmberLee2427/gladius",
        "https://archive.stsci.edu/missions-and-data/roman",
        "https://mldb.rges-pit.com",
    ):
        assert url.encode() in page
    assert b'src="./assets/gladius-logo.png"' in page
    for route in ("/assets/gladius-emblem.png", "/assets/gladius-logo.png", "/assets/rges-pit.png"):
        status, png = request(gui, route, token=False)
        assert status == 200 and png.startswith(b"\x89PNG\r\n\x1a\n")
    status, license_text = request(gui, "/license", token=False)
    assert status == 200 and b"Redistribution and use" in license_text
    status, notices = request(gui, "/notices", token=False)
    assert status == 200 and b"RGES-PIT" in notices
    status, dependencies = request(gui, "/dependencies", token=False)
    assert status == 200 and b"Astropy" in dependencies and b"Pydantic" in dependencies
    assert b"__NONCE__" not in dependencies
    assert b'id="themeToggle"' in dependencies
    status, licenses = request(gui, "/dependency-licenses", token=False)
    assert status == 200 and b"Copyright" in licenses and b"NumPy" in licenses
    assert request(gui, "/assets/unknown.png", token=False)[0] == 404
    assert request(gui, "/assets/../config.py", token=False)[0] == 404


def test_coordinate_conversion_and_workspace_are_portable(gui):
    status, data = request(
        gui,
        "/api/target-coordinate",
        {"id": "gc", "frame": "galactic", "longitude": 0, "latitude": 0},
    )
    assert status == 200
    assert data["target"]["ra"] == pytest.approx(266.405, abs=0.002)
    assert data["target"]["x"] is None
    assert (
        request(
            gui,
            "/api/target-coordinate",
            {"id": "bad", "frame": "galactic", "longitude": 0, "latitude": 91},
        )[0]
        == 400
    )
    _, defaults = request(gui, "/api/defaults")
    assert defaults["workspace"] == str(gui.workspace)
    assert defaults["configuration"]["astrometry"]["corrected_directory"] == "gaia_wcs"


def test_real_archive_test_configuration_uses_metadata_without_downloading(gui, monkeypatch):
    import sys
    from types import ModuleType

    from astropy.table import Table

    class Missions:
        dataset_kwds = {"roman": "fileSetName"}

        def query_criteria(self, **criteria):
            assert criteria["productLevel"] == "2" and criteria["limit"] == 5
            return Table(
                rows=[("data-a", 270.0, -29.0), ("data-b", 271.0, -30.0)],
                names=["fileSetName", "ra", "dec"],
            )

        def get_unique_product_list(self, rows):
            dataset = str(rows[0]["fileSetName"])
            return Table(
                rows=[(dataset + "_cal.asdf", 2000 if dataset == "data-a" else 1000)],
                names=["filename", "size"],
            )

        def filter_products(self, products, **criteria):
            assert criteria == {"file_suffix": "_cal"}
            return products

        def download_products(self, *args, **kwargs):
            pytest.fail("Load test must never download images")

    module = ModuleType("astroquery.mast")
    module.MastMissions = lambda **kwargs: Missions()
    monkeypatch.setitem(sys.modules, "astroquery.mast", module)
    monkeypatch.delenv("MAST_API_TOKEN", raising=False)
    status, data = request(gui, "/api/test-config", {"base_directory": str(gui.workspace)})
    assert status == 200
    config = data["configuration"]
    assert data["download_bytes"] == 1000
    assert config["inputs"]["mast_criteria"] == {"fileSetName": "data-b"}
    assert config["inputs"]["product_filename"] == "data-b_cal.asdf"
    assert config["targets"][0]["ra"] == 271
    assert config["extraction"]["size"] == 64 and not config["stacks"]["enabled"]
    assert config["storage"]["output_directory"] == str(gui.workspace / "gladius-mast-test")
    assert not (gui.workspace / "gladius-mast-test").exists()
    assert not (gui.workspace / ".gladius-gui").exists()


def test_jupyter_proxy_environment_and_explicit_override(monkeypatch):
    from gladius.web import _proxy_url

    for key in (
        "JUPYTERHUB_SERVICE_PREFIX",
        "JUPYTERHUB_PUBLIC_URL",
        "NEXUS_SERVER_URL",
        "JUPYTERHUB_HOST",
    ):
        monkeypatch.delenv(key, raising=False)
    assert _proxy_url(8768) is None
    monkeypatch.setenv("JUPYTERHUB_SERVICE_PREFIX", "/user/amber/commissioning/")
    assert _proxy_url(8768) is None  # A generic Hub prefix does not identify Nexus.
    assert (
        _proxy_url(8768, nexus=True)
        == "https://roman.science.stsci.edu/user/amber/commissioning/proxy/8768/"
    )
    monkeypatch.setenv("JUPYTERHUB_PUBLIC_URL", "https://hub.example/user/amber/analysis/")
    assert _proxy_url(8768) == "https://hub.example/user/amber/analysis/proxy/8768/"
    assert (
        _proxy_url(8768, "https://custom.example/work/proxy/8768/")
        == "https://custom.example/work/proxy/8768/"
    )
    for value in (
        "//evil.example/",
        "https://user:secret@host/",
        "https://host/?token=secret",
        'https://host/"bad',
    ):
        with pytest.raises(ValueError):
            _proxy_url(8768, value)


def test_proxy_origin_is_explicit_not_inferred_from_headers(tmp_path):
    server = GuiServer(
        tmp_path, port=0, public_url="https://roman.science.stsci.edu/user/amber/named/proxy/8768/"
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert request(server, "/api/defaults", origin="https://roman.science.stsci.edu")[0] == 200
        assert request(server, "/api/defaults", origin="https://evil.example")[0] == 403
        assert (
            request(server, "/api/defaults", token=False, origin="https://roman.science.stsci.edu")[
                0
            ]
            == 403
        )
        req = Request(
            server.url + "/",
            headers={"Host": "evil.example", "X-Forwarded-Host": "roman.science.stsci.edu"},
        )
        with pytest.raises(HTTPError) as error:
            urlopen(req)
        assert error.value.code == 403
        req = Request(server.url + "/", headers={"Host": "roman.science.stsci.edu"})
        with urlopen(req) as response:
            assert response.status == 200
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_browser_paths_remain_within_jupyter_proxy(gui):
    import re
    from urllib.parse import urljoin

    base = "https://roman.science.stsci.edu/user/amber/named/proxy/8768/"
    for route in ("/", "/dependencies"):
        _, raw = request(gui, route, token=False)
        html = raw.decode()
        for link in re.findall(r'(?:href|src)="([^"]+)"', html):
            if link.startswith("https:"):
                continue
            assert urljoin(base + route.lstrip("/"), link).startswith(base)
        assert 'href="/assets/' not in html and 'src="/assets/' not in html
    _, page = request(gui, "/", token=False)
    assert b'fetch("." + path' in page
    assert b'fetch("./api/jobs/"' in page


def test_startup_prints_named_server_link(tmp_path, monkeypatch, capsys):
    from gladius.web import serve

    monkeypatch.setenv("JUPYTERHUB_SERVICE_PREFIX", "/user/amber/commissioning/")
    monkeypatch.delenv("JUPYTERHUB_PUBLIC_URL", raising=False)
    monkeypatch.delenv("NEXUS_SERVER_URL", raising=False)
    monkeypatch.setattr(GuiServer, "serve_forever", lambda self: None)
    serve(tmp_path, port=0, nexus=True)
    output = capsys.readouterr().out
    assert "Gladius GUI: https://roman.science.stsci.edu/user/amber/commissioning/proxy/" in output
    assert "Local listener: http://127.0.0.1:" in output
    assert "token" not in output.lower()


def test_iframe_policy_is_explicit_and_origin_limited(tmp_path):
    from gladius.web import _frame_ancestors

    for origin, expected in (
        (None, "'none'"),
        ("self", "'self'"),
        ("http://localhost:8888", "'self' http://localhost:8888"),
    ):
        server = GuiServer(tmp_path, port=0, iframe_origin=origin)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(server.url) as response:
                assert f"frame-ancestors {expected};" in response.headers["Content-Security-Policy"]
            assert request(server, "/api/defaults", token=False)[0] == 403
            assert request(server, "/api/defaults", origin="http://localhost:8888")[0] == 403
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
    for origin in (
        "*",
        "https://example.com/path",
        "https://a.example https://b.example",
        "https://example.com; frame-ancestors *",
        "//example.com",
        "https://user:pass@host",
    ):
        with pytest.raises(ValueError):
            _frame_ancestors(origin)


def test_embedded_gui_starts_with_notebook_configuration(tmp_path):
    from gladius.config import RunConfig

    config = RunConfig(targets=[{"id": "notebook-target", "x": 5, "y": 6}], extraction={"size": 42})
    server = GuiServer(tmp_path, port=0, initial_config=config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, data = request(server, "/api/defaults")
        assert status == 200
        assert data["configuration"]["targets"][0]["id"] == "notebook-target"
        assert data["configuration"]["extraction"]["size"] == 42
        assert data["configuration"]["inputs"]["directory"] == str(tmp_path / "images")
        assert not (tmp_path / ".gladius-gui").exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
