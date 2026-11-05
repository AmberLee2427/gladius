"""Image-based review of every saved cutout, including quality-screen exclusions.

These helpers read revision manifests and images. They never query the archive,
change a quality decision, or write to a completed revision.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from PIL import Image, ImageDraw, ImageFont

from .core import pixel_to_world, world_to_pixel
from .io import read_cutout, read_exposure, sha256


def _manifest(path):
    path = Path(path)
    return path.parent, json.loads(path.read_text())


def _entries(manifest):
    times = {
        source.get("digest"): source.get("summary", {}).get("start_utc") or ""
        for source in manifest.get("sources", [])
    }
    return sorted(
        manifest["entries"].items(),
        key=lambda pair: (
            pair[1].get("target_id", pair[0].split("/")[0]),
            times.get(pair[1].get("parent_sha256"), ""),
            pair[1].get("source", ""),
            pair[0],
        ),
    )


def _cutout(directory, entry):
    names = sorted(entry["files"], key=lambda name: not name.endswith(".asdf"))
    return read_cutout(directory / names[0])


def audit_rows(manifest_path):
    """Return one row per attempted parent/target, including skips and failures.

    Quality comes from this revision, rather than a reused file's creation record.
    Pixel fractions refer to the entire saved cutout, including padded pixels.
    """
    directory, manifest = _manifest(manifest_path)
    rows = []
    for key, entry in _entries(manifest):
        quality = entry.get("quality", {})
        row = {
            "entry": key,
            "target": entry.get("target_id", key.split("/")[0]),
            "parent": Path(entry.get("source", "unknown")).name,
            "status": entry["status"],
            "filter": entry.get("filter", ""),
            "accepted": quality.get("accepted"),
            "display_eligible": (
                quality.get("accepted", False)
                or not manifest["configuration"]["quality"]["exclude_from_stacks"]
            )
            if entry["status"] == "complete"
            else None,
            "axis_ratio": quality.get("axis_ratio"),
            "reason": entry.get("error", entry.get("reason", quality.get("reason", ""))),
            "padding_fraction": None,
            "do_not_use_fraction": None,
            "saturated_fraction": None,
            "start_utc": None,
        }
        if entry["status"] == "complete":
            cutout = _cutout(directory, entry)
            data, dq = cutout.arrays["data"], cutout.arrays["dq"]
            row.update(
                padding_fraction=cutout.mapping["padding_pixels"] / data.size,
                do_not_use_fraction=float(np.mean((dq & 1) != 0)),
                saturated_fraction=float(np.mean((dq & 2) != 0)),
                start_utc=cutout.provenance.get("exposure", {}).get("start_utc"),
            )
        rows.append(row)
    return rows


def _limits(arrays):
    samples = []
    for data in arrays:
        finite = np.asarray(data)[np.isfinite(data)]
        samples.append(finite[:: max(1, finite.size // 2000)])
    finite = np.concatenate(samples) if samples else np.array([])
    low, high = np.percentile(finite, [1, 99.8]) if finite.size else (0, 1)
    return float(low), float(max(high, low + 1e-12))


def _image(data, limits):
    low, high = limits
    normal = np.clip((np.nan_to_num(data, nan=low) - low) / (high - low), 0, 1)
    grey = (255 * np.arcsinh(normal / 0.03) / np.arcsinh(1 / 0.03)).astype("uint8")
    rgb = np.repeat(grey[..., None], 3, axis=2)
    rgb[~np.isfinite(data)] = (55, 34, 68)
    # Native arrays count y upward in the displayed image; PIL rows count downward.
    return Image.fromarray(rgb[::-1].copy())


def image_preview(data, *, width=300):
    """Return a grayscale asinh PIL preview, with native y increasing upward.

    Each call chooses its own 1/99.8-percentile limits. It is a display stretch,
    not a flux conversion or a common stretch for quantitative noise comparison.
    """
    data = np.asarray(data)
    if data.ndim != 2 or min(data.shape) < 1 or width < 1:
        raise ValueError("Preview requires a nonempty 2D array and positive width")
    return _image(data, _limits([data])).resize(
        (width, max(1, round(width * data.shape[0] / data.shape[1]))), Image.Resampling.NEAREST
    )


@lru_cache(maxsize=1)
def _font():
    return ImageFont.truetype(
        str(files("gladius").joinpath("web_assets/family/family-font-2.ttf")), 13
    )


def _cross(draw, point, color):
    x, y = point
    draw.line((x - 6, y, x + 6, y), fill=color, width=2)
    draw.line((x, y - 6, x, y + 6), fill=color, width=2)


def _directions(draw, wcs, shape, box):
    """Orient N/E using the saved WCS; no image rotation or registration."""
    try:
        ny, nx = shape
        sky = pixel_to_world(wcs, (nx - 1) / 2, (ny - 1) / 2)
        centre = SkyCoord(float(sky[0]) * u.deg, float(sky[1]) * u.deg)
        px, py = world_to_pixel(wcs, centre.ra.deg, centre.dec.deg)
        anchor = (box[0] + 35, box[1] + box[3] - 38)
        for angle, label in ((0, "N"), (90, "E")):
            point = centre.directional_offset_by(angle * u.deg, 1 * u.arcsec)
            x, y = world_to_pixel(wcs, point.ra.deg, point.dec.deg)
            vector = np.array([float(x - px), -float(y - py)])
            length = np.linalg.norm(vector)
            if not np.isfinite(length) or length == 0:
                raise ValueError("No finite orientation")
            vector *= 24 / length
            tip = tuple(np.asarray(anchor) + vector)
            draw.line((*anchor, *tip), fill="#e4d8b1", width=2)
            draw.text(tip, label, fill="#e4d8b1", font=_font())
    except (ValueError, TypeError, ArithmeticError):
        draw.text((box[0] + 5, box[1] + box[3] - 14), "WCS orientation unavailable", fill="white")


def contact_sheets(manifest_path, *, page_size=12, columns=3):
    """Yield PIL image pages for ALL complete cutouts, accepted and flagged.

    Shared asinh limits are computed per target/filter/unit group, so thumbnails
    in that group are comparable. Gold rectangles mark the central ACF tile;
    crosses mark the predicted target, not a fitted star centroid. Invalid pixels
    are purple. N/E arrows use the saved WCS and do not validate absolute pointing.
    """
    if page_size < 1 or columns < 1:
        raise ValueError("page_size and columns must be positive")
    directory, manifest = _manifest(manifest_path)
    entries = [(k, e) for k, e in _entries(manifest) if e["status"] == "complete"]
    samples = {}
    for _, entry in entries:
        data = _cutout(directory, entry).arrays["data"]
        group = (entry["target_id"], entry["filter"], entry["data_units"])
        finite = data[np.isfinite(data)]
        samples.setdefault(group, []).append(finite[:: max(1, finite.size // 2000)])
    limits = {group: _limits(values) for group, values in samples.items()}
    width, height, stamp = 310, 385, 280
    for start in range(0, len(entries), page_size):
        page = entries[start : start + page_size]
        canvas = Image.new(
            "RGB", (columns * width, ((len(page) + columns - 1) // columns) * height), "#21142d"
        )
        draw = ImageDraw.Draw(canvas)
        draw.font = _font()
        for index, (_key, entry) in enumerate(page):
            x, y = (index % columns) * width + 15, (index // columns) * height + 8
            cutout = _cutout(directory, entry)
            data = cutout.arrays["data"]
            quality = entry["quality"]
            color = "#b3dbc5" if quality["accepted"] else "#e4c67b"
            label = "KEEP" if quality["accepted"] else "FLAG"
            ratio = quality.get("axis_ratio")
            ratio_text = f"{ratio:.3f}" if ratio is not None else "not measured"
            draw.text(
                (x, y),
                f"{label}  {entry['target_id']}  {entry['filter']}",
                fill=color,
                font=_font(),
            )
            draw.text((x, y + 15), Path(entry["source"]).name[:40], fill="white", font=_font())
            draw.text(
                (x, y + 30), f"ACF {ratio_text}: {quality['reason']}", fill=color, font=_font()
            )
            box = (x, y + 48, stamp, stamp)
            group = (entry["target_id"], entry["filter"], entry["data_units"])
            image = _image(data, limits[group]).resize((stamp, stamp), Image.Resampling.NEAREST)
            canvas.paste(image, box[:2])
            ny, nx = data.shape
            predicted = cutout.provenance["predicted_cutout_xy"]
            _cross(
                draw,
                (
                    x + (predicted[0] + 0.5) * stamp / nx,
                    y + 48 + (ny - 0.5 - predicted[1]) * stamp / ny,
                ),
                color,
            )
            tile = manifest["configuration"]["quality"]["tile_size"]
            if min(data.shape) >= tile:
                tx, ty = (nx - tile) // 2, (ny - tile) // 2
                draw.rectangle(
                    (
                        x + tx * stamp / nx,
                        y + 48 + (ny - ty - tile) * stamp / ny,
                        x + (tx + tile) * stamp / nx,
                        y + 48 + (ny - ty) * stamp / ny,
                    ),
                    outline="#e4d8b1",
                )
            _directions(draw, cutout.wcs, data.shape, box)
            padding = cutout.mapping["padding_pixels"] / data.size
            bad = np.mean((cutout.arrays["dq"] & 3) != 0)
            draw.text(
                (x, y + 335), f"Padding {padding:.1%}; DQ bad/saturated {bad:.1%}", fill="white"
            )
            date = cutout.provenance.get("exposure", {}).get("start_utc") or "time unavailable"
            draw.text((x, y + 350), str(date), fill="white")
            eligible = (
                quality["accepted"]
                or not manifest["configuration"]["quality"]["exclude_from_stacks"]
            )
            draw.text(
                (x, y + 365), "Eligible for displays: " + ("yes" if eligible else "no"), fill=color
            )
        yield canvas


def parent_preview(manifest_path, parent_sha256, *, width=900):
    """Return one parent image with each requested cutout boundary and target.

    Use retained parents for MAST or the existing original path for local inputs.
    This never fetches missing parents. Boundary overlays use zero-based native
    pixels; the image retains its detector orientation.
    """
    directory, manifest = _manifest(manifest_path)
    entries = [
        e
        for e in manifest["entries"].values()
        if e["status"] == "complete" and e["parent_sha256"] == parent_sha256
    ]
    if not entries:
        raise ValueError("No complete cutouts for that parent")
    original = manifest.get("retained_parents", {}).get(parent_sha256, entries[0]["source"])
    path = Path(original)
    if not path.is_file():
        raise FileNotFoundError(
            "Parent not retained. Set storage.retain_full_images=true and run again; cached cutouts will be reused."
        )
    if sha256(path) != parent_sha256:
        raise ValueError(
            "The available parent changed since this revision; do not compare it as the original."
        )
    exposure = read_exposure(path)
    data = exposure.arrays["data"]
    ny, nx = data.shape
    height = max(1, round(width * ny / nx))
    image = _image(data, _limits([data])).resize((width, height), Image.Resampling.BILINEAR)
    canvas = Image.new("RGB", (width, height + 42), "#21142d")
    canvas.paste(image, (0, 42))
    draw = ImageDraw.Draw(canvas)
    draw.font = _font()
    draw.text((8, 6), path.name, fill="white")
    draw.text(
        (8, 21),
        "Boxes: requested cutouts; crosses: predicted targets; detector orientation retained.",
        fill="white",
    )
    for entry in entries:
        cutout = _cutout(directory, entry)
        x0, y0, x1, y1 = cutout.mapping["parent_virtual_bounds_xyxy"]
        draw.rectangle(
            (
                x0 * width / nx,
                42 + (ny - y1) * height / ny,
                x1 * width / nx,
                42 + (ny - y0) * height / ny,
            ),
            outline="#e4c67b",
            width=2,
        )
        draw.text(
            (max(2, x0 * width / nx), max(44, 42 + (ny - y1) * height / ny)),
            entry["target_id"],
            fill="#e4c67b",
        )
        px, py = cutout.provenance["predicted_parent_xy"]
        _cross(draw, ((px + 0.5) * width / nx, 42 + (ny - 0.5 - py) * height / ny), "#b3dbc5")
    _directions(draw, exposure.wcs, data.shape, (0, 42, width, height))
    return canvas
