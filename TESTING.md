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

Before tagging, update **both** `pyproject.toml`'s `version` and
`src/gladius/__init__.py`'s `__version__`, update the changelog, and commit those
changes together with the release workflow. The workflow rejects tags that do
not match the package version exactly. For the current `0.1.0a3` version:

```sh
git push origin main
git tag -a v0.1.0a3 -m "Gladius 0.1.0a3"
git push origin v0.1.0a3
```

**The final command starts publication.** Use the version you actually intend
to release; the example above publishes an alpha release. The distribution name
is `roman-gladius`, while the Python import and CLI are `gladius`.
The workflow does not create a GitHub Release or publish to TestPyPI. PyPI release
files cannot be overwritten; corrections require a new version and tag.
