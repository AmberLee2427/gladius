# Tutorial notebooks

Open [`nexus_cutouts/nexus_cutouts.ipynb`](nexus_cutouts/nexus_cutouts.ipynb) in your notebook service on Nexus. It uses real MAST
data and requires an explicit `.env` file path. There is no synthetic mode,
implicit credential search or automatic query during documentation builds.
This notebook is separate from Read the Docs.

From an authorized checkout, install into your own environment:

```sh
python -m pip install -e '.[roman,mast,notebook]'
python -m ipykernel install --user --name gladius --display-name 'Python (Gladius)'
```

Select **Python (Gladius)** in the notebook, or an existing managed kernel with
the same dependencies. In the configuration cell, set `ENV_FILE` to your local
credential file and choose a writable `WORKSPACE`. The file must contain
`MAST_API_TOKEN=...`; its token is used for this notebook session without being
printed. Do not put the token itself in a cell.

The notebook selects one real calibrated parent using MAST metadata, shows its
advertised size, then downloads it and makes cutouts. Set `MAX_PARENT_MIB` to the
largest advertised parent size you intend to permit; this is a metadata preflight
check, not a streaming quota. A small cutout still needs a full detector download.

Optionally set `TARGET_CSV` to your own targets. Without it the notebook uses the
selected image's archive centre as a convenient sky position, not a claimed
source detection. This one-image example does not promise overlap with arbitrary
CSV targets; use a known matching image/target sample for that case.

Run cells in order. Outputs are retained under your workspace and restricted
metadata/pointing remain private. The tracked notebook has no outputs. Clear all
outputs before committing it. The distribution check rejects executed notebooks.

The optional embedded GUI is disabled by default (`RUN_GUI=False`), so automated
runs do not start a background web server. Enable it when exploring the notebook
in Nexus. Its iframe uses the same authenticated Jupyter proxy as your notebook.

For a credential-free local example, use
[`local_cutouts/local_cutouts.ipynb`](local_cutouts/local_cutouts.ipynb). It creates
synthetic images and embeds the local GUI; set `NOTEBOOK_ORIGIN` to your notebook's
actual scheme, host and port.

Each notebook has a sibling `requirements.txt`. The source follows the STScI
teaching structure and output hygiene described in [CONTRIBUTING.md](../CONTRIBUTING.md).
GUI cells and tutorial launcher commands require Gladius 0.1.0a3 or later.
