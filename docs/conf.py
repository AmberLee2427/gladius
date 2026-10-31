"""Sphinx configuration for the independent package documentation."""

from gladius_roman import __version__

project = "Gladius"
author = "Gladius contributors"
copyright = "2026, Gladius contributors"
version = release = __version__
extensions = ["myst_parser", "sphinx.ext.autodoc", "sphinx.ext.viewcode"]
html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_css_files = ["family/family.css"]
html_js_files = ["family/family-theme.js"]
html_logo = "_static/gladius-logo.png"
html_favicon = "_static/gladius-emblem.png"
html_title = f"Gladius {release}"
html_theme_options = {
    "logo_only": True,
    "collapse_navigation": False,
    "sticky_navigation": True,
    "navigation_depth": 4,
}
exclude_patterns = ["_build", "README.md", ".ipynb_checkpoints"]
myst_enable_extensions = ["colon_fence"]
myst_heading_anchors = 3
