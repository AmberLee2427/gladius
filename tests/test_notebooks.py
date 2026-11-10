"""Validate notebook inputs and output hygiene without archive access."""

import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def notebook_cells():
    notebook = json.loads(
        (ROOT / "notebooks/nexus_cutouts/nexus_cutouts.ipynb").read_text(encoding="utf-8")
    )
    return {cell["id"]: "".join(cell["source"]) for cell in notebook["cells"]}, notebook


def test_distribution_checker_rejects_executed_notebook(tmp_path):
    archive_path = tmp_path / "unsafe.whl"
    _, notebook = notebook_cells()
    cell = next(cell for cell in notebook["cells"] if cell["cell_type"] == "code")
    cell["execution_count"] = 1
    cell["outputs"] = [{"output_type": "stream", "name": "stdout", "text": ["private output"]}]
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("notebooks/nexus_cutouts/nexus_cutouts.ipynb", json.dumps(notebook))
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/check_distribution.py"), str(archive_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Notebook must have cleared outputs" in result.stderr


def test_nexus_configuration_starts_without_credentials_or_gui():
    cells, notebook = notebook_cells()
    namespace = {}
    exec(cells["ui-settings"], namespace)
    exec(cells["gladius-02"], namespace)
    assert namespace["ENV_FILE"] is None
    assert namespace["RUN_GUI"] is True
    assert namespace["RUN_ARCHIVE_EXAMPLE"] is False
    namespace["RUN_GUI"] = False
    for cell in notebook["cells"]:
        code = "".join(cell["source"])
        if cell["cell_type"] == "code" and "if RUN_GUI:" in code:
            exec(code, namespace)
    assert "gui_server" not in namespace
    requirements = ROOT / "notebooks/nexus_cutouts/requirements.txt"
    assert requirements.is_file()
