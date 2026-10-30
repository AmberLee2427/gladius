# Gladius

Roman detector cutouts from Python, the command line, or a local browser.

Extract all targets from each image in one pass. Keep native science pixels,
uncertainties, data-quality flags and parent metadata, with an explicit mapping
back to the original detector image.

```{raw} html
<div class="start-grid">
  <a class="start-card" href="quickstart.html"><strong>Start here</strong><span>Install Gladius and make your first cutouts.</span></a>
  <a class="start-card" href="products.html"><strong>Understand the outputs</strong><span>Native image planes, parent metadata, footprints and run records.</span></a>
  <a class="start-card" href="configuration.html"><strong>Configure a run</strong><span>Targets, MAST, astrometry, quality screening and outputs.</span></a>
  <a class="start-card" href="api.html"><strong>Python API</strong><span>Call the same functions used by the CLI and GUI.</span></a>
</div>
```

## A small Python example

```python
from pathlib import Path
from gladius_roman import RunConfig, read_targets_csv, run

config = RunConfig(
    targets=read_targets_csv("targets.csv"),
    inputs={"mode": "directory", "directory": "images"},
    extraction={"size": 150, "no_overlap": "skip"},
    storage={"output_directory": "cutouts"},
).resolved(Path.cwd())

manifest = run(config)
```

Use calibrated 2D detector images. ASDF retains the exact GWCS; FITS includes
SCI/ERR/DQ and the stored exact metadata alongside its FITS WCS representation.
See [the product format](products.md) for what each file contains.

## Choosing an interface

| Interface | Start with | Useful for |
| --- | --- | --- |
| Python | [API reference](api.rst) | Inspecting results and metadata in the same session |
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
science
api
```
