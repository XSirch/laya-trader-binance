from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def _bucket(value: float, edges: list[float], labels: list[str]) -> str:
    if value is None or not math.isfinite(float(value)):
        return "unknown"
    i = int(np.digitize([float(value)], edges, right=False)[0])
    return labels[min(i, len(labels) - 1)]


def _state_for_prefix(row: pd.Series, prefix: str = "") -> dict[str, Any]:
    g = lambda name: float(row.get(prefix + name, np.nan))
    return {
        "trend_fast": _bucket(
            g("trend_fast_atr"),
            [-1.5, -0.5, -0.15, 0.15, 0.5, 1.5],
            ["extreme_down", "strong_down", "down", "flat", "up", "strong_up", "extreme_up"],
        ),
        "trend_slow": _bucket(
            g("trend_slow_atr"),
            [-2.0, -0.75, -0.2, 0.2, 0.75, 2.0],
            ["extreme_down", "strong_down", "down", "flat", "up", "strong_up", "extreme_up"],
        ),
        "rsi": _bucket(g("rsi14"), [30, 45, 55, 70], ["oversold", "low", "neutral", "high", "overbought"]),
        "adx": _bucket(g("adx14"), [15, 22, 30, 45], ["very_weak", "weak", "trend", "strong", "extreme"]),
        "price_vs_ema20": _bucket(
            g("dist_ema20_atr"),
            [-1.5, -0.5, -0.15, 0.15, 0.5, 1.5],
            ["far_below", "below", "slightly_below", "near", "slightly_above", "above", "far_above"],
        ),
        "price_vs_ema200": _bucket(
            g("dist_ema200_atr"),
            [-3, -1, -0.25, 0.25, 1, 3],
            ["far_below", "below", "slightly_below", "near", "slightly_above", "above", "far_above"],
        ),
        "return_1": _bucket(
            g("ret_1_z"), [-2, -0.75, -0.2, 0.2, 0.75, 2],
            ["crash", "strong_down", "down", "flat", "up", "strong_up", "spike"],
        ),
        "return_4": _bucket(
            g("ret_4_z"), [-2, -0.75, -0.2, 0.2, 0.75, 2],
            ["crash", "strong_down", "down", "flat", "up", "strong_up", "spike"],
        ),
        "volume": _bucket(
            g("volume_z"), [-1, -0.25, 0.25, 1, 2],
            ["very_low", "low", "normal", "elevated", "high", "extreme"],
        ),
        "flow": _bucket(
            g("flow_imbalance"), [-0.35, -0.12, 0.12, 0.35],
            ["strong_sell", "sell", "balanced", "buy", "strong_buy"],
        ),
        "volatility": _bucket(
            g("atr_pct"), [0.0025, 0.005, 0.01, 0.02],
            ["very_low", "low", "normal", "high", "extreme"],
        ),
        "candle_location": _bucket(
            g("close_location"), [0.2, 0.4, 0.6, 0.8],
            ["near_low", "lower", "middle", "upper", "near_high"],
        ),
    }


def build_state(
    row: pd.Series,
    symbol: str,
    interval: str,
    higher_timeframes: tuple[str, ...],
    include_symbol: bool = True,
) -> dict[str, Any]:
    ts = pd.Timestamp(row["timestamp"])
    hour = ts.hour
    if 0 <= hour < 7:
        session = "asia"
    elif 7 <= hour < 12:
        session = "europe"
    elif 12 <= hour < 16:
        session = "europe_us_overlap"
    elif 16 <= hour < 21:
        session = "us"
    else:
        session = "late_us"

    state: dict[str, Any] = {
        "market": "crypto_usdt_perpetual",
        "interval": interval,
        "session": session,
        "weekday": ts.day_name().lower(),
        "base": _state_for_prefix(row),
    }
    if include_symbol:
        state["symbol"] = symbol
    for tf in higher_timeframes:
        state[tf] = _state_for_prefix(row, prefix=f"tf_{tf}_")
    return state
