# Configuration and execution

## Build a configuration in the GUI

Start with the GUI to explore the settings and build your YAML. The form presents
options with help text and defaults, so you can choose them in context and see
the resulting configuration in the YAML preview. It uses the same configuration
model, validation and scientific defaults as the CLI and Python API.

```sh
gladius gui --workspace /path/to/work --port 8768
```

Open the printed URL in your browser. The GUI runs on that machine, binds to
127.0.0.1, and uses the standard Python library; no extra GUI dependency is
required. Keep its terminal open while using it.

1. **Add targets.** Upload or paste a target CSV, or enter targets individually.
   The form explains the coordinate conventions. CSV imports replace the current
   target list; extra catalogue columns are preserved as target metadata.
2. **Choose images and processing.** Expand the settings sections to select local
   images or MAST, dates, detectors, cutout size, WCS handling and outputs. Read
   the help beside each setting; WCS policy help changes with your selection.
3. **Inspect and download the YAML.** The preview includes defaults and resolved
   paths. Choose **Download YAML** to save a configuration for the CLI, Python or
   a later GUI session. Target metadata is embedded, so the original CSV is not
   needed to rerun it.
4. **Make cutouts when ready.** Choose **Make cutouts** to run the configuration
   from the GUI, or run the saved file later:

   ```sh
   gladius run config.yaml
   ```

**Load YAML** and **Edit YAML** bring existing configurations back into the form.
The **Working directory** field sets the base for relative paths in imported or
pasted YAML. Set it to the intended directory when importing: the browser cannot
infer the uploaded file's original location. Downloaded YAML uses absolute paths;
update those paths when moving the configuration to another machine.

Uploads and outputs stay on the local server. See [authentication](#local-mast-authentication)
for MAST credentials, [GUI controls and testing](#gui-controls-and-testing) for
individual control behaviour, and [GUI execution and saved jobs](#gui-execution-and-saved-jobs)
for progress, failures and job records.

```{figure} _static/examples/gui.jpg
:alt: Gladius GUI with one synthetic target, the YAML preview, and cutout geometry settings.
:target: _static/examples/gui.jpg

The GUI with the synthetic demo configuration loaded. This is a screenshot;
start `gladius gui` to use the controls. Click the image to view it at full size.
```

### Use the GUI over SSH

Start the GUI in your remote shell:

```sh
gladius gui --workspace /path/to/work --port 8768
```

In a separate terminal **on your laptop**, open a tunnel:

```sh
ssh -N -L 8768:127.0.0.1:8768 username@remote-machine
```

Open `http://127.0.0.1:8768` in your laptop's browser. Keep both the remote GUI
process and the SSH tunnel running. Input paths and outputs refer to files on
the remote machine; uploading a CSV sends it from your browser to that machine.
The GUI remains bound to the remote machine's localhost.

If port 8768 is occupied on your laptop, choose another port, such as 8769,
**for all three places**: the remote `--port`, both port numbers in `-L`, and
the browser URL. The current GUI checks the request's hostname and port; forwarding
a different local port to 8768 is not supported.

### Roman Research Nexus and JupyterHub

For the full login, installation and launch sequence, see
[Start the GUI on Roman Research Nexus](quickstart.md#start-the-gui-on-roman-research-nexus).

In a **Nexus JupyterLab terminal**, activate the environment containing Gladius,
then start it with:

```sh
gladius gui --workspace /path/on/nexus/to/work --port 8768 --nexus
```

Open the **Gladius GUI** link printed in that terminal in your laptop's browser.
It uses the authenticated Jupyter proxy, for example:

```text
https://roman.science.stsci.edu/user/YOUR-USERNAME/YOUR-SERVER/proxy/8768/
```

Gladius reads `JUPYTERHUB_SERVICE_PREFIX` to retain your actual username and named
server. Do not copy the placeholders above literally. Keep the trailing slash,
the Gladius process, and the Nexus server running. Files and processing stay on
Nexus. The app still listens only on `127.0.0.1` inside that server; your existing
Jupyter login controls access through the proxy.

When JupyterHub provides `JUPYTERHUB_PUBLIC_URL`, Gladius detects the public server
address and prints the proxy link even without `--nexus`. A Nexus address in
`JUPYTERHUB_HOST` or `NEXUS_SERVER_URL`, together with the Jupyter server prefix,
also identifies Nexus. `--nexus` is the fallback when the public host is not
provided. It must be run inside the Jupyter server environment, not on your laptop.

For another JupyterHub, or if automatic detection cannot find the address, pass
the complete browser URL explicitly:

```sh
gladius gui --workspace /path/to/work --port 8768 \
  --public-url https://YOUR-HUB/user/YOUR-USERNAME/YOUR-SERVER/proxy/8768/
```

Use the URL prefix of your actual running JupyterLab server, replacing `lab/...`
with `proxy/8768/`. A default server has no `YOUR-SERVER` path component. The
public URL configures both the startup link and the allowed browser origin;
Gladius does not infer a trusted address from incoming forwarding headers.
Assets, API calls, job polling and downloads remain under that proxy path.

This requires **Jupyter Server Proxy** to be installed and enabled in the
Jupyter server environment. A proxy 404 is a Jupyter deployment issue, rather
than a reason to bind Gladius to a public network address. See the
[Jupyter Server Proxy instructions](https://jupyter-server-proxy.readthedocs.io/en/latest/arbitrary-ports-hosts.html).
The `remote-nexus` CLI can launch commands through Jupyter, but it is not needed
when starting Gladius from a Nexus terminal.

For a default server, JupyterHub also supports a login-aware redirect:
`https://YOUR-HUB/hub/user-redirect/proxy/8768/`. The printed direct link is
preferred for named servers: a generic user-redirect link may select a different
server from the one running Gladius. No login token is included in the printed URL.
Your MAST token file remains separate from your Nexus login.

### Embed the GUI in a notebook

Tutorial support is newer than the first PyPI `0.1.0a2` release. The local
`gladius --tutorial` and hosted `gladius --nexus-tutorial` notebooks contain
complete start, iframe and stop cells. They remain separate from this RTD site.

Within a Nexus notebook, start the server from the kernel and embed its proxy URL:

```python
import threading
from pathlib import Path

from IPython.display import IFrame, display
from gladius.web import GuiServer

workspace = Path.cwd()
server = GuiServer(workspace, port=0, nexus=True, iframe_origin="self")
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()

gladius_ui_url = server.public_url
display(IFrame(src=gladius_ui_url, width="100%", height=650))
```

`port=0` selects an unused port. On Nexus the notebook and proxy share one browser
origin, so `iframe_origin="self"` allows the frame. For a notebook on your laptop,
omit `nexus=True`, set `iframe_origin` to its exact browser origin (for example
`"http://localhost:8888"`), and use `server.url + "/"` as the iframe URL. Match the
scheme, hostname and port shown in your notebook's address bar, without its path
or any login token. The GUI's separate port is **not** the notebook origin.

You can pass `initial_config=config` with an existing `RunConfig` to populate
the form without starting a run. Existing GUI job history in that workspace takes
precedence when restoring the last job. This is how the supplied tutorial loads
its current settings into the form.

After any active run finishes, stop the embedded server:

```python
server.shutdown()
server.server_close()
thread.join(timeout=5)
```

The server belongs to the notebook kernel: closing the displayed frame does not
stop it, while restarting the kernel does. The tutorial's start cell reuses its
server when rerun; stop it before changing its allowed notebook origin.

For a GUI started separately in a terminal, add `--iframe-origin self` on Nexus,
or `--iframe-origin http://localhost:8888` for a local notebook. Without this
explicit option, embedding is blocked. The option changes only the allowed frame
parent; GUI session tokens and API origin checks remain enabled. The browser
still requires an authenticated Nexus session for a Nexus iframe.

## Create or edit YAML directly

For a text-based starting point, generate an annotated file:

```sh
gladius init-config config.yaml
gladius validate config.yaml
gladius run config.yaml
```

<details>
<summary>Full annotated YAML example — examples/config.yaml</summary>

```{literalinclude} ../examples/config.yaml
:language: yaml
```

</details>

The sections below explain the YAML fields, their defaults and their behaviour
in more detail.

Keys omitted from YAML receive documented defaults; every resolved value is
saved in the run's `resolved-config.yaml` and manifest. Paths in a saved YAML
file resolve relative to that file, independently of the shell's working
directory. Duplicate and unknown YAML keys are errors.

## Input selection

`inputs.mode: directory` reads `directory` using `pattern`, optionally recursively.
Only matched parents are read. Generated output under that directory is excluded
from input discovery. This mode does not contact MAST. FITS parents must provide
SCI, ERR and integer DQ plus a 2D celestial SCI WCS. ASDF parents must provide
`roman.data`, `roman.err`, `roman.dq`, `roman.meta.wcs` (or equivalent root keys).
Roman schema converters are installed with Gladius (`roman_datamodels`). Missing converters
produce explicit errors rather than stripping typed metadata silently.

`inputs.mode: mast` uses Astroquery's Roman MastMissions API (`astroquery>=0.4.11`).
With RA/Dec targets, leave `mast_criteria: {}`: the package queries each distinct
sky position, defaults to `productLevel: "2"` (calibrated detector images), and
uses `mast_radius_arcmin: 6.0`. Dates, detectors and filters are included in the
archive query and checked again locally. End dates remain exclusive even when
the archive's range query includes the endpoint.

The cone returns candidate images, not guaranteed overlap. Six arcminutes is a
conservative default for ordinary small cutouts from a WFI detector; increase it
for large cutouts or uncertain astrometry. It cannot recover images whose archive
positions are wrong by more than the chosen radius. The supported radius is
0 < radius <= 30 arcminutes. No-overlap handling follows `extraction.no_overlap`.
Overlapping searches are deduplicated before any parent is downloaded.

Use `mast_criteria` for optional overrides, e.g. `{program: 1043}` (an example ID,
not a promise of available data). Explicit positional criteria replace automatic
cones. Pixel-only targets require an explicit archive constraint because pixels
do not identify a sky position. Advanced filters can narrow the result further;
configured local selections are still enforced. `product_suffix: _cal` chooses
the calibrated files from the resulting product lists.

Queries reaching `query_limit` (per cone or combined unique observations) are
rejected as potentially incomplete. MAST access uses `astroquery`, installed with Gladius. Restricted data
require an authorized account and `MAST_API_TOKEN` in the launching shell/server
environment, never in YAML. Local environment loading is described under
[authentication](#local-mast-authentication); the package does not search
commissioning infrastructure for credentials. The authenticated live CI smoke
test checks a bounded archive download, which may be an associated product rather
than a calibrated science image. It is not full scientific validation of real
Roman cutouts.

Query syntax and columns follow [Astroquery mission searches](https://astroquery.readthedocs.io/en/stable/mast/mast_missions.html);
Roman column names were checked against the live MAST column-list service.

`selection.start` is inclusive; `end` is exclusive. Both refer to UTC exposure
start, not midpoint or any-overlap with the interval. Quote timestamps in YAML.
`end: '2026-02-01'` excludes all exposures starting on February 1. Other time
scales found in input metadata are retained there and converted to UTC for
selection and derived timing. Detectors are integer SCA numbers 1–18; parent
labels WFI01 through WFI18 or SCA01 through SCA18 are recognized. Filters are
case-insensitive. Missing metadata necessary for selection is an error.

Targets use unique filesystem-safe IDs and exactly one pair of coordinates:
`ra/dec` in ICRS degrees, or `x/y` in zero-based parent SCI pixels. A pixel target
uses the same pixel coordinates on every selected detector image. Neither form
is a measured centroid. Catalog motion and event/detector crossmatching are not
inferred automatically; select the appropriate exposures.

## Astrometry and extraction

The WCS is the image's coordinate model: it converts between detector pixels
and positions on the sky. Choose how Gladius uses it:

- **`astrometry.mode: use`** uses the input image's WCS without the optional
  numerical consistency check.
- **`validate`** checks 25 positions across the image. Each position must convert
  to a valid sky coordinate and back to within `roundtrip_tolerance_pixels` of
  its starting pixel. Near the image centre, a one-pixel step in either direction
  must also correspond to a nonzero separation on the sky. A failed check rejects
  that input. This catches numerical problems; a WCS that consistently points to
  the wrong sky position can still pass.
- **`corrected`** reads a replacement WCS from a separate ASDF file in
  `corrected_directory`, checks it as above, and uses it for extraction. The
  filename follows `corrected_pattern`: `{stem}` means the input filename without
  its extension; `{filename}` means the full input filename. Gladius retains both
  the original and replacement models and their metadata. It does not fit a
  correction against Gaia or generate the correction file for you.

`extraction.size` sets the square's side in pixels: `150` produces a 150 × 150
cutout. At a detector edge, `edge: pad` keeps that requested size and fills the
part outside the image; `edge: strict` rejects any cutout requiring such filling.
If the square misses the image entirely, `no_overlap` chooses whether to save an
entirely padded cutout (`pad`), skip it (`skip`, the default), or report an error (`error`).
`strict` still rejects entirely padded requests. Failure to convert sky
coordinates to pixels is an error, rather than an off-image skip.

See [Scientific conventions](science.md) for worked examples of pixel selection,
padding values and coordinate conversion.

## Quality, stacks, animations and colour

`quality.autocorrelation_limit: null` disables the optional elongation screen.
Set a threshold above one to flag elongated image patterns: a measured ratio at
or above that threshold is rejected by the screen. An image with too few usable
pixels or too little signal can also fail the screen. The score, settings and
reason are saved. **Native cutouts are retained even when flagged.**

`quality.exclude_from_stacks: true` excludes flagged cutouts from median stacks,
GIFs and colour composites. With `false`, they can contribute to those outputs.
The threshold needs testing on representative images; do not assume another
classifier's threshold has the same meaning here. See the
[quality-screen explanation](science.md#what-does-the-optional-quality-screen-measure).

Each display output can be enabled independently:

| Setting | Result |
| --- | --- |
| `stacks.enabled` | One median FITS image per target/filter, plus a `COVERAGE` extension counting contributing values at each pixel. |
| `stacks.gif_enabled` | A GIF cycling through individual exposures in time order, aligned to the same sky grid. `gif_frame_ms` is playback time per frame (default 500 ms; multiples of 10 ms). |
| `stacks.rgb_enabled` | One false-colour PNG per target. `red_filter`, `green_filter` and `blue_filter` select its channels (defaults F213, F184 and F062). |

Gladius aligns the images using their coordinate models. Alignment estimates
values between input pixels; it excludes nonfinite, DO_NOT_USE and SATURATED
pixels. A sampled value is used only when its interpolation weight from usable
pixels exceeds 0.999. Exposures combined within a filter must have the same units.
No output is made for a group with no eligible inputs; the display manifest
records quality exclusions and composite skips.

These outputs are for inspection. Gladius does not match the shapes of stars
between exposures, adjust exposures to the same brightness calibration, convert
units, or calculate combined uncertainties. See [example outputs](products.md#example-images)
for reproduction commands and [colour composites](products.md#colour-composites)
for how the RGB brightness limits are chosen.

`stacks.max_exposures` limits inputs per target/filter. `stacks.max_memory_mb`
checks an estimated memory requirement before creating the display output.
Set either to `0` to disable that check. Exceeding a nonzero limit fails the run;
Gladius keeps native cutouts already written and does not silently drop excess
inputs. Earlier completed display groups can also remain on disk.

The memory check is an estimate, not a hard limit on process memory. Disabling it
does not create more RAM; the operating system may terminate a process that
exhausts available memory.

## Named runs, revisions and reuse

Give a project a name in the YAML (the GUI has a **Run name** field):

```yaml
run:
  name: bulge-field-test
```

Outputs go under `storage.output_directory/runs/bulge-field-test/r0001/`.
The default name is `default`. Names accept letters, digits, underscores and
hyphens. A new name starts a separate result at `r0001`; it can still reuse
verified work cached beneath the same output directory.

The same name and unchanged inputs/settings resume an incomplete revision or
return the latest complete revision. Changed settings, local input contents,
WCS corrections, or relevant processing code/dependencies create `r0002`, then
`r0003`, and so on. Earlier completed revisions keep their files and membership.
If a completed revision has damaged output files, Gladius creates a replacement
revision rather than overwriting that history. Returning to an earlier configuration
creates another revision that can reuse its cached products.

**Changing one setting does not repeat the entire pipeline.**

| What you change | Work Gladius repeats | Work it can reuse |
| --- | --- | --- |
| Dates, detector/filter selection or MAST search criteria | Discover the input set again and apply the new selection. | Native cutouts for products already processed; quality/display products whose own inputs still match. |
| Add a target | Search new sky positions when needed; extract the new target from selected parents. | Existing targets' cutouts and previews. |
| Target coordinates/metadata, cutout size or edge policy | Extract affected cutouts with the new settings. | Unaffected targets and other verified products. |
| Selected WCS or correction file | Rebuild native variants whose coordinate model changed. | Unaffected native variants. |
| Numerical WCS validation policy or tolerance | Check the saved parent/cutout coordinate models again. | Native pixels and unchanged display products. |
| Autocorrelation threshold, tile side or lag radius | Reassess saved native pixels. | Native cutouts; display products if accepted input membership stays the same. |
| Whether flagged images enter stacks | Recalculate display membership. | Native cutouts and quality measurements. |
| Enable RGB, median stacks or GIFs | Build the requested products per target/filter group. | Native cutouts, assessments and existing independent display products. |
| GIF speed or RGB filter assignments | Rebuild the affected GIFs or composites. | Median stacks and native cutouts. |
| Add FITS output or change its approximation tolerance | Serialize saved native cutouts as FITS. | Native extraction and unchanged display products. |
| Turn on full-image retention | Obtain and save any missing parent files. | Existing cutouts; retention does not itself require extracting them again. |
| Exposure/memory limits | Check the new limits before producing or reusing the requested display group. | Native products. No inputs are silently dropped to meet a limit. |

A changed date range can therefore create a new revision with the same native
cutouts. If the range removes exposures, the new revision omits them from its
file list and display inputs; the earlier revision remains intact.

### When does MAST get queried or downloaded?

With unchanged discovery settings, a MAST run reuses its saved input list.
Quality or display changes do not trigger another archive query or download
when the native cutouts are already available. To look for newly available
observations without changing the selection, explicitly refresh that list:

```sh
gladius run config.yaml --refresh-inputs
```

Changing dates, search positions, or other discovery settings also refreshes the
query. **Gladius trusts MAST product identities:** known archive products reuse
the originally downloaded content identity. A refreshed search does not download
known products merely to check whether MAST changed their bytes. Newly encountered
products need downloading when their pixels are required. Parents may also be
needed for new cutout geometry, new targets, or full-image retention.

Local inputs are rediscovered and hashed on every call. This detects changed
local files without relying on filenames or modification times alone. Local
originals are never deleted. Temporary MAST downloads are removed after each
parent has been processed, including when processing fails.

### Start completely fresh

```sh
gladius run config.yaml --name bulge-field-test --fresh
```

`--fresh` starts a new revision and bypasses discovery, cutout, assessment and
display reuse. For MAST, it queries and downloads again. `execution.resume: false`
in the YAML has the same effect, including in the GUI. Leave resume enabled for
normal iterative work. A different name alone gives a separate result, not a
forced recomputation.

Python callers can use `run(config, refresh_inputs=True)` or
`run(config, fresh=True)`. The return value is still the revision's manifest path.

### What is recorded, and what is kept?

Each revision saves its resolved configuration, input identities, errors, current
quality assessments, file paths/checksums and stage reuse counts in `manifest.json`.
Its `stack-manifest.json` lists display membership and exclusions. **Use the
revision manifest for its current quality decision.** A reused ASDF/FITS file
keeps its original creation provenance, including the configuration that first
created it; Gladius does not rewrite that file just because a threshold changed.

Verified intermediate products live in `storage.output_directory/.cache/`.
Revision products are independent copies, so cache repair cannot change the
bytes of earlier revisions. Keep the cache to benefit from reuse; it can grow,
and Gladius currently has no automatic eviction or disk quota. Original parents
are retained under `parents/` only when requested. Removing the shared cache
loses the optimization; it does not delete revision copies.

Pre-existing alpha-3 hash-named runs remain readable and untouched. They are not
automatically imported into the new cache. New manifests use schema version 2;
the native cutout schema and FITS/ASDF image contents retain their existing format.

### Failures and concurrent runs

An output-directory lock protects shared caches and revision allocation across
all names. `execution.lock_timeout_seconds` is how long to wait: `0` fails
immediately if another process holds it. This is not a MAST network timeout.

By default, a processing error is recorded and stops the run.
`execution.continue_on_error: true` tries later inputs or targets after individual
read, coordinate-conversion, extraction or write failures. The final status
still reports failure, and the CLI returns a nonzero exit code. Invalid settings,
archive discovery, output-lock failures and display failures stop the run.
Processing remains sequential, one parent image at a time.

Cutouts are reopened and checked before publication. File checksums are verified
before cache reuse; incomplete/corrupt cached products are rebuilt. Manifest JSON
is replaced atomically. An interrupted attempt can leave unreferenced files;
their presence alone does not establish that they are complete or selected.

## Target CSV override

`run` and `validate` accept `--targets path/to/targets.csv`. This replaces the
YAML target list before validation, and may supply targets omitted from the YAML.
The CSV path follows the shell working directory, while paths inside YAML remain
relative to that YAML file.

CSV headers are `id,ra,dec` for decimal ICRS degrees or `id,x,y` for parent pixels.
Aliases `name`/`target_id` and `ra_deg`/`dec_deg` are accepted case-insensitively.
An omitted ID column generates IDs by nonempty row order. Explicit blank IDs,
duplicate IDs, ambiguous columns, malformed rows, NaNs and out-of-range sky
coordinates are errors with line numbers. Extra columns are retained as string
`metadata` on the target, without numeric inference that could destroy identifiers
with leading zeroes. UTF-8 CSVs with a byte-order mark are supported.

## GUI execution and saved jobs

Run progress and errors appear in the browser. Successful runs provide their
manifest path, cutout counts and a manifest download. A failed pipeline exposes
its error; pipeline manifests remain in the configured run output directories.
Closing or refreshing a tab does not cancel the run. Refresh reconnects to the
last submission while the server is alive. Keep the terminal open; interrupting
the GUI server stops serving requests but allows an active worker to finish its
cleanup. Only one GUI-owned run can execute at a time. Existing pipeline locks
also protect runs initiated through other processes.

Each submitted configuration and job record is saved in
`<workspace>/.gladius-gui/<job-id>/`. These job records and scientific
outputs are local working data, not package assets. They are never published by
the GUI. Job history is retained on disk across server restarts; it is not loaded
into a new server session automatically.

## Live MAST CI

The **Live Roman MAST download** workflow runs on pushes to the repository's
default branch that change package, integration-test or workflow files. It also
has a **Run workflow** button. Add an Actions repository secret named
`MAST_API_TOKEN` using an account authorized for the Roman data you want to test.
A missing or rejected token fails the live test; normal unit tests remain offline.

The test samples five Level 2 datasets, checks a target query generated from a
real archive position, and downloads exactly one associated product through the
package's production staging function. It accepts only products with a known,
positive advertised size of at most **20 MiB** and enforces that limit on file
writes in the Linux worker. It checks the downloaded length and temporary-file
cleanup. No suitable small product is a failure, not a skipped or successful test.

A calibrated detector image is preferred when one fits the cap. In that case the
test also reads its science planes/metadata, extracts a cutout, and writes/reopens
an ASDF cutout. Otherwise it tests a smaller associated product, such as a preview
or ancillary file. The job summary and report explicitly distinguish
`calibrated-image-and-cutout` from `associated-product-download`; the latter does
not establish that full Roman detector images can be processed. The manual
**Require a calibrated image** option turns absence of a small calibrated image
into a failure, without increasing the cap.

Only test reports are uploaded as Actions artifacts, never the downloaded Roman
data or cutouts. The workflow does not run on pull requests. Its token is supplied
only to the live test step, and Astroquery is told not to save it to a credential
store. The job has a ten-minute timeout.

For a local opt-in run on Linux/macOS, with `MAST_API_TOKEN` already set:

```sh
python -m pip install '.[test]'
GLADIUS_LIVE_MAST=1 python -m pytest tests/integration -m live_mast -v
```


## Local MAST authentication

1. Open [MAST API tokens](https://auth.mast.stsci.edu/tokens).
2. Sign in with your STScI account, create a token, and copy it.
3. Run the command below, then paste the token at its hidden prompt.

A token authenticates your account. It does not grant access to restricted
observations; the account must already be authorized for those data.

Save the token locally:

```sh
gladius token
```

It updates only `MAST_API_TOKEN` in the current directory's `.env`, preserves
other settings and comments, and asks before replacing an existing token.
`--force` skips the replacement question, but the token prompt is still hidden.
The command refuses to fall back to echoed input when a suitable terminal is
unavailable. It sets owner-only file permissions on macOS/Linux; on Windows,
file access follows the account's filesystem permissions.

Use `gladius token --env-file /path/to/credentials.env` to choose another file.
Do not pass the token as a shell argument. Alternatively copy the repository's
`.env.example` to `.env`, then edit it locally:

```text
MAST_API_TOKEN=your_token_here
```

Use your own MAST token from an account authorized for the requested Roman data.
Do not paste it into YAML, the browser, logs or Git. The repository ignores `.env`
and `.env.*` except the empty `.env.example` template. In a different repository,
add your own ignore rule. Restrict the file to your account on shared machines
(for example, `chmod 600 .env` on macOS/Linux).

- **GUI:** put `.env` directly in the `--workspace` directory. Without
  `--workspace`, this is the directory where you launch Gladius. It is loaded
  once at server startup. After changing the file, stop and restart the server;
  reloading the browser is insufficient. Editing the UI's Working directory or
  loading a YAML does not load a different environment file.
- **CLI:** `gladius run /path/to/config.yaml` loads `/path/to/.env` before running.
  Validation and configuration-generation commands do not load it.
- **MAST demo:** `gladius demo mast-demo` loads `.env` from the launch directory
  before querying the archive. Its generated YAML contains no token.
- **Python:** call `load_environment("/path/to/workspace")` explicitly before
  `run(config)`. Importing Gladius and loading YAML do not change the environment.

Only the specified directory is checked; parent directories are not searched.
`run`, `gui`, and `demo` accept `--env-file` to override their default credential
location; an explicitly requested missing file is an error. Python callers can
use `load_environment(env_file="/path/to/credentials.env")` too.
Already-set environment variables win, including empty values. Remove an old
shell variable with `unset MAST_API_TOKEN` before launching if you want the file
to supply it. Values are read literally, without shell execution or `${...}`
interpolation. Tokens are not included in downloaded YAML or job configurations.
A GitHub Actions secret is separate and cannot supply a local GUI token.

## GUI controls and testing

The GUI’s **Make cutouts** button calls the same pipeline as `gladius run`.
**Load test** makes real MAST metadata queries for up to five Level 2 datasets,
selects the smallest known-size calibrated product in that sample, and loads a
one-target, 64 × 64 ASDF configuration pinned to the dataset and exact product
filename. It does not download images or start a run. The UI shows the advertised
full-parent download size; the parent may be much larger than the cutout. Click
Make to download it. An inaccessible archive, timeout or empty sample produces an
error, never fabricated example data. Local archive access uses the launching
environment’s MAST_API_TOKEN; a repository secret is available only to Actions.
This one-image GUI test is distinct from CI’s 20 MiB associated-product smoke test.
`inputs.product_filename` optionally restricts products to one exact filename.

Manual targets support ICRS, Galactic and barycentric true ecliptic coordinates
(equinox J2000), all in decimal degrees, plus zero-based parent pixels. Astropy
converts sky frames to ICRS before the YAML is written. Non-ICRS input frame and
coordinates are retained as target metadata. Ecliptic does not infer distance,
proper motion or a different observing epoch. CSV ingestion still uses its
explicit ICRS/pixel column conventions.

The working directory starts from `--workspace`, which defaults to the launch
folder, and is editable. The corrected-WCS directory defaults to `gaia_wcs`, the
external correction tool’s default output location; Gladius only reads existing
corrections and does not run that tool or create the correction folder.

The WCS policy help changes with the selection. Numerical validation fails a
parent from the revision’s completed outputs if its supplied transform is inconsistent.
With continue-on-error enabled later images can be tried. Validation cannot
establish absolute sky accuracy. Corrected mode reads and validates the separate
correction and preserves the original transform.

The autocorrelation screen uses the central `tile_size` square in the cutout.
`radius` is the maximum offset from zero lag in the autocorrelation map used for
shape moments, not a sky aperture. A threshold of 2.0, with exploratory inspection
around 1.5–3.0, is a starting suggestion only; this method is uncalibrated. Ratios
at or above the threshold are flagged. Insufficient tile/signal also flags the
screen; native cutouts remain saved. A 150-pixel cutout is 150 × 150 native pixels,
not a promise of square angular pixels.

Resume reuses checksum-verified outputs for identical configuration, code and
dependency versions; without a previous run it starts normally. Parent discovery
and reading still occur. Lock timeout is how long to wait for another process
writing within the same output directory; 0 fails immediately, and is unrelated to network
timeouts. Continue-on-error handles failures inside individual image/target work
(download, read, WCS, coordinate inversion, extraction, product validation/write).
It records errors and keeps the final run failed. Configuration, initial archive
discovery, run-lock and stack-phase failures remain fatal. Quality flags are
recorded decisions, not exceptions governed by continue-on-error.

Coordinate-frame reference: [Astropy transformations](https://docs.astropy.org/en/stable/coordinates/transforming.html)
and [BarycentricTrueEcliptic](https://docs.astropy.org/en/stable/api/astropy.coordinates.BarycentricTrueEcliptic.html).
