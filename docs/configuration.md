# Configuration and execution

Generate an annotated file with `gladius init-config config.yaml`. The full
example is in `examples/config.yaml`. Keys omitted from YAML receive documented
defaults; every resolved value is saved in the run's `resolved-config.yaml` and
manifest. Paths are resolved relative to the YAML file, independently of the
working directory. Duplicate and unknown YAML keys are errors.

## Input selection

`inputs.mode: directory` reads `directory` using `pattern`, optionally recursively.
Only matched parents are read. Generated output under that directory is excluded
from input discovery. This mode does not contact MAST. FITS parents must provide
SCI, ERR and integer DQ plus a 2D celestial SCI WCS. ASDF parents must provide
`roman.data`, `roman.err`, `roman.dq`, `roman.meta.wcs` (or equivalent root keys).
Roman schema converters are installed by the `roman` extra. Missing converters
produce explicit errors rather than stripping typed metadata silently.

`inputs.mode: mast` uses Astroquery's Roman MastMissions API (`astroquery>=0.4.11`).
With RA/Dec targets, leave `mast_criteria: {}`: the package queries each distinct
sky position, defaults to `productLevel: "2"` (calibrated detector images), and
uses `mast_radius_arcmin: 6.0`. Dates, detectors and filters are included in the
archive query and checked again locally. End dates remain exclusive even when
the archive's range query includes the endpoint.

The cone returns candidate images, not guaranteed overlap. Six arcminutes is a
conservative default for ordinary small cutouts from a WFI detector; increase it
for large cutouts or uncertain astrometry. It cannot recover images whose archive
positions are wrong by more than the chosen radius. The supported radius is
0 < radius <= 30 arcminutes. No-overlap handling follows `extraction.no_overlap`.
Overlapping searches are deduplicated before any parent is downloaded.

Use `mast_criteria` for optional overrides, e.g. `{program: 1043}` (an example ID,
not a promise of available data). Explicit positional criteria replace automatic
cones. Pixel-only targets require an explicit archive constraint because pixels
do not identify a sky position. Advanced filters can narrow the result further;
configured local selections are still enforced. `product_suffix: _cal` chooses
the calibrated files from the resulting product lists.

Queries reaching `query_limit` (per cone or combined unique observations) are
rejected as potentially incomplete. Install the `mast` extra. Restricted data
require an authorized account and `MAST_API_TOKEN` in the launching shell/server
environment, never in YAML. Local environment loading is described under
[authentication](#local-mast-authentication); the package does not search
commissioning infrastructure for credentials. The authenticated live CI smoke
test checks a bounded archive download, which may be an associated product rather
than a calibrated science image. It is not full scientific validation of real
Roman cutouts.

Query syntax and columns follow [Astroquery mission searches](https://astroquery.readthedocs.io/en/stable/mast/mast_missions.html);
Roman column names were checked against the live MAST column-list service.

`selection.start` is inclusive; `end` is exclusive. Both refer to UTC exposure
start, not midpoint or any-overlap with the interval. Quote timestamps in YAML.
`end: '2026-02-01'` excludes all exposures starting on February 1. Other time
scales found in input metadata are retained there and converted to UTC for
selection and derived timing. Detectors are integer SCA numbers 1–18; parent
labels WFI01 through WFI18 or SCA01 through SCA18 are recognized. Filters are
case-insensitive. Missing metadata necessary for selection is an error.

Targets use unique filesystem-safe IDs and exactly one pair of coordinates:
`ra/dec` in ICRS degrees, or `x/y` in zero-based parent SCI pixels. A pixel target
uses the same pixel coordinates on every selected detector image. Neither form
is a measured centroid. Catalog motion and event/detector crossmatching are not
inferred automatically; select the appropriate exposures.

## Astrometry and extraction

- `astrometry.mode: use` accepts the supplied parent transform without the
  optional numerical validation screen.
- `validate` checks a 5×5 image grid for finite world coordinates and inverse
  round trips within `roundtrip_tolerance_pixels`, plus positive local scales.
  This catches numerical problems; a consistently wrong sky solution can pass.
- `corrected` requires a separate ASDF correction in `corrected_directory` with
  the configured filename pattern (`{stem}` and `{filename}` placeholders).
  The accepted corrected transform is validated and translated. The original
  parent transform, correction transform, source identity and correction
  metadata remain available in the product. The package does not run Gaia fits.

`extraction.size` is a positive integer square side. `edge: pad` keeps the full
requested virtual grid; `strict` rejects any padded request. `no_overlap` selects
pad, skip or error for entirely disjoint requests. Strict edges still reject a
fully padded request. Sky-to-pixel failures are errors, not silently skipped.
See science.md for centering and flag conventions.

## Quality and stacks

`quality.autocorrelation_limit: null` disables the screen. A finite threshold
above one enables the independent `gladius-acf-positive-moments-v1` method.
The method, tile size, radius, measured ratio, threshold and decision are stored.
Failure to measure is a rejected screen, never deletion of the native cutout.
`exclude_from_stacks` controls whether these flags affect display stacks.
Do not reuse the commissioning threshold without calibrating this method.

`stacks.enabled` writes one display median per target/filter. Inputs with
incompatible units are rejected. Nonfinite pixels, DO_NOT_USE and SATURATED are
masked, each exact WCS maps onto the first reference exposure's grid, and bilinear
samples are included only with full valid weight. A COVERAGE image records the
number contributing at each output pixel. No PSF matching, unit conversion,
photometric harmonization or uncertainty propagation is performed. No stack is
made for a group with no eligible inputs. Manifest exclusions explain why.
`max_exposures` and a conservative `max_memory_mb` estimate provide preflight
checks per target/filter stack. Set either value to `0` to disable that check.
Exceeding a nonzero limit raises an error and leaves the run failed; already
saved native cutouts remain available. Earlier completed stack groups can also
remain on disk. Excess inputs are never silently truncated. The memory estimate
is not an enforced process-memory cap, and disabling it does not guarantee
sufficient RAM; the operating system may terminate a process that exhausts RAM.

## Storage, restarts and failures

Each configuration/package/dependency/implementation combination has a run directory under
`storage.output_directory/runs`. Parent content hashes and correction hashes
identify cutout variants. Resume verifies output checksums before reusing them.
Changed parent files and corrections produce new variants; missing parents are
removed from the current manifest and stack membership. Historical variants
remain on disk. No auto-purge or quota enforcement is attempted.

`retain_full_images: true` copies selected parents into a content-addressed
`parents` directory. With false, local originals remain untouched and temporary
archive downloads are removed after processing each exposure, including failures.
Archive mode still downloads a parent before hash-based resume; it does not
trust filename identity as proof of unchanged archive content.

A portable file lock prevents concurrent execution of the same run. Cutouts are
built and reopened in a temporary directory before publishing their checksums
in an atomic manifest replacement. A crash may leave unreferenced files, which
are not trusted until validated. Per-file replacement repairs corrupt variants;
only the manifest describes a committed complete product set.

By default, a failure stops the run after recording it. `continue_on_error: true`
processes later targets/parents, records failures, and leaves a failed run status
with a nonzero CLI exit. It does not turn failed science into a successful run.
Execution is sequential; simultaneous downloads and processing are not yet exposed.

## Target CSV override

`run` and `validate` accept `--targets path/to/targets.csv`. This replaces the
YAML target list before validation, and may supply targets omitted from the YAML.
The CSV path follows the shell working directory, while paths inside YAML remain
relative to that YAML file.

CSV headers are `id,ra,dec` for decimal ICRS degrees or `id,x,y` for parent pixels.
Aliases `name`/`target_id` and `ra_deg`/`dec_deg` are accepted case-insensitively.
An omitted ID column generates IDs by nonempty row order. Explicit blank IDs,
duplicate IDs, ambiguous columns, malformed rows, NaNs and out-of-range sky
coordinates are errors with line numbers. Extra columns are retained as string
`metadata` on the target, without numeric inference that could destroy identifiers
with leading zeroes. UTF-8 CSVs with a byte-order mark are supported.

## Local run studio

`gladius gui --workspace /path/to/work --port 8768` launches the bundled web
GUI using the standard Python library; no extra GUI dependency is required. It
binds to 127.0.0.1. Open the printed URL, upload/paste a CSV or enter targets,
configure processing, and download YAML or press Run. Uploads stay on the local
server. The GUI and CLI share target parsing, configuration validation and the
pipeline; there is no separate set of scientific defaults.

YAML import and the advanced YAML editor load settings back into the form. The
base-directory field defines relative paths for pasted/imported configurations;
resolved YAML downloads use absolute paths. The browser cannot infer the original
local directory of an uploaded YAML file, so set that field explicitly when
necessary. CSV imports replace the current target list. Extra catalogue columns
are embedded in saved YAML; the original CSV is not needed to rerun it.

Run progress and errors appear in the browser. Successful runs provide their
manifest path, cutout counts and a manifest download. A failed pipeline exposes
its error; pipeline manifests remain in the configured run output directories.
Closing or refreshing a tab does not cancel the run. Refresh reconnects to the
last submission while the server is alive. Keep the terminal open; interrupting
the GUI server stops serving requests but allows an active worker to finish its
cleanup. Only one GUI-owned run can execute at a time. Existing pipeline locks
also protect runs initiated through other processes.

Each submitted configuration and job record is saved in
`<workspace>/.gladius-gui/<job-id>/`. These job records and scientific
outputs are local working data, not package assets. They are never published by
the GUI. Job history is retained on disk across server restarts; it is not loaded
into a new server session automatically.

## Live MAST CI

The **Live Roman MAST download** workflow runs on pushes to the repository's
default branch that change package, integration-test or workflow files. It also
has a **Run workflow** button. Add an Actions repository secret named
`MAST_API_TOKEN` using an account authorized for the Roman data you want to test.
A missing or rejected token fails the live test; normal unit tests remain offline.

The test samples five Level 2 datasets, checks a target query generated from a
real archive position, and downloads exactly one associated product through the
package's production staging function. It accepts only products with a known,
positive advertised size of at most **20 MiB** and enforces that limit on file
writes in the Linux worker. It checks the downloaded length and temporary-file
cleanup. No suitable small product is a failure, not a skipped or successful test.

A calibrated detector image is preferred when one fits the cap. In that case the
test also reads its science planes/metadata, extracts a cutout, and writes/reopens
an ASDF cutout. Otherwise it tests a smaller associated product, such as a preview
or ancillary file. The job summary and report explicitly distinguish
`calibrated-image-and-cutout` from `associated-product-download`; the latter does
not establish that full Roman detector images can be processed. The manual
**Require a calibrated image** option turns absence of a small calibrated image
into a failure, without increasing the cap.

Only test reports are uploaded as Actions artifacts, never the downloaded Roman
data or cutouts. The workflow does not run on pull requests. Its token is supplied
only to the live test step, and Astroquery is told not to save it to a credential
store. The job has a ten-minute timeout.

For a local opt-in run on Linux/macOS, with `MAST_API_TOKEN` already set:

```sh
python -m pip install '.[test,roman,mast]'
GLADIUS_LIVE_MAST=1 python -m pytest tests/integration -m live_mast -v
```


## Local MAST authentication

Copy the repository's `.env.example` to `.env`, then edit it locally:

```text
MAST_API_TOKEN=your_token_here
```

Use your own MAST token from an account authorized for the requested Roman data.
Do not paste it into YAML, the browser, logs or Git. The repository ignores `.env`
and `.env.*` except the empty `.env.example` template. In a different repository,
add your own ignore rule. Restrict the file to your account on shared machines
(for example, `chmod 600 .env` on macOS/Linux).

- **GUI:** put `.env` directly in the `--workspace` directory. Without
  `--workspace`, this is the directory where you launch Gladius. It is loaded
  once at server startup. After changing the file, stop and restart the server;
  reloading the browser is insufficient. Editing the UI's Working directory or
  loading a YAML does not load a different environment file.
- **CLI:** `gladius run /path/to/config.yaml` loads `/path/to/.env` before running.
  Validation and configuration-generation commands do not load it.
- **Python:** call `load_environment("/path/to/workspace")` explicitly before
  `run(config)`. Importing Gladius and loading YAML do not change the environment.

Only the specified directory is checked; parent directories are not searched.
Already-set environment variables win, including empty values. Remove an old
shell variable with `unset MAST_API_TOKEN` before launching if you want the file
to supply it. Values are read literally, without shell execution or `${...}`
interpolation. Tokens are not included in downloaded YAML or job configurations.
A GitHub Actions secret is separate and cannot supply a local GUI token.

## GUI controls and testing

The GUI’s **Make cutouts** button calls the same pipeline as `gladius run`.
**Load test** makes real MAST metadata queries for up to five Level 2 datasets,
selects the smallest known-size calibrated product in that sample, and loads a
one-target, 64 × 64 ASDF configuration pinned to the dataset and exact product
filename. It does not download images or start a run. The UI shows the advertised
full-parent download size; the parent may be much larger than the cutout. Click
Make to download it. An inaccessible archive, timeout or empty sample produces an
error, never fabricated example data. Local archive access uses the launching
environment’s MAST_API_TOKEN; a repository secret is available only to Actions.
This one-image GUI test is distinct from CI’s 20 MiB associated-product smoke test.
`inputs.product_filename` optionally restricts products to one exact filename.

Manual targets support ICRS, Galactic and barycentric true ecliptic coordinates
(equinox J2000), all in decimal degrees, plus zero-based parent pixels. Astropy
converts sky frames to ICRS before the YAML is written. Non-ICRS input frame and
coordinates are retained as target metadata. Ecliptic does not infer distance,
proper motion or a different observing epoch. CSV ingestion still uses its
explicit ICRS/pixel column conventions.

The working directory starts from `--workspace`, which defaults to the launch
folder, and is editable. The corrected-WCS directory defaults to `gaia_wcs`, the
external correction tool’s default output location; Gladius only reads existing
corrections and does not run that tool or create the correction folder.

The WCS policy help changes with the selection. Numerical validation fails a
parent before extracting its targets if the supplied transform is inconsistent.
With continue-on-error enabled later images can be tried. Validation cannot
establish absolute sky accuracy. Corrected mode reads and validates the separate
correction and preserves the original transform.

The autocorrelation screen uses the central `tile_size` square in the cutout.
`radius` is the maximum offset from zero lag in the autocorrelation map used for
shape moments, not a sky aperture. A threshold of 2.0, with exploratory inspection
around 1.5–3.0, is a starting suggestion only; this method is uncalibrated. Ratios
at or above the threshold are flagged. Insufficient tile/signal also flags the
screen; native cutouts remain saved. A 150-pixel cutout is 150 × 150 native pixels,
not a promise of square angular pixels.

Resume reuses checksum-verified outputs for identical configuration, code and
dependency versions; without a previous run it starts normally. Parent discovery
and reading still occur. Lock timeout is how long to wait for another process
writing the same run directory; 0 fails immediately, and is unrelated to network
timeouts. Continue-on-error handles failures inside individual image/target work
(download, read, WCS, coordinate inversion, extraction, product validation/write).
It records errors and keeps the final run failed. Configuration, initial archive
discovery, run-lock and stack-phase failures remain fatal. Quality flags are
recorded decisions, not exceptions governed by continue-on-error.

Coordinate-frame reference: [Astropy transformations](https://docs.astropy.org/en/stable/coordinates/transforming.html)
and [BarycentricTrueEcliptic](https://docs.astropy.org/en/stable/api/astropy.coordinates.BarycentricTrueEcliptic.html).
