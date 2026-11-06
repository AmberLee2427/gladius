# Getting started

## Install into your own environment

Install the published alpha release from [PyPI](https://pypi.org/project/roman-gladius/)
using Python 3.11 or newer. Choose a new work directory:

```sh
mkdir gladius-work
cd gladius-work
python -m venv .venv
source .venv/bin/activate
python -m pip install roman-gladius
```

On Windows, activate with `.venv\Scripts\activate` instead. The default install includes the Roman
ASDF converters, MAST archive access and JupyterLab for the tutorials. Python
3.11+ is required.

<details>
<summary>Install a development checkout instead</summary>

If you want to modify the code, install Git and use:

```sh
git clone https://github.com/AmberLee2427/gladius.git gladius
cd gladius
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.'
```

This installs your checkout, which may contain changes newer than the PyPI release.

</details>

## Open an interactive tutorial notebook

Copy/open the local tutorial in your current
directory:

```sh
python -m pip install roman-gladius
gladius --tutorial
```

In a **Nexus JupyterLab terminal**, use:

```sh
gladius --nexus-tutorial
```

Both commands write an editable notebook into the current directory. When
opening it, Gladius registers the current Python environment as a user Jupyter
kernel named **Gladius tutorial** and selects it in the copied notebook. Existing
files are never overwritten: a second copy gets a numbered filename. The local
command starts JupyterLab; the Nexus command locates the running server's file
root, prints its notebook link, and requests that it open in the browser. If the
remote terminal cannot open a tab automatically, click the printed link. When
the server root cannot be determined, open the copied file in JupyterLab's file
browser. Use `--no-open` to copy without opening anything.

The local tutorial uses synthetic images with no token. The Nexus tutorial uses
real MAST data and requires an explicit credential-file path before querying the
archive. Both demonstrate an embedded GUI, including how to stop it. Copying or
opening a notebook does not execute its cells, query MAST or download images.
Tutorials remain separate notebooks; they are not executed or embedded in RTD.

## Start with the GUI

```sh
gladius gui --workspace . --port 8768
```

Open the printed URL (normally `http://127.0.0.1:8768`) on the same machine. Upload your target CSV, select the
images and settings, then choose **Make cutouts**. You can download the YAML and
reuse it from Python or the CLI. Closing the browser does not stop a running job;
the server process must remain open. For a machine you access over SSH, see the
[SSH forwarding example](configuration.md#use-the-gui-over-ssh). On Nexus, run
`gladius gui --workspace /path/on/nexus/to/work --nexus` in its terminal and open
the printed Jupyter proxy link. See [Nexus instructions](configuration.md#roman-research-nexus-and-jupyterhub).
The notebook does not require a GUI server or port forwarding.

## Start the GUI on Roman Research Nexus

1. Sign in to [Roman Research Nexus](https://roman.science.stsci.edu/) and start
   your JupyterLab server. Choose the server containing the files you want to use.
2. Open **File → New → Terminal** in JupyterLab. Run the installation commands
   above there if Gladius is not installed yet. If you already made the `.venv`
   environment in your work directory, activate it in this terminal:

   ```sh
   cd /path/on/nexus/to/gladius-work
   source .venv/bin/activate
   ```

3. Start the GUI. `--workspace .` uses the current directory for relative paths
   and GUI job records; replace it with an existing work directory if preferred:

   ```sh
   gladius gui --workspace . --port 8768 --nexus
   ```

4. Click or copy the **Gladius GUI** link printed in the terminal into a browser
   tab. It points through Nexus's authenticated Jupyter proxy to the server you
   launched, including its named-server path. Do not open the printed local
   listener address on your laptop; that address is inside Nexus.

Keep the Gladius process and Nexus server running while making cutouts. To stop
Gladius, return to its terminal and press **Ctrl+C**. Restarting your Nexus server
also stops the app. To use restricted MAST data, run `gladius token` in the work
folder before launching the GUI, or pass `--env-file /path/on/nexus/credentials.env`.
This is your **MAST** token, not your Nexus login token.

The GUI reads images and writes outputs on Nexus. Browser CSV/YAML uploads come
from your laptop; a CSV already on Nexus can be downloaded via JupyterLab and
uploaded into the form, or imported with `--targets` in a CLI run. YAML paths
must refer to the Nexus filesystem, even when the YAML was prepared locally.

If the link fails, see the [Nexus proxy troubleshooting and explicit URL option](configuration.md#roman-research-nexus-and-jupyterhub).
The proxy extension must be enabled by the Jupyter deployment. You do not need
`remote-nexus`, an SSH tunnel, or a publicly exposed Gladius port for this workflow.

## Try it without observations or a token

```sh
gladius demo gladius-demo
```

Choose a destination that does not already contain a demo. This creates two
synthetic single-star detector images in F146, makes cutouts, writes ASDF/FITS
products, and creates a median display stack and an exposure GIF. The command
prints the manifest location. These are generated test images, not Roman observations.

## Try one real image from MAST

First obtain a token:

1. Open the [MAST token page](https://auth.mast.stsci.edu/tokens).
2. Sign in with your STScI account and create an API token there.
3. Copy the token, then paste it at the hidden prompt from `gladius token` below.

A token identifies your account; it does not grant access to restricted data.
Your account must already have permission to read the requested observations.

```sh
gladius token
gladius demo mast-demo
```

`gladius token` prompts without displaying your token and saves it in `.env` in
the current directory. It preserves other settings, asks before replacing an
existing token, and restricts file permissions to your account on macOS/Linux.
The token is not passed as a command-line argument or written into YAML.

The demo loads that `.env`, queries five accessible Level 2 datasets, and chooses
the smallest known-size calibrated parent in that sample. It writes
`mast-demo/demo.yaml`, downloads the full parent, and makes a 150 × 150 native
cutout in ASDF and FITS under `mast-demo/output/`. Stacks are disabled, and the
temporary downloaded parent is removed after processing.

The default preflight limit is 512 MiB **as advertised by MAST**, not a streaming
download cap. No image is downloaded if the selected parent exceeds it. This
example explicitly uses a 0.01-pixel numerical WCS round-trip tolerance, as does
the real-data notebook; the package default remains 0.001 pixels. The check does
not establish absolute sky accuracy.

Choose a new or empty destination. To select a different credential file or
destination:

```sh
gladius token --env-file /path/to/credentials.env
gladius demo mast-demo --env-file /path/to/credentials.env --directory another-demo
```

`--max-parent-mib` changes the advertised size limit. The default credential file
for this MAST demo is in the **launch directory**, so `gladius token` followed by
`gladius demo mast-demo` works without copying credentials into the demo folder.
To repeat a completed run with its saved YAML, use
`gladius run mast-demo/demo.yaml --env-file .env`.

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

The GUI above can build this configuration for you. To edit YAML manually instead:

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

## MAST and local credentials

Set `inputs.mode: mast` to query Roman using the targets. Leave `mast_criteria: {}`
for generated target-based searches, or add deliberate archive constraints.
See [Input selection](configuration.md#input-selection) before a large download.
Small cutouts can still require downloading full detector images.

For restricted data, run `gladius token` in the appropriate directory (or create
`.env` with `MAST_API_TOKEN=your_token_here`):

- GUI: put it in the startup `--workspace` directory and restart the server.
- CLI: put it beside the YAML passed to `gladius run`.
- Python: call `load_environment(your_workspace)` explicitly.

`gladius run` and `gladius gui` also accept `--env-file /path/to/credentials.env`.

Existing environment variables take precedence. Never put the token in YAML or a
notebook cell. The GUI's **Load test** queries real archive metadata and selects
one image; it does not download that image until **Make cutouts**. Authentication
and permission are provided by your own MAST account.
