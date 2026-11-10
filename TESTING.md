# Testing

```sh
python -m pip install -e '.[test,roman,mast,docs]'
python -m pytest --cov=gladius
python -m ruff check src tests docs/conf.py tools
python -m sphinx -W -b html docs docs/_build/html
python -m build
python tools/check_distribution.py dist/*
python -m twine check dist/*
```

The default suite is offline. It checks padded and fully disjoint detector grids,
odd/even centering, native plane values and flags, exact GWCS translation, SIP
translation, retained parent/custom metadata, ASDF and FITS round trips, timing
scale conversion, optional display stacks, selection, retained parents, changed
correction identity, corrupted-product repair, configuration and CLI failures.
Archive tests simulate MastMissions; they do not establish authenticated MAST
access or archive metadata availability. An optional Roman tagged-ImageModel test
runs when a compatible roman_datamodels package is installed.

No credentials, commissioning catalogues or large science files are needed. The
suite does not calibrate the autocorrelation threshold, validate absolute
astrometry against Gaia, or qualify products for photometry. A representative
real-Roman commissioning-data run is still required before scientific deployment.
CI declares Python 3.11–3.13 on Linux and current Python on macOS/Windows; a CI
configuration is not a claim that those remote jobs have already run.

## Publish a release to PyPI

The **Publish to PyPI** workflow (`.github/workflows/release.yml`) runs when a
`v*` tag is pushed. Branch pushes do not publish. It builds, tests, checks docs
and distribution contents, and runs the installed wheel's offline demo before
a separate job uploads the checked artifacts to **production PyPI**.

Add a repository secret named **`PYPI_API_TOKEN`** under **Settings → Secrets and
variables → Actions → New repository secret**. Paste the complete PyPI API token,
including its `pypi-` prefix. This is separate from `MAST_API_TOKEN`.
Create the token in your [PyPI account settings](https://pypi.org/manage/account/token/).
For a first publication, the project does not exist yet, so a project-scoped token
is not available; use an account-scoped token for that upload. Once `roman-gladius`
exists, replace the repository secret with a token scoped to that project.
Do not put either token in a commit or pass it in the tag command.

### Automated version bump (recommended)

Run **Actions → Bump version → Run workflow** on `main` and choose `pre`
(`0.1.0a4` → `0.1.0a5`), `release` (drop the `a`/`b`/`rc` marker), `patch`, `minor`,
`major`, or an explicit version. It runs `tools/bump_version.py`, which updates
`pyproject.toml`, `gladius.__version__`, `CITATION.cff` and turns the `Unreleased`
heading in `CHANGES.rst` into the dated release heading, then commits, tags `vX.Y.Z`,
pushes and starts the **Publish to PyPI** workflow for that tag. (Tags pushed by
`GITHUB_TOKEN` do not trigger other workflows, hence the explicit dispatch.) If `main`
is branch-protected, allow GitHub Actions to push or bump locally instead.

Locally: `python tools/bump_version.py pre` (add `--dry-run` to only print the result).

### Manual tagging

Before tagging by hand, update the version everywhere (`python tools/bump_version.py ...`
does this), update the changelog, and commit. The workflow rejects tags that do
not match the package version exactly. Run the bump script first, then tag the version it printed:

```sh
git push origin main
git tag -a vX.Y.Z -m "Gladius X.Y.Z"
git push origin vX.Y.Z
```

**The final command starts publication.** Use the version you actually intend
to release; the example above publishes an alpha release. The distribution name
is `roman-gladius`, while the Python import and CLI are `gladius`.
The workflow does not create a GitHub Release or publish to TestPyPI. PyPI release
files cannot be overwritten; corrections require a new version and tag.

## Coverage and lint

CI runs `ruff check` and `ruff format --check` (config in `.ruff.toml`; the release
workflow runs them before building). Format locally with
`python -m ruff format src tests docs/conf.py tools`.

Every `tests.yml` job uploads `coverage.xml` to [Codecov](https://app.codecov.io/gh/AmberLee2427/gladius)
using the repository secret **`CODECOV_TOKEN`**. Thresholds live in `codecov.yml`
(no project-wide drop beyond 1%, 80% on new lines). Locally:
`python -m pytest --cov=gladius --cov-report=term-missing`.

## Local commissioning checks

With `MAST_API_TOKEN` already set in your local environment, run:

```sh
GLADIUS_LOCAL_COMMISSIONING=1 python -m pytest tests/integration/test_commissioning_local.py -q
```

This test explicitly selects Roman Level 2 imaging datasets with
`program_category=COM`, samples up to five datasets, and downloads one eligible
calibrated parent. It checks exact SCI/ERR/DQ values and padding, parent/cutout
WCS agreement, metadata preservation, and an isolated epoch-propagated Gaia DR3
reference star. The Gaia search uses a small central field to avoid truncation
in dense regions. Accuracy and detection thresholds match the public simulation
checks. This is sample-based validation, not a claim about all commissioning data.

The test is disabled in GitHub Actions, including when explicitly enabled by an
environment variable. Its worker discards stdout/stderr and exposes only pass/fail.
No commissioning images, identifiers, coordinates, measurements, or diagnostic
artifacts are published. Temporary downloaded parents and derived cutouts are removed after the check.
