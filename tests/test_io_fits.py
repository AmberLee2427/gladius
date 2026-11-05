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
