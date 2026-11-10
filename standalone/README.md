# Roman cutouts: one script and a YAML file

This is a script for cutting small images out of larger Roman telescope images.
You give it a list of targets and choose a cutout size. The script copies the
pixels around each target and keeps the information that maps those pixels to
positions on the sky.

The script reads calibrated Roman Level 2 images in ASDF format. You can use files
on your computer or download them from the MAST archive.

You do not need to install Gladius to use this script. The
[Gladius package](https://github.com/AmberLee2427/gladius) offers more features,
including resumable runs, an interactive interface, and comprehensive documentation.

## Run the script

You need Python 3.11 or later and [uv](https://docs.astral.sh/uv/).

The script lists the Python packages it needs in a comment at the top of the file.
When you run it with `uv run`, uv reads that list, creates a separate Python
environment, and installs the packages there. It does not install them into your
current Python, virtual environment, or Conda environment. You do not need to
create or activate an environment yourself, or run `pip install` first.

Uv keeps this environment in its cache and reuses it on later runs. The first run
may take longer while it downloads packages. This lets you try the script without
changing the packages you use for other projects. See the
[uv script guide](https://docs.astral.sh/uv/guides/scripts/) for more about how this works.

Download these three files into the same folder:

- `roman_cutouts.py` contains the script.
- `config.yaml` contains the settings you can edit.
- `LICENSE.txt` contains the license.

Open `config.yaml` and enter the location of your images, your targets, and a name
for the output folder. Choose an output folder that does not exist yet. Then run:

```sh
uv run roman_cutouts.py config.yaml
```

Every run needs a new output folder. If you interrupt a run, the script may leave
some cutouts behind. Start the next run in another folder. The script does not
resume earlier work.

You can change some settings on the command line. For example, this command reads
targets from `events.csv`, makes cutouts that measure 101 pixels on each side, and
writes them into `another-run`:

```sh
uv run roman_cutouts.py config.yaml --targets events.csv --size 101 --output another-run
```

The script reads paths in the YAML file relative to that file's folder. It reads
paths on the command line relative to your current folder. If you supply a setting
in both places, the script uses the command-line value.

## Choose your targets

You can list targets in the YAML file or put them in a CSV file. When you use
`--targets`, the script uses the CSV file instead of the YAML target list.

For positions on the sky, give each target an ID, right ascension, and declination.
Use ICRS coordinates in degrees:

```csv
id,ra,dec
my-event,270.0,-29.0
```

You can give positions in pixels instead. Use the column names `id,x,y`, where
`x` and `y` refer to the original image. The first pixel has coordinates `(0, 0)`.

Give each target a different ID. Start the ID with a letter or digit. You can also
use dots, underscores, and hyphens after the first character. If you add other
columns, the script keeps their values with the target in the output.

## Download images from MAST

MAST is the archive that supplies Roman data. To download images, set
`inputs.mode: mast` in the YAML file and remove the directory settings. If the data
require authentication, set the `MAST_API_TOKEN` environment variable before you
run the script.

For targets with sky coordinates, the script searches around each position. These
settings control the search:

- `radius_arcmin` sets the search radius in arcminutes. The default is 6.
- `mast_criteria` lets you add archive search criteria, such as a program number.
- `query_limit` sets the maximum number of results per query. The default is 50000.

If your targets have only pixel coordinates, you must provide `mast_criteria` to
identify which images to search. A pixel position alone cannot identify an image
or a location on the sky.

Keep the search narrow. The script downloads each full image before it makes
cutouts, and a search can return many large files. If a query reaches the result
limit, the script stops. You can then narrow the search or raise the limit.

An archive search can return an image that does not contain your target. The
script checks the target's position when it opens the image and skips targets
that fall outside the detector.

The script downloads and processes one image at a time. It removes each temporary
download after processing it. It never deletes your local input images.

## Read the results

The script writes one ASDF file for each cutout. Each file contains the science
pixels, their uncertainties, and their data-quality flags. It also contains the
target's information, metadata from the original image, and the cutout's position
within that image.

The script keeps both the original image's world coordinate system (WCS) and the
adjusted WCS for the cutout. These describe how pixel coordinates correspond to
positions on the sky.

If the original file contains other arrays with the same spatial dimensions as
the detector image, the script crops them to the same region. It keeps other
metadata without cropping it. The cutout uses this script's file structure; it is
not a Roman pipeline data product.

If you also want FITS files, add `--fits`:

```sh
uv run roman_cutouts.py config.yaml --fits
```

The FITS file contains the science pixels, uncertainties, and data-quality flags.
It uses a TAN-SIP approximation to describe the sky coordinates. The script
compares that approximation with the full WCS at a grid of positions and rejects
it if the error exceeds 0.01 pixel. The ASDF file keeps the full WCS, metadata,
and additional arrays.

The script also writes `manifest.json`. This file records the settings and the
result for each target. If one target fails, the script records the failure and
continues with the remaining targets and images. It returns a nonzero exit code
if anything fails or if it creates no cutouts.

## How the script handles pixels and edges

The script copies pixels without rotating the image or interpolating new pixel values. It adjusts
the WCS to account for the cutout's position within the original image. It checks
that the WCS can map pixels to sky coordinates and back, but it does not fit a new
WCS or correct the original image's sky coordinates.

You can choose an odd or even cutout size. On each axis, the script starts the
cutout at `floor(position) - (size - 1) // 2`. Here, `floor` rounds down to an
integer, and `//` divides and rounds down. The script uses this rule to place the
requested region on the pixel grid.

By default, the script pads cutouts that cross a detector edge. It fills missing
science pixels and uncertainties with NaN and marks the missing pixels with the
DO_NOT_USE data-quality flag, whose bit value is 1. If you want an edge crossing
to count as a failure, set `edge: strict` in the YAML file.

This script makes individual cutouts. It does not combine images into stacks,
make color composites or animations, solve for a corrected WCS, or provide an
interactive interface.

## What the tests check

The tests write cutouts, reopen the files, and compare them with the original
image. They check that the script copies the science pixels, uncertainties, and
flags exactly. They also check the padding, sky coordinates, and metadata.

One test uses a public Roman I-Sim image from STScI. It checks cutouts that measure
50 and 51 pixels on each side, both at the detector center and at a corner that
needs padding.

Another check requests a cutout at the catalog position of an isolated Gaia DR3
star. The test accounts for the star's proper motion between the catalog's reference date
and the image's date. It then measures the star's center in the cutout. The star
must have a signal-to-noise ratio above 20, and its measured position must lie
within 0.3 arcsecond of the catalog position.

The public image is a pre-launch simulation. Its filename is
`r0003201001001001004_0001_wfi02_f106_cal.asdf`. You can find it in the STScI Open
Data Bucket through the [STScI cutout tutorial](https://github.com/spacetelescope/roman_notebooks/blob/b46bc6c3d6ab8d4e63419bd51843ca8acfdaa1fb/notebooks/roman_cutouts/roman_cutouts.ipynb).
The [simulation tutorial](https://github.com/spacetelescope/roman_notebooks/blob/b46bc6c3d6ab8d4e63419bd51843ca8acfdaa1fb/notebooks/romanisim/romanisim.ipynb)
describes the input catalog. The simulation excludes Gaia stars brighter than
G=16.5. These public-data tests need no MAST token.

The same pixel, WCS, metadata, and Gaia checks also passed on a commissioning-category
(`COM`) image that required authenticated access. Those checks run on a local
computer, and they publish no data, identifiers, positions, or measurements.

Other tests use synthetic images and a mock archive to check the script without
network access.

## AI disclosure and license

OpenAI Codex generated and revised this script and its documentation to meet the
maintainer's requirements. The script includes code adapted from
[Gladius](https://github.com/AmberLee2427/gladius).

The BSD-3-Clause license covers this script. See `LICENSE.txt` for the terms.
The script does not import or require Gladius.

## Glossary

- **Array** means a grid of values, such as the pixels in an image.
- **ASDF** is the Advanced Scientific Data Format. It stores the image arrays,
  metadata, and coordinate models together.
- **CSV** is a text file that stores a table with comma-separated columns.
- **FITS** is the Flexible Image Transport System, a file format that astronomy
  tools use for images and other data.
- **Gaia DR3** is the third data release from the Gaia mission. It includes a
  catalog of stellar positions and proper motions.
- **ICRS** is the International Celestial Reference System. Right ascension and
  declination specify a direction on the sky within that system.
- **Level 2** refers here to a calibrated Roman detector image.
- **MAST** is the Mikulski Archive for Space Telescopes.
- **Metadata** describes an image, such as its detector, filter, exposure time,
  and coordinate model.
- **NaN** means “not a number.” The script uses it to mark missing science pixels
  and uncertainties.
- **Proper motion** describes how a star's position on the sky changes over time.
- **SCI, ERR, and DQ** are the science, uncertainty, and data-quality image planes.
- **Signal-to-noise ratio** compares a measured signal with its uncertainty.
- **STScI** is the Space Telescope Science Institute.
- **TAN-SIP** combines a tangent-plane sky projection with polynomial corrections
  for distortion. The FITS output uses it to approximate the full coordinate model.
- **WCS** is a world coordinate system: the model that maps pixels to sky positions.
- **YAML** is the text format that the configuration file uses for its settings.
