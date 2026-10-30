# Derived product format

The custom schema identifier is `gladius/derived-1.0`. It represents derived
cutouts and does not claim compliance with Roman ImageModel schemas.

| Field | Meaning |
| --- | --- |
| data / err / dq | Unresampled SCI, uncertainty and integer flags on the requested square grid. |
| ancillary_arrays | All other numeric arrays aligned on the parent's last two spatial axes, cropped on those same axes; leading dimensions survive. |
| mapping | Parent dimensions, virtual origin, valid source/destination bounds, zero-based convention and padding count. |
| wcs | Chosen parent astrometry translated by the virtual origin. |
| parent_wcs | Original parent astrometry, even when a correction was selected. |
| parent_metadata | Original ASDF tree values or complete FITS headers and non-spatial arrays, namespaced away from derived metadata. |
| cutout_metadata | New valid-coverage and virtual-grid footprint polygons, array shape and derived exposure timing. |
| provenance | Source filename/hash, target prediction, selected correction and its metadata/WCS, configuration, dependency versions, quality method and processing decisions. |

Spatial arrays in `parent_metadata` become descriptors containing their original
paths, shapes and dtypes. Their cropped contents are in the science planes or
`ancillary_arrays`; full parents are retained only when configured. Non-spatial
metadata arrays are retained in full. Unsupported array types or unrecognized
ASDF conversions fail explicitly. Original mission tags are not promised in a
new schema: values and their parent context are preserved, rather than claiming
the derived file is the original datamodel with smaller arrays.

A parent's `roman.meta.wcsinfo.s_region` therefore remains at
`parent_metadata.roman.meta.wcsinfo.s_region`. The cutout's own `s_region` is in
`cutout_metadata`, and the padded virtual extent has a separate
`virtual_s_region`. These are pixel-edge corner polygons; for curved distortion
boundaries they approximate the boundary, not a densely sampled exact contour.
An entirely padded cutout has no valid `s_region`.

## ASDF

ASDF stores all fields directly, including serializable GWCS/Time/Quantity
objects. Use `gladius_roman.io.read_cutout(path)` to obtain arrays, mapping,
parent metadata, provenance and exact WCS through a common Python interface.

## FITS

FITS contains empty PRIMARY, SCI, ERR and DQ image HDUs, followed by AUXnnnn image
HDUs where applicable and a package-specific ASDFMETA binary-table HDU. Its single
ASDF_METADATA byte column stores the metadata tree, exact WCS and ancillary
extension/dtype lookup. It does not use stdatamodels' ASDF-in-FITS linking schema;
use this package's reader to interpret it. FITS-only output still retains parent
metadata and exact GWCS in that extension.

SCI/ERR carry their respective units; DQ is dimensionless. Roman float16
uncertainties/auxiliary arrays are losslessly promoted to float32 for FITS image
storage, with the original dtype recorded and restored by the package reader. Mapping, exposure
timing, parent identity and WCS approximation are visible in conventional FITS
headers. A GWCS is approximated with TAN-SIP for FITS-only readers. The maximum
inverse pixel error is measured on a 9×9 grid and stored as WCSERR; exports
exceeding the configured tolerance fail. This is a sampled bound, not a proof
over every subpixel. Exact astrometry remains embedded. All output HDUs receive
checksums, and the writer reopens outputs to compare every plane and sample the
stored exact WCS before committing a manifest entry.

## Run records

The run contains `manifest.json`, `resolved-config.yaml`, content-specific cutout
folders, and optional `stack-manifest.json` and display stacks. Manifests provide
output SHA-256 hashes, failures and quality exclusions. They describe current
inputs; old unreferenced variants may remain and should not be inferred as active
members by globbing the output directory.
