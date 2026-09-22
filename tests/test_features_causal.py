import numpy as np
import pandas as pd

from laya_trader.features.core import build_feature_frame


def synthetic_klines(n=900):
    ts = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    close = 100 + np.linspace(0, 20, n) + np.sin(np.arange(n) / 11)
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + 0.5
    low = np.minimum(open_, close) - 0.5
    volume = 1000 + 100 * np.sin(np.arange(n) / 7)
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "quote_volume": volume * close,
            "trades": np.full(n, 100),
            "taker_buy_base_volume": volume * 0.52,
            "taker_buy_quote_volume": volume * close * 0.52,
        }
    )


def test_future_price_changes_do_not_change_past_features():
    base = synthetic_klines()
    original = build_feature_frame(base, ("1h", "4h"))
    changed = base.copy()
    changed.loc[700:, ["open", "high", "low", "close"]] *= 3.0
    perturbed = build_feature_frame(changed, ("1h", "4h"))

    cols = [c for c in original.columns if c != "timestamp"]
    pd.testing.assert_series_equal(original.loc[650, cols], perturbed.loc[650, cols])
