"""Sphinx configuration for the independent package documentation."""

from roman_cutouts import __version__

project = "Roman event cutouts"
author = "Roman event cutouts contributors"
copyright = "2026, Roman event cutouts contributors"
version = release = __version__
extensions = ["myst_parser", "sphinx.ext.autodoc", "sphinx.ext.viewcode"]
html_theme = "alabaster"
exclude_patterns = ["_build", "README.md", "commissioning-handoff.md"]
