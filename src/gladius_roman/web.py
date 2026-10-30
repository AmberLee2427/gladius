"""Loopback-only GUI server sharing the package's configuration and execution API."""

from __future__ import annotations

import json
import secrets
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import yaml

from .config import RunConfig, Target, load_config, parse_config
from .io import atomic_json
from .pipeline import run
from .targets import parse_targets_csv, target_from_coordinates

MAX_REQUEST_BYTES = 16 * 1024 * 1024

# Fixed resource map: never turn a URL into an arbitrary filesystem path.
GUI_RESOURCES = {
    "/assets/theme.js": ("theme.js", "text/javascript; charset=utf-8"),
    "/assets/theme.css": ("theme.css", "text/css; charset=utf-8"),
    "/assets/gladius-logo.png": ("gladius-logo.png", "image/png"),
    "/dependencies": ("dependencies.html", "text/html; charset=utf-8"),
    "/dependency-licenses": ("dependency-licenses.txt", "text/plain; charset=utf-8"),
    "/assets/gladius-emblem.png": ("gladius-emblem.png", "image/png"),
    "/assets/rges-pit.png": ("rges-pit.png", "image/png"),
    "/license": ("license.txt", "text/plain; charset=utf-8"),
    "/notices": ("notices.txt", "text/plain; charset=utf-8"),
}


class BusyError(ValueError):
    """The GUI already owns an active pipeline run."""


class Jobs:
    """One active run with bounded progress history and durable submitted YAML."""

    def __init__(self, workspace, runner=run):
        self.workspace = Path(workspace).resolve()
        self.runner = runner
        self.lock = threading.RLock()
        self.jobs = {}

    def snapshot(self, identifier):
        with self.lock:
            if identifier not in self.jobs:
                raise KeyError("Unknown run")
            return json.loads(json.dumps(self.jobs[identifier]))

    def _save(self, identifier):
        atomic_json(
            self.workspace / ".gladius-gui" / identifier / "job.json", self.jobs[identifier]
        )

    def submit(self, config):
        with self.lock:
            if any(j["state"] in ("queued", "running") for j in self.jobs.values()):
                raise BusyError("A run is already active. Wait for it to finish.")
            identifier = uuid4().hex
            directory = self.workspace / ".gladius-gui" / identifier
            directory.mkdir(parents=True)
            (directory / "config.yaml").write_text(
                yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False)
            )
            self.jobs[identifier] = {
                "id": identifier,
                "state": "queued",
                "logs": [],
                "submitted_utc": datetime.now(UTC).isoformat(),
                "manifest": None,
                "summary": None,
                "error": None,
            }
            self._save(identifier)
            # Closing a browser does not end a run. On server exit, Python waits
            # for the active worker rather than interrupting its image cleanup.
            threading.Thread(target=self._execute, args=(identifier, config), daemon=False).start()
            return self.snapshot(identifier)

    def _execute(self, identifier, config):
        def progress(message):
            with self.lock:
                job = self.jobs[identifier]
                job["logs"] = (job["logs"] + [str(message)])[-500:]
                self._save(identifier)

        with self.lock:
            self.jobs[identifier]["state"] = "running"
            self._save(identifier)
        try:
            manifest_path = self.runner(config, progress=progress)
            manifest = json.loads(manifest_path.read_text())
            with self.lock:
                job = self.jobs[identifier]
                job["manifest"] = str(manifest_path)
                entries = list(manifest.get("entries", {}).values())
                job["summary"] = {
                    state: sum(e.get("status") == state for e in entries)
                    for state in ("complete", "skipped", "failed")
                }
                job["state"] = "complete" if manifest["status"] == "complete" else "failed"
                if job["state"] == "failed":
                    job["error"] = "The pipeline recorded failures. Inspect the manifest."
        except Exception as exc:
            with self.lock:
                self.jobs[identifier].update(state="failed", error=f"{type(exc).__name__}: {exc}")
        finally:
            with self.lock:
                self.jobs[identifier]["finished_utc"] = datetime.now(UTC).isoformat()
                self._save(identifier)


class GuiServer(ThreadingHTTPServer):
    """Local service; no remote binding or unauthenticated mutation endpoints."""

    def __init__(self, workspace, port=8768, runner=run):
        if not 0 <= port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        self.workspace = Path(workspace).expanduser().resolve()
        if not self.workspace.is_dir():
            raise ValueError("GUI workspace must be an existing directory")
        from .environment import load_environment

        load_environment(self.workspace)
        self.token = secrets.token_urlsafe(32)
        self.jobs = Jobs(self.workspace, runner)
        super().__init__(("127.0.0.1", port), Handler)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_port}"


class Handler(BaseHTTPRequestHandler):
    """Small JSON API; no arbitrary filesystem-serving route."""

    def log_message(self, format, *args):
        return  # Progress belongs in the GUI; request headers never enter logs.

    def _reply(self, status, data, content_type="application/json", filename=None):
        raw = (
            json.dumps(data, allow_nan=False).encode()
            if content_type == "application/json"
            else data
        )
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            f"script-src 'nonce-{self.server.token}'; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self):
        host = self.headers.get("Host")
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        origin = self.headers.get("Origin")
        if host not in allowed or (origin and origin not in {f"http://{h}" for h in allowed}):
            self._reply(403, {"error": "Only this local GUI origin is allowed"})
            return False
        if urlsplit(self.path).path.startswith("/api/") and not secrets.compare_digest(
            self.headers.get("X-Roman-Token", ""), self.server.token
        ):
            self._reply(403, {"error": "Reload the GUI to establish a local session"})
            return False
        return True

    def do_GET(self):
        if not self._authorized():
            return
        path = urlsplit(self.path).path
        if path == "/":
            page = files("gladius_roman").joinpath("web_assets/index.html").read_text(encoding="utf-8")
            bootstrap = json.dumps({"token": self.server.token}).replace("<", "\\u003c")
            page = page.replace("__BOOTSTRAP__", bootstrap).replace("__NONCE__", self.server.token)
            self._reply(200, page.encode(), "text/html; charset=utf-8")
        elif path in GUI_RESOURCES:
            resource, content_type = GUI_RESOURCES[path]
            raw = files("gladius_roman").joinpath("web_assets", resource).read_bytes()
            if content_type.startswith("text/html"):
                raw = raw.replace(b"__NONCE__", self.server.token.encode())
            self._reply(200, raw, content_type)
        elif path == "/api/defaults":
            configuration = RunConfig(targets=[Target(id="example", ra=270, dec=-29)]).model_dump(
                mode="json"
            )
            configuration["targets"] = []
            last_job = None
            with self.server.jobs.lock:
                if self.server.jobs.jobs:
                    identifier = next(reversed(self.server.jobs.jobs))
                    last_job = self.server.jobs.snapshot(identifier)
                    configuration = load_config(
                        self.server.workspace / ".gladius-gui" / identifier / "config.yaml"
                    ).model_dump(mode="json")
            self._reply(
                200,
                {
                    "configuration": configuration,
                    "schema": RunConfig.model_json_schema(),
                    "workspace": str(self.server.workspace),
                    "last_job": last_job,
                },
            )
        elif path.startswith("/api/jobs/"):
            parts = path.removeprefix("/api/jobs/").split("/")
            try:
                job = self.server.jobs.snapshot(parts[0])
                if len(parts) == 2 and parts[1] == "manifest":
                    if not job["manifest"]:
                        raise KeyError("No manifest available for this run")
                    self._reply(
                        200,
                        Path(job["manifest"]).read_bytes(),
                        "application/octet-stream",
                        "manifest.json",
                    )
                elif len(parts) == 1:
                    self._reply(200, job)
                else:
                    raise KeyError("Unknown endpoint")
            except KeyError as exc:
                self._reply(404, {"error": str(exc)})
        else:
            self._reply(404, {"error": "Not found"})

    def do_POST(self):
        if not self._authorized():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_REQUEST_BYTES:
                self._reply(413, {"error": "Request must be between 1 byte and 16 MiB"})
                return
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise ValueError("Expected application/json")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object")
            path = urlsplit(self.path).path
            if path == "/api/target-coordinate":
                target = target_from_coordinates(
                    target_id=payload["id"], frame=payload["frame"],
                    longitude=payload["longitude"], latitude=payload["latitude"],
                )
                self._reply(200, {"target": target.model_dump(mode="json")})
            elif path == "/api/test-config":
                from .inputs import mast_test_configuration

                base = Path(payload.get("base_directory") or self.server.workspace).expanduser()
                if not base.is_absolute():
                    base = self.server.workspace / base
                self._reply(200, mast_test_configuration(base))
            elif path == "/api/targets":
                if not isinstance(payload.get("csv"), str):
                    raise ValueError("csv must be UTF-8 CSV text")
                targets = parse_targets_csv(payload["csv"])
                self._reply(200, {"targets": [t.model_dump(mode="json") for t in targets]})
            elif path in ("/api/validate", "/api/run"):
                if not isinstance(payload.get("yaml"), str):
                    raise ValueError("yaml must be configuration text")
                base = Path(payload.get("base_directory") or self.server.workspace).expanduser()
                if not base.is_absolute():
                    base = self.server.workspace / base
                config = parse_config(payload["yaml"], base=base)
                if path == "/api/run":
                    self._reply(202, self.server.jobs.submit(config))
                else:
                    self._reply(
                        200,
                        {
                            "configuration": config.model_dump(mode="json"),
                            "yaml": yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False),
                        },
                    )
            else:
                self._reply(404, {"error": "Not found"})
        except BusyError as exc:
            self._reply(409, {"error": str(exc)})
        except (ValueError, TypeError, KeyError, OSError, yaml.YAMLError) as exc:
            self._reply(400, {"error": str(exc)})


def serve(workspace: Path, *, port=8768):
    """Start the local GUI; the workspace defines relative paths and job records."""
    server = GuiServer(workspace, port)
    print(f"Gladius GUI: {server.url}", flush=True)
    print(f"Workspace: {server.workspace}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
