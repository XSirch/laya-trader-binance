import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cycle07_minute_breakout_no_cooldown.py"
SPEC = importlib.util.spec_from_file_location("cycle07_minute_breakout_no_cooldown", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_scanner_keeps_each_valid_minute_close_with_one_minute_cooldown():
    minute_times = pd.date_range("2026-01-01T00:00:00Z", periods=32, freq="min")
    close_times = minute_times[1:]
    features = pd.DataFrame(0.0, index=close_times, columns=list(MODULE.engine.FEATURES[:-1]))
    features["atr"] = 1.0
    features["atr_pct"] = 0.01
    features["ema21"] = 100.0
    features["close"] = 101.0
    features["volume"] = 2.0
    features["don_high20"] = 100.0
    features["don_low20"] = 90.0
    features["volume_median20"] = 1.0
    features["context_long"] = True
    features["context_short"] = False

    candidates = MODULE.generate_minute_breakout_candidates(
        features, "BTCUSDT", "usd_m", minute_times
    )

    assert MODULE.SIGNAL_COOLDOWN_MINUTES == 1
    assert len(candidates) == len(close_times)
    assert candidates.signal_time.tolist() == close_times.tolist()
    assert candidates.signal_index.tolist() == list(range(len(close_times)))


def test_c07_retains_the_completed_15_minute_atr_stop():
    minute_index = pd.date_range("2026-01-01T00:01:00Z", periods=16, freq="min")
    atr15 = pd.Series(
        [0.5, 1.5],
        index=pd.to_datetime(["2026-01-01T00:00:00Z", "2026-01-01T00:15:00Z"], utc=True),
    )
    features = pd.DataFrame({"atr": np.arange(16, dtype=float)}, index=minute_index)

    adjusted = MODULE.apply_stop_atr_15m(features, atr15)

    assert adjusted.loc[pd.Timestamp("2026-01-01T00:14:00Z"), "atr"] == 0.5
    assert adjusted.loc[pd.Timestamp("2026-01-01T00:15:00Z"), "atr"] == 1.5
