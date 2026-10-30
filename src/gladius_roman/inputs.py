"""Local inputs and bounded, exposure-at-a-time Roman MAST staging."""

from __future__ import annotations

import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path

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
    criteria = {"productLevel": "2", **config.inputs.mast_criteria}
    selection = config.selection
    if selection.detectors:
        criteria.setdefault("detector", [
            f"{prefix}{number:02d}"
            for number in selection.detectors for prefix in ("WFI", "SCA")
        ])
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
        {**criteria, "coordinates": f"{ra} {dec}",
         "radius": f"{config.inputs.mast_radius_arcmin} arcmin"}
        for ra, dec in positions
    ]


def discover(config: RunConfig):
    """Return deterministic local paths or MAST product records; no images staged yet."""
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
        raise ImportError('MAST input requires pip install "gladius-roman[mast]"') from exc
    missions = MastMissions(mission="roman")
    if os.environ.get("MAST_API_TOKEN"):
        missions.login(token=os.environ["MAST_API_TOKEN"])
    if missions.dataset_kwds.get("roman") != "fileSetName":
        raise ImportError("Roman MAST support requires astroquery>=0.4.11; upgrade the [mast] extra")
    from astropy.table import unique, vstack

    tables = []
    for criteria in mast_queries(config):
        try:
            observations = missions.query_criteria(
                **criteria,
                select_cols=["fileSetName", "detector", "optical_element", "exposure_start_time"],
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
            raise ValueError("MAST query may be truncated; narrow criteria or increase query_limit")
        if len(observations):
            tables.append(observations)
            combined = unique(vstack(tables), keys="fileSetName", keep="first")
            if len(combined) >= config.inputs.query_limit:
                raise ValueError("MAST query may be truncated; narrow criteria or increase query_limit")
            tables = [combined]
    if not tables:
        raise ValueError("No MAST observations matched the target searches and criteria")
    observations = unique(vstack(tables), keys="fileSetName", keep="first")
    if len(observations) >= config.inputs.query_limit:
        raise ValueError("MAST query may be truncated; narrow criteria or increase query_limit")
    indices = []
    for index, row in enumerate(observations):
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
        raise ValueError("No MAST detector observations passed selection")
    products = missions.get_unique_product_list(observations[indices])
    products = missions.filter_products(products, file_suffix=config.inputs.product_suffix)
    if not len(products):
        raise ValueError("MAST returned no products with the requested product_suffix")
    if config.inputs.product_filename:
        products = products[[str(row["filename"]) == config.inputs.product_filename for row in products]]
        if not len(products):
            raise ValueError("MAST returned no product matching inputs.product_filename")
    names = [str(row["filename"]) for row in products]
    if len(set(names)) != len(names):
        raise ValueError("MAST returned duplicate filenames; ambiguous product identity")
    return missions, sorted(list(products), key=lambda row: str(row["filename"]))


@contextmanager
def staged(source, missions, work: Path):
    """Stage only one archive parent; never remove user-supplied local inputs."""
    if missions is None:
        yield Path(source)
        return
    from astropy.table import Table

    with tempfile.TemporaryDirectory(prefix="parent-", dir=work) as temporary:
        manifest = missions.download_products(Table(rows=[source]), download_dir=temporary)
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
        raise ValueError('Load test requires pip install "gladius-roman[mast]"') from exc
    missions = MastMissions(mission="roman")
    missions.TIMEOUT = 30
    if missions.dataset_kwds.get("roman") != "fileSetName":
        raise ValueError("Load test requires astroquery>=0.4.11")
    try:
        if os.environ.get("MAST_API_TOKEN"):
            missions.login(token=os.environ["MAST_API_TOKEN"], store_token=False)
        observations = missions.query_criteria(
            productLevel="2", limit=5, select_cols=["fileSetName", "ra", "dec"]
        )
        candidates = []
        for index, row in enumerate(observations):
            try:
                ra, dec = float(row["ra"]), float(row["dec"])
                if not (math.isfinite(ra) and math.isfinite(dec) and 0 <= ra < 360 and -90 <= dec <= 90):
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
                    if not name.lower().endswith(("_cal.asdf", "_cal.fits")):
                        continue
                    candidates.append((int(size), name, str(row["fileSetName"]), ra, dec))
                except (ValueError, TypeError, KeyError):
                    continue
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (401, 403):
            raise ValueError("MAST denied the test query. Set MAST_API_TOKEN in the launching "
                             "shell/server and verify Roman access; a GitHub secret is only "
                             "available inside GitHub Actions.") from exc
        raise ValueError(f"MAST test discovery failed: {type(exc).__name__}: {exc}") from exc
    if not candidates:
        raise ValueError("No accessible calibrated image with a known size and sky position "
                         "was found in the five-dataset MAST sample. No test YAML was loaded.")
    size, filename, dataset, ra, dec = min(candidates)
    config = RunConfig.model_validate({
        "targets": [{"id": "mast-test", "ra": ra, "dec": dec}],
        "inputs": {"mode": "mast", "mast_criteria": {"fileSetName": dataset},
                   "product_filename": filename, "query_limit": 100},
        "extraction": {"size": 64, "no_overlap": "error"},
        "storage": {"output_directory": "gladius-mast-test", "formats": ["asdf"]},
        "quality": {"autocorrelation_limit": None}, "stacks": {"enabled": False},
    }).resolved(base)
    return {"yaml": yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False),
            "configuration": config.model_dump(mode="json"), "download_bytes": size,
            "filename": filename, "dataset": dataset}
