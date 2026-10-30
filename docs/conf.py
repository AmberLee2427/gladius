"""Sphinx configuration for the independent package documentation."""

from gladius_roman import __version__

project = "Gladius"
author = "Gladius contributors"
copyright = "2026, Gladius contributors"
version = release = __version__
extensions = ["myst_parser", "sphinx.ext.autodoc", "sphinx.ext.viewcode"]
html_theme = "alabaster"
exclude_patterns = ["_build", "README.md", "commissioning-handoff.md"]
