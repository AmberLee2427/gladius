"""Optional resampled display stacks; native cutout products are never altered."""

from __future__ import annotations

import hashlib
import re
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np
from astropy.io import fits
from scipy.ndimage import map_coordinates

from .core import pixel_to_world, world_to_pixel
from .io import atomic_json, fits_header, read_cutout, sha256


def build_stacks(entries, run_directory: Path, config):
    """Combine per target/filter using exact WCS, bilinear sampling and a median."""
    groups = defaultdict(list)
    excluded = []
    for key, entry in sorted(entries.items()):
        if entry["status"] != "complete":
            continue
        quality = entry["quality"]
        if config.quality.exclude_from_stacks and not quality["accepted"]:
            excluded.append({"input": key, "quality": quality})
            continue
        groups[(entry["target_id"], entry["filter"])].append((key, entry))
    products = []
    for (target, band), rows in groups.items():
        if len(rows) > config.stacks.max_exposures:
            raise ValueError("Stack exceeds stacks.max_exposures; no inputs silently dropped")
        n = config.extraction.size
        # Median stack plus reprojection work arrays; conservatively bound memory.
        estimate = (len(rows) + 20) * n * n * 8 / 1024**2
        if estimate > config.stacks.max_memory_mb:
            raise ValueError(f"Stack needs approximately {estimate:.0f} MiB; exceeds max_memory_mb")
        units = {entry["data_units"] for _, entry in rows}
        if len(units) != 1:
            raise ValueError("Cannot combine exposures with different data units")
        first = rows[0][1]
        ref = read_cutout(run_directory / next(iter(first["files"])))
        yy, xx = np.indices(ref.arrays["data"].shape, dtype=float)
        sky = pixel_to_world(ref.wcs, xx, yy)
        values = []
        for _, entry in rows:
            cutout = read_cutout(run_directory / next(iter(entry["files"])))
            data, dq = cutout.arrays["data"], cutout.arrays["dq"]
            valid = np.isfinite(data) & ((dq & 3) == 0)
            sx, sy = np.asarray(world_to_pixel(cutout.wcs, *sky))
            sx = np.where(np.isfinite(sx), sx, -1e6)
            sy = np.where(np.isfinite(sy), sy, -1e6)
            weight = map_coordinates(
                valid.astype(float), [sy, sx], order=1, mode="constant", cval=0
            )
            sample = map_coordinates(
                np.where(valid, data, 0).astype(float), [sy, sx], order=1, mode="constant", cval=0
            )
            values.append(np.where(weight > 0.999, sample / np.maximum(weight, 1e-12), np.nan))
        cube = np.stack(values)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            image = np.nanmedian(cube, axis=0)
        coverage = np.isfinite(cube).sum(axis=0).astype(np.uint32)
        band_component = (
            band
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", band)
            else (
                "unknown-filter"
                if not band
                else "filter-" + hashlib.sha256(band.encode()).hexdigest()[:12]
            )
        )
        folder = run_directory / "stacks" / target / band_component
        folder.mkdir(parents=True, exist_ok=True)
        header = fits_header(ref.wcs, image.shape, config.astrometry.fits_tolerance_pixels)
        header["PREVIEW"], header["RESAMPLE"], header["PSFMATCH"] = True, True, False
        header["COMBINE"], header["NSTACK"] = "MEDIAN", len(rows)
        if first["data_units"]:
            header["BUNIT"] = first["data_units"]
        path = folder / "preview-stack.fits"
        # Per-run lock excludes concurrent writers; overwrite only this reproducible display product.
        fits.HDUList(
            [fits.PrimaryHDU(image, header=header), fits.ImageHDU(coverage, name="COVERAGE")]
        ).writeto(path, overwrite=True, checksum=True)
        products.append(
            {
                "path": str(path.relative_to(run_directory)),
                "sha256": sha256(path),
                "target": target,
                "filter": band,
                "inputs": [key for key, _ in rows],
                "reference": rows[0][0],
                "resampled": True,
                "display_only": True,
                "psf_matched": False,
                "photometric_calibration_applied": False,
                "combination": "unweighted median",
                "uncertainty_propagated": False,
            }
        )
    manifest = {
        "products": products,
        "excluded": excluded,
        "note": "Display products; native cutouts unchanged. No photometric or PSF matching.",
    }
    atomic_json(run_directory / "stack-manifest.json", manifest)
    return manifest
