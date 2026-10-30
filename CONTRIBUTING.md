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

There is no hosted repository configured yet. When one is established, use its
issue tracker and pull requests; this file deliberately does not invent a URL.
