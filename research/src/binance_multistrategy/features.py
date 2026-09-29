"""Only completed candles. No centered windows, ZigZag, bfill or future pivots."""
from __future__ import annotations
import numpy as np
import pandas as pd

PRICE_COLUMNS = ["open", "high", "low", "close"]


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    value = 100 - 100 / (1 + up / down.replace(0, np.nan))
    value = value.mask((down == 0) & (up > 0), 100)
    return value.mask((up == 0) & (down == 0), 50)


def indicators(bars: pd.DataFrame) -> pd.DataFrame:
    c, h, l, v = (bars[x].astype(float) for x in ["close", "high", "low", "volume"])
    f = pd.DataFrame(index=bars.index)
    for n in (9, 21, 50, 200):
        f[f"ema{n}"] = c.ewm(span=n, adjust=False, min_periods=n).mean()
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    f["atr"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    f["atr_pct"] = f.atr / c
    f["rsi"] = rsi(c)
    up, down = h.diff(), -l.diff()
    plus_dm = up.where((up > down) & (up > 0), 0)
    minus_dm = down.where((down > up) & (down > 0), 0)
    plus_di = 100 * plus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / f.atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / f.atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    f["adx"] = dx.fillna(0).ewm(alpha=1 / 14, adjust=False, min_periods=28).mean()
    f["di_spread"] = (plus_di - minus_di) / 100
    mid, std = c.rolling(20, min_periods=20).mean(), c.rolling(20, min_periods=20).std(ddof=0)
    f["bb_mid"], f["bb_up"], f["bb_low"] = mid, mid + 2 * std, mid - 2 * std
    f["bb_z"] = (c - mid) / std.replace(0, np.nan)
    f["bb_width"] = 4 * std / mid
    # The squeeze benchmark is itself strictly historical.
    f["squeeze"] = (f.bb_width < f.bb_width.shift().rolling(100).quantile(.25)).astype(float)
    f["don_high"] = h.shift().rolling(20, min_periods=20).max()
    f["don_low"] = l.shift().rolling(20, min_periods=20).min()
    f["break_high"] = (c - f.don_high) / f.atr
    f["break_low"] = (c - f.don_low) / f.atr
    f["volume_ratio"] = v / v.shift().rolling(20).mean().replace(0, np.nan)
    typical = (h + l + c) / 3
    # Explicitly a rolling 60-bar VWAP, not an exchange/session VWAP.
    f["vwap"] = (typical * v).rolling(60).sum() / v.rolling(60).sum().replace(0, np.nan)
    f["vwap_distance"] = (c - f.vwap) / f.atr
    macd = c.ewm(span=12, adjust=False, min_periods=26).mean() - c.ewm(span=26, adjust=False, min_periods=26).mean()
    f["macd_hist"] = (macd - macd.ewm(span=9, adjust=False, min_periods=9).mean()) / f.atr
    for n in (1, 5, 15, 60):
        f[f"ret{n}"] = c.pct_change(n, fill_method=None)
    for n in (21, 50, 200):
        f[f"distance_ema{n}"] = (c - f[f"ema{n}"]) / f.atr
    f["trend_gap"] = (f.ema21 - f.ema50) / f.atr
    f["ema_slope"] = f.ema50.diff(5) / f.atr
    f["realized_vol"] = np.log(c).diff().rolling(60).std(ddof=0)
    f["vol_ratio"] = f.atr_pct / f.atr_pct.shift().rolling(240).median().replace(0, np.nan)
    # Fibonacci anchors = prior rolling extrema, known now, not hindsight-selected swings.
    swing_h, swing_l = h.shift().rolling(120).max(), l.shift().rolling(120).min()
    f["range_position"] = (c - swing_l) / (swing_h - swing_l).replace(0, np.nan)
    for ratio in (.382, .5, .618):
        f[f"fib_up_{ratio}"] = (c - (swing_h - ratio * (swing_h - swing_l))) / f.atr
        f[f"fib_down_{ratio}"] = (c - (swing_l + ratio * (swing_h - swing_l))) / f.atr
    f["body_atr"] = (c - bars.open) / f.atr
    f["bar_range_atr"] = (h - l) / f.atr
    f["taker_imbalance"] = (2 * bars.taker_buy_base / v.replace(0, np.nan) - 1) if "taker_buy_base" in bars else np.nan
    return f.replace([np.inf, -np.inf], np.nan)


MODEL_BASE_FEATURES = [
    "atr_pct", "rsi", "adx", "di_spread", "bb_z", "bb_width", "squeeze",
    "break_high", "break_low", "volume_ratio", "vwap_distance", "macd_hist",
    "ret1", "ret5", "ret15", "ret60", "distance_ema21", "distance_ema50",
    "distance_ema200", "trend_gap", "ema_slope", "realized_vol", "vol_ratio",
    "range_position", "fib_up_0.382", "fib_up_0.5", "fib_up_0.618",
    "fib_down_0.382", "fib_down_0.5", "fib_down_0.618", "body_atr",
    "bar_range_atr", "taker_imbalance",
]
HIGHER_FEATURES = ["rsi", "adx", "atr_pct", "distance_ema200", "trend_gap", "ema_slope", "ret5"]
MODEL_FEATURES = MODEL_BASE_FEATURES + [f"{minutes}m_{name}" for minutes in (5, 15, 60) for name in HIGHER_FEATURES]


def build_features(bars: pd.DataFrame) -> pd.DataFrame:
    """bars sorted with 1-minute open_time; each row is known at open_time + 1m."""
    bars = bars.reset_index(drop=True)
    b = bars.copy()
    b.index = pd.DatetimeIndex(b.open_time) + pd.Timedelta(minutes=1)
    b.index.name = "decision_time"
    f = indicators(b)
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    if "taker_buy_base" in b:
        agg["taker_buy_base"] = "sum"
    for minutes in (5, 15, 60):
        # Input index is the CLOSE timestamp; (t-period, t] has exactly 'minutes' bars.
        resampler = b.resample(f"{minutes}min", closed="right", label="right", origin="epoch")
        higher = resampler.agg(agg)
        counts = resampler.close.count()
        higher = higher.loc[counts == minutes]  # No partial higher-timeframe candles.
        hf = indicators(higher)[HIGHER_FEATURES]
        aligned = hf.reindex(f.index, method="ffill")  # backward/as-of only
        for name in HIGHER_FEATURES:
            f[f"{minutes}m_{name}"] = aligned[name]
    f["close"], f["open"], f["high"], f["low"] = b.close, b.open, b.high, b.low
    f["decision_time"] = f.index
    f["bar_index"] = np.arange(len(f))
    up = (f["60m_distance_ema200"] > 0) & (f["15m_trend_gap"] > 0) & (f["15m_adx"] >= 20)
    down = (f["60m_distance_ema200"] < 0) & (f["15m_trend_gap"] < 0) & (f["15m_adx"] >= 20)
    f["regime"] = np.select([up, down], [1, -1], default=0)
    f["extreme_volatility"] = ((f.vol_ratio > 3) | (f.atr_pct > .025) | (f.bar_range_atr > 6))
    # Minimum 200 completed 1h bars; missing optional indicators are supported by HGB.
    f["ready"] = f[["atr", "rsi", "ema200", "60m_distance_ema200", "15m_adx"]].notna().all(axis=1)
    return f.reset_index(drop=True)
