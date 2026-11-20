"""Local inputs and bounded, exposure-at-a-time Roman MAST staging."""

from __future__ import annotations

import os
import re
import tempfile
import warnings
from contextlib import contextmanager
from pathlib import Path

import numpy as np
from astropy.time import Time

from .config import RunConfig


def selected(summary, selection):
    """Apply UTC [start, end), detector and filter cuts; missing required fields fail."""
    if selection.detectors:
        match = re.fullmatch(r"(?:WFI|SCA)0?(\d{1,2})", summary.get("detector", ""), re.I)
        if match is None:
            raise ValueError("Detector selection requested but parent detector is missing/unknown")
        if int(match[1]) not in selection.detectors:
            return False
    if selection.filters:
        if not summary.get("filter"):
            raise ValueError("Filter selection requested but parent filter is missing")
        if summary["filter"].upper() not in selection.filters:
            return False
    if selection.start or selection.end:
        if not summary.get("start_utc"):
            raise ValueError("Date selection requested but parent exposure start is missing")
        t = Time(summary["start_utc"], scale="utc")
        if selection.start and t < Time(selection.start, scale="utc"):
            return False
        if selection.end and t >= Time(selection.end, scale="utc"):
            return False
    return True


def mast_queries(config: RunConfig) -> list[dict]:
    """Build Roman candidate queries without network access.

    Sky targets supply one cone per distinct position, unless an explicit
    positional criterion is supplied. Advanced criteria override generated
    metadata filters; exact configured selections are still checked locally.
    The cone finds candidate images, not a guarantee of pixel overlap.
    """
    criteria = {
        "productLevel": "2",
        "exposure_type": "WFI_IMAGE",
        **config.inputs.mast_criteria,
    }
    selection = config.selection
    if selection.detectors:
        criteria.setdefault(
            "detector",
            [
                f"{prefix}{number:02d}"
                for number in selection.detectors
                for prefix in ("WFI", "SCA")
            ],
        )
    if selection.filters:
        criteria.setdefault("optical_element", selection.filters)
    if selection.start and selection.end:
        interval = f"{Time(selection.start).isot}..{Time(selection.end).isot}"
    elif selection.start:
        interval = f">={Time(selection.start).isot}"
    elif selection.end:
        interval = f"<{Time(selection.end).isot}"
    else:
        interval = None
    if interval:
        criteria.setdefault("exposure_start_time", interval)
    if any(key in criteria for key in ("coordinates", "objectname", "object_names")):
        return [criteria]
    positions = dict.fromkeys((t.ra, t.dec) for t in config.targets if t.ra is not None)
    if not positions:
        return [criteria]
    return [
        {
            **criteria,
            "coordinates": f"{ra} {dec}",
            "radius": f"{config.inputs.mast_radius_arcmin} arcmin",
        }
        for ra, dec in positions
    ]


def parse_s_region(text):
    """Return vertex (ra, dec) arrays in degrees for one IVOA POLYGON, else None.

    Anything else (circles, unions, several polygons or malformed text) returns None,
    and callers keep the candidate: an unknown footprint is never a reason to skip.
    """
    if not isinstance(text, str):
        return None
    tokens = text.replace(",", " ").split()
    if not tokens or tokens[0].upper() != "POLYGON":
        return None
    values = []
    for token in tokens[1:]:
        try:
            values.append(float(token))
        except ValueError:
            if values:
                return None
    if len(values) < 6 or len(values) % 2:
        return None
    vertices = np.asarray(values, dtype=float).reshape(-1, 2)
    if not np.isfinite(vertices).all():
        return None
    return vertices[:, 0], vertices[:, 1]


def footprint_contains(vertices, ra, dec, margin_arcsec=0.0):
    """Test a sky position against a polygon in the tangent plane at that position."""
    ra_v, dec_v = np.radians(vertices[0]), np.radians(vertices[1])
    ra0, dec0 = np.radians(ra), np.radians(dec)
    cos_c = np.sin(dec0) * np.sin(dec_v) + np.cos(dec0) * np.cos(dec_v) * np.cos(ra_v - ra0)
    if np.any(cos_c <= 0):
        return True  # a vertex 90 degrees away: this is not a detector footprint
    x = np.cos(dec_v) * np.sin(ra_v - ra0) / cos_c
    y = (np.cos(dec0) * np.sin(dec_v) - np.sin(dec0) * np.cos(dec_v) * np.cos(ra_v - ra0)) / cos_c
    x1, y1, x2, y2 = x, y, np.roll(x, 1), np.roll(y, 1)
    crosses = (y1 > 0) != (y2 > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        intercept = x1 - y1 * (x2 - x1) / (y2 - y1)
    if np.count_nonzero(crosses & (intercept > 0)) % 2:
        return True
    dx, dy = x2 - x1, y2 - y1
    length = dx * dx + dy * dy
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.clip(np.where(length > 0, -(x1 * dx + y1 * dy) / length, 0), 0, 1)
    distance = np.min(np.hypot(x1 + t * dx, y1 + t * dy))
    return bool(distance <= np.tan(np.radians(margin_arcsec / 3600)))


def footprint_filter(observations, config: RunConfig, stats=None):
    """Return row indices whose archive footprint may contain a configured sky target.

    Pixel targets have no sky position, so their presence disables the filter.
    """
    indices = list(range(len(observations)))
    positions = [(t.ra, t.dec) for t in config.targets if t.ra is not None]
    applied = (
        config.inputs.prefilter_footprint
        and bool(positions)
        and len(positions) == len(config.targets)
        and "s_region" in getattr(observations, "colnames", ())
    )
    unknown = rejected = 0
    if applied:
        kept = []
        for index in indices:
            value = observations[index]["s_region"]
            vertices = parse_s_region(None if np.ma.is_masked(value) else str(value))
            if vertices is None:
                unknown += 1
                kept.append(index)
            elif any(
                footprint_contains(vertices, ra, dec, config.inputs.footprint_margin_arcsec)
                for ra, dec in positions
            ):
                kept.append(index)
            else:
                rejected += 1
        indices = kept
    if stats is not None:
        stats.update(
            footprint_prefilter=bool(applied),
            candidate_observations=len(observations),
            footprint_rejected=rejected,
            footprint_unknown=unknown,
        )
    return indices


def discover(config: RunConfig, stats=None):
    """Return deterministic local paths or MAST product records; no images staged yet.

    ``stats``, when given, receives candidate and footprint-prefilter counts.
    """
    if config.inputs.mode == "directory":
        directory = config.inputs.directory
        if not directory.is_dir():
            raise ValueError(f"Input directory does not exist: {directory}")
        iterator = directory.rglob if config.inputs.recursive else directory.glob
        paths = sorted(p.resolve() for p in iterator(config.inputs.pattern) if p.is_file())
        # Do not rediscover generated products if output is nested under the input directory.
        paths = [p for p in paths if not p.is_relative_to(config.storage.output_directory)]
        if not paths:
            raise ValueError("No parent files matched inputs.pattern")
        return None, paths
    try:
        from astroquery.mast import MastMissions
    except ImportError as exc:
        raise ImportError('MAST input requires pip install "roman-gladius[mast]"') from exc
    missions = MastMissions(mission="roman")
    if os.environ.get("MAST_API_TOKEN"):
        missions.login(token=os.environ["MAST_API_TOKEN"], store_token=False)
    if missions.dataset_kwds.get("roman") != "fileSetName":
        raise ImportError(
            "Roman MAST support requires astroquery>=0.4.11; upgrade the [mast] extra"
        )
    from astropy.table import unique, vstack

    tables = []
    for criteria in mast_queries(config):
        try:
            observations = missions.query_criteria(
                **criteria,
                select_cols=[
                    "fileSetName",
                    "detector",
                    "optical_element",
                    "exposure_start_time",
                    "s_region",
                ],
                limit=config.inputs.query_limit,
            )
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (401, 403):
                raise PermissionError(
                    "MAST denied the Roman query. Set MAST_API_TOKEN in the server/shell "
                    "environment and verify that your account has access to these data."
                ) from exc
            raise
        if len(observations) >= config.inputs.query_limit:
            warnings.warn(
                "MAST query limit reached; processing a limited sample, not a complete inventory",
                UserWarning,
                stacklevel=2,
            )
        if len(observations):
            tables.append(observations)
            combined = unique(vstack(tables), keys="fileSetName", keep="first")
            if len(combined) > config.inputs.query_limit:
                warnings.warn(
                    "Combined MAST results exceed query_limit; processing a limited sample",
                    UserWarning,
                    stacklevel=2,
                )
            tables = [combined[: config.inputs.query_limit]]
    if not tables:
        raise ValueError("No MAST observations matched the target searches and criteria")
    observations = unique(vstack(tables), keys="fileSetName", keep="first")
    indices = []
    for index in footprint_filter(observations, config, stats):
        row = observations[index]
        if selected(
            {
                "detector": str(row["detector"]),
                "filter": str(row["optical_element"]),
                "start_utc": str(row["exposure_start_time"]),
            },
            config.selection,
        ):
            indices.append(index)
    if not indices:
        raise ValueError(
            "No MAST detector observations passed selection and the target footprint check"
            if stats and stats.get("footprint_rejected")
            else "No MAST detector observations passed selection"
        )
    products = missions.get_unique_product_list(observations[indices])
    products = missions.filter_products(products, file_suffix=config.inputs.product_suffix)
    if not len(products):
        raise ValueError("MAST returned no products with the requested product_suffix")
    if config.inputs.product_filename:
        products = products[
            [str(row["filename"]) == config.inputs.product_filename for row in products]
        ]
        if not len(products):
            raise ValueError("MAST returned no product matching inputs.product_filename")
    names = [str(row["filename"]) for row in products]
    if len(set(names)) != len(names):
        raise ValueError("MAST returned duplicate filenames; ambiguous product identity")
    return missions, sorted(list(products), key=lambda row: str(row["filename"]))


@contextmanager
def staged(source, missions, work: Path):
    """Stage one archive parent in a private folder; never remove user-supplied inputs.

    Safe to call from several threads with one logged-in client: each call has its
    own folder, and the client's HTTP session pools connections per thread.
    """
    if missions is None:
        yield Path(source)
        return
    from astropy.table import Table

    with tempfile.TemporaryDirectory(prefix="parent-", dir=work) as temporary:
        # Parallel progress bars would interleave; Gladius reports per-parent progress.
        manifest = missions.download_products(
            Table(rows=[source]), download_dir=temporary, verbose=False
        )
        paths = [
            Path(str(row["Local Path"]))
            for row in manifest
            if str(row["Status"]).upper() == "COMPLETE"
        ]
        paths = [
            p
            for p in paths
            if p.is_file() and p.resolve().is_relative_to(Path(temporary).resolve())
        ]
        if len(paths) != 1:
            raise RuntimeError("MAST staging did not produce exactly one successful local parent")
        yield paths[0]


def mast_test_configuration(base: Path) -> dict:
    """Query a small real metadata sample and prepare one-image YAML; never download.

    The smallest known-size calibrated product among five sampled L2 datasets is
    selected. This is a sample, not a claim to find the archive's smallest image.
    """
    import math

    import yaml

    try:
        from astroquery.mast import MastMissions
    except ImportError as exc:
        raise ValueError('Load test requires pip install "roman-gladius[mast]"') from exc
    missions = MastMissions(mission="roman")
    missions.TIMEOUT = 30
    if missions.dataset_kwds.get("roman") != "fileSetName":
        raise ValueError("Load test requires astroquery>=0.4.11")
    try:
        if os.environ.get("MAST_API_TOKEN"):
            missions.login(token=os.environ["MAST_API_TOKEN"], store_token=False)
        observations = missions.query_criteria(
            productLevel="2",
            exposure_type="WFI_IMAGE",
            limit=5,
            select_cols=["fileSetName", "ra", "dec"],
        )
        candidates = []
        for index, row in enumerate(observations):
            try:
                ra, dec = float(row["ra"]), float(row["dec"])
                if not (
                    math.isfinite(ra) and math.isfinite(dec) and 0 <= ra < 360 and -90 <= dec <= 90
                ):
                    continue
            except (ValueError, TypeError):
                continue
            products = missions.get_unique_product_list(observations[[index]])
            if not len(products):
                continue
            products = missions.filter_products(products, file_suffix="_cal")
            for product in products:
                try:
                    size = float(product["size"])
                    if not math.isfinite(size) or size <= 0 or size != int(size):
                        continue
                    name = str(product["filename"])
                    if not name.lower().endswith("_cal.asdf"):
                        continue
                    candidates.append((int(size), name, str(row["fileSetName"]), ra, dec))
                except (ValueError, TypeError, KeyError):
                    continue
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (401, 403):
            raise ValueError(
                "MAST denied the test query. Set MAST_API_TOKEN in the launching "
                "shell/server and verify Roman access; a GitHub secret is only "
                "available inside GitHub Actions."
            ) from exc
        raise ValueError(f"MAST test discovery failed: {type(exc).__name__}: {exc}") from exc
    if not candidates:
        raise ValueError(
            "No accessible calibrated image with a known size and sky position "
            "was found in the five-dataset MAST sample. No test YAML was loaded."
        )
    size, filename, dataset, ra, dec = min(candidates)
    config = RunConfig.model_validate(
        {
            "targets": [{"id": "mast-test", "ra": ra, "dec": dec}],
            "inputs": {
                "mode": "mast",
                "mast_criteria": {"fileSetName": dataset},
                "product_filename": filename,
                "query_limit": 100,
            },
            "extraction": {"size": 64},
            "storage": {"output_directory": "gladius-mast-test", "formats": ["asdf"]},
            "quality": {"autocorrelation_limit": None},
            "stacks": {"enabled": False},
        }
    ).resolved(base)
    return {
        "yaml": yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False),
        "configuration": config.model_dump(mode="json"),
        "download_bytes": size,
        "filename": filename,
        "dataset": dataset,
    }
