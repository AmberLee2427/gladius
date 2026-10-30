import numpy as np

from gladius_roman.config import Quality
from gladius_roman.quality import assess


def test_round_and_elongated_sources():
    yy, xx = np.indices((64, 64), dtype=float)
    options = Quality(autocorrelation_limit=1.8)
    dq = np.zeros((64, 64), np.uint32)
    round_source = np.exp(-((xx - 32) ** 2 + (yy - 32) ** 2) / 8)
    trail = np.exp(-((xx - 32) ** 2 / 80 + (yy - 32) ** 2 / 4))
    a, b = assess(round_source, dq, options), assess(trail, dq, options)
    assert a["accepted"] and abs(a["axis_ratio"] - 1) < 0.01
    assert not b["accepted"] and b["axis_ratio"] > 1.8
    dq[:] = 2
    assert assess(trail, dq, options)["reason"] == "insufficient_signal"
    assert assess(trail, dq, Quality())["reason"] == "disabled"
