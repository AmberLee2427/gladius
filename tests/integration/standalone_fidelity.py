"""Independent checks of serialized standalone cutouts against their raw parent."""

import importlib.util
import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import asdf
import numpy as np
import yaml
from astropy.coordinates import SkyCoord
from astropy.time import Time

SCRIPT = Path(__file__).resolve().parents[2] / "standalone" / "roman_cutouts.py"


def compare_metadata(original, saved, shape):
    """Walk original metadata, checking array descriptors separately from pixels."""
    if isinstance(original, Mapping):
        assert set(original) == set(saved)
        for key in original:
            compare_metadata(original[key], saved[key], shape)
    elif isinstance(original, (list, tuple)):
        assert len(original) == len(saved)
        for left, right in zip(original, saved, strict=True):
            compare_metadata(left, right, shape)
    elif hasattr(original, "shape") and hasattr(original, "dtype"):
        if original.ndim >= 2 and original.shape[-2:] == shape:
            assert saved["parent_shape"] == list(original.shape)
            assert saved["parent_dtype"] == str(original.dtype)
        else:
            np.testing.assert_array_equal(original, saved, strict=True)
    elif isinstance(original, Time):
        assert np.all(original == saved)
    elif callable(original) and hasattr(original, "input_frame"):
        # The parent WCS is checked numerically below, including its serialized copy.
        assert type(original) is type(saved)
    else:
        assert type(original) is type(saved)
        if isinstance(original, float) and np.isnan(original):
            assert np.isnan(saved)
        else:
            assert original == saved


def check_standalone_fidelity(parent, work):
    """Exercise the actual CLI and reopen its outputs before any comparisons."""
    spec = importlib.util.spec_from_file_location("standalone_fidelity_script", SCRIPT)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    with asdf.open(parent, memmap=False) as af:
        node = af.tree.get("roman", af.tree)
        ny, nx = node["data"].shape
        wcs = node["meta"]["wcs"]
        ra, dec = script.pixel_to_world(wcs, (nx - 1) / 2, (ny - 1) / 2)
        targets = [
            {"id": "center", "ra": float(ra), "dec": float(dec)},
            {"id": "corner", "x": 0, "y": 0},
        ]
        worst_separation = 0.0
        for size in (50, 51):
            config = work / f"fidelity-{size}.yaml"
            output = work / f"fidelity-{size}"
            config.write_text(
                yaml.safe_dump(
                    {
                        "inputs": {"directory": str(parent.parent), "pattern": parent.name},
                        "targets": targets,
                        "size": size,
                        "output": str(output),
                    }
                )
            )
            # Capture failures without copying potentially restricted metadata into CI logs.
            result = subprocess.run([sys.executable, str(SCRIPT), str(config)], capture_output=True)
            assert result.returncode == 0, "Standalone CLI failed; inspect locally with this parent"
            records = json.loads((output / "manifest.json").read_text())["results"]
            assert len(records) == 2 and all(r["status"] == "ok" for r in records)
            for record in records:
                with asdf.open(output / record["output"], memmap=False) as cutout:
                    tree = cutout.tree
                    # Derive expected bounds from the requested position, independently of mapping.
                    x, y = (
                        (0, 0)
                        if record["target"] == "corner"
                        else script.world_to_pixel(wcs, float(ra), float(dec))
                    )
                    x0 = int(np.floor(x + 1e-6)) - (size - 1) // 2
                    y0 = int(np.floor(y + 1e-6)) - (size - 1) // 2
                    assert (tree["mapping"]["x0"], tree["mapping"]["y0"]) == (x0, y0)
                    sx, sy = max(0, x0), max(0, y0)
                    ex, ey = min(nx, x0 + size), min(ny, y0 + size)
                    dx, dy = sx - x0, sy - y0
                    for key in ("data", "err", "dq"):
                        expected = np.full(
                            (size, size), 1 if key == "dq" else np.nan, dtype=node[key].dtype
                        )
                        expected[dy : dy + ey - sy, dx : dx + ex - sx] = node[key][sy:ey, sx:ex]
                        # Exact values and dtype: no rounding tolerance for copied pixels.
                        np.testing.assert_array_equal(tree[key], expected, strict=True)

                    yy, xx = np.mgrid[dy : dy + ey - sy, dx : dx + ex - sx]
                    reference = SkyCoord(*script.pixel_to_world(wcs, xx + x0, yy + y0), unit="deg")
                    translated = SkyCoord(*script.pixel_to_world(tree["wcs"], xx, yy), unit="deg")
                    separation = reference.separation(translated).arcsec
                    assert np.isfinite(separation).all()
                    assert np.max(separation) < 1e-7
                    worst_separation = max(worst_separation, float(np.max(separation)))
                    back = script.world_to_pixel(tree["wcs"], reference.ra.deg, reference.dec.deg)
                    assert np.max(np.hypot(back[0] - xx, back[1] - yy)) < 0.001
                    compare_metadata(af.tree, tree["parent_metadata"], (ny, nx))
                    saved_parent = SkyCoord(
                        *script.pixel_to_world(tree["parent_wcs"], xx + x0, yy + y0), unit="deg"
                    )
                    assert np.max(reference.separation(saved_parent).arcsec) < 1e-7
                    assert tree["resampled"] is False
    return {
        "standalone_pixel_fidelity": "exact SCI/ERR/DQ, including padding",
        "standalone_wcs_max_separation_arcsec": worst_separation,
        "standalone_metadata": "recursive parent-tree comparison passed",
        "standalone_cases": "center and padded corner; 50 and 51 pixels",
    }
