# Headers and metadata

A FITS **header** is a sequence of keyword/value records attached to a file
section, called an HDU (Header/Data Unit). An ASDF file instead stores a nested
metadata tree. Gladius keeps the input file's metadata and writes separate
information describing the new cutout.

The tables below cover the fields Gladius defines and the input fields it reads
for its summaries. Parent files can also contain instrument, calibration and
observation keywords specific to their producer. Those original keywords are
retained, with their original names and comments; they are not a fixed list
created by Gladius.

## Where are the original headers?

| Input | Saved location | Contents |
| --- | --- | --- |
| FITS | `parent_metadata.fits_headers` | One record for every input HDU, including PRIMARY. |
| FITS header record: `index` | Each item in `fits_headers` | Original zero-based HDU number. |
| FITS header record: `name` | Each item in `fits_headers` | Original HDU name, such as `SCI`. |
| FITS header record: `cards` | Each item in `fits_headers` | Ordered `[keyword, value, comment]` records. Repeated keywords, including COMMENT/HISTORY, are retained. Undefined FITS values are represented by `None`. |
| FITS | `parent_metadata.non_spatial_arrays` | Extra arrays that do not share the SCI image's final two dimensions, keyed by `fits/<HDU index>/<HDU name>`. Their full contents are retained. |
| Roman ASDF | `parent_metadata.roman` | Original input tree under `roman`, including `meta`. Other top-level input keys are also retained under `parent_metadata`. |
| Generic ASDF without a `roman` root | `parent_metadata` | Original input tree at its existing paths. |

Arrays that share the SCI image's final two dimensions are cropped rather than
copied in full. Their original locations in the ASDF metadata tree become records
with these fields:

| Field | Meaning |
| --- | --- |
| `parent_array_path` | Original path in the input tree, such as `roman/data`. |
| `parent_shape` | Full input array dimensions, including any leading axes. |
| `parent_dtype` | Original array storage type, such as `float32`. |
| `content` | Explanation that the spatial pixel contents are stored as cutout arrays. |
| `parent_unit` | Original unit, when the input array provides one. |

The cropped primary arrays are `data`, `err` and `dq`; other cropped arrays are
in `ancillary_arrays`. Keeping these descriptions does not retain a second full
detector image in each cutout. Use `storage.retain_full_images` to retain full
input images separately.

For example, an input Roman footprint at `roman.meta.wcsinfo.s_region` stays at
`parent_metadata.roman.meta.wcsinfo.s_region`. It still describes the original
image. The cutout's own footprint is `cutout_metadata.s_region`.

## Parent fields used by Gladius

These fields supply the cutout's exposure summary. For Roman ASDF inputs, the
paths below are relative to `roman.meta`. With a generic ASDF root, they are
relative to `meta`.

For FITS, Gladius starts with PRIMARY header values and then applies SCI header
values, so SCI wins for repeated keywords. ERR units are read from ERR's own
header. The complete original headers remain saved regardless of which values
supply the summary.

| Meaning | ASDF source | FITS source | Cutout summary field and treatment |
| --- | --- | --- | --- |
| Detector | `instrument.detector`, falling back to `detector` | `DETECTOR` | `detector`; stored as text. |
| Filter | `instrument.optical_element`, falling back to `filter` | `FILTER` | `filter`; converted to uppercase. |
| SCI units | `bunit_data`, falling back to `bunit`; the SCI array's attached unit is used if these are absent | `BUNIT` | `data_units`; absent units remain unset. |
| ERR units | `bunit_err`, otherwise the SCI metadata unit; the ERR array's attached unit is used if no metadata unit is available | ERR `BUNIT`, otherwise SCI units | `err_units`. |
| Start time | `exposure.start_time`, falling back to `exposure.observation_start_utc` | `DATE-BEG`, falling back to `DATE-OBS` | `start_utc`; converted to UTC. |
| End time | `exposure.end_time`, falling back to `exposure.observation_end_utc` | `DATE-END` | `end_utc`; converted to UTC. |
| Reported exposure duration | `exposure.exposure_time`, falling back to `exposure.exposure_time_s` | `EXPTIME` | `exposure_time_s`; seconds. A supplied unit is converted to seconds. The duration must be finite and nonnegative. |
| Input time scale | An Astropy `Time` object's own scale; plain values are interpreted as UTC | `TIMESYS`, defaulting to UTC | Output summary times use UTC. Original values stay in parent metadata. |
| Pixel-to-sky coordinate model | `meta.wcs`, falling back to root `wcs` | SCI WCS header keywords and associated FITS WCS information | Input model saved as `parent_wcs`; selected model adjusted for the cutout is `wcs`. |

A fallback is used when the preferred key is absent. Gladius does not infer end
time or exposure duration from other fields. End before start is an error.

## FITS cutout headers

The following Gladius-written keywords appear in each output `SCI`, `ERR` and
`DQ` header. A time, unit, detector or filter keyword is omitted when the
corresponding information is unavailable, as indicated below.

| Keyword | Meaning | Source or rule |
| --- | --- | --- |
| `X0` | Parent x coordinate corresponding to cutout column 0. | Requested cutout's start column, including padding; may be negative. |
| `Y0` | Parent y coordinate corresponding to cutout row 0. | Requested cutout's start row, including padding; may be negative. |
| `PIXORIG` | Pixel coordinate numbering starts at this value. | Always 0 for Gladius's saved pixel mapping. FITS WCS reference-pixel keywords retain the FITS convention described below. |
| `PADPIX` | Number of output pixels outside the input detector image. | Calculated from the requested square and its overlap with the input. |
| `RESAMPLE` | Whether values were estimated on a different pixel grid. | `False` for individual cutouts. |
| `ROTATED` | Whether Gladius rotated the pixels. | `False` for individual cutouts. |
| `PARENT` | Input file's basename. | `provenance.parent_filename`; `unknown` if not supplied by a Python caller. |
| `PARSHA` | SHA-256 fingerprint of the input file's contents. | `provenance.parent_sha256`; used to identify the precise input file. `unknown` if not supplied. |
| `DATE-BEG` | Exposure start as an ISO date/time in UTC. | `start_utc`; omitted when unavailable. |
| `DATE-OBS` | Exposure start, repeated for FITS readers using this keyword. | Same value as `DATE-BEG`; omitted when unavailable. |
| `DATE-END` | Exposure end as an ISO date/time in UTC. | `end_utc`; omitted when unavailable. |
| `DATE-AVG` | Halfway time between the reported start and end. | `midpoint_utc`; omitted unless both endpoints exist. |
| `MJD-BEG` | Same instant as `DATE-BEG`, expressed as Modified Julian Date in days. | Converted from the UTC start time. |
| `MJD-OBS` | Same instant as `DATE-OBS`, in Modified Julian Date. | Same value as `MJD-BEG`. |
| `MJD-END` | Same instant as `DATE-END`, in Modified Julian Date. | Converted from the UTC end time. |
| `MJD-AVG` | Same instant as `DATE-AVG`, in Modified Julian Date. | Converted from the UTC midpoint. |
| `EXPTIME` | Reported exposure duration in seconds. | Copied from the input duration field, not calculated from start/end. Omitted when unavailable. |
| `TIMESYS` | Time scale of the output header's dates. | `UTC`. |
| `TIMEUNIT` | Unit for time quantities expressed in seconds, including `EXPTIME`. | `s`. The `MJD-*` convention uses days. |
| `FILTER` | Exposure filter name. | Uppercase summary value; omitted when empty. |
| `DETECTOR` | Exposure detector name. | Summary value; omitted when empty. |
| `BUNIT` | Units of values in this particular extension. | SCI uses `data_units`; ERR uses `err_units`; omitted if unknown. DQ uses `1` for dimensionless flags. |
| `ORIGDTYP` | NumPy storage type before FITS conversion. | For example, `float16`. The package reader uses the embedded type record to restore arrays. |
| `WCSERR` | Largest measured pixel disagreement between the saved FITS WCS and the full coordinate model. | Measured on a 9 × 9 grid over the cutout. Export fails if it exceeds `astrometry.fits_tolerance_pixels`. This sampled check is not an absolute sky-position accuracy estimate. |
| `COMMENT` | Human-readable explanation of the pixel mapping. | `x_parent=x_cutout+X0; y_parent=y_cutout+Y0`. |

### Coordinate keywords

These are written by Astropy or GWCS according to the selected coordinate model.
The exact set varies with that model. Gladius adjusts the model to refer to the
cutout before writing these keywords.

| Keyword or family | Meaning |
| --- | --- |
| `WCSAXES` | Number of axes in the coordinate description. |
| `WCSNAME` | Name of the coordinate description or output coordinate frame. |
| `CTYPE1`, `CTYPE2` | Coordinate type and sky projection for each axis; for example `RA---TAN-SIP` and `DEC--TAN-SIP`. |
| `CUNIT1`, `CUNIT2` | Coordinate units, usually degrees. |
| `CRPIX1`, `CRPIX2` | Reference pixel for the sky projection. **These use FITS's one-based pixel convention**, so they are not zero-based target coordinates. |
| `CRVAL1`, `CRVAL2` | Sky coordinates at the projection's reference point. |
| `CDELT1`, `CDELT2` | Coordinate scale factors; interpreted together with any linear transformation matrix. |
| `PCi_j` or `CDi_j` | Linear transformation terms relating image axes to projection coordinates. Here `i` and `j` are axis numbers. |
| `LONPOLE`, `LATPOLE` | Orientation of the projection's native coordinate pole. |
| `RADESYS`, `EQUINOX` | Celestial reference system and reference equinox, when required by the model. |
| `MJDREF` | Reference time for a WCS time-coordinate description, in Modified Julian Date. A default value here is not an observation date or the cutout's exposure midpoint. |
| `A_ORDER`, `B_ORDER`, `A_i_j`, `B_i_j` | SIP forward-distortion polynomial orders and coefficients. `i`, `j` are the powers of the pixel offsets in each term. |
| `AP_ORDER`, `BP_ORDER`, `AP_i_j`, `BP_i_j` | Optional SIP inverse-polynomial orders and coefficients. |
| `SIPMXERR` | Maximum forward SIP approximation difference reported by the GWCS exporter, expressed as an equivalent pixel error. |
| `SIPIVERR` | Maximum inverse SIP approximation difference reported by the GWCS exporter, in pixels. |
| Other model-dependent WCS keywords | Additional coordinate-description values emitted by the model's FITS writer. Their definitions follow the [Astropy FITS WCS conventions](https://docs.astropy.org/en/stable/wcs/index.html). |

For GWCS input, the conventional FITS header is an approximation for ordinary
FITS readers. The complete model is also saved in `ASDFMETA`; Gladius's reader
uses that complete model. See [sky coordinates](science.md#what-happens-to-sky-coordinates)
for supported models and limitations.

### FITS file structure keywords

Astropy writes these to describe how the file is stored. They describe the
**output**, not the dimensions or checksums of the parent file.

| Keyword or family | Meaning |
| --- | --- |
| `SIMPLE` | Identifies a standard FITS primary header. |
| `BITPIX` | Numeric storage representation for an image or table data block. |
| `NAXIS`, `NAXISn` | Number of array axes and their lengths. An image's `NAXIS1` is width and `NAXIS2` is height. PRIMARY is empty in a cutout FITS file. |
| `EXTEND` | Indicates that extension HDUs may follow PRIMARY. |
| `XTENSION` | Extension type, such as an image or binary table. |
| `EXTNAME` | Extension name: `SCI`, `ERR`, `DQ`, `AUX0000`, etc., or `ASDFMETA`. |
| `PCOUNT`, `GCOUNT` | FITS data-layout parameters; Astropy fills them for the HDU type. |
| `BSCALE`, `BZERO` | Optional scale and offset translating stored numbers into array values, including FITS unsigned-integer handling. |
| `TFIELDS`, `TTYPEn`, `TFORMn` | Binary-table column count, names and storage formats. `ASDFMETA` has one byte-array column named `ASDF_METADATA`. |
| `CHECKSUM`, `DATASUM` | Integrity checks for each output HDU and its data, added by the writer. They are separate from the SHA-256 input fingerprint in `PARSHA`. |

Optional display stacks have their own PRIMARY image header. Their coordinate
keywords and `WCSERR` follow the same rules above, and their extra keywords are:

| Stack keyword | Meaning |
| --- | --- |
| `PREVIEW` | `True`: the image is intended for display. |
| `RESAMPLE` | `True`: inputs were interpolated onto a common grid. |
| `PSFMATCH` | `False`: point-spread functions were not matched. |
| `COMBINE` | `MEDIAN`: each output pixel is the median of eligible input values. |
| `NSTACK` | Number of selected input cutouts for this stack group. |
| `BUNIT` | Shared SCI unit, when known. |

A stack's `COVERAGE` extension counts how many input values contributed to each
pixel. The stack manifest lists input membership and exclusions.

## ASDF cutout fields and FITS embedded metadata

These fields are stored directly in a cutout ASDF file. A FITS cutout stores the
same metadata in the `ASDFMETA` extension; its science arrays live in the regular
image extensions. ASDF can also add its own library/version/history records.

| Top-level field | Meaning |
| --- | --- |
| `schema` | Gladius format identifier, currently `gladius/derived-1.0`. |
| `package_version` | Gladius version that wrote the file. |
| `data`, `err`, `dq` | Cropped SCI, uncertainty and quality arrays. |
| `ancillary_arrays` | Additional cropped arrays, named by their original input paths. |
| `mapping` | Pixel dimensions, offsets, copied bounds and padding information; see below. |
| `wcs` | Selected coordinate model adjusted to the cutout. |
| `parent_wcs` | Original input coordinate model, including when a corrected model was selected. |
| `parent_metadata` | Preserved input tree or FITS header records described above. |
| `cutout_metadata` | New dimensions, footprints and exposure summary describing this cutout. |
| `provenance` | Input identity and processing record, including target, configuration and quality results. |
| `ancillary_extensions` | FITS metadata only: maps each original ancillary-array path to its output FITS `extension` name and original `dtype`. |
| `plane_dtypes` | FITS metadata only: original storage types for `data`, `err` and `dq`. |

### Pixel mapping

All bounds are `[x_start, y_start, x_stop, y_stop]`, with starts included and
stops excluded. For example `[8, 20, 13, 25]` covers columns 8–12 and rows 20–24.
Coordinates in this table are zero-based.

| `mapping` field | Meaning |
| --- | --- |
| `parent_shape_yx` | Parent height and width, `[rows, columns]`. |
| `cutout_shape_yx` | Cutout height and width, `[size, size]`. |
| `x0` | Parent x coordinate corresponding to cutout column 0, including any padding. |
| `y0` | Parent y coordinate corresponding to cutout row 0, including any padding. |
| `pixel_origin` | `0`, the pixel numbering convention. |
| `axis_order` | Text stating that arrays use `[y, x]` and coordinate pairs use `(x, y)`. |
| `bounds_convention` | Text stating that starts are included and stops excluded. |
| `parent_virtual_bounds_xyxy` | Full requested square in parent coordinates; it can extend outside the image. “Virtual” here includes the part filled with padding. |
| `parent_valid_bounds_xyxy` | The part of that square actually copied from the parent, in parent coordinates. |
| `cutout_valid_bounds_xyxy` | Where the copied detector pixels lie within the output array, in cutout coordinates. |
| `prediction_on_detector` | Whether the requested target position itself lies within the parent image. This does not identify or measure a source. |
| `padding_pixels` | Number of output pixels filled because they lie outside the parent image. |
| `x_parent_equals` | Saved explanatory expression, `x_cutout + x0`. |
| `y_parent_equals` | Saved explanatory expression, `y_cutout + y0`. |

### Cutout metadata and timing

| `cutout_metadata` field | Meaning |
| --- | --- |
| `array_shape` | Output `[rows, columns]`. |
| `s_region` | Sky polygon around the copied detector portion, or `None` if no detector pixels were copied or finite corners cannot be calculated. |
| `virtual_s_region` | Sky polygon around the whole requested square, including padding; `None` if finite corners cannot be calculated. It is not proof of detector coverage. |
| `footprint_definition` | Text explaining how the polygons were constructed: join the four pixel-edge corners. Curved boundaries between corners are not traced. |
| `exposure` | Timing, units and instrument summary below; also saved in `provenance.exposure`. |

| `exposure` field | Meaning |
| --- | --- |
| `detector` | Detector label from the input, or empty text if unavailable. |
| `filter` | Uppercase filter label, or empty text if unavailable. |
| `data_units` | SCI unit text, or `None` if unavailable. |
| `err_units` | ERR unit text, or `None` if unavailable. |
| `start_utc` | Reported start converted to UTC, or `None`. |
| `end_utc` | Reported end converted to UTC, or `None`. |
| `midpoint_utc` | Halfway between reported start/end, or `None` if either is missing. |
| `exposure_time_s` | Reported exposure duration converted to seconds, or `None`. |
| `time_scale` | `UTC`, the summary time scale. |
| `midpoint_definition` | Text recording that midpoint means halfway between reported start/end. |

### Processing record

The following are written by the normal pipeline. A Python caller using
`make_cutout` directly can supply its own provenance; fields it does not supply
will not all be present.

| `provenance` field | Meaning |
| --- | --- |
| `parent_filename` | Input filename. |
| `parent_sha256` | SHA-256 fingerprint of the complete input file. |
| `source` | Source identifier used by the run, such as a local path or archive product URI. |
| `exposure` | Exposure summary from the input; fields listed above. |
| `astrometry_mode` | Selected WCS policy: `use`, `validate` or `corrected`. |
| `astrometry_validation` | Creation-time numerical-check record, or a marker directing you to the revision manifest for the current check. Fields listed below. |
| `correction` | `None`, or the separate corrected model's `path`, file fingerprint `sha256`, retained `parent_metadata`, and `applied_parent_wcs` before adjusting it to the cutout. |
| `configuration` | Fully resolved settings when this native cutout was created. Reused files keep these values; current revision settings are in its manifest. |
| `dependencies` | Versions of `numpy`, `astropy`, `asdf`, `gwcs`, `roman_datamodels`, `rad`, `asdf-astropy`, `scipy`, `pillow` and `astroquery`; unavailable optional packages have `None`. |
| `implementation_sha256` | Fingerprint of the package's Python implementation files, used in run identity. |
| `centering` | Text recording the pixel-selection formula explained in [Scientific conventions](science.md#which-pixels-are-included). |
| `ancillary_padding` | Text recording fill values for extra arrays. |
| `target` | Target record: `id`, `ra`, `dec`, `x`, `y` and `metadata`. Only the supplied coordinate pair has values; sky coordinates are ICRS degrees. Extra CSV columns and original manually entered coordinate-frame details are stored in `metadata`. |
| `predicted_parent_xy` | Requested position expressed as `(x, y)` in parent pixels. |
| `predicted_cutout_xy` | Same position expressed in cutout pixels. |
| `position_is_catalogue_prediction` | Always `True` in `make_cutout`: the position is supplied or coordinate-derived, not a source centre fitted from the pixels. The field is also used for direct pixel targets. |
| `resampled` | `False` for individual cutouts. |
| `rotated` | `False` for individual cutouts. |
| `quality` | Optional creation-time screen record in older files or caller-supplied products. New staged runs record current quality in the revision manifest, without rewriting native images. |
| `provenance_scope` | Explains that this file is a creation record; use the revision manifest for current settings, quality and numerical WCS validation. |

| `astrometry_validation` field | Meaning |
| --- | --- |
| `check` | `not_requested` in `use` mode; otherwise `finite_grid_and_numerical_inverse`. |
| `absolute_astrometry_validated` | `False`: Gladius did not compare sky coordinates against reference stars. |
| `max_error_pixels` | Largest return-to-start pixel error on the sampled grid; present when checked. |
| `sample_grid` | `[5, 5]`: number of sample points along each image axis; present when checked. |

| `quality` field | Meaning |
| --- | --- |
| `method` | Algorithm identifier, currently `gladius-acf-positive-moments-v1`. |
| `threshold` | Configured axis-ratio threshold, or `None` when the screen is disabled. |
| `tile_size` | Side length of the central test square, in pixels. |
| `radius` | Maximum pixel shift included in the autocorrelation shape calculation. |
| `status` | `provisional`: the screen is not scientifically calibrated. |
| `accepted` | Whether this screen passed. `True` also when the screen was disabled; inspect `reason`. |
| `reason` | `disabled`, `accepted`, `insufficient_tile`, `insufficient_signal`, `degenerate_acf`, or `autocorrelation_elongation`. |
| `axis_ratio` | Measured long/short autocorrelation axis ratio, or `None` when unavailable/disabled. |

## Inspect the original header records in Python

```python
from gladius.io import read_cutout

cutout = read_cutout("cutout.fits")  # Also accepts cutout.asdf.
for header in cutout.parent_metadata.get("fits_headers", []):
    print(header["index"], header["name"])
    for keyword, value, comment in header["cards"]:
        print(keyword, value, comment)
```

These are the input headers retained by Gladius. To inspect the new ordinary FITS
header, use `astropy.io.fits` and read the output `SCI`, `ERR` or `DQ` header.
