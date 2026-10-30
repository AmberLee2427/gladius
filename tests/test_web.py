import json
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
import yaml

from gladius_roman.config import load_config
from gladius_roman.web import GuiServer


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
