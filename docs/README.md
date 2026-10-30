# Documentation

Build with `python -m pip install -e '.[docs]'` followed by
`python -m sphinx -W -b html docs docs/_build/html`.
Sphinx warnings fail the build. Documentation does not include or execute the
separate Nexus notebook in `notebooks/`. No credentials, archive queries or
science outputs are used by the docs build.

`.readthedocs.yaml` configures the same build for Read the Docs. Connecting a
hosted project and deciding its visibility are separate steps; this file does
not publish documentation or grant a service access to the private repository.
