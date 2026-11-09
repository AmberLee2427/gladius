# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.24", "astropy>=6", "asdf>=4.1", "asdf-astropy>=0.6", "gwcs>=0.21", "roman_datamodels>=0.25", "astroquery>=0.4.11", "PyYAML>=6"]
# ///
# AI disclosure: generated and revised with OpenAI Codex, following the
# maintainer's requirements; includes code adapted from Gladius.
"""Native Roman cutouts. Run: uv run roman_cutouts.py config.yaml.

Standalone; does not import Gladius. See README.md and LICENSE.txt.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import tempfile
import warnings
from collections.abc import Mapping
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any

import asdf
import numpy as np
import yaml
from asdf.exceptions import AsdfConversionWarning
from asdf.tags.core.ndarray import NDArrayType
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.modeling.models import Shift
from astropy.time import Time
from astropy.wcs import WCS, Sip

DO_NOT_USE = 1
FLOOR_TOLERANCE = 1e-6


def geometry(x: float, y: float, shape: tuple[int, int], size: int) -> dict[str, Any]:
    """Commissioning convention: floor position minus (size-1)//2, for any parity."""
    if not np.isfinite([x, y]).all() or type(size) is not int or size < 1:
        raise ValueError("Finite x/y and a positive integer size are required")
    if len(shape) != 2 or min(shape) < 1:
        raise ValueError("Parent data must have two nonempty dimensions")

    ny, nx = map(int, shape)
    # Sky round trips leave ~1e-9 pixel noise; without a tolerance an integer pixel
    # centre can floor to the neighbouring pixel.
    x0 = int(np.floor(x + FLOOR_TOLERANCE)) - (size - 1) // 2
    y0 = int(np.floor(y + FLOOR_TOLERANCE)) - (size - 1) // 2

    # Clip the source rectangle, then locate it within the padded cutout.
    sx0, sx1 = min(nx, max(0, x0)), min(nx, max(0, x0 + size))
    sy0, sy1 = min(ny, max(0, y0)), min(ny, max(0, y0 + size))
    overlap = sx1 > sx0 and sy1 > sy0
    dx0, dy0 = (sx0 - x0, sy0 - y0) if overlap else (0, 0)
    dx1, dy1 = (sx1 - x0, sy1 - y0) if overlap else (0, 0)

    return dict(
        parent_shape_yx=[ny, nx],
        cutout_shape_yx=[size, size],
        x0=x0,
        y0=y0,
        pixel_origin=0,
        axis_order="array[y, x]; coordinates (x, y)",
        bounds_convention="zero-based start inclusive, stop exclusive",
        parent_virtual_bounds_xyxy=[x0, y0, x0 + size, y0 + size],
        parent_valid_bounds_xyxy=[sx0, sy0, sx1, sy1],
        cutout_valid_bounds_xyxy=[dx0, dy0, dx1, dy1],
        prediction_on_detector=bool(-0.5 <= x < nx - 0.5 and -0.5 <= y < ny - 0.5),
        padding_pixels=size * size - (sx1 - sx0) * (sy1 - sy0) if overlap else size * size,
        x_parent_equals="x_cutout + x0",
        y_parent_equals="y_cutout + y0",
    )


def extract_plane(array: np.ndarray, mapping: dict, *, dq=False) -> np.ndarray:
    """Copy a spatial array using shared slices; preserve leading dimensions."""
    array = np.asarray(array)
    if list(array.shape[-2:]) != mapping["parent_shape_yx"]:
        raise ValueError("All spatial planes must agree with parent SCI dimensions")
    if dq and (not np.issubdtype(array.dtype, np.integer) or np.any(array < 0)):
        raise ValueError("DQ must contain nonnegative integer flags")

    # Padding must never look like valid science or an unflagged DQ pixel.
    if dq:
        dtype, fill = array.dtype, DO_NOT_USE
    elif np.issubdtype(array.dtype, np.inexact):
        dtype, fill = array.dtype, np.nan
    elif np.issubdtype(array.dtype, np.integer) or array.dtype == bool:
        dtype, fill = array.dtype, 0
    else:
        raise ValueError(f"Unsupported spatial array dtype {array.dtype}")

    # Copy only the overlap; any leading axes belong to ancillary arrays.
    result = np.full(array.shape[:-2] + tuple(mapping["cutout_shape_yx"]), fill, dtype=dtype)
    sx0, sy0, sx1, sy1 = mapping["parent_valid_bounds_xyxy"]
    dx0, dy0, dx1, dy1 = mapping["cutout_valid_bounds_xyxy"]
    if dx1 > dx0 and dy1 > dy0:
        result[..., dy0:dy1, dx0:dx1] = array[..., sy0:sy1, sx0:sx1]
    return result


def pixel_to_world(wcs, x, y):
    """Evaluate exact stored astrometry without bounding-box masking."""
    if isinstance(wcs, WCS):
        return wcs.all_pix2world(x, y, 0)
    return wcs(x, y, with_bounding_box=False)


def world_to_pixel(wcs, ra, dec):
    if isinstance(wcs, WCS):
        return wcs.all_world2pix(ra, dec, 0)
    return wcs.invert(ra, dec, with_bounding_box=False)


def translate_wcs(wcs, mapping):
    """Translate the full WCS by the virtual origin, including negative padding."""
    result = deepcopy(wcs)
    x0, y0 = mapping["x0"], mapping["y0"]
    shape = tuple(mapping["cutout_shape_yx"])

    # Translate coordinates, preserving the parent transform rather than resampling.
    if isinstance(result, WCS):
        if result.cpdis1 or result.cpdis2 or result.det2im1 or result.det2im2 or result.wcs.tab:
            raise ValueError("FITS lookup-table distortions are not supported; supply a GWCS")
        result.wcs.crpix -= [x0, y0]
        if result.sip is not None:
            s = result.sip
            result.sip = Sip(s.a, s.b, s.ap, s.bp, s.crpix - [x0, y0])
        result.array_shape = shape
    else:
        result.insert_transform(result.input_frame, Shift(x0) & Shift(y0), after=True)
        result.bounding_box = ((-0.5, shape[1] - 0.5), (-0.5, shape[0] - 0.5))
        result.array_shape = shape
        result.pixel_shape = shape[::-1]
    return result


def require_icrs_degrees(wcs):
    """Reject celestial WCSs whose output is not ICRS (lon, lat) in degrees."""
    problem = None
    if isinstance(wcs, WCS):
        celestial = wcs.celestial
        ctypes = [str(c) for c in celestial.wcs.ctype]
        radesys = (celestial.wcs.radesys or "").strip().upper()
        if not (ctypes[0][:4] == "RA--" and ctypes[1][:4] == "DEC-"):
            problem = f"FITS WCS axes {ctypes} are not ordered equatorial (RA, Dec)"
        elif radesys not in ("", "ICRS"):
            problem = f"FITS WCS reference frame {radesys} is not ICRS"
        elif radesys == "" and np.isfinite(celestial.wcs.equinox) and celestial.wcs.equinox != 2000:
            problem = f"FITS WCS equinox {celestial.wcs.equinox:g} is not ICRS"
    elif getattr(wcs, "output_frame", None) is not None:
        frame = wcs.output_frame
        reference = getattr(frame, "reference_frame", None)
        if reference is None or reference.name != "icrs":
            problem = "WCS output frame is not a celestial ICRS frame"
        elif tuple(getattr(frame, "axes_order", ())) != (0, 1):
            problem = "WCS output frame axes are not ordered (RA, Dec)"
        elif any(getattr(u, "name", str(u)) != "deg" for u in frame.unit):
            problem = "WCS output frame is not in degrees"

    if problem:
        raise ValueError(f"{problem}; Gladius needs ICRS RA/Dec in degrees")


def validate_wcs(wcs, shape, tolerance=0.001, points=()):
    """Check finite coordinates and numerical inversion, not absolute sky accuracy.

    ``points`` are extra (x, y) pixel positions, such as predicted targets, that must
    also invert to within ``tolerance``.
    """
    require_icrs_degrees(wcs)
    ny, nx = shape
    xx, yy = np.meshgrid(np.linspace(0, nx - 1, 5), np.linspace(0, ny - 1, 5))
    if len(points):
        extra = np.asarray(points, dtype=float).reshape(-1, 2)
        xx, yy = np.append(xx.ravel(), extra[:, 0]), np.append(yy.ravel(), extra[:, 1])

    # A finite forward transform also needs a consistent numerical inverse.
    sky = np.asarray(pixel_to_world(wcs, xx, yy))
    back = np.asarray(world_to_pixel(wcs, *sky))
    if not np.isfinite(sky).all() or not np.isfinite(back).all():
        raise ValueError("WCS is not finite over the image")
    error = float(np.max(np.hypot(back[0] - xx, back[1] - yy)))
    if error > tolerance:
        raise ValueError(f"WCS numerical round-trip error {error:g} exceeds {tolerance:g} pixels")

    # Reject a collapsed or singular spatial mapping even if inverse calls appear successful.
    mid = (nx / 2, ny / 2)
    c = SkyCoord(*pixel_to_world(wcs, *mid), unit="deg")
    scales = [
        float(
            c.separation(
                SkyCoord(*pixel_to_world(wcs, mid[0] + dx, mid[1] + dy), unit="deg")
            ).arcsec
        )
        for dx, dy in ((1, 0), (0, 1))
    ]
    if not all(np.isfinite(scales)) or min(scales) <= 0:
        raise ValueError("WCS has zero or invalid local pixel scale")

    return {
        "check": "finite_grid_and_numerical_inverse",
        "max_error_pixels": error,
        "sample_grid": [5, 5],
        "absolute_astrometry_validated": False,
    }


def _partition(node, shape, ancillary, path=""):
    """Retain all non-spatial content; describe/crop every aligned numeric array."""
    if isinstance(node, (np.ndarray, NDArrayType)):
        a = np.asarray(node)
        if a.ndim >= 2 and a.shape[-2:] == shape:
            ancillary[path] = a.copy()
            descriptor = {
                "parent_array_path": path,
                "parent_shape": list(a.shape),
                "parent_dtype": str(a.dtype),
                "content": "spatial pixels stored as cutout arrays",
            }
            if hasattr(node, "unit"):
                descriptor["parent_unit"] = str(node.unit)
            return descriptor

        if hasattr(node, "unit"):
            return deepcopy(node)
        return a.copy()

    # Keep the original tree structure, replacing spatial arrays with descriptors.
    if isinstance(node, Mapping):
        return {
            key: _partition(value, shape, ancillary, f"{path}/{key}".lstrip("/"))
            for key, value in node.items()
        }
    if isinstance(node, (tuple, list)):
        return [_partition(value, shape, ancillary, f"{path}/{i}") for i, value in enumerate(node)]
    return deepcopy(node)


def targets_from(config, base, override):
    source = override or config.get("targets_csv")
    if source:
        path = Path(source) if override else base / source
        with path.open(newline="") as stream:
            targets = list(csv.DictReader(stream))
    else:
        targets = config.get("targets", [])
    if not targets:
        raise ValueError("Supply targets or targets_csv")

    # IDs become filenames; validate them before creating any output.
    seen = set()
    for target in targets:
        ident = str(target.get("id", ""))
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", ident) or ident in seen:
            raise ValueError("Target IDs must be unique, safe filenames")
        seen.add(ident)

        # CSV rows may contain empty columns for the unused coordinate system.
        sky = all(target.get(k) not in (None, "") for k in ("ra", "dec"))
        pixel = all(target.get(k) not in (None, "") for k in ("x", "y"))
        if sky == pixel:
            raise ValueError(f"{ident}: supply ra/dec OR zero-based x/y")
        for key in ("x", "y") if sky else ("ra", "dec"):
            target.pop(key, None)

        keys = ("ra", "dec") if sky else ("x", "y")
        for key in keys:
            target[key] = float(target[key])
        if not np.isfinite([target[k] for k in keys]).all():
            raise ValueError(f"{ident}: coordinates must be finite")
        if sky and not (0 <= target["ra"] < 360 and -90 <= target["dec"] <= 90):
            raise ValueError(f"{ident}: invalid ICRS degrees")

    return targets


def selected(meta, selection):
    instrument = meta.get("instrument", {})
    if selection.get("filters"):
        value = str(instrument.get("optical_element", "")).upper()
        if not value:
            raise ValueError("Missing filter metadata")
        if value not in [str(f).upper() for f in selection["filters"]]:
            return False

    if selection.get("detectors"):
        match = re.fullmatch(r"(?:WFI|SCA)0?(\d{1,2})", str(instrument.get("detector", "")))
        if not match:
            raise ValueError("Missing/unknown detector metadata")
        if int(match[1]) not in selection["detectors"]:
            return False

    # Date bounds select exposure starts in UTC: inclusive start, exclusive end.
    if selection.get("start") or selection.get("end"):
        value = meta.get("exposure", {}).get("start_time")
        if value is None:
            raise ValueError("Missing exposure start_time")
        time = value.utc if isinstance(value, Time) else Time(value, scale="utc")
        if selection.get("start") and time < Time(str(selection["start"]), scale="utc"):
            return False
        if selection.get("end") and time >= Time(str(selection["end"]), scale="utc"):
            return False
    return True


def sources(inputs, targets, base):
    if inputs.get("mode", "directory") == "directory":
        directory = (base / inputs.get("directory", "images")).resolve()
        glob = directory.rglob if inputs.get("recursive", False) else directory.glob
        paths = sorted(p for p in glob(inputs.get("pattern", "*_cal.asdf")) if p.is_file())
        if not paths:
            raise ValueError("No parent files matched")
        return None, paths

    if inputs["mode"] != "mast":
        raise ValueError("inputs.mode must be directory or mast")

    from astroquery.mast import MastMissions

    mast = MastMissions(mission="roman")
    mast.TIMEOUT = 120
    if os.environ.get("MAST_API_TOKEN"):
        mast.login(token=os.environ["MAST_API_TOKEN"], store_token=False)

    # Search around each sky target unless the user supplied a shared position.
    criteria = {"productLevel": "2", **inputs.get("mast_criteria", {})}
    positions = {(t["ra"], t["dec"]) for t in targets if "ra" in t}
    if not positions and not inputs.get("mast_criteria"):
        raise ValueError("Pixel-only MAST targets require explicit mast_criteria")
    queries = [criteria]
    if positions and "coordinates" not in criteria:
        queries = [
            dict(
                criteria,
                coordinates=f"{ra} {dec}",
                radius=f"{inputs.get('radius_arcmin', 6)} arcmin",
            )
            for ra, dec in sorted(positions)
        ]

    # Overlapping cones can find the same parent; download it once per run.
    products = {}
    for query in queries:
        observations = mast.query_criteria(**query, limit=inputs.get("query_limit", 50000))
        if len(observations) >= inputs.get("query_limit", 50000):
            raise ValueError("MAST query may be truncated; narrow criteria or raise query_limit")
        if not len(observations):
            continue

        for row in mast.get_unique_product_list(observations):
            name = str(row["filename"])
            if name.lower().endswith("_cal.asdf"):
                key = str(row["dataURI"]) if "dataURI" in row.colnames else name
                products[key] = row

    if not products:
        raise ValueError("No calibrated MAST products found")
    return mast, list(products.values())


@contextmanager
def staged(source, mast):
    if mast is None:
        yield source
        return

    from astropy.table import Table

    # Keep each downloaded parent only while its targets are being extracted.
    with tempfile.TemporaryDirectory(prefix="roman-parent-") as directory:
        manifest = mast.download_products(Table(rows=[source]), download_dir=directory)
        if len(manifest) != 1 or str(manifest[0]["Status"]).upper() != "COMPLETE":
            raise RuntimeError("MAST download failed")

        path = Path(str(manifest[0]["Local Path"]))
        if not path.is_file():
            raise RuntimeError("MAST returned no file")
        yield path


def write_fits(tree, path):
    """Export an explicitly approximate TAN-SIP WCS, checking its residual."""
    wcs, shape = tree["wcs"], tree["data"].shape
    header = (
        wcs.to_header(relax=True)
        if isinstance(wcs, WCS)
        else wcs.to_fits_sip(max_pix_error=0.01, max_inv_pix_error=0.01, degree=5)
    )

    # Compare the FITS approximation with the exact stored WCS across the cutout.
    approximate = WCS(header)
    yy, xx = np.meshgrid(
        np.linspace(0, shape[0] - 1, 9), np.linspace(0, shape[1] - 1, 9), indexing="ij"
    )
    back = approximate.all_world2pix(*pixel_to_world(wcs, xx, yy), 0)
    error = float(np.max(np.hypot(back[0] - xx, back[1] - yy)))
    if not np.isfinite(error) or error > 0.01:
        raise ValueError(f"FITS WCS approximation exceeds 0.01 pixel: {error}")

    # Full metadata lives in ASDF; this companion exposes the three image planes.
    hdus = [fits.PrimaryHDU()]
    for key, name in (("data", "SCI"), ("err", "ERR"), ("dq", "DQ")):
        array = tree[key]
        if array.dtype == np.float16:
            array = array.astype(np.float32)
        hdus.append(fits.ImageHDU(array, header=header, name=name))
    fits.HDUList(hdus).writeto(path, checksum=True)


def extract_parent(path, target_list, config, output, index, report):
    # Unknown ASDF converters must fail rather than silently discard typed metadata.
    with warnings.catch_warnings():
        warnings.simplefilter("error", AsdfConversionWarning)
        with asdf.open(path, lazy_load=True, memmap=False, strict_extension_check=True) as af:
            if path.suffix.lower() != ".asdf" or "schema" in af.tree:
                raise ValueError("Use original Roman calibrated ASDF parents")

            # Read and validate the detector planes once for all targets in this parent.
            node = af.tree.get("roman", af.tree)
            arrays = {k: np.asarray(node[k]) for k in ("data", "err", "dq")}
            shape = arrays["data"].shape
            if len(shape) != 2 or any(a.shape != shape for a in arrays.values()):
                raise ValueError("SCI/ERR/DQ must be matching 2D arrays")
            if any(not np.issubdtype(arrays[k].dtype, np.floating) for k in ("data", "err")):
                raise ValueError("SCI/ERR must be floating point")
            if not np.issubdtype(arrays["dq"].dtype, np.integer) or np.any(arrays["dq"] < 0):
                raise ValueError("DQ must contain nonnegative integer flags")

            meta = node.get("meta", {})
            if not selected(meta, config.get("selection", {})):
                report.append({"parent": path.name, "status": "filtered"})
                return

            wcs = deepcopy(meta.get("wcs", node.get("wcs")))
            validation = validate_wcs(wcs, shape)

            # Separate full metadata from arrays that must follow the cutout slices.
            ancillary = {}
            metadata = _partition(af.tree, shape, ancillary)
            prefix = "roman/" if "roman" in af.tree else ""
            for key in arrays:
                ancillary.pop(prefix + key, None)

            for target in target_list:
                record = {"parent": path.name, "target": target["id"]}
                report.append(record)
                try:
                    x, y = (
                        (target["x"], target["y"])
                        if "x" in target
                        else map(float, world_to_pixel(wcs, target["ra"], target["dec"]))
                    )
                    ny, nx = shape
                    if not np.isfinite([x, y]).all() or not (
                        -0.5 <= x < nx - 0.5 and -0.5 <= y < ny - 0.5
                    ):
                        record["status"] = "off_detector"
                        continue

                    # One geometry keeps science, errors, flags, and ancillary arrays aligned.
                    mapping = geometry(x, y, shape, config.get("size", 150))
                    if config.get("edge", "pad") == "strict" and mapping["padding_pixels"]:
                        raise ValueError("Cutout crosses detector boundary")

                    tree = {k: extract_plane(a, mapping, dq=k == "dq") for k, a in arrays.items()}
                    tree.update(
                        schema="roman-script-cutout-1",
                        wcs=translate_wcs(wcs, mapping),
                        parent_wcs=wcs,
                        parent_metadata=metadata,
                        mapping=mapping,
                        target=target,
                        parent_filename=path.name,
                        wcs_validation=validation,
                        resampled=False,
                        ancillary_arrays={
                            k: extract_plane(
                                a, mapping, dq=k.split("/")[-1].lower() in ("dq", "pixeldq")
                            )
                            for k, a in ancillary.items()
                        },
                    )

                    # The parent index avoids collisions between identical archive filenames.
                    stem = f"{index:05d}_{path.stem}_{target['id']}"
                    destination = output / f"{stem}.asdf"
                    asdf.AsdfFile(tree).write_to(destination)
                    if config.get("fits", False):
                        write_fits(tree, output / f"{stem}.fits")
                    record.update(status="ok", output=destination.name)
                except Exception as exc:
                    # Record this target's failure and still attempt the remaining targets.
                    record.update(status="failed", error=str(exc))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--targets", help="CSV path relative to current directory")
    parser.add_argument(
        "--output", type=Path, help="Fresh directory, relative to current directory"
    )
    parser.add_argument("--size", type=int)
    parser.add_argument("--edge", choices=("pad", "strict"))
    parser.add_argument("--fits", action="store_true", default=None)
    args = parser.parse_args(argv)

    # Load YAML first; explicit command-line options take precedence.
    config = yaml.safe_load(args.config.read_text())
    if not isinstance(config, dict):
        raise ValueError("YAML must contain a mapping")
    unknown = set(config) - {
        "inputs",
        "targets",
        "targets_csv",
        "output",
        "size",
        "edge",
        "fits",
        "selection",
    }
    if unknown:
        raise ValueError(f"Unknown config keys: {sorted(unknown)}")

    for key in ("size", "edge", "fits"):
        if getattr(args, key) is not None:
            config[key] = getattr(args, key)

    if type(config.get("size", 150)) is not int or config.get("size", 150) < 1:
        raise ValueError("size must be a positive integer")
    if config.get("edge", "pad") not in ("pad", "strict"):
        raise ValueError("edge must be pad or strict")

    for section, allowed in {
        "inputs": {
            "mode",
            "directory",
            "pattern",
            "recursive",
            "mast_criteria",
            "radius_arcmin",
            "query_limit",
        },
        "selection": {"filters", "detectors", "start", "end"},
    }.items():
        settings = config.get(section, {})
        if not isinstance(settings, dict) or set(settings) - allowed:
            raise ValueError(f"Invalid or unknown {section} settings")
    if type(config.get("fits", False)) is not bool:
        raise ValueError("fits must be true or false")

    # Resolve paths and discover parents before creating the fresh output directory.
    base = args.config.resolve().parent
    targets = targets_from(config, base, args.targets)
    output = (args.output or base / config.get("output", "cutouts")).resolve()
    if output.exists():
        raise ValueError(f"Output directory must not exist: {output}")

    mast, parents = sources(config.get("inputs", {}), targets, base)
    output.mkdir(parents=True, exist_ok=False)

    # Processing is deliberately linear: open one parent, extract its targets, close it.
    report = []
    try:
        for index, source in enumerate(parents, 1):
            name = str(source if mast is None else source["filename"])
            print(f"[{index}/{len(parents)}] {Path(name).name}", flush=True)
            try:
                with staged(source, mast) as path:
                    extract_parent(path, targets, config, output, index, report)
            except Exception as exc:
                report.append({"parent": Path(name).name, "status": "failed", "error": str(exc)})
    finally:
        # Preserve the results collected so far even if processing is interrupted.
        (output / "manifest.json").write_text(
            json.dumps({"config": config, "results": report}, indent=2, default=str) + "\n"
        )

    successes = sum(r["status"] == "ok" for r in report)
    failures = sum(r["status"] == "failed" for r in report)
    print(f"{successes} cutouts; {failures} failures. Manifest: {output / 'manifest.json'}")
    return 1 if failures or not successes else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError) as exc:
        sys.exit(str(exc))
