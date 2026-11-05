# Practical Gladius tutorials

- [Local practice](local_cutouts/local_cutouts.ipynb): five noisy synthetic parent
  images, two targets, a deliberately elongated star and edge padding. Build and
  inspect the configuration, every cutout and quality decision, then re-screen
  and add display products without recutting.
- [Nexus and MAST](nexus_cutouts/nexus_cutouts.ipynb): choose one exact accessible
  `fileSetName`, inspect the bounded queries and advertised image size before
  download, retain the parent for context, compare a finding chart, and review
  all results. Real data only; the notebook has no synthetic fallback.

These revised tutorials require the development checkout containing named run
revisions and `gladius.inspection`; those additions are newer than PyPI 0.1.0a3.
From an authorized checkout, install into your own Python environment:

```sh
python -m pip install -e '.[roman,mast,notebook]'
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

The optional GUI is disabled by default. Set `RUN_GUI=True` to explore the loaded
configuration. On local JupyterLab also set `NOTEBOOK_ORIGIN` to the actual scheme,
host and port in your notebook address; Nexus uses its authenticated proxy.
Stop the GUI with the provided shutdown cell when finished.

Each notebook has a sibling requirements file. Source copies and packaged copies
must match, and outputs remain cleared. Keep tokens and restricted observations/
pointing metadata out of Git; these notebooks are separate from RTD builds.
[CONTRIBUTING.md](../CONTRIBUTING.md) describes contribution conventions. An offline
synthetic service fixture tests the Nexus code path; it does not replace a full
real-MAST execution of a user-selected dataset.
