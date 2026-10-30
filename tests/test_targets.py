import json

import pytest
import yaml

from gladius_roman.cli import main
from gladius_roman.config import load_config
from gladius_roman.io import read_cutout
from gladius_roman.targets import parse_targets_csv, read_targets_csv


def test_csv_aliases_bom_extra_metadata_and_default_ids(tmp_path):
    path = tmp_path / "targets.csv"
    path.write_text(
        '\ufeffName, RA_deg ,DEC_deg,catalogue,note\r\nOGLE-1,270.1,-29.1,001,"two, words"\r\n',
        encoding="utf-8",
    )
    targets = read_targets_csv(path)
    assert targets[0].id == "OGLE-1" and targets[0].ra == 270.1
    assert targets[0].metadata == {"catalogue": "001", "note": "two, words"}
    targets = parse_targets_csv("x,y\n3.5,7\n4.5,8\n")
    assert [t.id for t in targets] == ["target-000001", "target-000002"]
    assert targets[0].x == 3.5


@pytest.mark.parametrize(
    "text",
    [
        "",
        "id,ra\ne,1\n",
        "ra,dec,x,y\n1,2,3,4\n",
        "id,ra,dec\ne,nan,2\n",
        "id,ra,dec\ne,1,2\ne,3,4\n",
        "id,ra,dec\ne,1\n",
        "id,ra,dec\ne,1,2,3\n",
        "ra,RA_deg,dec\n1,2,3\n",
        "ra,dec\n",
        '"unterminated header\n',
        'ra,dec\n1,"broken\n',
    ],
)
def test_invalid_csv_reports_a_useful_error(text):
    with pytest.raises(ValueError):
        parse_targets_csv(text)


def test_cli_csv_replaces_targets_before_yaml_validation(demo, tmp_path):
    data = yaml.safe_load(demo.read_text())
    data.pop("targets")
    data["stacks"]["enabled"] = False
    demo.write_text(yaml.safe_dump(data))
    csv = tmp_path / "targets.csv"
    csv.write_text("id,ra,dec,catalogue\nmy-event,270,-29,original\n")
    assert main(["validate", str(demo), "--targets", str(csv)]) == 0
    assert main(["run", str(demo), "--targets", str(csv)]) == 0
    manifest = next((demo.parent / "output/runs").glob("*/manifest.json"))
    records = json.loads(manifest.read_text())
    assert len(records["entries"]) == 2
    product = manifest.parent / next(iter(next(iter(records["entries"].values()))["files"]))
    assert read_cutout(product).provenance["target"]["metadata"] == {"catalogue": "original"}
    assert load_config(demo, targets_path=csv).targets[0].id == "my-event"


def test_galactic_ecliptic_and_pixel_coordinates():
    from gladius_roman.targets import target_from_coordinates

    galactic = target_from_coordinates(target_id="gc", frame="galactic", longitude=0, latitude=0)
    assert galactic.ra == pytest.approx(266.405, abs=0.002)
    assert galactic.dec == pytest.approx(-28.936, abs=0.002)
    assert galactic.metadata["input_frame"] == "galactic"
    ecliptic = target_from_coordinates(target_id="ec", frame="ecliptic", longitude=90, latitude=0)
    assert ecliptic.ra == pytest.approx(90, abs=0.01)
    assert ecliptic.dec == pytest.approx(23.439, abs=0.01)
    assert ecliptic.metadata["input_equinox"] == "J2000"
    pixel = target_from_coordinates(target_id="px", frame="pixel", longitude=-2, latitude=12)
    assert pixel.x == -2 and pixel.ra is None
    for frame, lon, lat in [("galactic", 361, 0), ("ecliptic", 1, 91),
                            ("unknown", 1, 2), ("sky", float("nan"), 0)]:
        with pytest.raises(ValueError):
            target_from_coordinates(target_id="bad", frame=frame, longitude=lon, latitude=lat)
