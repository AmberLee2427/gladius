"""Sphinx configuration for the independent package documentation."""

from gladius_roman import __version__

project = "Gladius"
author = "Gladius contributors"
copyright = "2026, Gladius contributors"
version = release = __version__
extensions = ["myst_parser", "sphinx.ext.autodoc", "sphinx.ext.viewcode"]
html_theme = "furo"
html_static_path = ["_static"]
html_css_files = ["gladius.css"]
html_logo = "_static/gladius-logo.png"
html_favicon = "_static/gladius-emblem.png"
html_title = f"Gladius {release}"
html_theme_options = {
    "sidebar_hide_name": True,
    "light_css_variables": {
        "color-brand-primary": "#62398b",
        "color-brand-content": "#62398b",
        "color-background-primary": "#fcfaff",
        "color-background-secondary": "#f2edf7",
    },
    "dark_css_variables": {
        "color-brand-primary": "#c9a4ed",
        "color-brand-content": "#c9a4ed",
        "color-background-primary": "#17121d",
        "color-background-secondary": "#241b2d",
    },
}
exclude_patterns = ["_build", "README.md", "commissioning-handoff.md", ".ipynb_checkpoints"]
myst_enable_extensions = ["colon_fence"]
myst_heading_anchors = 3
