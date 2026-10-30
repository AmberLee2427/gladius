"""Read parents and serialize derived products without flattening parent metadata."""

from __future__ import annotations

import hashlib
import json
import warnings
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import asdf
import numpy as np
from asdf.exceptions import AsdfConversionWarning
from asdf.tags.core.ndarray import NDArrayType
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS

from . import __version__
from .core import Cutout, pixel_to_world

SCHEMA = "gladius/derived-1.0"


@dataclass
class Exposure:
    arrays: dict
    wcs: object
    parent_metadata: dict
    ancillary_arrays: dict
    summary: dict


def sha256(path: Path) -> str:
    """Hash in bounded chunks; parent images may be large."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, data):
    """Replace a manifest only after its complete temporary write."""
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(data, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


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
    if isinstance(node, Mapping):
        return {
            key: _partition(value, shape, ancillary, f"{path}/{key}".lstrip("/"))
            for key, value in node.items()
        }
    if isinstance(node, (tuple, list)):
        return [_partition(value, shape, ancillary, f"{path}/{i}") for i, value in enumerate(node)]
    return deepcopy(node)


def _time(value):
    if value is None:
        return None
    t = value if isinstance(value, Time) else Time(value, scale="utc")
    return t.utc


def _summary(meta):
    instrument = meta.get("instrument", {})
    exposure = meta.get("exposure", {})
    start = _time(exposure.get("start_time", exposure.get("observation_start_utc")))
    end = _time(exposure.get("end_time", exposure.get("observation_end_utc")))
    if start is not None and end is not None and end < start:
        raise ValueError("Parent exposure end precedes its start")
    midpoint = start + (end - start) / 2 if start is not None and end is not None else None
    duration = exposure.get("exposure_time", exposure.get("exposure_time_s"))
    if hasattr(duration, "to_value"):
        duration = duration.to_value("s")
    if duration is not None and (not np.isfinite(float(duration)) or float(duration) < 0):
        raise ValueError("Parent exposure duration must be finite and nonnegative")
    units = meta.get("bunit_data", meta.get("bunit"))
    return {
        "detector": str(instrument.get("detector", meta.get("detector", ""))),
        "filter": str(instrument.get("optical_element", meta.get("filter", ""))).upper(),
        "data_units": str(units) if units is not None else None,
        "err_units": str(meta["bunit_err"])
        if meta.get("bunit_err") is not None
        else (str(units) if units is not None else None),
        "start_utc": start.isot if start is not None else None,
        "end_utc": end.isot if end is not None else None,
        "midpoint_utc": midpoint.isot if midpoint is not None else None,
        "exposure_time_s": float(duration) if duration is not None else None,
        "time_scale": "UTC",
        "midpoint_definition": "midpoint of reported start/end",
    }


def read_exposure(path: str | Path) -> Exposure:
    """Load one 2D calibrated ASDF or SCI/ERR/DQ FITS parent.

    Roman ASDF extensions must be installed when required by input tags. Unknown
    ASDF converters raise rather than silently losing typed metadata.
    """
    path = Path(path)
    if path.suffix.lower() in (".fits", ".fit", ".fts"):
        return _read_fits(path)
    with warnings.catch_warnings():
        warnings.simplefilter("error", AsdfConversionWarning)
        with asdf.open(path, lazy_load=True, memmap=False, strict_extension_check=True) as af:
            node = af.tree.get("roman", af.tree)
            if any(name not in node for name in ("data", "err", "dq")):
                raise ValueError(
                    "Parent ASDF requires data, err, dq; install [roman] for Roman tags"
                )
            arrays = {name: np.asarray(node[name]).copy() for name in ("data", "err", "dq")}
            if arrays["data"].ndim != 2:
                raise ValueError("Only 2D calibrated detector images are supported")
            meta = node.get("meta", {})
            wcs = deepcopy(meta.get("wcs", node.get("wcs")))
            if wcs is None:
                raise ValueError("No parent WCS found")
            ancillary = {}
            parent_metadata = _partition(af.tree, arrays["data"].shape, ancillary)
            prefix = "roman/" if "roman" in af.tree else ""
            for key in arrays:
                ancillary.pop(prefix + key, None)
            summary = _summary(meta)
            for key, label in (("data", "data_units"), ("err", "err_units")):
                if summary[label] is None and hasattr(node[key], "unit"):
                    summary[label] = str(node[key].unit)
            return Exposure(arrays, wcs, parent_metadata, ancillary, summary)


def _read_fits(path):
    with fits.open(path, memmap=False) as hdul:
        arrays = {
            name: np.array(hdul[label].data, copy=True)
            for name, label in (("data", "SCI"), ("err", "ERR"), ("dq", "DQ"))
        }
        header = hdul["SCI"].header
        wcs = WCS(header, fobj=hdul)
        if not wcs.has_celestial or wcs.pixel_n_dim != 2:
            raise ValueError("FITS parent needs a 2D celestial WCS on SCI")
        wcs.array_shape = arrays["data"].shape
        ancillary, headers, other = {}, [], {}
        for index, hdu in enumerate(hdul):
            headers.append(
                {
                    "index": index,
                    "name": hdu.name,
                    "cards": [
                        [
                            c.keyword,
                            None if isinstance(c.value, fits.card.Undefined) else c.value,
                            c.comment,
                        ]
                        for c in hdu.header.cards
                    ],
                }
            )
            if hdu.data is not None and hdu.name not in ("SCI", "ERR", "DQ"):
                key = f"fits/{index}/{hdu.name}"
                if hdu.data.ndim >= 2 and hdu.data.shape[-2:] == arrays["data"].shape:
                    ancillary[key] = hdu.data.copy()
                else:
                    other[key] = hdu.data.copy()
        # Observation metadata is often on PRIMARY while the WCS is on SCI.
        header = hdul[0].header.copy()
        header.extend(hdul["SCI"].header, update=True)
        meta = {
            "instrument": {
                "detector": header.get("DETECTOR", ""),
                "optical_element": header.get("FILTER", ""),
            },
            "bunit_data": header.get("BUNIT"),
            "bunit_err": hdul["ERR"].header.get("BUNIT"),
            "exposure": {"exposure_time": header.get("EXPTIME")},
        }
        timesys = header.get("TIMESYS", "UTC").lower()
        for label, keys in (("start_time", ("DATE-BEG", "DATE-OBS")), ("end_time", ("DATE-END",))):
            value = next((header[k] for k in keys if k in header), None)
            if value is not None:
                meta["exposure"][label] = Time(value, scale=timesys)
        return Exposure(
            arrays,
            wcs,
            {"fits_headers": headers, "non_spatial_arrays": other},
            ancillary,
            _summary(meta),
        )


def read_correction(path: Path):
    """Read a separately supplied corrected WCS and its non-spatial provenance."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", AsdfConversionWarning)
        with asdf.open(path, memmap=False, strict_extension_check=True) as af:
            node = af.tree.get("roman", af.tree)
            wcs = node.get("wcs", node.get("meta", {}).get("wcs"))
            if wcs is None:
                raise ValueError(f"No WCS in correction product {path}")
            # Corrections normally have a small wcs/provenance tree; avoid copying full images.
            ancillary = {}
            shape = np.asarray(node["data"]).shape if "data" in node else (-1, -1)
            meta = _partition(af.tree, shape, ancillary)
            return deepcopy(wcs), meta


def _tree(cutout):
    ny, nx = cutout.arrays["data"].shape

    def footprint(x0, y0, x1, y1):
        if x1 <= x0 or y1 <= y0:
            return None
        ra, dec = pixel_to_world(
            cutout.wcs, np.array([x0, x1, x1, x0]) - 0.5, np.array([y0, y0, y1, y1]) - 0.5
        )
        if not np.isfinite([ra, dec]).all():
            return None
        return "POLYGON ICRS " + " ".join(
            f"{value:.12f}" for pair in zip(ra, dec, strict=False) for value in pair
        )

    spatial = {
        "array_shape": [ny, nx],
        "s_region": footprint(*cutout.mapping["cutout_valid_bounds_xyxy"]),
        "virtual_s_region": footprint(0, 0, nx, ny),
        "footprint_definition": "pixel-edge corner polygon; valid coverage versus padded grid",
        "exposure": cutout.provenance.get("exposure", {}),
    }
    return {
        "schema": SCHEMA,
        "package_version": __version__,
        "mapping": cutout.mapping,
        "wcs": cutout.wcs,
        "parent_wcs": cutout.parent_wcs,
        "parent_metadata": cutout.parent_metadata,
        "cutout_metadata": spatial,
        "provenance": cutout.provenance,
    }


def fits_header(wcs, shape, tolerance):
    """Export a FITS WCS and measure its error against the full stored transform."""
    if isinstance(wcs, WCS):
        header = wcs.to_header(relax=True)
    else:
        header = wcs.to_fits_sip(max_pix_error=tolerance, max_inv_pix_error=tolerance, degree=5)
    approx = WCS(header)
    yy, xx = np.meshgrid(
        np.linspace(0, shape[0] - 1, 9), np.linspace(0, shape[1] - 1, 9), indexing="ij"
    )
    rx, ry = approx.all_world2pix(*pixel_to_world(wcs, xx, yy), 0)
    error = float(np.max(np.hypot(rx - xx, ry - yy)))
    if not np.isfinite(error) or error > tolerance:
        raise ValueError(f"FITS WCS approximation error {error:g} exceeds {tolerance:g} pixels")
    header["WCSERR"] = (error, "Measured max error on 9x9 grid, pixels")
    return header


def _fits_array(array):
    """Use lossless FITS storage types; Roman uncertainties may be float16."""
    if array.dtype.kind == "f" and array.dtype.itemsize == 2:
        return array.astype(np.float32)
    if array.dtype == bool:
        return array.astype(np.uint8)
    if array.dtype.kind not in "uif" or array.dtype.itemsize > 8:
        raise ValueError(f"FITS image storage cannot represent {array.dtype}; choose ASDF output")
    return array


def write_cutout(cutout: Cutout, folder: Path, formats=("asdf", "fits"), *, tolerance=0.01):
    """Write and reopen each file, checking native planes and stored astrometry.

    FITS contains a package-specific ASDFMETA extension with complete metadata
    and exact WCS; SCI/ERR/DQ remain normal image extensions. This is a derived
    product format, not a schema-valid Roman mission datamodel.
    """
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    metadata = _tree(cutout)
    if "asdf" in formats:
        path = folder / "cutout.asdf"
        asdf.AsdfFile(
            {**metadata, **cutout.arrays, "ancillary_arrays": cutout.ancillary_arrays}
        ).write_to(path)
        files.append(path)
    if "fits" in formats:
        header = fits_header(cutout.wcs, cutout.arrays["data"].shape, tolerance)
        mapping, exposure = cutout.mapping, cutout.provenance.get("exposure", {})
        header["X0"], header["Y0"] = mapping["x0"], mapping["y0"]
        header["PIXORIG"], header["PADPIX"] = 0, mapping["padding_pixels"]
        header["RESAMPLE"], header["ROTATED"] = False, False
        header["PARENT"] = cutout.provenance.get("parent_filename", "unknown")
        header["PARSHA"] = cutout.provenance.get("parent_sha256", "unknown")
        for label, key in (
            ("DATE-BEG", "start_utc"),
            ("DATE-OBS", "start_utc"),
            ("DATE-END", "end_utc"),
            ("DATE-AVG", "midpoint_utc"),
        ):
            if exposure.get(key) is not None:
                header[label] = exposure[key]
                mjd_label = {
                    "DATE-BEG": "MJD-BEG",
                    "DATE-OBS": "MJD-OBS",
                    "DATE-END": "MJD-END",
                    "DATE-AVG": "MJD-AVG",
                }[label]
                header[mjd_label] = float(Time(exposure[key], scale="utc").mjd)
        if exposure.get("exposure_time_s") is not None:
            header["EXPTIME"] = exposure["exposure_time_s"]
        header["TIMESYS"], header["TIMEUNIT"] = "UTC", "s"
        if exposure.get("filter"):
            header["FILTER"] = exposure["filter"]
        if exposure.get("detector"):
            header["DETECTOR"] = exposure["detector"]
        header.add_comment("Parent pixels: x_parent=x_cutout+X0; y_parent=y_cutout+Y0.")
        hdus = [fits.PrimaryHDU()]
        for key, label in (("data", "SCI"), ("err", "ERR"), ("dq", "DQ")):
            h = header.copy()
            unit = (
                "1" if key == "dq" else exposure.get("err_units" if key == "err" else "data_units")
            )
            if unit:
                h["BUNIT"] = unit
            h["ORIGDTYP"] = str(cutout.arrays[key].dtype)
            hdus.append(fits.ImageHDU(_fits_array(cutout.arrays[key]), header=h, name=label))
        # Additional aligned arrays can have leading dimensions; preserve names in metadata.
        ancillary_names = {}
        for index, (key, value) in enumerate(cutout.ancillary_arrays.items()):
            label = f"AUX{index:04d}"
            hdus.append(fits.ImageHDU(_fits_array(value), name=label))
            ancillary_names[key] = {"extension": label, "dtype": str(value.dtype)}
        embedded = BytesIO()
        asdf.AsdfFile(
            {
                **metadata,
                "ancillary_extensions": ancillary_names,
                "plane_dtypes": {key: str(value.dtype) for key, value in cutout.arrays.items()},
            }
        ).write_to(embedded)
        raw = np.frombuffer(embedded.getvalue(), dtype=np.uint8)
        hdus.append(
            fits.BinTableHDU.from_columns(
                [fits.Column(name="ASDF_METADATA", format=f"{len(raw)}B", array=[raw])],
                name="ASDFMETA",
            )
        )
        path = folder / "cutout.fits"
        fits.HDUList(hdus).writeto(path, checksum=True)
        files.append(path)
    for path in files:
        saved = read_cutout(path)
        for key, value in cutout.arrays.items():
            np.testing.assert_array_equal(value, saved.arrays[key])
        for key, value in cutout.ancillary_arrays.items():
            np.testing.assert_array_equal(value, saved.ancillary_arrays[key])
        ny, nx = cutout.arrays["data"].shape
        xx, yy = np.meshgrid(np.linspace(0, nx - 1, 3), np.linspace(0, ny - 1, 3))
        np.testing.assert_allclose(
            pixel_to_world(saved.wcs, xx, yy),
            pixel_to_world(cutout.wcs, xx, yy),
            atol=1e-10,
            rtol=0,
        )
    return files


def read_cutout(path: str | Path) -> Cutout:
    """Read this package's ASDF or FITS derived-cutout format."""
    path = Path(path)
    if path.suffix == ".asdf":
        with asdf.open(path, lazy_load=False, memmap=False) as af:
            tree = deepcopy(dict(af.tree))
        arrays = {key: tree[key] for key in ("data", "err", "dq")}
        ancillary = tree.get("ancillary_arrays", {})
    else:
        with fits.open(path, memmap=False, checksum=True) as hdul:
            raw = hdul["ASDFMETA"].data["ASDF_METADATA"][0].tobytes()
            with asdf.open(BytesIO(raw), lazy_load=False, memmap=False) as af:
                tree = deepcopy(dict(af.tree))
            arrays = {
                key: hdul[name].data.astype(tree["plane_dtypes"][key])
                for key, name in (("data", "SCI"), ("err", "ERR"), ("dq", "DQ"))
            }
            ancillary = {
                key: hdul[value["extension"]].data.astype(value["dtype"])
                for key, value in tree.get("ancillary_extensions", {}).items()
            }
    if tree.get("schema") != SCHEMA:
        raise ValueError("Unrecognized derived cutout schema")
    return Cutout(
        arrays,
        tree["mapping"],
        tree["wcs"],
        tree["parent_wcs"],
        tree["parent_metadata"],
        tree["provenance"],
        ancillary,
    )
