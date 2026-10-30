# Scientific conventions and limits

The calibrated detector SCI grid is the parent grid. `(x, y)` coordinates are
zero-based, array indexing is `[y, x]`, and intervals are start-inclusive,
stop-exclusive. Parent coordinates satisfy `x_parent = x_cutout + x0`, with the
same equation for y. The virtual origin can be negative. The centering rule is
`floor(position) - (size - 1)//2` on each axis. This intentionally preserves the
commissioning rule for odd/even sides and fractional positions.

All valid SCI/ERR/DQ samples are copied without interpolation, rotation, smoothing
or flux conversion. SCI/ERR must be floating-point 2D planes of matching shape;
DQ must have nonnegative integer flags. Missing SCI/ERR are NaN and missing DQ
is DO_NOT_USE (bit value 1). Existing flags, including SATURATED (2), are retained.
Other aligned floating arrays are NaN padded, integer arrays zero padded, and
arrays named dq/pixeldq receive DO_NOT_USE padding. Auxiliary zeros do not imply
valid coverage; consult the shared valid bounds and DQ.

The exact input transform is deep-copied and translated by the **virtual** origin,
not the clipped on-detector slice. This keeps padded GWCS correct. GWCS bounding
boxes and shapes describe the full cutout grid. Astropy FITS/SIP parents are
supported; lookup-table FITS distortions are rejected. Evaluation in padding is
an extrapolation of the parent model and is not evidence of detector coverage.
Original and applied parent solutions remain distinct in correction mode.

Exposure start, end, and native integration duration are retained. Derived UTC
midpoint is halfway between reported start and end; exposure time is not inferred
from their difference. A catalogue prediction is not a confirmed identification
or a measured source centroid. No proper-motion or parallax propagation occurs.

The autocorrelation implementation uses a central tile, masks bad and saturated
pixels, subtracts the mean, applies a Hann window, computes autocorrelation and
takes the square root of the positive-moment covariance eigenvalue ratio within
the configured lag radius. It is provisional and independently implemented; it
is not asserted numerically equivalent to the external commissioning classifier.
It is disabled until a threshold is explicitly supplied. Scientific calibration
of that threshold remains necessary.

Display stacks use interpolation and medians and must not substitute for native
exposures in photometric, centroid or lens-flux inference. Keep their limitations
and membership manifest with exported previews.
