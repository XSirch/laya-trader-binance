from __future__ import annotations

import numpy as np
import pandas as pd

KLINE_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trades",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
    "ignore",
]

NUMERIC_COLUMNS = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_volume",
    "trades",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
]


def _timestamp_unit(values: pd.Series) -> str:
    sample = float(values.dropna().iloc[0])
    return "us" if sample > 1e14 else "ms"


def normalize_klines(df: pd.DataFrame) -> pd.DataFrame:
    if list(df.columns) != KLINE_COLUMNS:
        if len(df.columns) != len(KLINE_COLUMNS):
            raise ValueError(f"expected {len(KLINE_COLUMNS)} kline columns, got {len(df.columns)}")
        df = df.copy()
        df.columns = KLINE_COLUMNS
    else:
        df = df.copy()

    for col in NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ("open_time", "close_time"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
        unit = _timestamp_unit(df[col])
        df[col] = pd.to_datetime(df[col], unit=unit, utc=True)
    df["timestamp"] = df["close_time"]
    df = df.loc[df["timestamp"].notna()].copy()
    df = df.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    return df.reset_index(drop=True)


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(avg_loss != 0, 100.0)


def _atr_adx(df: pd.DataFrame, period: int = 14) -> tuple[pd.Series, pd.Series]:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    up = high.diff()
    down = -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    return atr, adx


def compute_features(df: pd.DataFrame, prefix: str = "") -> pd.DataFrame:
    x = df.copy()
    close = x["close"]
    log_close = np.log(close.where(close > 0))
    x["ret_1"] = log_close.diff()
    x["ret_4"] = log_close.diff(4)
    x["ret_16"] = log_close.diff(16)

    x["ema20"] = close.ewm(span=20, adjust=False, min_periods=20).mean()
    x["ema50"] = close.ewm(span=50, adjust=False, min_periods=50).mean()
    x["ema200"] = close.ewm(span=200, adjust=False, min_periods=200).mean()
    x["atr14"], x["adx14"] = _atr_adx(x, 14)
    x["rsi14"] = _rsi(close, 14)

    atr = x["atr14"].replace(0, np.nan)
    x["dist_ema20_atr"] = (close - x["ema20"]) / atr
    x["dist_ema50_atr"] = (close - x["ema50"]) / atr
    x["dist_ema200_atr"] = (close - x["ema200"]) / atr
    x["trend_fast_atr"] = (x["ema20"] - x["ema50"]) / atr
    x["trend_slow_atr"] = (x["ema50"] - x["ema200"]) / atr
    x["atr_pct"] = atr / close
    x["range_atr"] = (x["high"] - x["low"]) / atr

    rolling_sigma = x["ret_1"].rolling(48, min_periods=24).std().replace(0, np.nan)
    x["ret_1_z"] = x["ret_1"] / rolling_sigma
    x["ret_4_z"] = x["ret_4"] / (rolling_sigma * np.sqrt(4))
    x["realized_vol_16"] = x["ret_1"].rolling(16, min_periods=12).std() * np.sqrt(16)

    log_volume = np.log1p(x["volume"].clip(lower=0))
    vol_mean = log_volume.rolling(48, min_periods=24).mean()
    vol_std = log_volume.rolling(48, min_periods=24).std().replace(0, np.nan)
    x["volume_z"] = (log_volume - vol_mean) / vol_std

    x["taker_buy_ratio"] = (
        x["taker_buy_base_volume"] / x["volume"].replace(0, np.nan)
    ).clip(0, 1)
    x["flow_imbalance"] = 2 * x["taker_buy_ratio"] - 1
    candle_range = (x["high"] - x["low"]).replace(0, np.nan)
    x["close_location"] = ((close - x["low"]) / candle_range).clip(0, 1)

    keep = [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "atr14",
        "rsi14",
        "adx14",
        "dist_ema20_atr",
        "dist_ema50_atr",
        "dist_ema200_atr",
        "trend_fast_atr",
        "trend_slow_atr",
        "atr_pct",
        "range_atr",
        "ret_1_z",
        "ret_4_z",
        "realized_vol_16",
        "volume_z",
        "flow_imbalance",
        "close_location",
    ]
    out = x[keep].copy()
    if prefix:
        rename = {c: f"{prefix}{c}" for c in keep if c != "timestamp"}
        out = out.rename(columns=rename)
    return out


def _aggregate_ohlcv(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    x = df.copy()
    bucket = x["timestamp"].dt.floor(timeframe)
    grouped = x.groupby(bucket, sort=True, observed=True)
    out = grouped.agg(
        timestamp=("timestamp", "max"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        quote_volume=("quote_volume", "sum"),
        trades=("trades", "sum"),
        taker_buy_base_volume=("taker_buy_base_volume", "sum"),
        taker_buy_quote_volume=("taker_buy_quote_volume", "sum"),
    ).reset_index(drop=True)
    return out


def add_higher_timeframes(
    normalized_klines: pd.DataFrame,
    base_features: pd.DataFrame,
    higher_timeframes: tuple[str, ...],
) -> pd.DataFrame:
    out = base_features.sort_values("timestamp").copy()
    for tf in higher_timeframes:
        aggregated = _aggregate_ohlcv(normalized_klines, tf)
        tf_features = compute_features(aggregated, prefix=f"tf_{tf}_")
        out = pd.merge_asof(
            out.sort_values("timestamp"),
            tf_features.sort_values("timestamp"),
            on="timestamp",
            direction="backward",
            allow_exact_matches=True,
        )
    return out


def build_feature_frame(
    normalized_klines: pd.DataFrame,
    higher_timeframes: tuple[str, ...] = ("1h", "4h"),
) -> pd.DataFrame:
    base = compute_features(normalized_klines)
    return add_higher_timeframes(normalized_klines, base, higher_timeframes)
