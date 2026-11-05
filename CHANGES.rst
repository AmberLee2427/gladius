Unreleased
==========

* Add named run workspaces and numbered revisions, with shared verified native,
  serialization, quality and per-target display caches. Changed dates refresh
  discovery while unchanged products reuse cutouts. Quality and display edits
  no longer force extraction or download of already cached pixels.
* Trust stable MAST product identities across refreshed searches. Add explicit
  ``--refresh-inputs``, ``--fresh`` and ``--name`` controls; local files remain
  content-checked. Completed revisions preserve historical membership and bytes.
* Record current quality/configuration in revision manifests while reused native
  files retain their creation provenance. Document output layout and reuse rules.
* Rewrite local/Nexus tutorials around bounded input selection, complete YAML,
  parent/finding-chart context, all-image review and iterative screening. Add
  read-only audit/contact-sheet/parent-preview helpers using current revision
  quality decisions. The local practice field has a known elongated star, edge
  padding, multiple filters and real display-product examples.
* Simplify the Nexus tutorial credential path to an editable ``ENV_FILE`` example.

0.1.0a3 (2026-11-01)
===================

* Add local and Nexus tutorial launchers, bundled notebooks and matching kernel
  registration. The Nexus tutorial keeps its real-MAST workflow and explicitly
  selected credential file; interactive GUI cells are optional.
* Support notebook GUI iframes with explicit parent-origin permissions, loaded
  run configuration and shutdown cells. Fix horizontal overflow in narrow frames.
* Move the GUI theme toggle into the header, replacing the Local badge and
  keeping the footer clear.
* Structure tutorials for potential STScI contribution, with learning goals,
  dependency files, explanations, resources and cleared outputs.

0.1.0a2 (2026-11-01)
===================

* Add ``gladius token`` with hidden input and private dotenv persistence, explicit
  ``--env-file`` selection, and a real-data ``gladius demo mast-demo`` command
  with an advertised parent-size preflight and reusable YAML.
* Add Read the Docs build configuration, branded light/dark documentation and a
  getting-started guide. Add a separate real-MAST Nexus notebook requiring an
  explicit credential-file path; notebook outputs are excluded from distributions.
* Exclude internal handoff material from distributions, enforce archive content
  checks in CI, and fix minimal-dependency
  and Windows validation failures.
* Load local .env credentials at CLI/GUI startup without overriding shell values,
  and document local MAST authentication in the GUI and configuration guide.
* Add a real-MAST GUI test preset, Galactic/ecliptic input conversion, zero/unlimited
  stack limits, context-sensitive help, and icon-only theme controls.
* Rename the project to Gladius, distribution roman-gladius, import gladius
  and CLI gladius.
* Add an opt-in authenticated live MAST download workflow with a 20 MiB cap,
  generated-query checks, cleanup checks and explicit image/associated-product coverage.
* Add a bundled loopback web GUI with target CSV upload, configuration builder,
  YAML import/export, run button and live progress.
* Generate target-based Roman MAST searches with calibrated Level 2 defaults,
  configurable cone radius, query-level selections and deduplicated observations.
  Require Astroquery 0.4.11 for Roman support and report archive authorization errors.
* Document direct Python configuration/run calls and export Target/CSV helpers.
* Add --targets CSV overrides for run and validate; preserve catalogue columns
  as target metadata and embed imported targets in resolved configurations.

0.1.0a1 (unreleased)
===================

* Generate an independent package scaffold from the pinned STScI template.
* Add validated YAML, native SCI/ERR/DQ extraction, parent metadata retention,
  exact astrometry translation, derived ASDF/FITS formats and checksum-based resume.
* Add local and optional Roman MAST inputs, supplied corrected GWCS support,
  provisional autocorrelation screening and bounded display median stacks.
* Add offline examples, scientific regression tests, documentation and CI.

* Fix missing display-stack edge pixels caused by numerical WCS roundtrip errors.
  Real off-image coordinates remain excluded. Increase the synthetic demo's
  Gaussian background noise so its effect on the two-exposure median is visible.

* Add optional, timestamped GIF previews of sky-aligned exposures, with a shared
  brightness stretch and configurable playback duration, independently of median
  stacks. Add GUI controls, YAML settings and a synthetic documentation example.

* Add optional RGB colour composites with configurable channel filters, one
  common sky grid, per-filter medians and independent Astropy z-scale display
  limits, following the ICE dashboard's normalization approach. Record inputs,
  display settings and missing-filter skips in the stack manifest.

* Support the GUI behind Jupyter Server Proxy with relative asset/API paths,
  configured public origins, automatic JupyterHub URL detection, and --nexus /
  --public-url launch options. Print named-server-aware browser links at startup.

* Use ``gladius`` as the Python import and CLI name, and ``roman-gladius`` as
  the PyPI distribution name (normalized to ``roman_gladius`` in wheel filenames).
