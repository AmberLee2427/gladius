# Gladius

```{raw} html
<section class="family-billboard"><div class="family-kicker">Gladius · Roman image cutouts</div><h1>Gladius</h1><p>Gladius creates small images around your targets from Roman detector images. You can use Python, the command line, or a local browser. It extracts all targets from each image in one pass and retains uncertainties, flags and metadata from the original image.</p></section>
```

```{raw} html
<div class="start-grid">
  <a class="start-card" href="quickstart.html"><strong>Getting started</strong><span>This guide covers installation and your first cutouts.</span></a>
  <a class="start-card" href="products.html"><strong>Output files</strong><span>These files contain pixels, original metadata, sky coverage and run records.</span></a>
  <a class="start-card" href="configuration.html"><strong>Run settings</strong><span>Targets, MAST, astrometry, quality screening and outputs.</span></a>
  <a class="start-card" href="api.html"><strong>Python API</strong><span>Python provides the same functions as the command line and browser interface.</span></a>
</div>
```

## A small Python example

```python
from pathlib import Path
from gladius import RunConfig, read_targets_csv, run

config = RunConfig(
    targets=read_targets_csv("targets.csv"),
    inputs={"mode": "directory", "directory": "images"},
    extraction={"size": 150},
    storage={"output_directory": "cutouts"},
).resolved(Path.cwd())

manifest_path = run(config)
```

Gladius takes Roman Level 2 calibrated images (`*_cal.asdf`) as input; it does not
cut out other products. ASDF output retains the exact generalized world coordinate
system (GWCS), which maps pixels to sky positions. FITS output includes the science,
uncertainty and quality arrays (SCI/ERR/DQ), the exact saved metadata and a FITS
representation of the coordinate model.
See [Outputs](products.md) for what each file contains.

## Choosing an interface

| Interface | Start with | Useful for |
| --- | --- | --- |
| Python | [API reference](api.rst) | Inspecting results and metadata in the same session |
| Jupyter Notebooks | `gladius --tutorial` | Opening the local tutorial with the Gladius UI and Python examples |
| Roman Research Nexus | `gladius --nexus-tutorial` | Opening the tutorial and its Gladius UI on Nexus |
| Local GUI | `gladius gui --workspace .` | Building YAML and importing target CSVs without writing Python |
| CLI | `gladius run config.yaml --targets targets.csv` | Repeating saved settings or running a batch |

Gladius is currently alpha software. Native cutouts are separate from optional,
resampled display stacks. Numerical WCS checks do not establish absolute sky
accuracy, and the autocorrelation screen is provisional. These boundaries are
explained in [Scientific conventions](science.md).

```{toctree}
:hidden:
:maxdepth: 2

quickstart
configuration
products
headers
science
api
```
