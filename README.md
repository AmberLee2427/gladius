# Gladius

[![Tests](https://github.com/AmberLee2427/gladius/actions/workflows/tests.yml/badge.svg)](https://github.com/AmberLee2427/gladius/actions/workflows/tests.yml)
[![codecov](https://codecov.io/gh/AmberLee2427/gladius/graph/badge.svg)](https://codecov.io/gh/AmberLee2427/gladius)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

Gladius makes small images around targets you choose from larger Roman Space
Telescope images. It copies the original detector pixels and keeps their
uncertainties, quality flags, metadata, and mapping to positions on the sky.
You can use Gladius from Python, the command line, or a browser interface.

**[Documentation](https://roman-gladius.readthedocs.io/en/latest/)** ·
[Getting started](docs/quickstart.md) ·
[Example configuration](examples/config.yaml) ·
[Standalone script](standalone/README.md)

Gladius accepts **Roman Wide Field Instrument Level 2 calibrated ASDF images**
(`*_cal.asdf`). You can supply local images or ask it to find images in the MAST
archive. For other telescopes or input formats, [Astrocut](https://astrocut.readthedocs.io)
may be a better fit.

Gladius is alpha software. It is an independent project and is not affiliated
with or endorsed by STScI or Astropy.

## Installing Gladius

Gladius requires Python 3.11 or later. The published alpha release is available
from [PyPI](https://pypi.org/project/roman-gladius/) as `roman-gladius`; its Python
import and command are both `gladius`.

The following commands create a work folder and a virtual environment, install
Gladius, and start its browser interface. A virtual environment keeps Gladius
and its Python packages separate from those you use for other projects.

```sh
mkdir gladius-work
cd gladius-work
python -m venv .venv
source .venv/bin/activate
python -m pip install roman-gladius
gladius gui --workspace .
```

On Windows, the activation command is `.venv\Scripts\activate` instead.
The printed URL opens the interface in a browser on the same machine. There,
you can add targets, choose images and settings, and make cutouts. The terminal
needs to remain open while Gladius runs; closing the browser does not stop a job.

The default installation includes JupyterLab for the tutorials. A smaller
installation without the notebook packages uses `--no-deps` together with all
packages in [lite-requirements.txt](lite-requirements.txt).

The tutorials open a notebook with the Gladius interface inside it. On Roman
Research Nexus, `gladius --nexus-tutorial` opens the notebook from a JupyterLab
terminal. On your own machine, `gladius --tutorial` starts JupyterLab and opens
the local notebook. Both open the interface without archive credentials, so you
can choose local files. Their optional MAST example requires a credential file
and a dataset you can access. The offline `gladius demo` example
below needs no credentials.

The [quickstart](docs/quickstart.md) also covers installation from source,
interactive notebooks, and running the interface on Roman Research Nexus.

## Trying an example

The offline demo generates its own test images, so it needs no observations or
credentials. The destination must not already contain a demo.

```sh
gladius demo gladius-demo
```

Gladius creates two synthetic exposures and makes ASDF and FITS cutouts, a median
display image, and an animation. It also saves the configuration and a manifest:
a file recording the run's outputs and status. These test images are not Roman
observations.

The MAST demo instead downloads one calibrated archive image and makes cutouts.
It requires a MAST token. After creating a token on the
[MAST token page](https://auth.mast.stsci.edu/tokens), you can paste it into the
hidden prompt opened by `gladius token`:

```sh
gladius token
gladius demo mast-demo
```

The first command saves the token in `.env` in the current directory. A token
identifies your account; restricted observations still require access permission
for that account. Tokens belong outside Git, YAML configurations, and notebooks.

The demo checks the image size reported by MAST before downloading. Its default
limit is 512 MiB, which `--max-parent-mib` can change. It makes no display stack.
The [MAST demo guide](docs/quickstart.md#a-demo-with-one-real-image-from-mast)
explains its outputs and coordinate checks. The
[authentication guide](docs/configuration.md#local-mast-authentication) explains
credential locations for the browser interface, command line, and Python.

## Using your own targets and images

The browser interface can build and save a YAML configuration for you. For a
configuration you can edit in a text editor, `init-config` creates an annotated
example. After you edit its targets, input paths, and output directory, the next
two commands check it and run Gladius:

```sh
gladius init-config config.yaml
gladius validate config.yaml
gladius run config.yaml
```

A target CSV can replace the targets in the YAML file:

```sh
gladius run config.yaml --targets targets.csv
```

For example, a sky-coordinate target list contains an ID, right ascension, and
declination in ICRS degrees:

```csv
id,ra,dec
my-target,270.0,-29.0
```

These are example coordinates. Pixel targets use `id,x,y` instead, with zero-based
coordinates in the original image. Extra CSV columns remain in the target metadata.
Paths inside YAML resolve relative to that file; the `--targets` path resolves
relative to your terminal's current directory.

The [configuration guide](docs/configuration.md) covers archive searches, date
and filter selection, cutout size, quality screening, and output choices.
[Named runs and reuse](docs/configuration.md#named-runs-revisions-and-reuse)
explains how Gladius saves revisions and avoids repeating unchanged work.

## Pixels, coordinates, and outputs

Individual cutouts retain the original pixels without rotation or interpolation.
At detector edges, Gladius can reject the request or pad the missing region.
Science and uncertainty padding contain `NaN`; quality padding carries the
`DO_NOT_USE` flag. A target outside the detector is skipped.

The world coordinate system (WCS) maps pixels to positions on the sky. Gladius
adjusts the chosen WCS for the cutout's offset and saves the original WCS and
metadata separately. It can use a correction you supply, but does not fit one.
Its numerical checks test coordinate consistency, not absolute sky accuracy.

ASDF output stores the complete coordinate model. FITS output provides science,
uncertainty, and quality arrays, a conventional coordinate header, and embedded
ASDF metadata containing the complete model. These files use Gladius's cutout
format rather than the Roman pipeline's image format. The Python function
`read_cutout` reads either output format.

Optional median stacks, animations, and false-colour images are for inspection.
Gladius interpolates pixels to align them; it does not match stellar image shapes,
match photometric calibration, or propagate uncertainties through stacking.
Individual cutouts retain the pixels needed for scientific measurements.
The optional elongation screen remains provisional and needs calibration on
representative images.

The [output guide](docs/products.md) explains the files and how to read them.
[Scientific conventions](docs/science.md) explains pixel selection, padding,
coordinate handling, and scientific limits. The
[metadata reference](docs/headers.md) describes saved fields.

## Python and tutorials

The browser interface and command line use the same Python functions. For example,
this configuration makes 150 × 150 pixel cutouts from local images:

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

The [Python API reference](docs/api.rst) describes the available functions.
`gladius --tutorial` copies and opens the local MAST notebook;
`gladius --nexus-tutorial` opens or links the MAST notebook on Nexus.
The [notebook guide](notebooks/README.md) explains their requirements.

## Development, testing, and releases

The following commands install development dependencies and run the tests,
code checks, documentation build, and package build from a source checkout:

```sh
python -m pip install -e '.[dev]'
python -m pytest
python -m ruff check src tests docs/conf.py
python -m sphinx -W -b html docs docs/_build/html
python -m build
```

Normal tests run offline. Separate opt-in checks cover archive access, a public
Roman simulation, and local commissioning-category images.
[TESTING.md](TESTING.md) describes the validation scope and release process.
Authenticated archive workers keep their output private; downloaded archive images
and cutouts do not become public CI artifacts.

The **Bump version** GitHub Actions workflow updates version files, creates a tag,
and starts the PyPI release workflow. A matching `v<version>` tag can also trigger
publication. The release workflow requires the `PYPI_API_TOKEN` Actions secret.

## Contributing and project information

Gladius uses the BSD-3-Clause license. [NOTICE.md](NOTICE.md) describes attribution
and license scope, and [TEMPLATE.json](TEMPLATE.json) records the STScI
Cookiecutter scaffold.

Gladius normally uses the coordinate model from the original image. It can also
read a corrected WCS from a compatible ASDF file (for example, an output from
Maxime’s Gaia-solving script). Gladius does not generate that correction itself.

The repository also contains [contribution guidance](CONTRIBUTING.md), a
[code of conduct](CODE_OF_CONDUCT.md), an [AI disclosure](AI_POLICY.md), and
[citation metadata](CITATION.cff). The project has no DOI yet.
[SECURITY.md](SECURITY.md) explains how to report a vulnerability privately.
