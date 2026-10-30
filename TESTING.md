# Testing

```sh
python -m pip install -e '.[test,roman,mast,docs]'
python -m pytest --cov=gladius_roman
python -m ruff check src tests docs/conf.py
python -m sphinx -W -b html docs docs/_build/html
python -m build
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
