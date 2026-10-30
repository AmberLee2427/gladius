"""Validate notebook inputs and output hygiene without archive access."""

import ast
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def notebook_cells():
    notebook = json.loads((ROOT / "notebooks/nexus_cutouts.ipynb").read_text(encoding="utf-8"))
    return {cell["id"]: "".join(cell["source"]) for cell in notebook["cells"]}, notebook


def test_notebook_requires_explicit_credentials_before_archive_access(tmp_path, monkeypatch, capsys):
    cells, notebook = notebook_cells()
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            assert not cell["outputs"] and cell["execution_count"] is None
            ast.parse("".join(cell["source"]))
    namespace = {}
    exec(cells["gladius-02"], namespace)
    with pytest.raises(ValueError, match="Set ENV_FILE"):
        exec(cells["gladius-03"], namespace)
    namespace["ENV_FILE"] = tmp_path / "missing.env"
    with pytest.raises(FileNotFoundError, match="existing file"):
        exec(cells["gladius-03"], namespace)
    namespace["ENV_FILE"] = tmp_path / "chosen.env"
    namespace["ENV_FILE"].write_text("MAST_API_TOKEN=\n", encoding="utf-8")
    with pytest.raises(ValueError, match="nonempty"):
        exec(cells["gladius-03"], namespace)
    monkeypatch.setenv("MAST_API_TOKEN", "previous-test-only-value")
    namespace["ENV_FILE"].write_text("MAST_API_TOKEN=selected-test-only-value\n", encoding="utf-8")
    exec(cells["gladius-03"], namespace)
    assert os.environ["MAST_API_TOKEN"] == "selected-test-only-value"
    assert "selected-test-only-value" not in capsys.readouterr().out


def test_distribution_checker_rejects_executed_notebook(tmp_path):
    archive_path = tmp_path / "unsafe.whl"
    _, notebook = notebook_cells()
    cell = next(cell for cell in notebook["cells"] if cell["cell_type"] == "code")
    cell["execution_count"] = 1
    cell["outputs"] = [{"output_type": "stream", "name": "stdout", "text": ["private output"]}]
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("notebooks/nexus_cutouts.ipynb", json.dumps(notebook))
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/check_distribution.py"), str(archive_path)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "Notebook must have cleared outputs" in result.stderr
