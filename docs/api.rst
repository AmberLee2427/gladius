Python API
==========

The CLI and GUI call these same Python functions. No subprocess or YAML file is
required when constructing a ``RunConfig`` directly.

.. code-block:: python

   from pathlib import Path
   from roman_cutouts import RunConfig, read_targets_csv, run

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

.. autofunction:: roman_cutouts.parse_config

.. autoclass:: roman_cutouts.Target

.. autofunction:: roman_cutouts.inputs.mast_queries


.. autofunction:: roman_cutouts.load_config

.. autoclass:: roman_cutouts.RunConfig

.. autofunction:: roman_cutouts.make_cutout

.. autoclass:: roman_cutouts.Cutout
   :members:

.. autofunction:: roman_cutouts.run

.. autofunction:: roman_cutouts.io.read_exposure

.. autofunction:: roman_cutouts.io.read_cutout

.. autofunction:: roman_cutouts.io.write_cutout

.. autofunction:: roman_cutouts.targets.read_targets_csv

.. autofunction:: roman_cutouts.targets.parse_targets_csv

.. autofunction:: roman_cutouts.web.serve
