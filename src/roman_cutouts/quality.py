"""A provisional, independently implemented autocorrelation elongation screen."""

from __future__ import annotations

import numpy as np
from scipy.signal import fftconvolve

from .config import Quality

METHOD = "roman-cutouts-acf-positive-moments-v1"


def assess(data, dq, options: Quality):
    """Measure central-tile autocorrelation second moments inside a fixed radius.

    Mask nonfinite, DO_NOT_USE and SATURATED pixels, subtract their valid-pixel
    mean, apply a Hann window, and measure positive autocorrelation moments.
    This is a display screen, not a calibrated scientific trailing classifier.
    """
    result = {
        "method": METHOD,
        "threshold": options.autocorrelation_limit,
        "tile_size": options.tile_size,
        "radius": options.radius,
        "status": "provisional",
        "accepted": True,
    }
    if options.autocorrelation_limit is None:
        return {**result, "reason": "disabled", "axis_ratio": None}
    n = options.tile_size
    if min(data.shape) < n:
        return {**result, "accepted": False, "reason": "insufficient_tile", "axis_ratio": None}
    y, x = [(s - n) // 2 for s in data.shape]
    tile = np.asarray(data[y : y + n, x : x + n], dtype=float)
    flags = np.asarray(dq[y : y + n, x : x + n])
    valid = np.isfinite(tile) & ((flags & 3) == 0)
    if valid.mean() < 0.5 or np.std(tile[valid]) == 0:
        return {**result, "accepted": False, "reason": "insufficient_signal", "axis_ratio": None}
    signal = np.where(valid, tile - tile[valid].mean(), 0)
    signal *= np.outer(np.hanning(n), np.hanning(n))
    acf = fftconvolve(signal, signal[::-1, ::-1], mode="full")
    yy, xx = np.indices(acf.shape, dtype=float)
    xx -= n - 1
    yy -= n - 1
    weights = np.where(xx**2 + yy**2 <= options.radius**2, np.maximum(acf, 0), 0)
    total = weights.sum()
    covariance = (
        np.array(
            [
                [np.sum(weights * xx * xx), np.sum(weights * xx * yy)],
                [np.sum(weights * xx * yy), np.sum(weights * yy * yy)],
            ]
        )
        / total
    )
    eigenvalues = np.linalg.eigvalsh(covariance)
    if not np.isfinite(eigenvalues).all() or eigenvalues[0] <= 0:
        return {**result, "accepted": False, "reason": "degenerate_acf", "axis_ratio": None}
    ratio = float(np.sqrt(eigenvalues[1] / eigenvalues[0]))
    accepted = ratio < options.autocorrelation_limit
    return {
        **result,
        "accepted": accepted,
        "axis_ratio": ratio,
        "reason": "accepted" if accepted else "autocorrelation_elongation",
    }
