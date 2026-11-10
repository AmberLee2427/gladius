"""Opt-in commissioning checks, deliberately disabled in GitHub Actions."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


@pytest.mark.skipif(
    os.environ.get("GLADIUS_LOCAL_COMMISSIONING") != "1" or bool(os.environ.get("GITHUB_ACTIONS")),
    reason="Local only: set GLADIUS_LOCAL_COMMISSIONING=1 and MAST_API_TOKEN",
)
def test_commissioning_fidelity_and_gaia(tmp_path):
    """Expose only pass/fail; keep all commissioning worker output private."""
    worker = (
        "import sys; from pathlib import Path; "
        "sys.path.insert(0, sys.argv[1]); "
        "from test_commissioning_local import _check_commissioning; "
        "_check_commissioning(Path(sys.argv[2]))"
    )
    # Remove both the downloaded parent and derived cutouts, even after a failure.
    with tempfile.TemporaryDirectory(dir=tmp_path) as work:
        result = subprocess.run(
            [sys.executable, "-c", worker, str(Path(__file__).parent), work],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    if result.returncode:
        pytest.fail("Commissioning check failed; private diagnostics withheld", pytrace=False)


def _check_commissioning(work):
    """Require a commissioning image, exact cutout fidelity, and a Gaia match."""
    from astroquery.mast import MastMissions
    from gaia_reference import check_gaia_reference
    from standalone_fidelity import check_standalone_fidelity
    from test_mast_live import bounded_files, choose_product

    from gladius.inputs import staged

    assert not os.environ.get("GITHUB_ACTIONS"), "Commissioning checks are local only"
    token = os.environ.get("MAST_API_TOKEN")
    assert token, "MAST_API_TOKEN is required"
    missions = MastMissions(mission="roman")
    missions.TIMEOUT = 120
    missions.login(token=token, store_token=False)

    # Do not treat a generic Level 2 archive sample as proof of commissioning coverage.
    observations = missions.query_criteria(
        productLevel="2",
        program_category="COM",
        exposure_type="WFI_IMAGE",
        limit=5,
        select_cols=["fileSetName", "program_category", "exposure_type"],
    )
    assert len(observations), "No accessible commissioning imaging datasets"
    assert all(str(row["program_category"]) == "COM" for row in observations)
    product = choose_product(missions.get_unique_product_list(observations))

    with bounded_files(), staged(product, missions, work) as parent:
        check_standalone_fidelity(parent, work)
        # Restrict the catalog query to a central field, retaining the isolation margin.
        check_gaia_reference(parent, work, search_radius_deg=0.02)
        downloaded = Path(parent)
    assert not downloaded.exists(), "Temporary commissioning parent was not cleaned up"
