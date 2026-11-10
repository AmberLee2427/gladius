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


def _snap_to_image_edges(coordinates, length):
    """Keep numerical WCS roundoff at an image boundary inside the image.

    Only coordinates within 1e-7 pixel of the first or last pixel centre are
    snapped. Real offsets outside the image still have no coverage.
    """
    coordinates = np.asarray(coordinates)
    for edge in (0, length - 1):
        coordinates = np.where(np.abs(coordinates - edge) <= 1e-7, edge, coordinates)
    return coordinates


def _write_animation(cube, path, frame_ms, frame_info):
    """Write aligned exposure frames with a shared stretch and explicit labels."""
    from PIL import Image, ImageDraw

    finite = cube[np.isfinite(cube)]
    low, high = np.percentile(finite, [1, 99.95]) if finite.size else (0, 1)
    if high <= low:
        high = low + 1
    palette = [34, 22, 46] + [c for level in range(255) for c in (level, level, level)]
    frames = []
    scale = max(1, min(4, 256 // cube.shape[2]))
    width = max(300, cube.shape[2] * scale)
    height = cube.shape[1] * scale
    for index, (data, info) in enumerate(zip(cube, frame_info, strict=True)):
        normal = np.clip((np.nan_to_num(data, nan=low) - low) / (high - low), 0, 1)
        pixels = (1 + 254 * np.arcsinh(normal / 0.03) / np.arcsinh(1 / 0.03)).astype("uint8")
        pixels[~np.isfinite(data)] = 0
        # Match the median and RGB previews: array y increases upward.
        image = Image.fromarray(pixels[::-1].copy()).convert("P")
        image.putpalette(palette)
        image = image.resize((cube.shape[2] * scale, height), Image.Resampling.NEAREST)
        frame = Image.new("P", (width, height + 34), 0)
        frame.putpalette(palette)
        frame.paste(image, ((width - image.width) // 2, 34))
        draw = ImageDraw.Draw(frame)
        draw.text((6, 2), f"Exposure {index + 1}/{len(cube)} - aligned preview", fill=255)
        draw.text((6, 17), info["start_utc"] or "Exposure time unavailable", fill=255)
        frames.append(frame)
    temporary = path.with_suffix(".gif.tmp")
    frames[0].save(
        temporary,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=frame_ms,
        loop=0,
        disposal=2,
        optimize=False,
    )
    temporary.replace(path)
    return {
        "stretch": "shared 1/99.95 percentile asinh, a=0.03",
        "limits": [float(low), float(high)],
    }


def _aligned_exposures(rows, run_directory, ref):
    yy, xx = np.indices(ref.arrays["data"].shape, dtype=float)
    sky = pixel_to_world(ref.wcs, xx, yy)
    values = []
    frame_info = []
    for key, entry in rows:
        cutout = read_cutout(run_directory / next(iter(entry["files"])))
        frame_info.append(
            {
                "input": key,
                "start_utc": cutout.provenance.get("exposure", {}).get("start_utc"),
            }
        )
        data, dq = cutout.arrays["data"], cutout.arrays["dq"]
        valid = np.isfinite(data) & ((dq & 3) == 0)
        sx, sy = np.asarray(world_to_pixel(cutout.wcs, *sky))
        sx = _snap_to_image_edges(sx, data.shape[1])
        sy = _snap_to_image_edges(sy, data.shape[0])
        sx = np.where(np.isfinite(sx), sx, -1e6)
        sy = np.where(np.isfinite(sy), sy, -1e6)
        weight = map_coordinates(valid.astype(float), [sy, sx], order=1, mode="constant", cval=0)
        sample = map_coordinates(
            np.where(valid, data, 0).astype(float), [sy, sx], order=1, mode="constant", cval=0
        )
        values.append(np.where(weight > 0.999, sample / np.maximum(weight, 1e-12), np.nan))
    return np.stack(values), frame_info


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
    animations = []
    for (target, band), rows in groups.items():
        if not (config.stacks.enabled or config.stacks.gif_enabled):
            continue
        if config.stacks.max_exposures and len(rows) > config.stacks.max_exposures:
            raise ValueError("Stack exceeds stacks.max_exposures; no inputs silently dropped")
        n = config.extraction.size
        # Median stack plus reprojection work arrays; conservatively bound memory.
        estimate = (len(rows) * (3 if config.stacks.gif_enabled else 1) + 20) * n * n * 8 / 1024**2
        if config.stacks.max_memory_mb and estimate > config.stacks.max_memory_mb:
            raise ValueError(f"Stack needs approximately {estimate:.0f} MiB; exceeds max_memory_mb")
        units = {entry["data_units"] for _, entry in rows}
        if len(units) != 1:
            raise ValueError("Cannot combine exposures with different data units")
        first = rows[0][1]
        ref = read_cutout(run_directory / next(iter(first["files"])))
        cube, frame_info = _aligned_exposures(rows, run_directory, ref)
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
        if config.stacks.gif_enabled:
            order = sorted(
                range(len(frame_info)),
                key=lambda i: (
                    frame_info[i]["start_utc"] is None,
                    frame_info[i]["start_utc"] or "",
                    frame_info[i]["input"],
                ),
            )
            ordered_info = [frame_info[i] for i in order]
            gif_path = folder / "preview-animation.gif"
            display = _write_animation(
                cube[order], gif_path, config.stacks.gif_frame_ms, ordered_info
            )
            animations.append(
                {
                    "path": str(gif_path.relative_to(run_directory)),
                    "sha256": sha256(gif_path),
                    "target": target,
                    "filter": band,
                    "reference": rows[0][0],
                    "frames": ordered_info,
                    "frame_ms": config.stacks.gif_frame_ms,
                    "display_only": True,
                    "resampled": True,
                    **display,
                }
            )
        if config.stacks.enabled:
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
    composites, composite_skips = _build_composites(groups, run_directory, config)
    manifest = {
        "products": products,
        "animations": animations,
        "composites": composites,
        "composite_skips": composite_skips,
        "excluded": excluded,
        "note": "Display products; native cutouts unchanged. No photometric or PSF matching.",
    }
    atomic_json(run_directory / "stack-manifest.json", manifest)
    return manifest


def _zscale_channel(image):
    """Display normalization using Astropy z-scale, independently per channel."""
    from astropy.visualization import ZScaleInterval

    valid = np.isfinite(image)
    if not valid.any():
        return np.zeros(image.shape), valid, [None, None]
    low, high = ZScaleInterval(
        n_samples=1000,
        contrast=0.25,
        max_reject=0.5,
        min_npixels=5,
        krej=2.5,
        max_iterations=5,
    ).get_limits(image[valid])
    normalized = np.zeros(image.shape, dtype=float)
    normalized[valid] = np.clip((image[valid] - low) / max(high - low, 1e-12), 0, 1)
    return normalized, valid, [float(low), float(high)]


def _build_composites(groups, run_directory, config):
    """Median each chosen filter on ONE sky grid before assigning RGB channels."""
    from PIL import Image

    if not config.stacks.rgb_enabled:
        return [], []
    filters = [config.stacks.red_filter, config.stacks.green_filter, config.stacks.blue_filter]
    products, skipped = [], []
    for target in sorted({target for target, _ in groups}):
        missing = sorted({band for band in filters if not groups.get((target, band))})
        if missing:
            skipped.append(
                {"target": target, "reason": "missing eligible filters", "filters": missing}
            )
            continue
        # Blue is a deterministic reference regardless of input filename ordering.
        reference_id, reference_entry = groups[(target, filters[2])][0]
        ref = read_cutout(run_directory / next(iter(reference_entry["files"])))
        channels, masks, limits, membership = [], [], {}, {}
        for band in filters:
            rows = groups[(target, band)]
            if config.stacks.max_exposures and len(rows) > config.stacks.max_exposures:
                raise ValueError(
                    "Composite exceeds stacks.max_exposures; no inputs silently dropped"
                )
            n = config.extraction.size
            estimate = (len(rows) + 30) * n * n * 8 / 1024**2
            if config.stacks.max_memory_mb and estimate > config.stacks.max_memory_mb:
                raise ValueError(
                    f"Composite needs approximately {estimate:.0f} MiB; exceeds max_memory_mb"
                )
            if len({entry["data_units"] for _, entry in rows}) != 1:
                raise ValueError("Cannot median a composite filter with different data units")
            cube, _ = _aligned_exposures(rows, run_directory, ref)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                median = np.nanmedian(cube, axis=0)
            channel, valid, limits[band] = _zscale_channel(median)
            channels.append(channel)
            masks.append(valid)
            membership[band] = [key for key, _ in rows]
            del cube
        common = np.logical_and.reduce(masks)
        if not common.any():
            skipped.append({"target": target, "reason": "no common valid RGB coverage"})
            continue
        rgb = np.stack(channels, axis=-1)
        rgb[~common] = 0.25
        # PNG rows run top-to-bottom; detector arrays are displayed with y upward.
        pixels = np.round(255 * rgb[::-1]).astype("uint8")
        path = run_directory / "stacks" / target / "colour-composite.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".png.tmp")
        Image.fromarray(pixels).save(temporary, format="PNG")
        temporary.replace(path)
        products.append(
            {
                "path": str(path.relative_to(run_directory)),
                "sha256": sha256(path),
                "target": target,
                "channel_filters": dict(zip(("red", "green", "blue"), filters, strict=True)),
                "reference": reference_id,
                "inputs_by_filter": membership,
                "normalization": "independent per-filter z-scale followed by linear clipping to [0, 1]",
                "zscale_parameters": {
                    "n_samples": 1000,
                    "contrast": 0.25,
                    "max_reject": 0.5,
                    "min_npixels": 5,
                    "krej": 2.5,
                    "max_iterations": 5,
                },
                "zscale_limits": limits,
                "missing_channel_rgb": [0.25, 0.25, 0.25],
                "common_valid_pixels": int(common.sum()),
                "display_only": True,
                "resampled": True,
                "combination": "per-filter unweighted median",
                "psf_matched": False,
                "photometric_calibration_applied": False,
                "physical_colours": False,
            }
        )
    return products, skipped
