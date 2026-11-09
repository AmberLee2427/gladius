# Roman cutouts: one script and YAML

Extract native Roman Level 2 calibrated ASDF detector cutouts without installing
Gladius. [Gladius](https://github.com/AmberLee2427/gladius) is the fuller-featured
Python package for this workflow, with resumable runs, an interactive UI, and
comprehensive documentation.

Requires Python 3.11+; [uv](https://docs.astral.sh/uv/) installs the script's
declared dependencies automatically.

Download `roman_cutouts.py`, `config.yaml`, and `LICENSE.txt` into one directory.
Edit the YAML to point at your images and targets, then run:

```sh
uv run roman_cutouts.py config.yaml
uv run roman_cutouts.py config.yaml --targets events.csv --size 101 --output another-run
uv run roman_cutouts.py config.yaml --fits
```

The output directory must not exist. There is no cache, resume, or revision system.
YAML paths are relative to the YAML file; CLI paths are relative to the current
directory. Flags override YAML values. CSV targets replace YAML targets:

```csv
id,ra,dec
my-event,270.0,-29.0
```

Use `id,x,y` for zero-based parent detector pixels instead. IDs must be unique
and contain only letters, digits, dots, underscores, or hyphens, starting with a
letter or digit. Optional extra target columns are preserved.

For MAST, set `inputs.mode: mast`, remove directory settings, and optionally add
`mast_criteria`, `radius_arcmin` (default 6), and `query_limit` (default 50000).
Sky targets generate cone queries; pixel-only targets require explicit archive
criteria. Set `MAST_API_TOKEN` in the environment for authenticated access. The
script downloads full calibrated parents, one at a time, and deletes temporary
downloads afterward. It never deletes local inputs. Queries can return many large
files: narrow criteria before running. A cone finds candidates, not guaranteed
image overlap; queries reaching the limit fail so you can narrow the search.

Each ASDF output stores SCI/ERR/DQ, the translated full WCS, original parent WCS,
parent metadata, cropped ancillary arrays, target, and extraction geometry.
Aligned spatial arrays are cropped; non-spatial metadata is retained. Outputs
use this script's own schema marker, not a Roman pipeline product schema.
Optional FITS contains SCI/ERR/DQ and a TAN-SIP approximation checked to 0.01 pixel
on a grid; complete metadata and ancillary arrays remain in the ASDF companion.

The script checks numerical WCS inversion, not absolute astrometric accuracy.
It preserves native pixels without rotation or resampling. Even sizes follow
`floor(position) - (size - 1) // 2`; padded pixels are NaN in SCI/ERR and
DO_NOT_USE (bit 1) in DQ. Targets outside a detector are recorded and skipped.
`edge: strict` treats boundary crossings as failures.

`manifest.json` records settings and per-target results. Failures are recorded
while remaining parents/targets continue; exit status is nonzero if anything
fails or no cutouts are produced. An interrupted run can leave partial outputs;
start again in a new directory. No stacks, composites, animations, corrected-WCS
solver, UI, or persistent state.

Derived from [Gladius](https://github.com/AmberLee2427/gladius), BSD-3-Clause;
see `LICENSE.txt`. The script does not import or require Gladius.

## AI disclosure

This script and its documentation were generated and revised with OpenAI Codex,
following the maintainer's requirements, with code adapted from Gladius. Automated
checks cover synthetic extraction, mocked archive access, and the public
simulation described below.

## Checks on a public Roman simulation

Tested against STScI's publicly released Roman I-Sim tutorial image for exact
SCI/ERR/DQ pixel fidelity, WCS consistency with the parent, and metadata
preservation. Checks reopen the written files and cover 50- and 51-pixel cutouts
at the detector center and a padded corner. A separate sky-coordinate cutout
checks an isolated Gaia DR3 star, propagated to the simulation epoch, against
an image centroid (S/N > 20; positional tolerance 0.3 arcsec).

This is a pre-launch simulation, not an on-sky Roman observation. The fixture is
`r0003201001001001004_0001_wfi02_f106_cal.asdf` from the anonymous STScI Open Data
Bucket, linked in the [STScI cutout tutorial](https://github.com/spacetelescope/roman_notebooks/blob/b46bc6c3d6ab8d4e63419bd51843ca8acfdaa1fb/notebooks/roman_cutouts/roman_cutouts.ipynb).
The [simulation tutorial](https://github.com/spacetelescope/roman_notebooks/blob/b46bc6c3d6ab8d4e63419bd51843ca8acfdaa1fb/notebooks/romanisim/romanisim.ipynb)
describes its Gaia input catalog and the exclusion of stars brighter than G=16.5.
These tests need no MAST secret.
