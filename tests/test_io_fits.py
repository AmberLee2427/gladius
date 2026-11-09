import numpy as np
import pytest
from astropy.io import fits


def test_summary_time_keeps_sub_millisecond_precision():
    from gladius.io import _summary

    out = _summary(
        {
            "exposure": {
                "start_time": "2027-01-01T00:00:00.123456",
                "end_time": "2027-01-01T00:01:00.123456",
            }
        }
    )
    assert out["start_utc"] == "2027-01-01T00:00:00.123456"


def test_non_roman_files_point_to_astrocut(tmp_path):
    from gladius.io import read_exposure

    path = tmp_path / "image.fits"
    fits.HDUList([fits.PrimaryHDU(np.zeros((4, 4)))]).writeto(path)
    with pytest.raises(ValueError, match="astrocut"):
        read_exposure(path)
    with pytest.raises(ValueError, match="astrocut"):
        read_exposure(tmp_path / "image.fits.gz")


def test_gladius_fits_cutout_is_not_accepted_as_parent(exposure, tmp_path):
    from gladius.config import Target
    from gladius.core import make_cutout
    from gladius.io import read_cutout, read_exposure, write_cutout

    cutout = make_cutout(exposure.arrays, exposure.wcs, Target(id="test", x=50, y=50))
    write_cutout(cutout, tmp_path, formats=("fits",))
    path = tmp_path / "cutout.fits"
    assert read_cutout(path).arrays["data"].shape == cutout.arrays["data"].shape
    with pytest.raises(ValueError, match="astrocut"):
        read_exposure(path)
