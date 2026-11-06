import numpy as np
import pytest
from astropy.io import fits

from gladius.io import _read_fits


def test_multiple_sci_extensions_are_rejected(tmp_path):
    path = tmp_path / "multi.fits"
    hdus = [fits.PrimaryHDU()]
    for ver in (1, 2):
        for name in ("SCI", "ERR", "DQ"):
            hdus.append(fits.ImageHDU(np.zeros((4, 4), "f4"), name=name, ver=ver))
    fits.HDUList(hdus).writeto(path)
    with pytest.raises(ValueError, match="several SCI"):
        _read_fits(path)


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


def test_split_date_and_time_obs_are_combined(tmp_path):
    from astropy.wcs import WCS

    from gladius.io import read_exposure

    path = tmp_path / "split.fits"
    primary = fits.PrimaryHDU()
    primary.header["DATE-OBS"] = "2026-01-01"
    primary.header["TIME-OBS"] = "12:34:56.123456"
    sci = fits.ImageHDU(np.zeros((4, 4), "f4"), name="SCI")
    sci.header.update(WCS(naxis=2).to_header())
    sci.header.update({"CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN", "CDELT1": 1e-5, "CDELT2": 1e-5})
    hdus = [primary, sci, fits.ImageHDU(np.zeros((4, 4), "f4"), name="ERR")]
    hdus.append(fits.ImageHDU(np.zeros((4, 4), "i4"), name="DQ"))
    fits.HDUList(hdus).writeto(path)
    assert read_exposure(path).summary["start_utc"] == "2026-01-01T12:34:56.123456"


def test_non_roman_files_point_to_astrocut(tmp_path):
    from gladius.io import read_exposure

    path = tmp_path / "image.fits"
    fits.HDUList([fits.PrimaryHDU(np.zeros((4, 4)))]).writeto(path)
    with pytest.raises(ValueError, match="astrocut"):
        read_exposure(path)
    with pytest.raises(ValueError, match="astrocut"):
        read_exposure(tmp_path / "image.fits.gz")
