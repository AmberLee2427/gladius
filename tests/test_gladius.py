import tomllib
from importlib.resources import files
from pathlib import Path

from gladius import __version__


def test_version_and_bundled_config():
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert __version__ == project["project"]["version"]
    assert (
        "autocorrelation_limit" in files("gladius").joinpath("data/example.yaml").read_text()
    )
