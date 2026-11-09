# Scientific conventions and limits

Gladius copies a square region from an input detector image. Throughout these
docs, **parent image** means that original input image, and **cutout** means the
smaller image Gladius creates. This page explains how pixels are chosen, how
coordinates and metadata are carried over, and which checks Gladius performs.
The [header and metadata reference](headers.md) describes the saved fields.

## What happens to the pixels?

Each cutout contains three matching two-dimensional arrays:

| Array | Meaning | What Gladius copies |
| --- | --- | --- |
| `SCI` (`data` in ASDF) | The science image: the recorded value of each pixel. | The input pixel values, with their existing units. |
| `ERR` (`err`) | The uncertainty reported for each science pixel. | The input uncertainties. Gladius does not recalculate them. |
| `DQ` (`dq`) | Data-quality flags identifying conditions such as saturation. | The input integer flags, including combinations of flags. |

For individual cutouts, Gladius copies existing pixels without rotating,
interpolating, smoothing, or changing their flux units. It requires all three
arrays to be present, with the same height and width. Science and uncertainty
arrays must store floating-point values; quality flags must be nonnegative
integers.

When a requested square extends beyond the detector, the default behaviour is to
keep the requested size and fill the part outside the image. This filling is
called **padding**. Science and uncertainty padding contain `NaN` (a marker for
an unavailable numeric value); quality padding has `DO_NOT_USE` set (value 1).
Existing detector flags, including `SATURATED` (value 2), remain unchanged.
You can instead reject edge-crossing requests with `extraction.edge: strict`.
A target whose position is not on the detector image is skipped and recorded as `target_off_detector`; it is never padded into a cutout.

Other arrays that share the science image's height and width are cropped in the
same place. Their floating-point padding is `NaN`; integer padding is zero,
except arrays named `dq` or `pixeldq`, which receive `DO_NOT_USE`. A zero in an
extra array therefore does not establish that a detector pixel existed there.
Use the cutout's valid-pixel bounds and quality flags to identify actual coverage.

## Which pixels are included?

The requested **position** is the target's `(x, y)` location in the parent image,
either supplied directly or [calculated from RA/Dec](#from-radec-to-detector-pixels)
using the image's coordinate model. `x` counts columns and `y` counts rows. Pixel centres start at `(0, 0)`.
A NumPy array uses the opposite written order: `data[y, x]`.

The requested **size** is `extraction.size`: the number of pixels along each
side. A size of 150 produces 150 rows and 150 columns. A fractional target
position is allowed, but the copied pixels keep their original centres.
Gladius does not shift the image to put the target exactly at its geometric centre.

For example, with target column `x = 10.8`:

| Requested size | First parent column copied | Last parent column copied | Target x in the cutout |
| --- | --- | --- | --- |
| 5 pixels | 8 | 12 | 2.8 |
| 4 pixels | 9 | 12 | 1.8 |

The same rule applies to rows. This is the pixel-selection convention inherited
from the commissioning helper; it determines the choice of central pixels for
even sizes as well as how fractional positions are handled.

<details>
<summary>Exact pixel-selection rule and array bounds</summary>

On each axis, the first requested parent pixel is:

```text
start = floor(position) - (size - 1) // 2
```

`position` is that axis's target coordinate in parent pixels. `size` is the square
side length. `floor` rounds down to an integer; `// 2` divides by two and discards
the remainder. For `position = 10.8` and `size = 4`, this gives `10 - 1 = 9`.

Saved bounds use Python's slice convention: include the start and exclude the
stop. For example, columns `[8, 13)` contain columns 8, 9, 10, 11 and 12.
The NumPy slice `data[20:25, 8:13]` selects rows 20–24 and columns 8–12.

</details>

## From RA/Dec to detector pixels

The image's WCS describes which sky position corresponds to a detector pixel.
To place a target supplied as RA/Dec, Gladius asks that model to work backwards:
**which pixel position maps to these sky coordinates?** This is called the
inverse coordinate transformation. The result is a possibly fractional `(x, y)`
position, which then goes through the pixel-selection rule above.

This calculation can be nontrivial. Sky projection and instrument distortion
make the relationship vary across the detector. The library may need to start
with an approximate pixel position and repeatedly improve it until the model
maps back sufficiently close to the requested sky position.

Gladius uses the chosen image WCS, including a separately supplied correction
when `astrometry.mode: corrected` is selected:

- **FITS WCS:** it calls Astropy's `wcs.all_world2pix(ra, dec, 0)`. This uses the
  model's supported distortion corrections and numerical inversion. The final
  `0` requests zero-based pixel coordinates, matching Gladius's `(x, y)` inputs.
- **GWCS:** it calls `wcs.invert(ra, dec, with_bounding_box=False)`. GWCS uses a
  defined inverse model when one is available, or attempts a numerical solution
  otherwise. `with_bounding_box=False` allows coordinates outside the model's
  declared pixel range to be returned instead of masking them solely for being
  outside that range. A numerical solution outside the image is not guaranteed.

Gladius keeps the library's default inversion settings for these calls. Its
separate `roundtrip_tolerance_pixels` setting controls the subsequent numerical
validation check; it is not a setting for the inverse solver itself.

If the library raises an exception or returns a nonfinite coordinate, Gladius
records an error. GWCS can also return its best available finite estimate without
raising when its default numerical solver has difficulty converging. The
subsequent validation samples a grid across the image; it does not independently
certify every target conversion. A finite result outside the detector follows the
configured edge/no-overlap policy. The calculation uses only the coordinate
model: it does not inspect pixel brightness to find or recenter a star.

The library references describe the solver details:
[Astropy `all_world2pix`](https://docs.astropy.org/en/stable/api/astropy.wcs.WCS.html#astropy.wcs.WCS.all_world2pix)
and [GWCS `invert`](https://gwcs.readthedocs.io/en/latest/gwcs/generated/gwcs.wcs.WCS.html#gwcs.wcs.WCS.invert).

## How does a cutout position map back to the detector?

The fields `x0` and `y0` give the parent-image position corresponding to cutout
pixel `(0, 0)`. Add them to a cutout coordinate to recover the parent coordinate:

```text
parent_x = cutout_x + x0
parent_y = cutout_y + y0
```

They refer to the full requested square, including any padding. The metadata
uses “virtual” for this full region, including the part outside the detector.
For a 5-pixel cutout centred at `x = 1.2`, `x0` is −1:

| Cutout column | Corresponding parent column | Contents |
| --- | --- | --- |
| 0 | −1 | Padding: outside the input image. |
| 1 | 0 | First detector column. |
| 2 | 1 | Second detector column. |
| 3 | 2 | Third detector column. |
| 4 | 3 | Fourth detector column. |

The negative offset records where the requested square starts; it is not a
negative index used to read the NumPy array. Gladius copies only the part that
actually overlaps the input image.

## What happens to sky coordinates?

A **world coordinate system (WCS)** is the image's model for converting pixel
positions to sky coordinates such as RA and Dec. Gladius copies this model and
adjusts it for the cutout's `x0` and `y0` offsets. A copied detector pixel should
therefore have the same sky coordinates in the parent and the cutout.

That adjustment includes padding. In the example above, cutout column 1 must map
to detector column 0. Using the first available detector column as the cutout's
start would put its sky coordinates one pixel out of place.

The model may also return a sky position for a padded pixel. That is a calculation
outside the input image: it does **not** mean the detector observed that position.
For GWCS models, the saved model's image size and allowed pixel range describe
the whole cutout, including padding; the valid-pixel bounds separately identify
which pixels came from the detector.

### Supported coordinate models

Roman ASDF images store a **GWCS** (Generalized World Coordinate System),
which represents the pixel-to-sky calculation as a sequence of models. Gladius
reads that model directly. FITS cutout output carries a TAN-SIP approximation of it.

**Distortion corrections** account for departures from an idealised mapping
between the detector and sky. One FITS convention, **SIP** (Simple Imaging
Polynomial), stores polynomial coefficients in the header. Gladius reads FITS
coordinate information with Astropy’s `astropy.wcs.WCS`, including supported
SIP corrections.

Some FITS WCS models instead use additional lookup tables. Gladius currently
rejects these table-based models when creating a cutout: its FITS coordinate
adjustment handles reference pixels and SIP coefficients but does not update
those tables. The input file can be valid; this is a Gladius support limitation.
The error asks for a compatible GWCS model, which must be supplied separately.
See [Astropy's WCS documentation](https://docs.astropy.org/en/stable/wcs/index.html)
and [SIP reference](https://docs.astropy.org/en/stable/api/astropy.wcs.Sip.html)
for the underlying formats.

### Original, corrected and checked coordinates

If you select a separately supplied corrected WCS, Gladius uses it to locate the
target and calculate the cutout's sky coordinates. The original image's WCS is
still saved as `parent_wcs`. The correction's WCS and identifying information are
saved under `provenance.correction`, and `wcs` is the chosen model adjusted to the
cutout. Gladius reads existing corrections; it does not fit them.

Numerical validation checks that pixel-to-sky and sky-to-pixel calculations return
to the same pixels within the configured tolerance. A model can pass that check
and still assign the wrong sky positions. It is not a comparison with reference
stars or a measurement of absolute astrometric accuracy.

## Where do exposure times come from?

They come from the **input file's metadata**, not from the cutout dimensions or
the time Gladius runs. For Roman ASDF files, Gladius reads the exposure start,
end and duration from `roman.meta.exposure`. The [source-field table](headers.md#parent-fields-used-by-gladius)
lists the supported names and fallback rules.

Gladius preserves the original metadata and writes a UTC timing summary for the
cutout. If both start and end are supplied, it calculates their halfway point.
For example, reported times 12:00:00 and 12:01:00 give midpoint 12:00:30.
The exposure duration is copied from the input's duration field; Gladius does
not assume it equals the elapsed 60 seconds. Missing start/end information leaves
the corresponding summary values, including an unavailable midpoint, unset.

## Does the target position identify or measure a star?

No source fitting or identification is performed. The cutout is placed using the
coordinates you supplied and the chosen WCS. Gladius does not measure a star's
centre from the pixels or check that a catalogue object is visible there.

It also does not update target coordinates for motion across the sky (**proper
motion**) or the apparent positional shift caused by the observer's changing
location (**parallax**). Supply coordinates appropriate for the image's epoch
when those effects matter.

## What does the optional quality screen measure?

The screen looks for elongation in the image structure near the cutout centre.
It compares a central square of pixels with shifted copies of itself; this
comparison is **autocorrelation**. It measures the long-to-short axis ratio of
the resulting pattern. A value near 1 means a roughly round pattern; larger
values indicate a more elongated pattern. This is not a fitted stellar shape.

`quality.tile_size` sets the central square's side length in pixels.
`quality.radius` limits the pixel shifts included in the shape measurement.
The screen ignores nonfinite, `DO_NOT_USE` and saturated pixels. It subtracts
the valid-pixel mean and gradually reduces the square's edges to zero before the
comparison, so sharp crop boundaries have less influence.

It is disabled until you set `quality.autocorrelation_limit`. A measured ratio
at or above that limit is flagged; insufficient usable pixels or signal can
also produce a flag. Native cutouts are still saved. Flagged cutouts are excluded
from display stacks when `quality.exclude_from_stacks` is enabled.

The method and threshold need testing on representative images before scientific
use. Gladius implements its own screen; its scores have not been shown to match
the commissioning classifier's scores.

## Can I use a display stack for measurements?

**No. Use the individual cutouts for scientific measurements; display stacks
are for visual inspection.**

A display stack aligns cutouts onto a common sky grid and takes a median of the
available values at each output pixel. Alignment requires estimating values
between input pixels (interpolation), so stack pixels differ from the copied
pixels in individual cutouts.

Stacks are intended for inspection. Gladius does not match the point-spread
functions (the shapes produced by unresolved sources), bring exposures onto a
common photometric calibration, or propagate uncertainties through stacking.
Use the individual cutouts for flux or position measurements, and assess the
input calibration and quality flags for your analysis. Keep the stack's input
list and coverage image when sharing a preview; they record which exposures
contributed and how many values were available at each pixel.
