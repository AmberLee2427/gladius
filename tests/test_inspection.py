"""Review images must include exclusions and use the correct original parent."""

import json

import pytest

from gladius import RunConfig, load_config, run
from gladius.inspection import audit_rows, contact_sheets, parent_preview


def test_review_includes_all_flagged_images_and_correct_parent(demo):
    data = load_config(demo).model_dump(mode="json")
    # A too-large tile deliberately flags BOTH cutouts as unassessable.
    data["quality"].update(autocorrelation_limit=2.6, tile_size=128)
    manifest_path = run(RunConfig.model_validate(data), progress=lambda _: None)
    rows = audit_rows(manifest_path)
    assert len(rows) == 2
    assert all(row["accepted"] is False and row["reason"] == "insufficient_tile" for row in rows)
    assert all(row["display_eligible"] is False for row in rows)
    pages = list(contact_sheets(manifest_path, page_size=1, columns=1))
    assert len(pages) == 2  # Flagged images cannot disappear from visual review.
    assert all(page.mode == "RGB" and page.width > 0 for page in pages)
    manifest = json.loads(manifest_path.read_text())
    parent = next(iter(manifest["entries"].values()))["parent_sha256"]
    assert parent_preview(manifest_path, parent, width=300).size == (300, 342)
    first = next(iter(manifest["entries"].values()))
    # A changed local file must not be shown as if it were the original parent.
    from pathlib import Path

    with Path(first["source"]).open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="parent changed"):
        parent_preview(manifest_path, parent)


def test_review_reports_skipped_pairs_instead_of_silently_dropping_them(demo):
    data = load_config(demo).model_dump(mode="json")
    data["targets"].append({"id": "off-detector", "x": 10000, "y": 10000})
    data["extraction"]["no_overlap"] = "skip"
    manifest_path = run(RunConfig.model_validate(data), progress=lambda _: None)
    rows = audit_rows(manifest_path)
    assert len(rows) == 4
    assert sum(row["status"] == "skipped" for row in rows) == 2
    assert all(row["reason"] == "no_overlap" for row in rows if row["status"] == "skipped")
