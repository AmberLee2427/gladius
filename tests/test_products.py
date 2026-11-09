from copy import deepcopy

import asdf
import numpy as np
from astropy.io import fits

from gladius.config import Extraction, Target
from gladius.core import make_cutout, pixel_to_world
from gladius.io import read_cutout, write_cutout


def test_all_metadata_and_arrays_survive_in_both_formats(exposure, tmp_path):
    c = make_cutout(
        exposure.arrays,
        exposure.wcs,
        Target(id="edge", x=1.2, y=1.7),
        extraction=Extraction(size=10),
        parent_metadata=exposure.parent_metadata,
        ancillary_arrays=exposure.ancillary_arrays,
        provenance={"exposure": exposure.summary},
    )
    paths = write_cutout(c, tmp_path)
    for path in paths:
        saved = read_cutout(path)
        parent = saved.parent_metadata
        assert parent["roman"]["meta"]["wcsinfo"]["s_region"] == "original parent footprint"
        assert parent["roman"]["custom_scalar"] == "retain me"
        np.testing.assert_array_equal(parent["custom_top_level"]["reference"], np.arange(4))
        assert parent["roman"]["meta"]["exposure"]["start_time"].scale == "utc"
        np.testing.assert_array_equal(
            saved.ancillary_arrays["roman/var_poisson"], c.ancillary_arrays["roman/var_poisson"]
        )
        np.testing.assert_allclose(
            pixel_to_world(saved.wcs, 5.0, 5.0), pixel_to_world(exposure.wcs, 2.0, 2.0)
        )
    with asdf.open(tmp_path / "cutout.asdf") as af:
        assert (
            af.tree["cutout_metadata"]["s_region"] != af.tree["cutout_metadata"]["virtual_s_region"]
        )
        assert af.tree["parent_metadata"]["roman"]["data"]["parent_shape"] == [96, 96]
    with fits.open(tmp_path / "cutout.fits", checksum=True) as hdul:
        assert hdul["DQ"].header["BUNIT"] == "1"
        assert hdul["SCI"].header["EXPTIME"] == 55.0
        assert hdul["SCI"].header["DATE-AVG"] == "2026-01-01T00:00:30.000000"
        assert hdul["SCI"].header["X0"] == -3
        assert "ASDFMETA" in hdul
        assert all(h.verify_checksum() == 1 for h in hdul)


def test_original_parent_metadata_is_not_modified(exposure, tmp_path):
    before = deepcopy(exposure.parent_metadata)
    c = make_cutout(
        exposure.arrays,
        exposure.wcs,
        Target(id="e", x=40, y=40),
        parent_metadata=exposure.parent_metadata,
        extraction=Extraction(size=10),
    )
    write_cutout(c, tmp_path)
    assert (
        exposure.parent_metadata["roman"]["meta"]["wcsinfo"] == before["roman"]["meta"]["wcsinfo"]
    )


def test_nonspatial_quantity_metadata_retains_units(exposure, tmp_path):
    from astropy import units as u

    from gladius.io import _partition

    original = {"calibration_wavelengths": np.arange(4) * u.nm}
    parent_metadata = _partition(original, (96, 96), {})
    c = make_cutout(
        exposure.arrays,
        exposure.wcs,
        Target(id="e", x=10, y=10),
        extraction=Extraction(size=10),
        parent_metadata=parent_metadata,
    )
    write_cutout(c, tmp_path)
    for name in ("cutout.asdf", "cutout.fits"):
        saved = read_cutout(tmp_path / name)
        assert saved.parent_metadata["calibration_wavelengths"].unit == u.nm
