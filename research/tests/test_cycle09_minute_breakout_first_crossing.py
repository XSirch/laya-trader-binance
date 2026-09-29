import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cycle09_minute_breakout_first_crossing.py"
SPEC = importlib.util.spec_from_file_location("cycle09_minute_breakout_first_crossing", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_long_scanner_emits_crossing_and_recrossing_but_not_sustained_state():
    minute_times = pd.date_range("2026-01-01T00:00:00Z", periods=5, freq="min")
    close_times = minute_times[1:]
    features = pd.DataFrame(0.0, index=close_times, columns=list(MODULE.engine.FEATURES[:-1]))
    features["atr"] = 1.0
    features["atr_pct"] = 0.01
    features["ema21"] = 100.0
    features["close"] = [101.0, 102.0, 99.0, 101.0]
    features["prior_close"] = [99.0, 101.0, 102.0, 99.0]
    features["volume"] = 2.0
    features["don_high20"] = 100.0
    features["don_low20"] = 90.0
    features["volume_median20"] = 1.0
    features["context_long"] = True
    features["context_short"] = False

    candidates = MODULE.generate_minute_breakout_candidates(
        features, "BTCUSDT", "usd_m", minute_times
    )

    assert candidates.signal_time.tolist() == [close_times[0], close_times[3]]
    assert candidates.side.tolist() == [1, 1]


def test_short_scanner_requires_a_cross_below_the_causal_channel():
    minute_times = pd.date_range("2026-01-01T00:00:00Z", periods=5, freq="min")
    close_times = minute_times[1:]
    features = pd.DataFrame(0.0, index=close_times, columns=list(MODULE.engine.FEATURES[:-1]))
    features["atr"] = 1.0
    features["atr_pct"] = 0.01
    features["ema21"] = 100.0
    features["close"] = [89.0, 88.0, 91.0, 89.0]
    features["prior_close"] = [91.0, 89.0, 88.0, 91.0]
    features["volume"] = 2.0
    features["don_high20"] = 110.0
    features["don_low20"] = 90.0
    features["volume_median20"] = 1.0
    features["context_long"] = False
    features["context_short"] = True

    candidates = MODULE.generate_minute_breakout_candidates(
        features, "BTCUSDT", "usd_m", minute_times
    )

    assert candidates.signal_time.tolist() == [close_times[0], close_times[3]]
    assert candidates.side.tolist() == [-1, -1]
