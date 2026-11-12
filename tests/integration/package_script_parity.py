"""Compare script and package products without assuming identical file schemas."""

import importlib.util
import json
from pathlib import Path

import asdf
import numpy as np
import yaml

SCRIPT = Path(__file__).resolve().parents[2] / "standalone" / "roman_cutouts.py"


def check_package_script_parity(parent, tmp_path, size):
    """Run both entry points on one parent and compare their saved cutouts."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    from astropy.io import fits
    from standalone_fidelity import compare_metadata

    from gladius import RunConfig, run
    from gladius.core import pixel_to_world
    from gladius.io import read_cutout

    spec = importlib.util.spec_from_file_location("parity_standalone", SCRIPT)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    with asdf.open(parent) as source:
        node = source.tree.get("roman", source.tree)
        ny, nx = node["data"].shape
        ra, dec = pixel_to_world(node["meta"]["wcs"], (nx - 1) / 2, (ny - 1) / 2)

    # A sky target exercises the inverse WCS; corners exercise padding on both axes.
    targets = [
        {"id": "sky", "ra": float(ra), "dec": float(dec)},
        {"id": "lower", "x": 0.0, "y": 0.0},
        {"id": "upper", "x": float(nx - 1), "y": float(ny - 1)},
    ]
    images = parent.parent
    output = tmp_path / "script-products"
    config_path = tmp_path / "script.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "inputs": {"directory": str(images), "pattern": parent.name},
                "targets": targets,
                "size": size,
                "fits": True,
                "output": str(output),
            }
        )
    )
    assert script.main([str(config_path)]) == 0

    config = RunConfig(
        targets=targets,
        inputs={"mode": "directory", "directory": str(images), "pattern": parent.name},
        extraction={"size": size, "edge": "pad"},
        stacks={"enabled": False, "gif_enabled": False, "rgb_enabled": False},
        storage={
            "output_directory": str(tmp_path / "package-products"),
            "formats": ["asdf", "fits"],
        },
    ).resolved(tmp_path)
    manifest_path = run(config, progress=lambda _: None)
    manifest = json.loads(manifest_path.read_text())

    # Match by parent and target, independently of each writer's filename scheme.
    package = {}
    for entry in manifest["entries"].values():
        path = next(name for name in entry["files"] if name.endswith(".asdf"))
        cutout = read_cutout(manifest_path.parent / path)
        key = (Path(cutout.provenance["source"]).name, cutout.provenance["target"]["id"])
        package[key] = (cutout, entry)

    records = json.loads((output / "manifest.json").read_text())["results"]
    assert len(records) == len(package) == 3
    for record in records:
        assert record["status"] == "ok"
        cutout, entry = package.pop((record["parent"], record["target"]))
        with asdf.open(output / record["output"]) as saved:
            tree = saved.tree
            assert tree["mapping"] == cutout.mapping
            for name in ("data", "err", "dq"):
                np.testing.assert_array_equal(tree[name], cutout.arrays[name], strict=True)
            assert set(tree["ancillary_arrays"]) == set(cutout.ancillary_arrays)
            for name, array in cutout.ancillary_arrays.items():
                np.testing.assert_array_equal(tree["ancillary_arrays"][name], array, strict=True)

            # Both files preserve the same recursive parent metadata and exact WCS.
            compare_metadata(cutout.parent_metadata, tree["parent_metadata"], (ny, nx))
            yy, xx = np.indices((size, size))
            for name in ("wcs", "parent_wcs"):
                np.testing.assert_allclose(
                    script.pixel_to_world(tree[name], xx, yy),
                    pixel_to_world(getattr(cutout, name), xx, yy),
                    rtol=0,
                    atol=1e-10,
                )

        package_fits = next(name for name in entry["files"] if name.endswith(".fits"))
        with (
            fits.open((output / record["output"]).with_suffix(".fits")) as left,
            fits.open(manifest_path.parent / package_fits) as right,
        ):
            for name in ("SCI", "ERR", "DQ"):
                np.testing.assert_array_equal(left[name].data, right[name].data, strict=True)
    assert not package
