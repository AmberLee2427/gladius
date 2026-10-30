# Getting started

## Install into your own environment

Gladius has not been published to PyPI yet. From an authorized checkout:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[roman,mast]'
```

On Windows, activate with `.venv\Scripts\activate` instead. `roman` adds the
converters needed for Roman-tagged ASDF images; `mast` adds archive queries and
downloads. Neither is required for the synthetic demo. Python 3.11+ is required.

## Try it without observations or a token

```sh
gladius demo gladius-demo
```

Choose a destination that does not already contain a demo. This creates two
synthetic detector images, makes cutouts, writes ASDF/FITS products, and builds
display stacks. The command prints the manifest location. These are generated
test images, not Roman observations.

## Use your own images and targets

Put calibrated detector images in `images/` and write a target CSV:

```text
id,ra,dec
my-target,270.0,-29.0
```

The coordinates above are examples, not a commissioning target. Supply your own
ICRS coordinates in degrees. Alternatively use `id,x,y` for zero-based parent
SCI pixels. A pixel target is applied at those same pixels on every selected
image. Extra CSV columns become target metadata.

Generate and edit the configuration:

```sh
gladius init-config config.yaml
gladius validate config.yaml --targets targets.csv
gladius run config.yaml --targets targets.csv
```

Set `inputs.directory`, `inputs.pattern` and `storage.output_directory` for your
files. The default pattern is `*_cal.asdf`; change it to match FITS inputs when
needed. Paths in YAML resolve beside the YAML file. The CLI's `--targets` path
resolves from the shell's current directory.

An image is opened once and all requested targets are processed before moving to
the next image. Existing local source images are never deleted. Inspect the run's
manifest for completed, skipped or failed entries; output filenames alone do not
establish success.

## Or build the YAML in the GUI

```sh
gladius gui --workspace . --port 8768
```

Open the printed loopback URL on that machine. Upload your target CSV, select the
images and settings, then choose **Make cutouts**. You can download the YAML and
reuse it from Python or the CLI. Closing the browser does not stop a running job;
the server process must remain open. On a remote server such as Nexus, use an
SSH tunnel if local policy permits; loopback on Nexus is not your laptop's
loopback. The notebook does not require a GUI server or port forwarding.

## MAST and local credentials

Set `inputs.mode: mast` to query Roman using the targets. Leave `mast_criteria: {}`
for generated target-based searches, or add deliberate archive constraints.
See [Input selection](configuration.md#input-selection) before a large download.
Small cutouts can still require downloading full detector images.

For restricted data, create `.env` with `MAST_API_TOKEN=your_token_here`:

- GUI: put it in the startup `--workspace` directory and restart the server.
- CLI: put it beside the YAML passed to `gladius run`.
- Python: call `load_environment(your_workspace)` explicitly.

Existing environment variables take precedence. Never put the token in YAML or a
notebook cell. The GUI's **Load test** queries real archive metadata and selects
one image; it does not download that image until **Make cutouts**. Authentication
and permission are provided by your own MAST account.

