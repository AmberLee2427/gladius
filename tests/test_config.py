from pathlib import Path

import pytest
from pydantic import ValidationError

from gladius_roman.config import RunConfig, Selection, Target, load_config


def test_unknown_duplicate_nonfinite_and_invalid_fields(tmp_path):
    base = {"targets": [{"id": "event", "x": 3.2, "y": 4.1}]}
    for update in (
        {"unexpected": 4},
        {"extraction": {"size": True}},
        {"selection": {"detectors": [0]}},
        {"targets": [{"id": "e", "x": float("nan"), "y": 1}]},
        {"astrometry": {"mode": "corrected", "corrected_directory": None}},
        {"storage": {"formats": []}},
    ):
        with pytest.raises(ValidationError):
            RunConfig.model_validate({**base, **update})
    path = tmp_path / "bad.yaml"
    path.write_text("targets: []\ntargets: []\n")
    with pytest.raises(ValueError, match="Duplicate YAML key"):
        load_config(path)


@pytest.mark.parametrize(
    "values",
    [
        dict(ra=3),
        dict(x=2),
        dict(ra=1, dec=2, x=3, y=4),
        dict(ra=1, dec=2, x=4),
        dict(ra=360, dec=0),
        dict(dec=91, ra=0),
    ],
)
def test_coordinate_pair(values):
    with pytest.raises(ValidationError):
        Target(id="target", **values)


def test_date_interval_and_paths(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(
        "targets: [{id: event, ra: 2, dec: 3}]\nselection: {start: 2026-01-01, end: 2026-02-01}\n"
    )
    monkeypatch.chdir(Path("/tmp"))
    config = load_config(path)
    assert config.inputs.directory == tmp_path / "images"
    assert config.selection.start == "2026-01-01"
    assert config.extraction.size == 150
    with pytest.raises(ValidationError):
        Selection(start="2026-02-01", end="2026-01-01")


def test_yaml_timestamp_with_utc_timezone(tmp_path):
    path = tmp_path / "utc.yaml"
    path.write_text("targets: [{id: e, x: 0, y: 0}]\nselection: {start: 2026-01-01T00:00:00Z}\n")
    assert load_config(path).selection.start == "2026-01-01T00:00:00"
