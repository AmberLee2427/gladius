"""Render plain PNG previews from the deterministic synthetic demo.

Requires the notebook extra for Matplotlib. Science files live in a temporary
folder; only documentation previews are written to the output directory.
"""

import argparse
import json
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path


def build_images(output: Path):
    import asdf
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from astropy.io import fits
    from astropy.visualization import AsinhStretch, ImageNormalize

    from gladius_roman import load_config, run
    from gladius_roman.demo import create_demo
    from gladius_roman.io import read_cutout

    output.mkdir(parents=True, exist_ok=True)
    written = []
    with tempfile.TemporaryDirectory(prefix="gladius-docs-") as temporary:
        config_path = create_demo(Path(temporary) / "demo")
        manifest_path = run(load_config(config_path), progress=lambda _: None)
        manifest = json.loads(manifest_path.read_text())
        assert manifest["status"] == "complete"
        directory = manifest_path.parent
        entries = sorted(manifest["entries"].values(), key=lambda e: e["source"])
        assert len(entries) == 2
        images = {}
        for index, entry in enumerate(entries, start=1):
            with asdf.open(entry["source"]) as parent:
                images[f"demo-parent-{index}"] = np.array(parent["roman"]["data"])
            cutout = read_cutout(directory / next(p for p in entry["files"] if p.endswith(".asdf")))
            images[f"demo-cutout-{index}"] = cutout.arrays["data"]
            print(f"Parent {index} cutout bounds: {cutout.mapping['parent_virtual_bounds_xyxy']}")
        products = json.loads((directory / "stack-manifest.json").read_text())["products"]
        assert len(products) == 1
        product = products[0]
        assert len(product["inputs"]) == 2 and product["display_only"]
        with fits.open(directory / product["path"]) as hdus:
            images["demo-stack"] = hdus[0].data.copy()
        animations = json.loads((directory / "stack-manifest.json").read_text())["animations"]
        assert len(animations) == 1 and len(animations[0]["frames"]) == 2
        animation_path = output / "demo-animation.gif"
        shutil.copyfile(directory / animations[0]["path"], animation_path)
        written.append(animation_path)
        values = np.concatenate([images[f"demo-parent-{i}"].ravel() for i in (1, 2)])
        norm = ImageNormalize(
            vmin=np.percentile(values, 1),
            vmax=np.percentile(values, 99.95),
            stretch=AsinhStretch(a=0.03),
            clip=True,
        )
        cmap = plt.get_cmap("gray").copy()
        cmap.set_bad("#22162e")
        for name, data in images.items():
            # One PNG pixel per science pixel; the docs scale these with nearest-
            # neighbour rendering. A shared stretch changes display brightness only.
            rgba = cmap(norm(np.ma.masked_invalid(data)))
            path = output / f"{name}.png"
            plt.imsave(path, rgba, origin="lower")
            written.append(path)
    written.append(build_colour_example(output))
    return written


def build_colour_example(output):
    """Make a small synthetic three-filter star field, with no mission data."""
    import asdf
    import numpy as np
    import yaml

    from gladius_roman import load_config, run
    from gladius_roman.demo import create_demo

    with tempfile.TemporaryDirectory(prefix="gladius-colour-docs-") as temporary:
        root = Path(temporary) / "demo"
        config_path = create_demo(root)
        yy, xx = np.indices((96, 96))
        rng = np.random.default_rng(137)
        for index in range(2):
            path = root / f"images/demo{index}_cal.asdf"
            with asdf.open(path, lazy_load=False, memmap=False) as af:
                original = deepcopy(dict(af.tree))
            for band, amplitudes in {
                "F213": [80, 100, 15, 70, 20, 50],
                "F184": [80, 30, 45, 60, 80, 20],
                "F062": [80, 10, 100, 20, 70, 50],
            }.items():
                tree = deepcopy(original)
                data = rng.normal(2, 1.5, xx.shape)
                for (x, y), amplitude in zip(
                    [(48, 48), (32, 38), (63, 60), (58, 30), (30, 63), (71, 44)],
                    amplitudes,
                    strict=True,
                ):
                    data += amplitude * np.exp(-((xx - x - index * 1.5) ** 2 + (yy - y) ** 2) / 5)
                tree["roman"]["data"] = data.astype("float32")
                tree["roman"]["err"][:] = 1.5
                tree["roman"]["var_poisson"] = np.maximum(data, 0).astype("float32")
                tree["roman"]["meta"]["instrument"]["optical_element"] = band
                asdf.AsdfFile(tree).write_to(root / f"images/{band}-{index}_cal.asdf")
            path.unlink()
        config = yaml.safe_load(config_path.read_text())
        config["stacks"] = {"rgb_enabled": True}
        config_path.write_text(yaml.safe_dump(config))
        manifest_path = run(load_config(config_path), progress=lambda _: None)
        manifest = json.loads((manifest_path.parent / "stack-manifest.json").read_text())
        assert len(manifest["composites"]) == 1 and not manifest["composite_skips"]
        destination = output / "demo-colour-composite.png"
        shutil.copyfile(manifest_path.parent / manifest["composites"][0]["path"], destination)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).resolve().parents[1] / "docs/_static/examples"
    )
    args = parser.parse_args()
    for filename in build_images(args.output):
        print(filename)
