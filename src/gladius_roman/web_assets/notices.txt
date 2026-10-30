# Attribution and license scope

The new installable package under src/gladius_roman, its tests and project
documentation are licensed under BSD-3-Clause (LICENSE.txt). The distribution is
independent: no Astropy affiliation, STScI ownership or institutional endorsement
is claimed. The contributor copyright label does not override any underlying
rights held by contributors or their employers.

The scaffold was generated with Cookiecutter from the STScI package template.
TEMPLATE.json records its exact commit and options. The original boilerplate
license is retained in licenses/STSCI_TEMPLATE_LICENSE.txt. Institutional
branding and project-specific administrative workflows were adapted or removed.

The native geometry convention was adapted from the commissioning extraction
helper supplied with this project. The new autocorrelation implementation is
independent and does not import roman_ice_sim or assert identical metrics.

local-snapshot/, nexus-snapshot/, nexus-source-snapshot.zip and .agents/ are
historical/reference or working material and are excluded from built packages.
This package license does not relicense those collections. In particular,
nexus-snapshot/external_reference/gaia_wcs_correction.py is not distributed or
imported by the package; its separate ownership/licensing remains unresolved.
No external Gaia solving code was incorporated.

The Gladius logo drafts in assets/brand were generated from the user-supplied
concept. The bundled RGES-PIT logo was supplied through the team's local website
source. Project branding retains its respective ownership; the package's BSD
license is not a grant of rights to RGES-PIT names or logos.
