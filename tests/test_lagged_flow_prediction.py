from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from jev_trader import lagged_flow_prediction as prediction


H = 3_600_000
T0 = 1_704_067_200_000


def bar(timestamp, price=100.0, *, volume=100.0, buy=50.0, trades=10):
    return SimpleNamespace(open_ms=timestamp, open=price, high=price * 1.01,
        low=price * 0.99, close=price, volume=volume, taker_buy_base=buy,
        quote_volume=volume * price, trades=trades)


def panel_for(times):
    fields = ("asset.is_BTCUSDT", "leader.BTCUSDT.return_1h", "own.return_1h")
    panel = {}
    for timestamp in times:
        for i, symbol in enumerate(prediction.SYMBOLS):
            panel[(timestamp, symbol)] = {"execution_ms": timestamp, "symbol": symbol,
                "latest_observed_close_ms": timestamp - H,
                "features": [float(symbol == "BTCUSDT"), None if symbol == "BTCUSDT" else .001,
                             .002 + i * .0001], "context_sha256": "a" * 64}
    return panel, fields


def spots_through(last):
    return {symbol: {timestamp: bar(timestamp, 100 + (timestamp - T0) / (100 * H))
                     for timestamp in range(T0, last + H, H)}
            for symbol in prediction.SYMBOLS}


def test_lag_features_require_complete_bars_and_do_not_impute_zero_volume():
    spot = {T0: bar(T0, 100), T0 + H: bar(T0 + H, 101), T0 + 2 * H: bar(T0 + 2 * H, 102)}
    ret, flow = prediction._lag_values(spot, T0 + 2 * H, 2)
    assert ret == pytest.approx(.02)
    assert flow == 0
    assert prediction._lag_values({**spot, T0 + H: bar(T0 + H, 101, volume=0)}, T0 + 2 * H, 2) == (None, None)
    assert prediction._lag_values({T0: bar(T0, 100), T0 + 2 * H: bar(T0 + 2 * H, 102)},
                                  T0 + 2 * H, 2) == (None, None)


def test_eight_hour_label_becomes_available_after_exit_candle_close():
    panel, _ = panel_for([T0])
    spot = spots_through(T0 + 8 * H)
    labels, unavailable = prediction.labels_for(panel, spot)
    outcome = labels[(T0, "BTCUSDT")]
    assert not unavailable
    assert outcome["label_end_ms"] == T0 + 8 * H
    assert outcome["available_ms"] == T0 + 9 * H
    assert outcome["true_return"] > 0


def test_missing_intermediate_hour_invalidates_label_instead_of_bridging_gap():
    panel, _ = panel_for([T0])
    spot = spots_through(T0 + 8 * H)
    del spot["BTCUSDT"][T0 + 4 * H]
    labels, unavailable = prediction.labels_for(panel, spot)
    assert (T0, "BTCUSDT") not in labels
    assert unavailable[0]["failure_hour_ms"] == T0 + 4 * H


def test_training_excludes_recent_open_labels_and_uses_only_strictly_available_events():
    panel, fields = panel_for([T0, T0 + 8 * H, T0 + 16 * H])
    spots = spots_through(T0 + 24 * H)

    class MeanEstimator:
        def __init__(self, **_kwargs):
            self.value = 0.0

        def fit(self, _x, y, sample_weight=None):
            self.value = float(np.average(y, weights=sample_weight))
            return self

        def predict(self, x):
            return np.full(len(x), self.value)

    runtime = {"numpy": "test", "scikit-learn": "test"}
    with patch.object(prediction, "MIN_TRAINING_ROWS", 4), \
         patch.object(prediction, "_runtime", return_value=(MeanEstimator, nullcontext,
               lambda rows: np.asarray(rows, dtype=np.float64), runtime)):
        result = prediction.build_forecasts(panel, fields, spots)

    at_one_block = [(T0 + 8 * H, asset) for asset in prediction.SYMBOLS]
    assert all(key not in result["predictions"]["own_hgb"] for key in at_one_block)
    at_two_blocks = [(T0 + 16 * H, asset) for asset in prediction.SYMBOLS]
    assert all(key in result["predictions"]["leader_hgb"] for key in at_two_blocks)
    assert len(result["fits"]) == 1
    fit = result["fits"][0]
    assert fit["latest_label_available_ms"] < fit["fit_cutoff_ms"]
    assert fit["training_samples"] == 4
    assert fit["training_counts_by_symbol"] == {symbol: 1 for symbol in prediction.SYMBOLS}
