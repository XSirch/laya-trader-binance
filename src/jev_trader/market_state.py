"""Causal multi-parameter market states from complete Binance candles."""

from __future__ import annotations

import math

from .binance_data import Bar, HOUR_MS
from .strategies import rsi, sma


def ema(values, period):
    if not values:
        return []
    result = [values[0]]
    alpha = 2 / (period + 1)
    for value in values[1:]:
        result.append(alpha * value + (1 - alpha) * result[-1])
    return result


def wilder(values, period):
    result = [None] * len(values)
    if len(values) < period:
        return result
    result[period - 1] = sum(values[:period]) / period
    for i in range(period, len(values)):
        result[i] = (result[i - 1] * (period - 1) + values[i]) / period
    return result


def aggregate(bars, hours):
    interval = hours * HOUR_MS
    groups = {}
    for bar in bars:
        groups.setdefault(bar.open_ms // interval * interval, []).append(bar)
    result = []
    for timestamp, group in sorted(groups.items()):
        if [b.open_ms for b in group] != [timestamp + j * HOUR_MS for j in range(hours)]:
            raise ValueError("incomplete aggregate candle")
        extra = [sum(getattr(b, field) for b in group)
                 if all(getattr(b, field) is not None for b in group) else None
                 for field in ("quote_volume", "trades", "taker_buy_base")]
        result.append(Bar(timestamp, group[0].open, max(b.high for b in group),
                          min(b.low for b in group), group[-1].close,
                          sum(b.volume for b in group), *extra))
    return result


def states(bars):
    """Return indicator bundles after 200 bars; each prefix is self-contained."""
    close = [b.close for b in bars]
    averages = {n: sma(close, n) for n in (10, 20, 50, 100, 200)}
    exponential = {n: ema(close, n) for n in (12, 26, 50, 200)}
    macd = [a - b for a, b in zip(exponential[12], exponential[26])]
    macd_signal = ema(macd, 9)
    momentum = rsi(close, 14)
    true_range, plus_dm, minus_dm = [bars[0].high - bars[0].low], [0], [0]
    obv = [0]
    for i in range(1, len(bars)):
        b, prev = bars[i], bars[i - 1]
        true_range.append(max(b.high - b.low, abs(b.high - prev.close), abs(b.low - prev.close)))
        up, down = b.high - prev.high, prev.low - b.low
        plus_dm.append(up if up > down and up > 0 else 0)
        minus_dm.append(down if down > up and down > 0 else 0)
        obv.append(obv[-1] + (b.volume if b.close > prev.close else -b.volume if b.close < prev.close else 0))
    atr, plus, minus = (wilder(values, 14) for values in (true_range, plus_dm, minus_dm))
    dx = [100 * abs(p - m) / (p + m) if p is not None and p + m else 0
          for p, m in zip(plus, minus)]
    adx_values = wilder(dx[13:], 14)
    adx = [None] * 13 + adx_values
    result = [None] * len(bars)
    for i in range(200, len(bars)):
        b = bars[i]
        recent = bars[i - 19:i + 1]
        mean = averages[20][i]
        std = math.sqrt(sum((x.close - mean) ** 2 for x in recent) / 20)
        volume_mean = sum(x.volume for x in bars[i - 20:i]) / 20
        volume_std = math.sqrt(sum((x.volume - volume_mean) ** 2 for x in bars[i - 20:i]) / 20)
        stochastic_low = min(x.low for x in bars[i - 13:i + 1])
        stochastic_high = max(x.high for x in bars[i - 13:i + 1])
        returns = [close[j] / close[j - 1] - 1 for j in range(i - 19, i + 1)]
        ret_mean = sum(returns) / 20
        realized = math.sqrt(sum((r - ret_mean) ** 2 for r in returns) / 20)
        total_volume = sum(x.volume for x in recent)
        quote = sum(x.quote_volume for x in recent) if all(x.quote_volume is not None for x in recent) else None
        taker = sum(x.taker_buy_base for x in recent) if all(x.taker_buy_base is not None for x in recent) else None
        vwap = quote / total_volume if quote is not None and total_volume else None
        fib = {}
        for period in (60, 180):
            sample = bars[i - period + 1:i + 1]
            low_i = min(range(period), key=lambda j: sample[j].low)
            high_i = max(range(period), key=lambda j: sample[j].high)
            low, high = sample[low_i].low, sample[high_i].high
            levels = {str(ratio): high - ratio * (high - low) for ratio in (0.236, 0.382, 0.5, 0.618, 0.786)}
            fib[str(period)] = {"high_after_low": high_i > low_i,
                "retracement_fraction": (high - b.close) / (high - low) if high > low else 0,
                "distance_to_level_pct": {key: 100 * (b.close / value - 1) for key, value in levels.items()}}
        result[i] = {
            "trend": {"distance_sma_pct": {str(n): 100 * (b.close / values[i] - 1) for n, values in averages.items()},
                      "distance_ema_pct": {str(n): 100 * (b.close / values[i] - 1) for n, values in exponential.items()},
                      "sma50_slope_5bars_pct": 100 * (averages[50][i] / averages[50][i - 5] - 1),
                      "adx14": adx[i],
                      "plus_di14": 100 * plus[i] / atr[i] if atr[i] else 0,
                      "minus_di14": 100 * minus[i] / atr[i] if atr[i] else 0},
            "momentum": {"return_pct": {str(n): 100 * (b.close / close[i - n] - 1) for n in (1, 7, 30, 90)},
                         "rsi14": momentum[i], "macd_pct": 100 * macd[i] / b.close,
                         "macd_histogram_pct": 100 * (macd[i] - macd_signal[i]) / b.close,
                         "stochastic_k14": 100 * (b.close - stochastic_low) / (stochastic_high - stochastic_low)
                         if stochastic_high > stochastic_low else 50},
            "volatility": {"atr14_pct": 100 * atr[i] / b.close,
                           "realized20_per_bar_pct": 100 * realized,
                           "bollinger_position": (b.close - (mean - 2 * std)) / (4 * std) if std else 0.5,
                           "bollinger_width_pct": 400 * std / mean,
                           "drawdown_from_high60_pct": 100 * (b.close / max(x.high for x in bars[i - 59:i + 1]) - 1)},
            "participation": {"relative_volume20": b.volume / volume_mean if volume_mean else 0,
                              "volume_zscore20": (b.volume - volume_mean) / volume_std if volume_std else 0,
                              "obv_change20_over_volume": (obv[i] - obv[i - 20]) / total_volume if total_volume else 0,
                              "taker_buy_fraction20": taker / total_volume if taker is not None and total_volume else None,
                              "distance_vwap20_pct": 100 * (b.close / vwap - 1) if vwap else None,
                              "quote_volume": b.quote_volume, "trade_count": b.trades},
            "structure": {"distance_prior_high20_pct": 100 * (b.close / max(x.high for x in bars[i - 20:i]) - 1),
                          "distance_prior_low20_pct": 100 * (b.close / min(x.low for x in bars[i - 20:i]) - 1),
                          "close_position_in_bar": (b.close - b.low) / (b.high - b.low) if b.high > b.low else 0.5,
                          "fibonacci": fib},
        }
    return result


def rounded(value):
    if isinstance(value, dict):
        return {k: rounded(v) for k, v in value.items()}
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("nonfinite market feature")
        return round(value, 6)
    return value


def composite_votes(state):
    d, h = state["daily"], state["four_hour"]
    t, m, v, p, st = (d[name] for name in ("trend", "momentum", "volatility", "participation", "structure"))
    trend = (t["distance_sma_pct"]["50"] > 0 and t["distance_sma_pct"]["200"] > 0
             and t["sma50_slope_5bars_pct"] > 0 and t["plus_di14"] > t["minus_di14"])
    momentum = (m["macd_histogram_pct"] > 0 and 45 <= m["rsi14"] <= 75
                and h["momentum"]["macd_histogram_pct"] > 0)
    participation = p["obv_change20_over_volume"] > 0 and p["relative_volume20"] >= 0.8
    safe = v["atr14_pct"] < 8 and v["bollinger_position"] < 1.2
    fib = st["fibonacci"]["60"]
    pullback = (fib["high_after_low"] and 0.382 <= fib["retracement_fraction"] <= 0.618
                and st["close_position_in_bar"] >= 0.5 and h["momentum"]["macd_histogram_pct"] > 0)
    relative = state["cross_asset"]["return30_minus_btc_pct"] >= 0
    breakout = st["distance_prior_high20_pct"] > 0 and p["relative_volume20"] > 1.2
    return {
        "confluence_trend": safe and trend and momentum and participation,
        "confluence_fibonacci": safe and trend and pullback,
        "confluence_breakout": safe and trend and breakout and relative,
        "confluence_regime": safe and trend and sum((momentum, participation, pullback, relative)) >= 2,
    }
