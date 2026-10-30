Python API
==========

The CLI and GUI call these same Python functions. No subprocess or YAML file is
required when constructing a ``RunConfig`` directly.

.. code-block:: python

   from pathlib import Path
   from gladius_roman import RunConfig, read_targets_csv, run

   config = RunConfig(
       targets=read_targets_csv("targets.csv"),
       inputs={"mode": "mast"},
       selection={"start": "2026-01-01", "end": "2026-02-01"},
       extraction={"size": 150, "no_overlap": "skip"},
       storage={"output_directory": "cutouts"},
   ).resolved(Path.cwd())
   manifest_path = run(config, progress=print)

Those dates illustrate the API; they do not imply available observations. To use
local files, replace inputs with ``{"mode": "directory", "directory": "images"}``.
To run a saved configuration, use ``run(load_config("config.yaml"))``.
``run`` returns the manifest path; inspect its status for recorded failures when
``continue_on_error`` is enabled. ``make_cutout`` is the lower-level in-memory
array operation and does not query, download or write files.

.. autofunction:: gladius_roman.parse_config

.. autoclass:: gladius_roman.Target

.. autofunction:: gladius_roman.inputs.mast_queries


.. autofunction:: gladius_roman.load_config

.. autoclass:: gladius_roman.RunConfig

.. autofunction:: gladius_roman.make_cutout

.. autoclass:: gladius_roman.Cutout
   :members:

.. autofunction:: gladius_roman.run

.. autofunction:: gladius_roman.io.read_exposure

.. autofunction:: gladius_roman.io.read_cutout

.. autofunction:: gladius_roman.io.write_cutout

.. autofunction:: gladius_roman.targets.read_targets_csv

.. autofunction:: gladius_roman.targets.parse_targets_csv

.. autofunction:: gladius_roman.web.serve
