Python API
==========

The CLI and GUI use these same Python functions. You can construct a
``RunConfig`` in Python or load one from a YAML file created in the GUI.

Configure and run in Python
---------------------------

This example searches MAST for the targets in a CSV, selects exposures by date,
and makes cutouts. Install Gladius first. For restricted
archive access, save your token with ``gladius token`` in the workspace directory.
The ``load_environment`` call below loads that directory's ``.env`` before the
archive is queried. Existing shell variables take precedence.

.. code-block:: python

   import json
   from pathlib import Path

   from gladius import RunConfig, load_environment, read_targets_csv, run

   # A Path object identifying the directory used for input and output paths.
   workspace = Path.cwd()

   # Load workspace/.env if present, without replacing existing shell variables.
   load_environment(workspace)

   # A list of Target objects: each has an ID, coordinates and optional metadata.
   targets = read_targets_csv(workspace / "targets.csv")

   # A RunConfig object containing validated settings for the whole run.
   config = RunConfig(
       run={"name": "bulge-field-test"},
       targets=targets,
       inputs={"mode": "mast"},  # Query the archive using the targets' RA/Dec.
       # Include exposure starts in January; exclude February 1 onwards.
       selection={"start": "2026-01-01", "end": "2026-02-01"},
       # Make 150 x 150 pixel cutouts; skip requests wholly outside an image.
       extraction={"size": 150, "no_overlap": "skip"},
       storage={"output_directory": "cutouts"},  # Save beneath workspace/cutouts.
   ).resolved(workspace)  # Fill in defaults and resolve relative paths here.

   # Query/download images and make cutouts, printing progress as work proceeds.
   # The return value is a Path to manifest.json, not an image or results object.
   manifest_path = run(config, progress=print)

   # Read the JSON run record into a Python dictionary to inspect the result.
   manifest = json.loads(manifest_path.read_text())
   print(manifest["status"])  # Overall run status: "complete" or "failed".

The dates above illustrate the API; they do not promise that the archive has
accessible images for that interval. To use local images, replace ``inputs`` with
``{"mode": "directory", "directory": "images"}``.

What the objects contain
~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 20 20 60

   * - Variable
     - Python type
     - Contents
   * - ``targets``
     - ``list[Target]``
     - Target IDs, coordinates and metadata read from the CSV.
   * - ``config``
     - ``RunConfig``
     - Targets, input source, exposure selections, cutout settings, WCS policy,
       quality/stack options, output location and execution settings. Omitted
       options receive defaults. ``.resolved(workspace)`` returns a configuration
       with paths resolved against that directory.
   * - ``manifest_path``
     - ``pathlib.Path``
     - Location of the JSON run record, typically
       ``cutouts/runs/<run-name>/<revision>/manifest.json``. Each named workspace
       has numbered revisions; unchanged stages can be reused across revisions.
   * - ``manifest``
     - ``dict``
     - Run status, configuration, per-input/target entries, output file paths and
       checksums, skipped work and recorded errors. The image arrays are stored
       in the output files, not in this dictionary.

When ``execution.continue_on_error`` is enabled, ``run`` can finish processing
later images and return a manifest whose status is ``failed``. Inspect the
manifest before treating a returned path as a successful run. Fatal errors still
raise an exception; their details are recorded in the run directory when possible.

Refresh inputs or change downstream settings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``run(config)`` reuses verified native cutouts, assessments and display products
when the inputs to those stages match. MAST input lists are pinned until discovery
settings change or an explicit refresh is requested:

.. code-block:: python

   # Re-query membership; trust known MAST product identities and reuse cutouts.
   manifest_path = run(config, refresh_inputs=True)

   # Force all stages, including MAST downloads, into a fresh revision.
   manifest_path = run(config, fresh=True)

Changing a quality threshold or enabling a composite creates a new revision
without extracting unchanged native cutouts. The revision manifest holds current
quality decisions; reused image files retain their creation provenance.
See :doc:`configuration` for the dependency table and named-run behavior.

Run a configuration saved by the GUI
------------------------------------

.. code-block:: python

   from pathlib import Path

   from gladius import load_config, load_environment, run

   # A Path to the YAML downloaded from the GUI.
   config_path = Path("config.yaml").resolve()

   # Load credentials stored beside that YAML file.
   load_environment(config_path.parent)

   # Read YAML, validate its settings and resolve its relative paths.
   config = load_config(config_path)

   # Execute those settings; receive the path to the JSON run record.
   manifest_path = run(config, progress=print)

Choose a different credential file
-----------------------------------

.. code-block:: python

   from gladius import load_environment

   # Load this particular file instead of workspace/.env.
   load_environment(env_file="/path/to/credentials.env")

An explicitly selected missing file is an error. Importing Gladius and loading a
configuration do not load credentials automatically in Python. See
`Local MAST authentication <configuration.html#local-mast-authentication>`_ for file locations and precedence.

Function and class reference
-----------------------------

``make_cutout`` copies arrays already in memory and returns a ``Cutout`` object.
It does not query MAST or write files. ``run`` performs the full configured
pipeline, including reading inputs and saving products.

.. autofunction:: gladius.parse_config

.. autoclass:: gladius.Target

.. autofunction:: gladius.inputs.mast_queries

.. autofunction:: gladius.inputs.mast_test_configuration


.. autofunction:: gladius.load_config

.. autoclass:: gladius.RunConfig

.. autofunction:: gladius.make_cutout

.. autoclass:: gladius.Cutout
   :members:

.. autofunction:: gladius.run

.. autofunction:: gladius.io.read_exposure

.. autofunction:: gladius.io.read_cutout

.. autofunction:: gladius.io.write_cutout

.. autofunction:: gladius.targets.read_targets_csv

.. autofunction:: gladius.targets.parse_targets_csv

.. autofunction:: gladius.web.serve

.. autofunction:: gladius.target_from_coordinates

.. autofunction:: gladius.load_environment

Review saved images without archive access
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

These helpers read a revision's current quality decisions. They include flagged
native cutouts rather than hiding them from inspection. Parent previews need a
retained parent or the unchanged original local file. They do not fetch data or
perform an independent astrometric match.

.. code-block:: python

   from IPython.display import display
   from gladius.inspection import audit_rows, contact_sheets, parent_preview

   # Every attempted pair, including skips and failures.
   rows = audit_rows(manifest_path)

   # Every completed cutout, including images flagged by the screen.
   for page in contact_sheets(manifest_path):
       display(page)

.. autofunction:: gladius.inspection.audit_rows

.. autofunction:: gladius.inspection.contact_sheets

.. autofunction:: gladius.inspection.parent_preview

.. autofunction:: gladius.inspection.image_preview
