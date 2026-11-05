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
