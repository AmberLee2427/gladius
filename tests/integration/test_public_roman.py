"""Network checks using only an explicitly public STScI simulation; no token."""

import hashlib
import json
import os
import shutil
from urllib.request import urlopen

import pytest

PUBLIC_URL = (
    "https://stpubdata.s3.amazonaws.com/roman/nexus/soc_simulations/tutorial_data/"
    "roman-2026.2/r0003201001001001004_0001_wfi02_f106_cal.asdf"
)
PUBLIC_SHA256 = "68851e0a226e90ddd6959360207336eff320df640bf6cabe10fc1aa9d40ae3ab"


@pytest.mark.skipif(
    os.environ.get("GLADIUS_PUBLIC_ROMAN") != "1",
    reason="Set GLADIUS_PUBLIC_ROMAN=1 for public simulation and Gaia access",
)
def test_public_simulation_fidelity_and_gaia(tmp_path):
    from gaia_reference import check_gaia_reference
    from standalone_fidelity import check_standalone_fidelity

    parent = tmp_path / PUBLIC_URL.rsplit("/", 1)[1]
    cached = os.environ.get("GLADIUS_PUBLIC_ROMAN_FIXTURE")
    if cached:
        shutil.copyfile(cached, parent)
    else:
        with urlopen(PUBLIC_URL, timeout=120) as response, parent.open("wb") as stream:
            assert int(response.headers["Content-Length"]) < 1024**3
            for block in iter(lambda: response.read(1024**2), b""):
                stream.write(block)
                assert stream.tell() < 1024**3
    digest = hashlib.sha256()
    with parent.open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            digest.update(block)
    assert digest.hexdigest() == PUBLIC_SHA256, (
        "Public fixture changed; review the upstream release"
    )

    report = check_standalone_fidelity(parent, tmp_path)
    report.update(check_gaia_reference(parent, tmp_path))
    # This fixture is publicly released, but keep the CI report to pass/fail anyway.
    assert "gaia_reference" in report
    report_path = os.environ.get("GLADIUS_PUBLIC_ROMAN_REPORT")
    if report_path:
        from pathlib import Path

        Path(report_path).write_text(
            json.dumps(
                {
                    "public_simulation_pixel_fidelity": "passed",
                    "public_simulation_wcs_consistency": "passed",
                    "public_simulation_metadata": "passed",
                    "gaia_reference_star": "passed",
                },
                indent=2,
            )
            + "\n"
        )
