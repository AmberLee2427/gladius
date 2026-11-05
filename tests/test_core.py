from copy import deepcopy

import numpy as np
import pytest
from astropy.wcs import WCS, Sip

from gladius.config import Extraction, Target
from gladius.core import OffDetectorError, make_cutout, pixel_to_world, validate_wcs


@pytest.mark.parametrize(
    "size,x,y",
    [(10, 1.2, 1.7), (9, 35.2, 30.7), (10, 35.2, 30.7), (11, 94.2, 94.9)],
)
def test_native_values_padding_and_exact_wcs(exposure, size, x, y):
    exposure.arrays["dq"][0, 0] = 2 | 1024
    original = deepcopy(exposure.arrays)
    c = make_cutout(
        exposure.arrays,
        exposure.wcs,
        Target(id="e", x=x, y=y),
        extraction=Extraction(size=size),
    )
    m = c.mapping
    assert m["x0"] == int(np.floor(x)) - (size - 1) // 2
    assert m["y0"] == int(np.floor(y)) - (size - 1) // 2
    sx0, sy0, sx1, sy1 = m["parent_valid_bounds_xyxy"]
    dx0, dy0, dx1, dy1 = m["cutout_valid_bounds_xyxy"]
    valid = np.zeros((size, size), bool)
    valid[dy0:dy1, dx0:dx1] = True
    for key in original:
        if valid.any():
            np.testing.assert_array_equal(
                c.arrays[key][dy0:dy1, dx0:dx1], original[key][sy0:sy1, sx0:sx1]
            )
        np.testing.assert_array_equal(exposure.arrays[key], original[key])
    assert np.all(c.arrays["dq"][~valid] == 1)
    assert np.all(np.isnan(c.arrays["data"][~valid]))
    assert np.all(np.isnan(c.arrays["err"][~valid]))
    assert c.wcs.array_shape == (size, size)
    xx, yy = np.meshgrid(np.arange(size), np.arange(size))
    np.testing.assert_allclose(
        pixel_to_world(c.wcs, xx, yy),
        pixel_to_world(exposure.wcs, xx + m["x0"], yy + m["y0"]),
        atol=1e-12,
    )


def test_off_detector_and_strict_policies(exposure):
    with pytest.raises(OffDetectorError):
        make_cutout(
            exposure.arrays,
            exposure.wcs,
            Target(id="e", x=-900, y=-900),
            extraction=Extraction(size=10),
        )
    with pytest.raises(ValueError, match="boundary"):
        make_cutout(
            exposure.arrays,
            exposure.wcs,
            Target(id="e", x=1, y=1),
            extraction=Extraction(size=10, edge="strict"),
        )
    exposure.arrays["dq"] = np.zeros((4, 4), np.uint32)
    with pytest.raises(ValueError, match="identical shapes"):
        make_cutout(exposure.arrays, exposure.wcs, Target(id="e", x=-900, y=-900))


def test_fits_sip_translation(exposure):
    w = WCS(naxis=2)
    w.wcs.crpix = [48, 48]
    w.wcs.cdelt = [0.001, 0.001]
    w.wcs.crval = [270, -29]
    w.wcs.ctype = ["RA---TAN-SIP", "DEC--TAN-SIP"]
    a, b = np.zeros((3, 3)), np.zeros((3, 3))
    a[2, 0], b[0, 2] = 1e-5, -1e-5
    w.sip = Sip(a, b, None, None, w.wcs.crpix)
    w.array_shape = (96, 96)
    c = make_cutout(
        exposure.arrays, w, Target(id="e", x=1.2, y=1.7), extraction=Extraction(size=10)
    )
    np.testing.assert_allclose(
        pixel_to_world(c.wcs, [2, 5], [3, 8]),
        pixel_to_world(w, np.array([2, 5]) - 3, np.array([3, 8]) - 3),
        atol=1e-12,
    )
    assert not validate_wcs(c.wcs, (10, 10))["absolute_astrometry_validated"]


@pytest.mark.parametrize("x,y", [(-0.6, 50), (50, -0.6), (99.6, 50), (50, 99.6), (-3, 50)])
def test_target_outside_detector_is_rejected_even_if_square_overlaps(exposure, x, y):
    ny, nx = exposure.arrays["data"].shape
    x, y = (nx + (x - 99.5) if x > 99 else x), (ny + (y - 99.5) if y > 99 else y)
    with pytest.raises(OffDetectorError):
        make_cutout(
            exposure.arrays, exposure.wcs, Target(id="e", x=x, y=y), extraction=Extraction(size=40)
        )


def test_pixel_centre_survives_sky_round_trip(exposure):
    from gladius.core import geometry, world_to_pixel

    ra, dec = pixel_to_world(exposure.wcs, 20.0, 20.0)
    x, y = world_to_pixel(exposure.wcs, ra, dec)
    assert geometry(float(x), float(y), (100, 100), 5)["x0"] == 18
    assert geometry(19.9999999990, 20.0, (100, 100), 5)["x0"] == 18


def test_correction_for_another_exposure_is_rejected(exposure):
    from astropy.modeling.models import Shift

    from gladius.core import check_correction_matches_parent

    shape = exposure.arrays["data"].shape
    check_correction_matches_parent(exposure.wcs, shape, exposure.wcs, shape)
    with pytest.raises(ValueError, match="shape"):
        check_correction_matches_parent(exposure.wcs, (7, 7), exposure.wcs, shape)
    shifted = deepcopy(exposure.wcs)
    shifted.insert_transform(
        shifted.input_frame,
        Shift(5000) & Shift(0),
        after=True,
    )
    with pytest.raises(ValueError, match="centre"):
        check_correction_matches_parent(shifted, shape, exposure.wcs, shape)
