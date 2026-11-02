"""Offline synthetic and real MAST examples with saved, reusable configurations."""

import math
from pathlib import Path

import asdf
import numpy as np
import yaml
from astropy import units as u
from astropy.coordinates import ICRS
from astropy.modeling import models
from astropy.time import Time
from gwcs import WCS
from gwcs.coordinate_frames import CelestialFrame, Frame2D


def create_demo(directory: Path) -> Path:
    """Create two offset synthetic exposures, configuration and output location."""
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    config_path = directory / "demo.yaml"
    images = directory / "images"
    if config_path.exists() or images.exists():
        raise FileExistsError("Demo destination already contains demo.yaml or images")
    images.mkdir()
    yy, xx = np.indices((96, 96))
    rng = np.random.default_rng(42)
    noise_sigma = 2.0  # Visible independent Gaussian background noise, in DN/s.
    for index, dx in enumerate((0.0, 1.5)):
        transform = (
            (models.Shift(-48 - dx) & models.Shift(-48))
            | (models.Scale(0.11 / 3600) & models.Scale(0.11 / 3600))
            | models.Pix2Sky_TAN()
            | models.RotateNative2Celestial(270, -29, 180)
        )
        wcs = WCS(
            [
                (Frame2D(name="detector", unit=(u.pix, u.pix)), transform),
                (CelestialFrame(reference_frame=ICRS(), name="sky"), None),
            ]
        )
        wcs.bounding_box = ((-0.5, 95.5), (-0.5, 95.5))
        data = (
            rng.normal(0, noise_sigma, xx.shape)
            + 100 * np.exp(-((xx - 48 - dx) ** 2 + (yy - 48) ** 2) / 8)
        ).astype(np.float32)
        tree = {
            "roman": {
                "data": data,
                "err": np.full(xx.shape, noise_sigma, np.float32),
                "dq": np.zeros(xx.shape, np.uint32),
                "var_poisson": np.maximum(data, 0),
                "meta": {
                    "wcs": wcs,
                    "bunit_data": "DN/s",
                    "bunit_err": "DN/s",
                    "instrument": {"detector": "WFI01", "optical_element": "F146"},
                    "exposure": {
                        "start_time": Time(f"2026-01-0{index + 1}T00:00:00"),
                        "end_time": Time(f"2026-01-0{index + 1}T00:01:00"),
                        "exposure_time": 55.0,
                    },
                    "wcsinfo": {"s_region": "original parent footprint"},
                },
                "custom_scalar": "retain me",
            },
            "custom_top_level": {"reference": np.arange(4)},
        }
        asdf.AsdfFile(tree).write_to(images / f"demo{index}_cal.asdf")
    config = {
        "targets": [{"id": "demo-event", "ra": 270.0, "dec": -29.0}],
        "inputs": {"directory": "images"},
        "extraction": {"size": 64},
        "stacks": {"enabled": True, "gif_enabled": True},
        "storage": {"output_directory": "output"},
    }
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    return config_path


def create_mast_demo(directory: Path, *, max_parent_mib: float = 512) -> Path:
    """Discover one real parent and write demo YAML; do not download the image.

    The size check uses MAST's advertised bytes, not a streaming download cap.
    The demo explicitly uses a 0.01-pixel numerical WCS tolerance, matching the
    real-data notebook; the package default remains 0.001 pixels.
    """
    from .config import RunConfig
    from .inputs import mast_test_configuration

    if not math.isfinite(max_parent_mib) or max_parent_mib <= 0:
        raise ValueError("max_parent_mib must be finite and positive")
    directory = directory.expanduser().resolve()
    if directory.exists() and (not directory.is_dir() or any(directory.iterdir())):
        raise FileExistsError("MAST demo requires a new or empty destination directory")
    selection = mast_test_configuration(directory)
    size_mib = selection["download_bytes"] / 1024**2
    if size_mib > max_parent_mib:
        raise ValueError(
            f"Selected parent is advertised as {size_mib:.1f} MiB, exceeding "
            f"--max-parent-mib {max_parent_mib:g}. No image was downloaded."
        )
    settings = selection["configuration"]
    settings["extraction"]["size"] = 150
    settings["astrometry"]["roundtrip_tolerance_pixels"] = 0.01
    settings["storage"].update(output_directory=str(directory / "output"), formats=["asdf", "fits"])
    config = RunConfig.model_validate(settings).resolved(directory)
    directory.mkdir(parents=True, exist_ok=True)
    config_path = directory / "demo.yaml"
    with config_path.open("x") as stream:
        stream.write(yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False))
    return config_path
