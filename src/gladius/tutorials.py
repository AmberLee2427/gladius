"""Copy clean tutorial notebooks and open them in local or hosted JupyterLab."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import webbrowser
from importlib.resources import files
from importlib.util import find_spec
from pathlib import Path
from urllib.parse import quote


def write_tutorial(directory: Path, *, nexus=False) -> Path:
    """Copy a bundled tutorial without overwriting an existing user's notebook."""
    directory = Path(directory).resolve()
    source = "nexus_cutouts.ipynb" if nexus else "local_cutouts.ipynb"
    content = files("gladius").joinpath("data/tutorials", source).read_bytes()
    stem = "gladius-nexus-tutorial" if nexus else "gladius-local-tutorial"
    for number in range(1, 10000):
        path = directory / f"{stem}{'' if number == 1 else f'-{number}'}.ipynb"
        try:
            with path.open("xb") as stream:
                stream.write(content)
        except FileExistsError:
            continue
        return path
    raise FileExistsError("No unused tutorial filename found")


def _running_servers(jupyter):
    result = subprocess.run(
        [jupyter, "server", "list", "--json"],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    servers = []
    for line in result.stdout.splitlines():
        try:
            server = json.loads(line)
        except ValueError:
            continue
        if isinstance(server, dict) and server.get("root_dir"):
            servers.append(server)
    return servers


def _register_kernel(path):
    """Point the copied notebook at the Python environment running Gladius."""
    if find_spec("ipykernel") is None:
        return "Notebook saved. Install roman-gladius[notebook] in this environment to register its kernel, then open the file in JupyterLab."
    name = (
        "gladius-" + hashlib.sha256(str(Path(sys.executable).resolve()).encode()).hexdigest()[:12]
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ipykernel",
            "install",
            "--user",
            "--name",
            name,
            "--display-name",
            "Gladius tutorial",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode:
        return "Notebook saved. Could not register this Python kernel; choose a Jupyter kernel containing Gladius manually."
    notebook = json.loads(path.read_text())
    notebook["metadata"]["kernelspec"] = {
        "display_name": "Gladius tutorial",
        "language": "python",
        "name": name,
    }
    path.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n")
    return None


def open_tutorial(path: Path, *, nexus=False) -> str:
    """Open a copied notebook; return an explanation if auto-opening is unavailable."""
    jupyter = shutil.which("jupyter")
    if not jupyter:
        return "Notebook saved. Open it in JupyterLab, or install roman-gladius[notebook]."
    try:
        kernel_message = _register_kernel(path)
    except (OSError, subprocess.TimeoutExpired):
        kernel_message = "Notebook saved. Could not register this Python kernel; choose a Jupyter kernel containing Gladius manually."
    if kernel_message:
        return kernel_message
    if not nexus:
        subprocess.Popen(
            [jupyter, "lab", path.name, "--ServerApp.root_dir", str(path.parent)],
            cwd=path.parent,
        )
        return "Starting JupyterLab; its terminal output includes the browser link."
    from .web import _proxy_url

    prefix = os.environ.get("JUPYTERHUB_SERVICE_PREFIX")
    if not prefix:
        return "Notebook saved. On Nexus, run this command in a JupyterLab terminal, or open the file manually."
    try:
        servers = _running_servers(jupyter)
    except (OSError, subprocess.TimeoutExpired):
        servers = []
    for server in servers:
        if server.get("base_url", "/").rstrip("/") != prefix.rstrip("/"):
            continue
        try:
            relative = path.resolve().relative_to(Path(server["root_dir"]).resolve())
        except ValueError:
            continue
        # Do not expose the server-list token or local-only server URL.
        base = _proxy_url(8768, nexus=True).rsplit("/proxy/", 1)[0]
        url = base + "/lab/tree/" + quote(relative.as_posix(), safe="/")
        webbrowser.open(url)
        return f"Open tutorial: {url}"
    return "Notebook saved. Open it from the JupyterLab file browser; its server root could not be determined automatically."
