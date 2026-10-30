# Gladius

Native image cutouts for the Roman Space Telescope.

Native detector cutouts from calibrated Roman images, with explicit parent-pixel
mapping, separately retained parent metadata, exact stored astrometry, and optional
display stacks. An independent alpha package built from the STScI Cookiecutter
scaffold; it is not affiliated with or endorsed by STScI or Astropy.

## Install and run

Python 3.11 or newer is required. From this checkout:

```sh
python -m pip install -e '.[roman]'
gladius init-config config.yaml
# Edit targets and inputs in config.yaml.
gladius validate config.yaml
gladius run config.yaml
```

For archive access, install `'.[roman,mast]'` and set `inputs.mode: mast` with
bounded `mast_criteria`. Restricted data use `MAST_API_TOKEN` from the environment.
Directory mode does not perform archive queries or downloads.

Try a complete offline example with no credentials or mission data:

```sh
gladius demo /tmp/my-gladius-demo
```

This creates two synthetic ASDF exposures, a YAML file, native ASDF/FITS cutouts,
a display stack, a resolved configuration and a run manifest. Choose a new demo
folder; existing demo inputs are not overwritten.

## Configuration

[examples/config.yaml](examples/config.yaml) documents every option. Paths are
relative to the configuration file. Unknown keys, duplicate YAML keys, invalid
coordinates and inconsistent settings are rejected before input discovery.
`gladius config-schema schema.json` writes JSON Schema for editor support.

- Select exposure-start dates in a UTC `[start, end)` interval, detectors 1–18,
  and filters. Empty detector/filter lists mean all; missing metadata needed for
  a requested selection causes an explicit error.
- Choose square cutout size, padding/strict edges and fully off-detector policy.
- Use supplied WCS, validate its numerical consistency, or require a separately
  supplied corrected GWCS. Validation does **not** establish absolute sky accuracy.
- Enable an autocorrelation elongation screen and decide whether failures enter
  display stacks. Native cutouts remain available regardless of quality flags.
- Retain full parent images or keep only their derived products. Local input
  files are never deleted. Archive parents are staged one at a time.
- Choose ASDF, FITS or both; configure bounded display stacks, resume and failure
  handling. Resolved defaults and dependency versions are recorded for each run.

See [configuration](docs/configuration.md), [product format](docs/products.md),
[scientific conventions](docs/science.md), and [Python API](docs/api.rst).

## Scientific contract

SCI and ERR are unresampled floating-point pixels with NaN padding. DQ flags stay
integer; missing pixels are DO_NOT_USE (1), and existing saturation flags survive.
Centering follows the commissioning convention `floor(position) - (size - 1)//2`,
including odd sizes. Coordinates are zero-based `(x, y)` on the calibrated SCI
array, with `array[y, x]` indexing. Origins can be negative.

The cutout WCS is a translation of the chosen parent WCS. The original WCS and
metadata are retained under `parent_wcs` and `parent_metadata`; derived footprints
are in `cutout_metadata`. Spatial arrays are cropped using the shared mapping,
with descriptors recording their original paths, shapes and types. Non-spatial
metadata arrays and custom fields are retained, including FITS header ordering,
comments and duplicate HISTORY cards.

ASDF stores the exact GWCS. FITS provides SCI/ERR/DQ extensions, a measured TAN-SIP
approximation where necessary, auxiliary arrays and a package-specific ASDFMETA
extension retaining full metadata and exact WCS. These are **derived products**,
not schema-valid Roman mission datamodels. Read them with `read_cutout`.

## Current boundaries

The first version handles 2D calibrated detector images, not raw ramps, mosaics,
spectral products or moving-target ephemerides. A supplied correction can be
applied, but the separately authored Gaia solver is not bundled. The new
independent autocorrelation method is provisional; its threshold must be
calibrated, and the old commissioning threshold is not assumed equivalent.
Stacks are resampled display products, not photometrically or PSF-matched science
coadds. They do not propagate uncertainties. Execution is sequential and portable.

MAST staging is covered by mocked service tests; real archive access depends on
service availability, permissions and input metadata. See TESTING.md for actual
validation scope. No automatic upload, publication or external solver invocation
occurs.

## Development and provenance

```sh
python -m pip install -e '.[dev,roman,mast]'
python -m pytest
python -m ruff check src tests docs/conf.py
python -m sphinx -W -b html docs docs/_build/html
python -m build
```

The original source snapshots remain as historical references. Their original
handoff is preserved in [docs/commissioning-handoff.md](docs/commissioning-handoff.md).
They are excluded from distributions. [TEMPLATE.json](TEMPLATE.json) records the
Cookiecutter template and exact commit; [NOTICE.md](NOTICE.md) explains license
scope and attribution. The copied external Gaia solver has not been incorporated
into the package.

New package code is BSD-3-Clause. Template attribution is retained separately.
See [contributing](CONTRIBUTING.md), [conduct](CODE_OF_CONDUCT.md),
[AI disclosure](AI_POLICY.md), and [citation](CITATION.cff). The project has not yet
been published to PyPI or assigned a DOI.

## Local web GUI and target CSVs

For restricted MAST access, copy `.env.example` to `.env` in your workspace
and set `MAST_API_TOKEN=your_token_here`. The GUI loads that file when the server
starts; restart the server after editing it. Existing shell variables take
precedence. For `gladius run config.yaml`, place `.env` beside the YAML instead.
Keep `.env` private and out of Git; the repository already ignores it. GitHub
Actions secrets do not populate this local file. See the
[authentication instructions](docs/configuration.md#local-mast-authentication).

```sh
gladius gui --workspace . --port 8768
```

Open the printed local URL. The GUI builds the same validated configuration used
by the CLI, imports target CSVs, downloads self-contained YAML, and runs the
pipeline with live progress. It includes a YAML editor/importer for existing
configurations. Relative paths resolve from the directory shown in the builder;
downloaded YAML contains absolute paths. The server binds only to loopback.
Keep its terminal open during runs; closing a browser tab does not cancel a run.

```sh
gladius validate config.yaml --targets targets.csv
gladius run config.yaml --targets targets.csv
```

`--targets` replaces YAML targets before validation, so the YAML may omit targets
when that option is supplied. The CSV path is relative to the CLI working
directory; other paths retain their YAML-relative meaning.

```csv
id,ra,dec,catalogue
OGLE-2019-BLG-0011,270.123,-29.456,OGLE
```

Use decimal ICRS degrees (`ra,dec`) or zero-based pixels (`x,y`), never both.
`ra_deg/dec_deg` and `name/target_id` aliases are supported. IDs can be omitted to
generate stable row-order IDs such as `target-000001`. Extra columns are retained
as strings under each target's `metadata`, including in cutout provenance.
Invalid rows and duplicate IDs fail explicitly. The GUI preview shows the first
50 targets; all rows are included in the configuration and run.

Each GUI submission saves its resolved YAML and progress record in
`.gladius-gui/` under the workspace; scientific outputs still go to the
configured output directory. Only one GUI-owned run is active at a time. Reloading
the page reconnects to the last run while the server remains open. After a server
restart, run history remains on disk rather than being automatically restarted.

## Python API

The CLI and GUI use the same importable functions:

```python
from pathlib import Path
from gladius_roman import RunConfig, load_config, read_targets_csv, run

# Existing YAML, with an optional CSV override:
config = load_config("config.yaml", targets_path="targets.csv")
manifest_path = run(config, progress=print)

# Or construct the configuration directly:
config = RunConfig(
    targets=read_targets_csv("targets.csv"),
    inputs={"mode": "mast"},
    extraction={"size": 150, "no_overlap": "skip"},
).resolved(Path.cwd())
# manifest_path = run(config)
```

MAST sky searches are generated from target RA/Dec, with Level 2 calibrated
images and a configurable 6 arcminute candidate radius by default. Additional
criteria are optional for sky targets; pixel-only targets need an archive
constraint such as a program ID. See the configuration guide for authentication,
query limits and overlap conventions. `make_cutout()` also accepts in-memory
SCI/ERR/DQ arrays, a WCS and a `Target`; see the Python API documentation.

## Live archive tests in GitHub Actions

Add `MAST_API_TOKEN` under **Settings → Secrets and variables → Actions**.
The **Live Roman MAST download** workflow runs on default-branch code changes,
or manually from Actions. It downloads one product capped at 20 MiB and reports
whether it tested a calibrated image/cutout or a small associated product.
The manual calibrated-image option requires full extraction coverage within the
same cap. Downloaded science data are not uploaded as artifacts. Normal tests
remain offline. See the configuration guide for the exact coverage and limits.
