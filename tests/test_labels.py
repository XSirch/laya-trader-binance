import numpy as np
import pandas as pd

from laya_trader.config import LabelConfig
from laya_trader.labels.triple_barrier import add_triple_barrier_labels


def frame_from_prices(opens, highs, lows, closes, atr=1.0):
    n = len(opens)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC"),
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "atr14": np.full(n, atr, dtype=float),
        }
    )


def test_decision_enters_on_next_open_and_long_tp_wins():
    df = frame_from_prices(
        opens=[100, 100, 101, 102, 102, 102],
        highs=[100.5, 101, 103.0, 103, 103, 103],
        lows=[99.5, 99.5, 100.5, 101, 101, 101],
        closes=[100, 100.5, 102.5, 102, 102, 102],
    )
    cfg = LabelConfig(
        horizon_bars=3,
        take_profit_atr=2,
        stop_loss_atr=1,
        fee_bps_per_side=0,
        slippage_bps_per_side=0,
        min_edge_r=0,
    )
    out = add_triple_barrier_labels(df, cfg)
    first = out.iloc[0]
    assert first["entry_price"] == 100
    assert first["long_r"] == 2.0
    assert first["target_long"] > first["target_flat"]


def test_same_candle_tp_and_stop_is_dropped():
    df = frame_from_prices(
        opens=[100, 100, 100, 100, 100],
        highs=[100, 103, 101, 101, 101],
        lows=[100, 98, 99, 99, 99],
        closes=[100, 100, 100, 100, 100],
    )
    cfg = LabelConfig(
        horizon_bars=2,
        take_profit_atr=2,
        stop_loss_atr=1,
        fee_bps_per_side=0,
        slippage_bps_per_side=0,
        drop_ambiguous=True,
    )
    out = add_triple_barrier_labels(df, cfg)
    assert not (out["timestamp"] == df.loc[0, "timestamp"]).any()


def test_invalid_atr_rows_are_filtered_without_nan_targets():
    df = frame_from_prices(
        opens=[100, 100, 101, 102, 102, 102],
        highs=[100.5, 101, 103.0, 103, 103, 103],
        lows=[99.5, 99.5, 100.5, 101, 101, 101],
        closes=[100, 100.5, 102.5, 102, 102, 102],
    )
    df.loc[0, "atr14"] = np.nan
    cfg = LabelConfig(horizon_bars=3, take_profit_atr=2, stop_loss_atr=1)

    out = add_triple_barrier_labels(df, cfg)

    target_columns = [column for column in out if column.startswith("target_")]
    assert not out.empty
    assert not out[target_columns].isna().any().any()
