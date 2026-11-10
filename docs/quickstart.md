# Getting started

Gladius makes small image cutouts around targets you choose. You can use your own calibrated Roman detector images or ask Gladius to find images in the MAST archive. This guide starts with installation, then shows tutorials, the graphical interface, and command-line examples.

## Installing Gladius

Gladius requires Python 3.11 or later. The published alpha release is available
from [PyPI](https://pypi.org/project/roman-gladius/), the Python Package Index.

The example below installs that release in a virtual environment: a separate
place for Gladius and its Python packages. This keeps the installation separate
from the packages you use for other projects. The commands create a work folder,
create and activate the environment, and install Gladius:

```sh
mkdir gladius-work
cd gladius-work
python -m venv .venv
source .venv/bin/activate
python -m pip install roman-gladius
```

On Windows, the activation command is `.venv\Scripts\activate` instead. The default installation includes the Roman ASDF converters, access to the MAST archive, and JupyterLab for the tutorials.

<details>
<summary>Installing a development checkout</summary>

A development checkout is useful if you want to modify the code. It requires Git. The following commands clone the repository and install the checkout:

```sh
git clone https://github.com/AmberLee2427/gladius.git gladius
cd gladius
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.'
```

This installs your checkout, which may contain changes newer than the PyPI release.

</details>

## Interactive tutorial notebooks

The tutorials let you explore Gladius in an editable notebook. Both tutorials use MAST data and require an explicit credential-file path and an accessible dataset. The following commands install Gladius, copy the local tutorial into your current directory, and open it:

```sh
python -m pip install roman-gladius
gladius --tutorial
```

In a **Nexus JupyterLab terminal**, this command opens the Nexus tutorial instead:

```sh
gladius --nexus-tutorial
```

Both commands write an editable notebook into the current directory. When opening it, Gladius registers the current Python environment as a user Jupyter kernel named **Gladius tutorial** and selects it in the copied notebook. A kernel is the Python environment that runs the notebook's code. Gladius never overwrites an existing file; a second copy gets a numbered filename.

The local command starts JupyterLab. The Nexus command finds the file root of the running server, prints a link to the notebook, and requests that it open in the browser. If the remote terminal cannot open a tab automatically, you can open the printed link. If Gladius cannot determine the server root, you can open the copied file in JupyterLab's file browser. The `--no-open` option copies the notebook without opening anything.

Both demonstrate an embedded GUI and show how to stop it. Copying or opening a notebook does not execute its cells, query MAST, or download images. The tutorials remain separate notebooks. Read the Docs does not run them or display them within its pages.

## Using the GUI locally

The following command starts the graphical interface on your own machine:

```sh
gladius gui --workspace . --port 8768
```

You can open the printed URL on the same machine, normally `http://127.0.0.1:8768`. In the interface, you can upload your target CSV, select the images and settings, and choose **Make cutouts**. You can download the YAML configuration and reuse it from Python or the command line.

Closing the browser does not stop a running job. The server process needs to remain open while the job runs. If you access the machine over SSH, the [SSH forwarding example](configuration.md#using-the-gui-over-ssh) shows how to reach the interface. On Nexus, you can run `gladius gui --workspace /path/on/nexus/to/work --nexus` in its terminal and open the printed Jupyter proxy link. The next section gives the Nexus steps. The notebook does not require a GUI server or port forwarding.

## Using the GUI on Roman Research Nexus

1. After signing in to [Roman Research Nexus](https://roman.science.stsci.edu/), you can start the JupyterLab server containing the files you want to use.
2. In JupyterLab, you can open a terminal through **File → New → Terminal**. If Gladius is not installed, the installation commands above install it in that terminal. If you already created `.venv` in your work directory, these commands activate it:

   ```sh
   cd /path/on/nexus/to/gladius-work
   source .venv/bin/activate
   ```

3. The following command starts the GUI. Here, `--workspace .` uses the current directory for relative paths and GUI job records. You can replace `.` with an existing work directory.

   ```sh
   gladius gui --workspace . --port 8768 --nexus
   ```

4. You can open the **Gladius GUI** link printed in the terminal. The link uses Nexus's authenticated Jupyter proxy, which lets your logged-in browser reach the app on the remote server. It includes the path of the Jupyter server you selected. The printed local listener address is inside Nexus and will not open the app on your laptop.

The Gladius process and Nexus server need to keep running while you make cutouts. To stop Gladius, you can return to its terminal and press **Ctrl+C**. Restarting your Nexus server also stops the app.

For restricted MAST data, you can run `gladius token` in the work folder before launching the GUI, or pass `--env-file /path/on/nexus/credentials.env`. This is your **MAST** token, not your Nexus login token.

The GUI reads images and writes outputs on Nexus. The browser's CSV and YAML upload buttons select files from your laptop. If your target CSV is already on Nexus, you can download it through JupyterLab before uploading it into the form. You can also run Gladius from the command line on Nexus and import the CSV with `--targets`.

Paths in a YAML file must point to files on Nexus, even if you prepared the YAML on your laptop.

If the link fails, the [Nexus proxy troubleshooting and explicit URL option](configuration.md#roman-research-nexus-and-jupyterhub) may help. The Jupyter deployment must have the proxy extension enabled. This workflow does not require `remote-nexus`, an SSH tunnel, or a publicly exposed Gladius port.

## A demo without observations or a token

The synthetic demo needs a destination that does not already contain a demo. This command creates one at `gladius-demo`:

```sh
gladius demo gladius-demo
```

Gladius creates two synthetic single-star detector images in F146 and makes cutouts from them. It writes ASDF and FITS products, a median display stack, and an exposure GIF. It also prints the location of the manifest, a file that records what happened during the run. These generated test images are not Roman observations.

## A demo with one real image from MAST

This demo makes a cutout from an image in MAST and requires a token. After signing in to the [MAST token page](https://auth.mast.stsci.edu/tokens) with your STScI account, you can create one. The `gladius token` command below opens a hidden prompt where you can paste the token you copied from that page.

A token identifies your account; it does not grant access to restricted data. Your account must already have permission to read the requested observations.

```sh
gladius token
gladius demo mast-demo
```

`gladius token` prompts without displaying your token and saves it in `.env` in the current directory. It preserves other settings, asks before replacing an existing token, and restricts file permissions to your account on macOS/Linux. Gladius does not pass the token as a command-line argument or write it into YAML.

The demo loads that `.env` and queries five accessible Level 2 datasets. It chooses the smallest calibrated parent image with a known size in that sample. A parent image is the original image from which Gladius takes a cutout. The demo writes `mast-demo/demo.yaml`, downloads the full parent, and makes a 150 × 150 native cutout in ASDF and FITS under `mast-demo/output/`. It disables stacks and removes the temporary downloaded parent after processing.

Before downloading, Gladius checks the size advertised by MAST. The default limit is 512 MiB; this is not a streaming download cap. Gladius does not download the image if the selected parent exceeds the limit. `--max-parent-mib` changes the advertised size limit.

This example and the real-data notebook use a 0.01-pixel tolerance for checking the world coordinate system (WCS), which maps image pixels to positions on the sky. The check measures the numerical error when the coordinate model maps a pixel to the sky and back. The package default remains 0.001 pixels. This check does not establish absolute sky accuracy.

The demo needs a new or empty destination. The following commands show how to select a different credential file or destination:

```sh
gladius token --env-file /path/to/credentials.env
gladius demo mast-demo --env-file /path/to/credentials.env --directory another-demo
```

For this MAST demo, the default credential file is in the **launch directory**. That is why `gladius token` followed by `gladius demo mast-demo` works without copying credentials into the demo folder. You can repeat a completed run with its saved YAML using `gladius run mast-demo/demo.yaml --env-file .env`.

## Using your own images and targets

Gladius can make cutouts from your calibrated detector images and a CSV file listing your targets. In this example, the images are in `images/`, and the target CSV contains:

```text
id,ra,dec
my-target,270.0,-29.0
```

These coordinates are examples, not a commissioning target. Your own ICRS coordinates need to be in degrees. Alternatively, you can use `id,x,y` for zero-based pixel coordinates in the parent image's SCI array. Gladius applies a pixel target at those same pixels on every selected image. Extra CSV columns become target metadata.

The GUI can build the configuration for you. For a manual configuration, the first command creates a YAML file. You can then edit its settings before the remaining commands validate it against the target list and run it:

```sh
gladius init-config config.yaml
gladius validate config.yaml --targets targets.csv
gladius run config.yaml --targets targets.csv
```

In the YAML file, you can set `inputs.directory`, `inputs.pattern`, and `storage.output_directory` for your files and output directory. The default pattern is `*_cal.asdf`. Gladius resolves paths in YAML beside the YAML file. For `--targets`, Gladius reads the path relative to your current directory in the terminal.

Gladius opens each image once and processes all requested targets before moving to the next image. It never deletes existing local source images. The run's manifest records completed, skipped, and failed entries; output filenames alone do not establish success.

## MAST and local credentials

The setting `inputs.mode: mast` tells Gladius to query Roman data using the targets. For generated target-based searches, `mast_criteria: {}` leaves the criteria empty; you can also add deliberate archive constraints. The [Input selection](configuration.md#input-selection) guide explains these choices before a large download. Even small cutouts can require downloading full detector images.

For restricted data, you can run `gladius token` in the appropriate directory or create `.env` with `MAST_API_TOKEN=your_token_here`. The location depends on how you use Gladius:

- For the GUI, the file belongs in the startup `--workspace` directory. The server needs a restart after you add it.
- For the command line, the file belongs beside the YAML passed to `gladius run`.
- For Python, you can call `load_environment(your_workspace)` explicitly.

`gladius run` and `gladius gui` also accept `--env-file /path/to/credentials.env`. Existing environment variables take precedence. The token must not go in YAML or a notebook cell.

The GUI's **Load test** queries real archive metadata and selects one image. It does not download that image until you choose **Make cutouts**. Your own MAST account provides authentication and permission.

## Terms used in this guide

- **ASDF** is the Advanced Scientific Data Format. Roman uses it to store images, metadata, and coordinate models together. The ASDF converters let Python read the Roman data types in those files.
- **CSV** is a text file that stores a table with comma-separated columns. Gladius reads target lists from these files.
- **F146** names one of Roman's imaging filters.
- **FITS** is the Flexible Image Transport System, a file format that astronomy tools use for images and other data.
- **GUI** means graphical user interface: the forms and buttons you use in your browser. **CLI** means command-line interface: the commands you type in a terminal.
- **ICRS** is the International Celestial Reference System. The `ra` and `dec` columns give right ascension and declination in this system.
- **MAST** is the Mikulski Archive for Space Telescopes. An API token lets a program identify your account to the archive.
- **Metadata** describes an image or target, such as the detector, filter, exposure time, or catalog information.
- **MiB** means mebibytes. One MiB is 1,048,576 bytes.
- **Native pixels** are the original detector pixels. Gladius copies their values without rotating the image or interpolating new values.
- **SCI** names the science image array in a data product. Zero-based pixel coordinates start at `(0, 0)` for the first pixel.
- **Stack** means an image that combines several exposures. A median display stack uses the median pixel values for viewing. An exposure GIF plays a sequence of images as an animation.
- **STScI** is the Space Telescope Science Institute.
- **YAML** is the text format that Gladius uses for its configuration files.
