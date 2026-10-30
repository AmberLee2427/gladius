# Gladius public release review

**Candidate:** `gladius-roman` 0.1.0a2, an alpha Python package. Import:
`gladius_roman`; command: `gladius`. **Status: prepared for review, not approved
or published.** The GitHub repository remains private. No PyPI publishing workflow
or automatic release is enabled.

## Decision requested

The project is being asked to approve public distribution of the package's code,
documentation and examples under BSD-3-Clause, including the acknowledged native
cutout centering convention adapted from its commissioning helper. This is a
software release, not a release of commissioning observations, target lists,
footprint inventories, calibration results or production infrastructure.

| Decision | Status |
| --- | --- |
| Project review of commissioning-derived convention and any contributor/employer release requirements | Pending project review |
| Permission to distribute the bundled RGES-PIT logo | Pending Scott's confirmation via Amber |
| Public PyPI upload of this candidate | Pending the above and Amber's release decision |
| Making the GitHub repository public | Separate decision; not authorized by this review |

Record the reviewers, decision date, approved version and exact Git commit or
artifact checksums when approval is given. Any requested changes should be built
and reviewed as a new candidate.

## What users receive

- Python API, CLI and a bundled local browser GUI for selecting targets, building
  YAML configurations and executing cutouts. Python 3.11 or later is required.
- Native 2D detector SCI/ERR/DQ extraction, configurable square sizes and edge
  handling, auxiliary spatial arrays, preserved parent metadata, and explicit
  parent-to-cutout pixel mapping.
- Exact translated GWCS in ASDF; FITS science extensions plus the stored exact
  metadata/WCS and a checked FITS approximation when required. Output is a
  Gladius derived product, not a schema-valid Roman mission datamodel.
- Local input files or optional authenticated Roman MAST queries/downloads,
  date/detector/filter selections, checksum-based output reuse, and optional
  retention of full parent images. Local originals are never deleted.
- Manual ICRS, Galactic and J2000 barycentric true ecliptic input; CSV targets;
  optional existing corrected WCS input; a provisional autocorrelation screen;
  and optional resampled median display stacks.
- Synthetic examples and offline tests, the template attribution and dependency
  license acknowledgements, Gladius branding and the proposed RGES-PIT footer.

The wheel contains the runtime code, GUI assets, example YAML and license files.
The source archive additionally contains tests, documentation, review material
and synthetic target examples. Neither contains actual image files or catalogues.

## Commissioning provenance and boundaries

The centering rule is `floor(position) - (size - 1)//2` on each axis. Its origin
in the commissioning extraction helper remains acknowledged in `NOTICE.md` and
the scientific documentation. That provenance is retained for project review.
The new autocorrelation method is independently implemented and is not claimed
to match the commissioning classifier or its threshold.

The runtime does not import the Ice dashboard, a commissioning footprint service,
an event registry, NEA crossmatches, production S3 publishing code or the external
Gaia solver. It calculates cutout footprints from the chosen parent WCS. Parent
footprint metadata are preserved as provenance. Corrected WCS files are read
only when selected and supplied by the user; fitting the correction is outside
this package.

Historical commissioning source collections, the internal handoff, assistant
working files, local credentials, downloaded observations and generated outputs
are excluded from the release. `tools/check_distribution.py` checks both built
archives for these categories before CI uploads distribution artifacts.

## Data access and output disclosure

MAST access uses the installing user's own permissions. It does not ship a token
or grant access to restricted data. `.env` is local and excluded; only an empty
template is distributed. The GUI binds to loopback and runs on the user's machine.
Website footer links are links, not commissioning service integrations. There is
no automatic scientific-product upload or publication.

Cutouts deliberately preserve parent metadata, supplied correction provenance
and user target metadata. Products made from restricted inputs can therefore
remain restricted, including their pointing and footprint information. Approval
to release this software does not approve redistribution of those products.

## Scientific and operational limits

This is an alpha release for calibrated 2D detector images, not raw ramps,
mosaics, spectra or moving-target propagation. Numerical WCS consistency is not
absolute astrometric validation; a consistently wrong sky solution can pass.
No Gaia fit is bundled. Autocorrelation thresholds need calibration against
representative images. Stacks interpolate pixels and do not propagate
uncertainties; they are display products and are not qualified science coadds.
Disabling stack limits can exhaust memory. Native metadata retention is intended
to be comprehensive, but representative real Roman products still need scientific
validation before operational use.

## Validation and release procedure

The preparation run has 65 passing offline tests and one intentionally skipped
authenticated MAST test. Lint, documentation, wheel/source builds, distribution
content checks and a clean wheel-installed synthetic demo must pass for the final
candidate. A configured CI matrix is not itself evidence of passing remote jobs.
Authenticated archive service availability and scientific commissioning
acceptance are separate from these offline results; do not describe them as
established by the test suite.

Before publication:

1. Record the project and logo decisions above against the final candidate.
2. Review successful CI results and any real-data validation the project requires.
3. Build from the approved commit, run `python tools/check_distribution.py dist/*`
   and `python -m twine check dist/*`, and record artifact SHA256 checksums.
4. Inspect/install the final wheel and run its synthetic demo in a clean
   environment. Mark the release date in `CHANGES.rst` and rebuild/recheck if any
   tracked file changes. The first intended public version is an alpha.
5. Tag and upload only after Amber's explicit release instruction. PyPI package
   naming and account/publishing access must be checked at that time. Public
   availability is a release action; this preparation does not perform it.
