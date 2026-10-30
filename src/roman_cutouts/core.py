"""Unresampled array extraction with explicit virtual parent coordinates."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.modeling.models import Shift
from astropy.wcs import WCS, Sip

from .config import Extraction, Target

DO_NOT_USE = 1
SATURATED = 2


class NoOverlapError(ValueError):
    """Requested cutout has no valid parent pixels."""


@dataclass
class Cutout:
    """Native image planes, mapping, astrometry, and retained parent metadata."""

    arrays: dict[str, np.ndarray]
    mapping: dict[str, Any]
    wcs: Any
    parent_wcs: Any
    parent_metadata: dict[str, Any]
    provenance: dict[str, Any]
    ancillary_arrays: dict[str, np.ndarray]


def geometry(x: float, y: float, shape: tuple[int, int], size: int) -> dict[str, Any]:
    """Commissioning convention: floor position minus (size-1)//2, for any parity."""
    if not np.isfinite([x, y]).all() or type(size) is not int or size < 1:
        raise ValueError("Finite x/y and a positive integer size are required")
    if len(shape) != 2 or min(shape) < 1:
        raise ValueError("Parent data must have two nonempty dimensions")
    ny, nx = map(int, shape)
    x0, y0 = int(np.floor(x)) - (size - 1) // 2, int(np.floor(y)) - (size - 1) // 2
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
        prediction_on_detector=bool(0 <= x < nx and 0 <= y < ny),
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
    if dq:
        dtype, fill = array.dtype, DO_NOT_USE
    elif np.issubdtype(array.dtype, np.inexact):
        dtype, fill = array.dtype, np.nan
    elif np.issubdtype(array.dtype, np.integer) or array.dtype == bool:
        dtype, fill = array.dtype, 0
    else:
        raise ValueError(f"Unsupported spatial array dtype {array.dtype}")
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


def validate_wcs(wcs, shape, tolerance=0.001):
    """Check finite coordinates and numerical inversion, not absolute sky accuracy."""
    ny, nx = shape
    xx, yy = np.meshgrid(np.linspace(0, nx - 1, 5), np.linspace(0, ny - 1, 5))
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


def make_cutout(
    arrays: dict[str, np.ndarray],
    wcs,
    target: Target,
    *,
    extraction: Extraction | None = None,
    parent_metadata=None,
    parent_wcs=None,
    provenance=None,
    ancillary_arrays=None,
) -> Cutout:
    """Extract native SCI/ERR/DQ using the commissioning centering convention.

    SCI and ERR must be floating point; DQ flags must be integers. Metadata and
    original parent astrometry are retained separately from derived values.
    """
    extraction = extraction or Extraction()
    if set(arrays) != {"data", "err", "dq"}:
        raise ValueError("Exactly data, err and dq planes are required")
    for name in ("data", "err"):
        if not np.issubdtype(arrays[name].dtype, np.floating):
            raise ValueError(f"{name} must be floating point to support NaN padding")
    if any(a.ndim != 2 or a.shape != arrays["data"].shape for a in arrays.values()):
        raise ValueError("SCI, ERR and DQ must be 2D with identical shapes")
    if target.x is None:
        x, y = map(float, world_to_pixel(wcs, target.ra, target.dec))
    else:
        x, y = target.x, target.y
    mapping = geometry(x, y, arrays["data"].shape, extraction.size)
    padding = mapping["padding_pixels"]
    if padding == extraction.size**2 and extraction.no_overlap != "pad":
        raise NoOverlapError("Target cutout does not overlap detector")
    if padding and extraction.edge == "strict":
        raise ValueError("Cutout crosses detector boundary with edge=strict")
    output = {name: extract_plane(a, mapping, dq=name == "dq") for name, a in arrays.items()}
    result_wcs = translate_wcs(wcs, mapping)
    prov = deepcopy(provenance or {})
    prov.update(
        target=target.model_dump(mode="json"),
        predicted_parent_xy=[x, y],
        predicted_cutout_xy=[x - mapping["x0"], y - mapping["y0"]],
        position_is_catalogue_prediction=True,
        resampled=False,
        rotated=False,
    )
    return Cutout(
        output,
        mapping,
        result_wcs,
        deepcopy(parent_wcs if parent_wcs is not None else wcs),
        deepcopy(parent_metadata or {}),
        prov,
        {
            key: extract_plane(a, mapping, dq=key.split("/")[-1].lower() in ("dq", "pixeldq"))
            for key, a in (ancillary_arrays or {}).items()
        },
    )
