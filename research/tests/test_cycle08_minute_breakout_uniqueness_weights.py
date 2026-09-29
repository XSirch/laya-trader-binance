import importlib.util
from pathlib import Path

import pandas as pd
import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cycle08_minute_breakout_uniqueness_weights.py"
SPEC = importlib.util.spec_from_file_location("cycle08_minute_breakout_uniqueness_weights", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_overlapping_mature_labels_receive_less_weight_than_an_isolated_label():
    starts = pd.date_range("2026-01-01T00:00:00Z", periods=6, freq="min")
    labels = pd.DataFrame({
        "symbol": ["BTCUSDT"] * 7,
        "side": [1] * 7,
        "signal_time": list(starts) + [pd.Timestamp("2026-01-01T01:00:00Z")],
        "label_end_time": list(starts + pd.offsets.Minute(10))
        + [pd.Timestamp("2026-01-01T01:10:00Z")],
    })

    weights, diagnostics = MODULE.label_uniqueness_weights(labels)

    assert weights.mean() == pytest.approx(1.0)
    assert (weights.iloc[:6] < weights.iloc[6]).all()
    assert diagnostics["effective_sample_size"] < len(labels)
    assert diagnostics["effective_sample_fraction"] < 1.0


def test_weights_are_computed_only_from_the_mature_training_rows_supplied():
    starts = pd.to_datetime([
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:01:00Z",
        "2026-01-01T00:20:00Z",
    ], utc=True)
    labels = pd.DataFrame({
        "symbol": ["ETHUSDT"] * 3,
        "side": [1] * 3,
        "signal_time": starts,
        "label_end_time": starts + pd.offsets.Minute(5),
    })

    weights, _ = MODULE.label_uniqueness_weights(labels.iloc[:2].copy())

    assert weights.index.tolist() == [0, 1]
    assert weights.iloc[0] == pytest.approx(weights.iloc[1])


def test_non_positive_or_subminute_label_intervals_are_rejected():
    labels = pd.DataFrame({
        "symbol": ["BTCUSDT"],
        "side": [1],
        "signal_time": pd.to_datetime(["2026-01-01T00:00:00Z"], utc=True),
        "label_end_time": pd.to_datetime(["2026-01-01T00:00:30Z"], utc=True),
    })

    with pytest.raises(ValueError, match="whole minutes"):
        MODULE.label_uniqueness_weights(labels)
