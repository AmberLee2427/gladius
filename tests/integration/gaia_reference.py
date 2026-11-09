"""Independent catalog check of the standalone sky-coordinate extraction path."""

import importlib.util
import json
import subprocess
import sys
import warnings
from pathlib import Path

import asdf
import numpy as np
import yaml
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time

SCRIPT = Path(__file__).resolve().parents[2] / "standalone" / "roman_cutouts.py"


def check_gaia_reference(parent, work):
    """Check one predetermined isolated Gaia star, without fitting a new WCS."""
    from astroquery.gaia import Gaia

    spec = importlib.util.spec_from_file_location("gaia_cutout_script", SCRIPT)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    with asdf.open(parent, memmap=False) as af:
        node = af.tree.get("roman", af.tree)
        ny, nx = node["data"].shape
        wcs = node["meta"]["wcs"]
        epoch = node["meta"]["exposure"]["start_time"]
        epoch = epoch if isinstance(epoch, Time) else Time(epoch, scale="utc")
        center = SkyCoord(*script.pixel_to_world(wcs, (nx - 1) / 2, (ny - 1) / 2), unit="deg")
        corners = SkyCoord(
            *script.pixel_to_world(
                wcs, np.array([0, nx - 1, nx - 1, 0]), np.array([0, 0, ny - 1, ny - 1])
            ),
            unit="deg",
        )
        radius = float(np.max(center.separation(corners).deg)) + 0.01

        # Query a bounded field, including fainter neighbors for the isolation check.
        # Fail on truncation rather than declaring a star isolated from an incomplete list.
        query = f"""SELECT TOP 5001 source_id, ra, dec, pmra, pmdec, ref_epoch,
            phot_g_mean_mag FROM gaiadr3.gaia_source
            WHERE CONTAINS(POINT('ICRS', ra, dec),
            CIRCLE('ICRS', {center.ra.deg:.12f}, {center.dec.deg:.12f}, {radius:.12f}))=1
            AND phot_g_mean_mag < 19 AND pmra IS NOT NULL AND pmdec IS NOT NULL
            ORDER BY phot_g_mean_mag, source_id"""
        catalog = Gaia.launch_job_async(query, dump_to_file=False).get_results()
        assert 0 < len(catalog) < 5001, "Gaia field empty or truncated; choose a narrower field"
        stars = SkyCoord(
            ra=np.asarray(catalog["ra"]) * u.deg,
            dec=np.asarray(catalog["dec"]) * u.deg,
            pm_ra_cosdec=np.asarray(catalog["pmra"]) * u.mas / u.yr,
            pm_dec=np.asarray(catalog["pmdec"]) * u.mas / u.yr,
            obstime=Time(np.asarray(catalog["ref_epoch"]), format="jyear"),
        )
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*distance overridden.*")
            stars = stars.apply_space_motion(new_obstime=epoch)
        px, py = script.world_to_pixel(wcs, stars.ra.deg, stars.dec.deg)

        # Pick by catalog brightness, geometry, and catalog isolation, before looking
        # for a detection. A missing/misplaced image star must fail this check.
        chosen = None
        for i in range(len(stars)):
            if not (12 <= catalog["phot_g_mean_mag"][i] <= 18):
                continue
            if not (30 <= px[i] < nx - 30 and 30 <= py[i] < ny - 30):
                continue
            separation = stars[i].separation(stars).arcsec
            if np.count_nonzero(separation < 3) != 1:
                continue
            chosen = i
            break
        assert chosen is not None, "No isolated Gaia reference star in the parent footprint"
        star = stars[chosen]

    config = work / "gaia-reference.yaml"
    output = work / "gaia-reference"
    config.write_text(
        yaml.safe_dump(
            {
                "inputs": {"directory": str(parent.parent), "pattern": parent.name},
                "output": str(output),
                "size": 51,
                "targets": [
                    {"id": "gaia-reference", "ra": float(star.ra.deg), "dec": float(star.dec.deg)}
                ],
            }
        )
    )
    result = subprocess.run([sys.executable, str(SCRIPT), str(config)], capture_output=True)
    assert result.returncode == 0, "Gaia-coordinate standalone extraction failed"
    records = json.loads((output / "manifest.json").read_text())["results"]
    assert len(records) == 1 and records[0]["status"] == "ok"
    with asdf.open(output / records[0]["output"], memmap=False) as af:
        image = np.asarray(af["data"], dtype=float)
        error = np.asarray(af["err"], dtype=float)
        dq = np.asarray(af["dq"])
        predicted = script.world_to_pixel(af["wcs"], star.ra.deg, star.dec.deg)
        yy, xx = np.indices(image.shape)
        distance = np.hypot(xx - predicted[0], yy - predicted[1])
        good = np.isfinite(image) & np.isfinite(error) & (error > 0) & ((dq & 3) == 0)
        annulus = good & (distance >= 12) & (distance <= 20)
        assert np.count_nonzero(annulus) >= 50, "Insufficient clean background pixels"
        background = np.median(image[annulus])
        # Look over a fixed region, not a region centered on a fitted image position.
        aperture = good & (distance <= 8)
        weights = np.where(aperture, np.maximum(image - background, 0), 0)
        noise = np.sqrt(np.sum(np.where(aperture, error**2, 0)))
        assert weights.sum() > 20 * noise, "Gaia star not detected at integrated S/N > 20"
        cx = float(np.sum(weights * xx) / weights.sum())
        cy = float(np.sum(weights * yy) / weights.sum())
        measured = SkyCoord(*script.pixel_to_world(af["wcs"], cx, cy), unit="deg")
        offset = float(star.separation(measured).arcsec)
        assert offset < 0.3, f"Gaia reference-star offset {offset:.3f} arcsec exceeds 0.3"
    return {
        "gaia_reference": "isolated DR3 star, epoch-propagated; S/N > 20",
        "gaia_centroid_offset_arcsec": offset,
        "gaia_tolerance_arcsec": 0.3,
    }
