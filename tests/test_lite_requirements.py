import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_ONLY = {"ipykernel", "matplotlib", "jupyterlab"}


def _names(requirements):
    return {r.split(">")[0].split("<")[0].split("=")[0].strip() for r in requirements}


def test_lite_requirements_match_pyproject_minus_notebook_stack():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    lines = (ROOT / "lite-requirements.txt").read_text().splitlines()
    lite = [x.strip() for x in lines if x.strip() and not x.startswith("#")]
    expected = [d for d in project["dependencies"] if _names([d]) - NOTEBOOK_ONLY]
    assert sorted(lite) == sorted(expected)
