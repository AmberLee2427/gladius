# Contributing

Create a virtual environment and install `python -m pip install -e '.[dev,roman,mast]'`.
Run pytest, Ruff and the Sphinx documentation build before proposing changes.
TESTING.md describes the supported verification steps and their limits.

Keep extraction independent of services and UI. Add scientific regression tests
for changes to centering, flags, timing, GWCS, metadata and serialization. Document
new configuration keys and regenerate docs/config.schema.json. Changes to product
semantics require a schema/version decision and migration notes in CHANGES.rst.
Do not edit historical snapshots as if they were the active implementation.

Report bugs with package/dependency versions, a small redistributable example and
the resolved configuration. Remove credentials and private data before sharing.
Do not add external solver code without an explicit compatible license and
attribution. Contributions must follow CODE_OF_CONDUCT.md and AI_POLICY.md.

Use [GitHub issues and pull requests](https://github.com/AmberLee2427/gladius)
for contributions.

## Notebook contributions

Each source notebook lives in its own folder under `notebooks/`, with a sibling
`requirements.txt`. Keep outputs cleared and credentials/data out of Git. Bundled
tutorial copies must match those sources. The Nexus notebook requires an explicit
credential-file path set in its configuration cell.
Its optional live GUI stays disabled for unattended execution.

These conventions follow the [STScI notebook contribution guide](https://github.com/spacetelescope/notebooks/blob/main/CONTRIBUTING.md)
and [notebook infrastructure workflow](https://spacetelescope.github.io/notebook-infrastructure/contributing_notebooks/).
Preparing our source does not submit it or imply acceptance. An eventual STScI PR
needs the chosen repository's layout/footer, scientific and technical review,
a released version supporting any enabled GUI cells, and an agreed way for its
CI to access the required real data. Restricted-input outputs must not be exposed
in a public notebook build. The user-selected credential path remains required;
we do not replace inaccessible observations with synthetic data.
