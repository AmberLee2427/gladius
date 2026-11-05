"""Input validation and astrometry edge cases in the extraction core."""

import numpy as np
import pytest
from astropy.wcs import WCS, DistortionLookupTable

from gladius.config import Extraction, Target
from gladius.core import extract_plane, geometry, make_cutout, translate_wcs, validate_wcs


def tan_wcs(shape=(96, 96)):
    w = WCS(naxis=2)
    w.wcs.crpix = [48, 48]
    w.wcs.cdelt = [0.001, 0.001]
    w.wcs.crval = [270, -29]
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.array_shape = shape
    return w


@pytest.mark.parametrize(
    ("x", "y", "size"),
    [(np.nan, 1.0, 5), (1.0, np.inf, 5), (1.0, 1.0, 0), (1.0, 1.0, -3), (1.0, 1.0, 4.0)],
)
def test_geometry_rejects_unusable_position_or_size(x, y, size):
    with pytest.raises(ValueError, match="Finite x/y and a positive integer size"):
        geometry(x, y, (10, 10), size)


@pytest.mark.parametrize("shape", [(10,), (0, 10), (3, 3, 3)])
def test_geometry_rejects_degenerate_parent_shapes(shape):
    with pytest.raises(ValueError, match="two nonempty dimensions"):
        geometry(1.0, 1.0, shape, 3)


def test_geometry_flags_off_detector_prediction():
    on = geometry(5.5, 5.5, (10, 10), 3)
    off = geometry(50.0, 5.0, (10, 10), 3)
    assert on["prediction_on_detector"] and on["padding_pixels"] == 0
    assert not off["prediction_on_detector"]
    assert off["padding_pixels"] == 9 and off["cutout_valid_bounds_xyxy"] == [0, 0, 0, 0]


def test_extract_plane_requires_parent_shape_agreement():
    mapping = geometry(2.0, 2.0, (6, 6), 3)
    with pytest.raises(ValueError, match="agree with parent SCI dimensions"):
        extract_plane(np.zeros((5, 6)), mapping)


@pytest.mark.parametrize("bad", [np.full((6, 6), -1, np.int32), np.zeros((6, 6), np.float32)])
def test_extract_plane_rejects_non_flag_dq(bad):
    mapping = geometry(2.0, 2.0, (6, 6), 3)
    with pytest.raises(ValueError, match="nonnegative integer flags"):
        extract_plane(bad, mapping, dq=True)


def test_extract_plane_pads_by_dtype_and_keeps_leading_dimensions():
    mapping = geometry(0.0, 0.0, (6, 6), 4)  # one row/column of padding on two sides
    ints = extract_plane(np.arange(36, dtype=np.int16).reshape(6, 6), mapping)
    assert ints.dtype == np.int16 and ints[0, 0] == 0 and ints[2, 2] == 7
    flags = extract_plane(np.ones((6, 6), bool), mapping)
    assert flags.dtype == bool and not flags[0].any() and flags[1:, 1:].all()
    cube = extract_plane(np.ones((2, 6, 6), np.float32), mapping)
    assert cube.shape == (2, 4, 4) and np.isnan(cube[:, 0]).all()
    dq = extract_plane(np.zeros((6, 6), np.uint32), mapping, dq=True)
    assert dq[0, 0] == 1  # DO_NOT_USE marks padded pixels


def test_extract_plane_rejects_unsupported_dtype():
    mapping = geometry(2.0, 2.0, (6, 6), 3)
    with pytest.raises(ValueError, match="Unsupported spatial array dtype"):
        extract_plane(np.full((6, 6), "x"), mapping)


def test_translate_plain_fits_wcs_without_sip_shifts_reference_pixel():
    parent = tan_wcs()
    mapping = geometry(20.2, 30.7, (96, 96), 10)
    moved = translate_wcs(parent, mapping)
    assert moved.sip is None and moved.array_shape == (10, 10)
    np.testing.assert_allclose(moved.wcs.crpix, parent.wcs.crpix - [mapping["x0"], mapping["y0"]])
    assert parent.wcs.crpix.tolist() == [48, 48]  # the parent is never mutated


def test_translate_rejects_lookup_table_distortion():
    parent = tan_wcs()
    parent.cpdis1 = DistortionLookupTable(np.zeros((4, 4), np.float32), (0, 0), (0, 0), (1, 1))
    with pytest.raises(ValueError, match="lookup-table distortions"):
        translate_wcs(parent, geometry(20.0, 30.0, (96, 96), 10))


class FakeGwcs:
    """Callable with the small surface validate_wcs uses for non-FITS astrometry."""

    def __init__(self, forward, inverse):
        self._forward, self._inverse = forward, inverse

    def __call__(self, x, y, with_bounding_box=True):
        return self._forward(np.asarray(x, float), np.asarray(y, float))

    def invert(self, ra, dec, with_bounding_box=True):
        return self._inverse(ra, dec)


def linear(x, y):
    return 270 + 0.001 * x, -29 + 0.001 * y


def unlinear(ra, dec):
    return (ra - 270) / 0.001, (dec + 29) / 0.001


def test_validate_wcs_accepts_consistent_astrometry_and_reports_scope():
    report = validate_wcs(FakeGwcs(linear, unlinear), (10, 10))
    assert report["max_error_pixels"] < 1e-6
    assert report["absolute_astrometry_validated"] is False
    assert report["sample_grid"] == [5, 5]


def test_validate_wcs_rejects_nonfinite_sky_positions():
    wcs = FakeGwcs(lambda x, y: (np.full_like(x, np.nan), np.full_like(y, np.nan)), unlinear)
    with pytest.raises(ValueError, match="not finite"):
        validate_wcs(wcs, (10, 10))


def test_validate_wcs_rejects_inconsistent_inverse():
    wcs = FakeGwcs(linear, lambda ra, dec: tuple(c + 1.0 for c in unlinear(ra, dec)))
    with pytest.raises(ValueError, match="round-trip error"):
        validate_wcs(wcs, (10, 10))


def test_validate_wcs_rejects_collapsed_pixel_scale():
    grid = np.meshgrid(np.linspace(0, 9, 5), np.linspace(0, 9, 5))
    wcs = FakeGwcs(lambda x, y: (np.full_like(x, 270.0), np.full_like(y, -29.0)), lambda *_: grid)
    with pytest.raises(ValueError, match="zero or invalid local pixel scale"):
        validate_wcs(wcs, (10, 10))


def planes(shape=(8, 8)):
    return {
        "data": np.ones(shape, np.float32),
        "err": np.ones(shape, np.float32),
        "dq": np.zeros(shape, np.uint32),
    }


def test_make_cutout_requires_exactly_science_error_and_quality_planes():
    arrays = planes()
    arrays["extra"] = np.zeros((8, 8), np.float32)
    with pytest.raises(ValueError, match="Exactly data, err and dq"):
        make_cutout(arrays, tan_wcs((8, 8)), Target(id="t", x=4, y=4))
    del arrays["extra"], arrays["err"]
    with pytest.raises(ValueError, match="Exactly data, err and dq"):
        make_cutout(arrays, tan_wcs((8, 8)), Target(id="t", x=4, y=4))


@pytest.mark.parametrize("plane", ["data", "err"])
def test_make_cutout_rejects_integer_science_planes(plane):
    arrays = planes()
    arrays[plane] = arrays[plane].astype(np.int32)
    with pytest.raises(ValueError, match="must be floating point"):
        make_cutout(arrays, tan_wcs((8, 8)), Target(id="t", x=4, y=4))


def test_make_cutout_converts_sky_targets_and_keeps_ancillary_planes():
    wcs = tan_wcs((8, 8))
    ra, dec = wcs.all_pix2world(3.0, 4.0, 0)
    cutout = make_cutout(
        planes(),
        wcs,
        Target(id="sky", ra=float(ra), dec=float(dec)),
        extraction=Extraction(size=4),
        ancillary_arrays={
            "area": np.ones((8, 8), np.float32),
            "group/PixelDQ": np.zeros((8, 8), np.uint32),
        },
    )
    np.testing.assert_allclose(cutout.provenance["predicted_parent_xy"], [3.0, 4.0], atol=1e-6)
    assert cutout.ancillary_arrays["area"].dtype == np.float32
    assert cutout.ancillary_arrays["group/PixelDQ"].dtype == np.uint32
    assert cutout.provenance["resampled"] is False and cutout.provenance["rotated"] is False


def test_validate_wcs_rejects_non_icrs_fits_wcs():
    from gladius.core import require_icrs_degrees

    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ["GLON-TAN", "GLAT-TAN"]
    with pytest.raises(ValueError, match="RA, Dec"):
        require_icrs_degrees(wcs)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    wcs.wcs.radesys = "FK5"
    with pytest.raises(ValueError, match="not ICRS"):
        require_icrs_degrees(wcs)
    wcs.wcs.radesys = "ICRS"
    require_icrs_degrees(wcs)
