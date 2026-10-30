0.1.0a2 (unreleased)
===================

* Add a real-MAST GUI test preset, Galactic/ecliptic input conversion, zero/unlimited
  stack limits, context-sensitive help, and icon-only theme controls.
* Rename the project to Gladius, distribution gladius-roman, import gladius_roman
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
