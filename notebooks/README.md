# Practical Gladius tutorials

The [local notebook](local_cutouts/local_cutouts.ipynb) and
[Nexus notebook](nexus_cutouts/nexus_cutouts.ipynb) teach the same MAST workflow.
Both open the interface without archive credentials, with local files available
as an input choice. Their worked MAST example is optional: `RUN_ARCHIVE_EXAMPLE`
enables it after you provide a credential-file path and one accessible Roman
`fileSetName`. They inspect the query and advertised image size before downloading,
retain the original image for context, and review cutouts and quality decisions.
Only their embedded UI connection differs: localhost for a local notebook and the
authenticated Jupyter proxy on Nexus. `gladius demo` provides a separate offline
example with synthetic images.

Install into your own Python environment, from PyPI or from a checkout:

```sh
python -m pip install 'roman-gladius[notebook]'      # or: pip install -e '.[notebook]'
python -m ipykernel install --user --name gladius --display-name 'Python (Gladius)'
```

Select that kernel. For Nexus, set `ENV_FILE` to a credential file in the notebook;
no prior environment-variable export is needed. Also set the exact `DATASET_ID`.
For your science sample, supply a target CSV and an independent finding chart.
The dataset's archive centre is only a practice coordinate, not a star identity.

The audit table includes skips and failures; image contact sheets include accepted
AND flagged native cutouts. Parent images show cutout boundaries and target
predictions. N/E arrows come from the saved WCS and do not independently validate
pointing. Contact sheets share a brightness stretch per target/filter/unit group.

The GUI opens by default, before the optional archive example. It does not
require a Python `config` variable; you can build a configuration in the form. On local JupyterLab also set `NOTEBOOK_ORIGIN` to the actual scheme,
host and port in your notebook address; Nexus uses its authenticated proxy.
Stop the GUI with the provided shutdown cell when finished.

Each notebook has a sibling requirements file. Source copies and packaged copies
must match, and outputs remain cleared. Keep tokens and restricted observations/
pointing metadata out of Git; these notebooks are separate from RTD builds.
[CONTRIBUTING.md](../CONTRIBUTING.md) describes contribution conventions. An offline
synthetic service fixture tests the Nexus code path; it does not replace a full
real-MAST execution of a user-selected dataset.
