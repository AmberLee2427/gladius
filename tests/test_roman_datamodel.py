"""Use real Roman schema tags when the optional mission dependency is available."""

import numpy as np
import pytest
from astropy.io import fits
from astropy.time import Time

from gladius_roman.config import Extraction, Target
from gladius_roman.core import make_cutout
from gladius_roman.io import read_cutout, read_exposure, write_cutout


def test_tagged_roman_image_and_float16_uncertainty(exposure, tmp_path):
    pytest.importorskip("roman_datamodels")
    from roman_datamodels.datamodels import ImageModel

    if not hasattr(ImageModel, "create_fake_data"):
        pytest.skip("Installed Roman release predates the fake-data factory")
    model = ImageModel.create_fake_data(shape=(32, 32))
    model.meta.wcs = exposure.wcs
    model.meta.exposure.start_time = Time("2026-01-01T00:00:00")
    model.meta.exposure.end_time = Time("2026-01-01T00:01:00")
    model.meta.exposure.exposure_time = 55.0
    model.data[:] = np.arange(1024).reshape(32, 32)
    model.err[:] = np.float16(0.125)
    model.dq[:] = 0
    model.dq[0, 0] = 2 | 1024
    path = tmp_path / "tagged_cal.asdf"
    model.save(path)
    parent = read_exposure(path)
    assert parent.summary["filter"] == "F062"
    assert parent.arrays["err"].dtype == np.float16
    cutout = make_cutout(
        parent.arrays,
        parent.wcs,
        Target(id="e", x=1.2, y=1.7),
        extraction=Extraction(size=10),
        parent_metadata=parent.parent_metadata,
        ancillary_arrays=parent.ancillary_arrays,
        provenance={"exposure": parent.summary},
    )
    write_cutout(cutout, tmp_path / "derived")
    saved = read_cutout(tmp_path / "derived/cutout.fits")
    assert saved.arrays["err"].dtype == np.float16
    np.testing.assert_array_equal(saved.arrays["err"], cutout.arrays["err"])
    assert saved.arrays["dq"][3, 3] == 1026
    with fits.open(tmp_path / "derived/cutout.fits") as hdul:
        assert hdul["ERR"].data.dtype.itemsize == 4
        assert hdul["ERR"].header["ORIGDTYP"] == "float16"
