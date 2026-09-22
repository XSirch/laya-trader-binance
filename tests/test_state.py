import pandas as pd

from laya_trader.dataset.state import build_state


def test_state_never_serializes_label_or_future_columns():
    row = pd.Series(
        {
            "timestamp": pd.Timestamp("2026-01-01T12:00:00Z"),
            "trend_fast_atr": 0.4,
            "trend_slow_atr": 0.2,
            "rsi14": 60,
            "adx14": 25,
            "dist_ema20_atr": 0.5,
            "dist_ema200_atr": 1.0,
            "ret_1_z": 0.2,
            "ret_4_z": 0.4,
            "volume_z": 1.0,
            "flow_imbalance": 0.2,
            "atr_pct": 0.01,
            "close_location": 0.7,
            "target_long": 0.99,
            "long_r": 2.0,
            "label_end_ts": pd.Timestamp("2026-01-01T16:00:00Z"),
        }
    )
    state = build_state(row, "BTCUSDT", "15m", (), True)
    text = str(state)
    assert "target_long" not in text
    assert "long_r" not in text
    assert "label_end" not in text
