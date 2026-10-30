"""Shared, explicit CSV target ingestion for the CLI and local web GUI."""

import csv
from io import StringIO
from pathlib import Path

from .config import Target

ALIASES = {
    "id": "id",
    "target_id": "id",
    "name": "id",
    "ra": "ra",
    "ra_deg": "ra",
    "dec": "dec",
    "dec_deg": "dec",
    "x": "x",
    "y": "y",
}


def parse_targets_csv(text: str) -> list[Target]:
    """Read UTF-8 CSV with decimal ICRS degrees or zero-based pixel coordinates.

    IDs default to target-000001, etc. Additional catalogue columns are retained
    in Target.metadata. Duplicate columns/IDs, missing pairs and invalid numbers
    are rejected with CSV line numbers. No coordinate/unit inference occurs.
    """
    reader = csv.DictReader(StringIO(text.lstrip("\ufeff"), newline=""), strict=True)
    try:
        fieldnames = reader.fieldnames
    except csv.Error as exc:
        raise ValueError(f"CSV header: {exc}") from exc
    if not fieldnames:
        raise ValueError("CSV has no header")
    headers = [h.strip() for h in fieldnames]
    canonical = [ALIASES.get(h.lower(), h) for h in headers]
    if any(not h for h in headers) or len(set(canonical)) != len(canonical):
        raise ValueError("CSV contains blank, duplicate or ambiguous alias columns")
    coordinate_columns = {h for h in canonical if h in ("ra", "dec", "x", "y")}
    if coordinate_columns not in ({"ra", "dec"}, {"x", "y"}):
        raise ValueError("CSV needs exactly one coordinate pair: ra,dec or x,y")
    result, seen = [], set()
    try:
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(
                    f"CSV line {reader.line_num}: number of fields does not match header"
                )
            values = dict(zip(canonical, (row[h].strip() for h in reader.fieldnames), strict=True))
            if not any(values.values()):
                continue
            try:
                identifier = (
                    values.get("id") if "id" in canonical else f"target-{len(result) + 1:06d}"
                )
                target = Target(
                    id=identifier,
                    **{key: float(values[key]) for key in coordinate_columns},
                    metadata={
                        headers[i]: values[key]
                        for i, key in enumerate(canonical)
                        if key not in ("id", "ra", "dec", "x", "y")
                    },
                )
                if target.id in seen:
                    raise ValueError(f"duplicate target ID {target.id!r}")
            except (ValueError, TypeError) as exc:
                raise ValueError(f"CSV line {reader.line_num}: {exc}") from exc
            seen.add(target.id)
            result.append(target)
    except csv.Error as exc:
        raise ValueError(f"CSV line {reader.line_num}: {exc}") from exc
    if not result:
        raise ValueError("CSV contains no target rows")
    return result


def read_targets_csv(path: str | Path) -> list[Target]:
    """Load a CSV path relative to the caller's working directory."""
    return parse_targets_csv(Path(path).expanduser().read_text(encoding="utf-8-sig"))
