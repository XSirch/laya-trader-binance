from __future__ import annotations
import numpy as np
import pandas as pd
import pytest
from binance_multistrategy.data import validate_candles


def synthetic_bars(n: int = 18000, seed: int = 13, market: str = "spot") -> pd.DataFrame:
    """Artificial OHLC for software tests only, not a market dataset."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    drift = np.select([(t // 3500) % 3 == 0, (t // 3500) % 3 == 1], [.00016, -.00016], default=0)
    ret = rng.normal(0, .0017, n) + drift
    close = 100 * np.exp(np.cumsum(ret))
    opening = np.r_[100, close[:-1]]
    wiggle = rng.uniform(.0001, .001, n)
    bars = pd.DataFrame({"open_time": pd.date_range("2020-01-01", periods=n, freq="min", tz="UTC"),
                         "symbol": "SYNTHETIC", "market": market,
                         "open": opening, "close": close,
                         "high": np.maximum(opening, close) * (1 + wiggle),
                         "low": np.minimum(opening, close) * (1 - wiggle),
                         "volume": rng.lognormal(6, .5, n)})
    bars["taker_buy_base"] = bars.volume * rng.uniform(.3, .7, n)
    if market == "usd_m":
        for key in ["open", "high", "low", "close"]:
            bars[f"mark_{key}"] = bars[key]
        bars["funding_rate"] = 0.0
        bars["funding_event"] = 0
        bars.loc[::480, "funding_rate"] = .0001
        bars.loc[::480, "funding_event"] = 1
    return validate_candles(bars, market)


@pytest.fixture(scope="session")
def bars():
    return synthetic_bars()
