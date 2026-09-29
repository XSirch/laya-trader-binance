import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cycle05_minute_breakout.py"
SPEC = importlib.util.spec_from_file_location("cycle05_minute_breakout", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_minute_breakout_levels_use_only_previous_300_minutes():
    bars = pd.DataFrame({
        "high": np.arange(301, dtype=float) + 10,
        "low": np.arange(301, dtype=float) + 1,
        "volume": np.arange(301, dtype=float) + 1,
    })
    bars.loc[300, "high"] = 10_000
    bars.loc[300, "low"] = -10_000
    bars.loc[300, "volume"] = 10_000
    features = pd.DataFrame(index=pd.RangeIndex(301))

    result = MODULE.add_minute_breakout_levels(features, bars)

    assert result.loc[300, "don_high20"] == 309
    assert result.loc[300, "don_low20"] == 1
    assert result.loc[300, "volume_median20"] == 150.5


def test_minute_scanner_evaluates_each_close_and_keeps_existing_15m_cooldown():
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

    assert len(candidates) == 3
    assert candidates.signal_time.tolist() == [close_times[0], close_times[15], close_times[30]]
    assert candidates.side.tolist() == [1, 1, 1]
    assert candidates.signal_index.tolist() == [0, 15, 30]
