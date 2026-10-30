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


def target_from_coordinates(*, target_id: str, frame: str, longitude: float,
                            latitude: float) -> Target:
    """Convert decimal-degree sky coordinates with Astropy; preserve input metadata.

    Ecliptic means barycentric true ecliptic at equinox J2000, with no inferred
    distance, motion or observing epoch. Pixel positions bypass sky conversion.
    """
    import math

    from astropy.coordinates import BarycentricTrueEcliptic, SkyCoord
    from astropy.time import Time

    lon, lat = float(longitude), float(latitude)
    if not all(math.isfinite(v) for v in (lon, lat)):
        raise ValueError("Coordinates must be finite")
    if frame == "pixel":
        return Target(id=target_id, x=lon, y=lat)
    if frame not in ("sky", "galactic", "ecliptic"):
        raise ValueError("Choose ICRS, Galactic, ecliptic or pixel coordinates")
    if not 0 <= lon < 360 or not -90 <= lat <= 90:
        raise ValueError("Longitude/RA must be in [0, 360); latitude/Dec in [-90, 90] degrees")
    if frame == "sky":
        return Target(id=target_id, ra=lon, dec=lat)
    system = "galactic" if frame == "galactic" else BarycentricTrueEcliptic(equinox=Time("J2000"))
    sky = SkyCoord(lon, lat, unit="deg", frame=system).icrs
    metadata = {"input_frame": frame, "input_longitude_deg": str(lon),
                "input_latitude_deg": str(lat)}
    if frame == "ecliptic":
        metadata.update(input_frame="barycentric_true_ecliptic", input_equinox="J2000")
    return Target(id=target_id, ra=float(sky.ra.deg), dec=float(sky.dec.deg), metadata=metadata)
