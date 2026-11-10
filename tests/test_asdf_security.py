from io import BytesIO

import asdf
import numpy as np
import pytest
from astropy.io import fits

from gladius.io import read_correction, read_cutout, read_exposure


def _external_source_file(path):
    path.write_text(
        """#ASDF 1.0.0
#ASDF_STANDARD 1.6.0
%YAML 1.1
---
data: !<tag:stsci.edu:asdf/core/ndarray-1.1.0>
  source: file:///no-such-gladius-test/external.asdf
  datatype: float32
  byteorder: little
  shape: [2, 2]
...
"""
    )
    return path


@pytest.mark.parametrize(
    "reader",
    [read_exposure, read_correction, read_cutout],
    ids=["exposure", "correction", "cutout"],
)
def test_package_asdf_readers_reject_external_array_sources(reader, tmp_path):
    path = _external_source_file(tmp_path / "external.asdf")

    with pytest.raises(ValueError, match="External ASDF array sources"):
        reader(path)


def test_cutout_reader_rejects_external_array_reference(tmp_path):
    path = tmp_path / "reference.asdf"
    asdf.AsdfFile(
        {
            "reference": asdf.ExternalArrayReference(
                "file:///no-such-gladius-test/reference.fits", 0, "float32", (2, 2)
            )
        }
    ).write_to(path)

    with pytest.raises(ValueError, match="External ASDF array sources"):
        read_cutout(path)


def test_fits_cutout_reader_rejects_external_asdf_reference(tmp_path):
    metadata = BytesIO()
    asdf.AsdfFile(
        {"external": {"$ref": "file:///no-such-gladius-test/reference.asdf#/data"}}
    ).write_to(metadata)
    raw = np.frombuffer(metadata.getvalue(), dtype=np.uint8)
    metadata_hdu = fits.BinTableHDU.from_columns(
        [fits.Column(name="ASDF_METADATA", format=f"{len(raw)}B", array=[raw])],
        name="ASDFMETA",
    )
    path = tmp_path / "external-reference.fits"
    fits.HDUList([fits.PrimaryHDU(), metadata_hdu]).writeto(path)

    with pytest.raises(ValueError, match="External ASDF array sources"):
        read_cutout(path)


@pytest.mark.parametrize("location", ["plane", "ancillary"])
@pytest.mark.parametrize("dtype", ["U100000000", "object", "V1000000000"])
def test_fits_cutout_reader_rejects_unsafe_embedded_dtypes(location, dtype, tmp_path):
    plane_dtypes = {"data": "float32", "err": "float32", "dq": "uint8"}
    ancillary_extensions = {}
    if location == "plane":
        plane_dtypes["data"] = dtype
    else:
        ancillary_extensions["test_array"] = {"extension": "AUX0000", "dtype": dtype}
    metadata = BytesIO()
    asdf.AsdfFile(
        {
            "schema": "gladius/derived-1.0",
            "plane_dtypes": plane_dtypes,
            "ancillary_extensions": ancillary_extensions,
        }
    ).write_to(metadata)
    raw = np.frombuffer(metadata.getvalue(), dtype=np.uint8)
    hdus = [fits.PrimaryHDU()]
    hdus.extend(
        fits.ImageHDU(np.zeros((2, 2), dtype=np.float32), name=name)
        for name in ("SCI", "ERR", "DQ")
    )
    if location == "ancillary":
        hdus.append(fits.ImageHDU(np.zeros((2, 2), dtype=np.float32), name="AUX0000"))
    hdus.append(
        fits.BinTableHDU.from_columns(
            [fits.Column(name="ASDF_METADATA", format=f"{len(raw)}B", array=[raw])],
            name="ASDFMETA",
        )
    )
    path = tmp_path / "unsafe-dtype.fits"
    fits.HDUList(hdus).writeto(path)

    with pytest.raises(ValueError, match="FITS dtype metadata"):
        read_cutout(path)
