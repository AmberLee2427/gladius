from importlib.resources import files

from gladius_roman import __version__


def test_version_and_bundled_config():
    assert __version__ == "0.1.0a2"
    assert (
        "autocorrelation_limit" in files("gladius_roman").joinpath("data/example.yaml").read_text()
    )
