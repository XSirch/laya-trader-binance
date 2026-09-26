"""Fixed, causal long-or-flat spot strategies for the first research pass."""

from __future__ import annotations

from dataclasses import dataclass

from .binance_data import Bar


@dataclass(frozen=True)
class Candidate:
    name: str
    family: str
    fast: int = 0
    slow: int = 0


# Frozen before looking at the new replay results. No grid search on validation data.
CANDIDATES = (
    Candidate("hold", "hold"),
    Candidate("trend_24_96", "trend", 24, 96),
    Candidate("trend_48_192", "trend", 48, 192),
    Candidate("breakout_24_12", "breakout", 24, 12),
    Candidate("breakout_72_24", "breakout", 72, 24),
    Candidate("rsi2_10_60", "rsi", 2, 10),
    Candidate("rsi14_30_55", "rsi", 14, 30),
    Candidate("momentum_24", "momentum", 24, 200),
)


def sma(values: list[float], window: int) -> list[float | None]:
    if window < 1:
        raise ValueError("window must be positive")
    total = 0.0
    result: list[float | None] = []
    for index, value in enumerate(values):
        total += value
        if index >= window:
            total -= values[index - window]
        result.append(total / window if index + 1 >= window else None)
    return result


def rsi(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return result
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gain = sum(max(value, 0) for value in changes[:period]) / period
    loss = sum(max(-value, 0) for value in changes[:period]) / period

    def score(g: float, l: float) -> float:
        if g == l == 0:
            return 50.0
        if l == 0:
            return 100.0
        return 100 - 100 / (1 + g / l)

    result[period] = score(gain, loss)
    for index in range(period + 1, len(values)):
        change = values[index] - values[index - 1]
        gain = (gain * (period - 1) + max(change, 0)) / period
        loss = (loss * (period - 1) + max(-change, 0)) / period
        result[index] = score(gain, loss)
    return result


def make_signals(bars: list[Bar], candidate: Candidate) -> list[bool]:
    """Signal at index t uses bars through t; execution occurs at open t+1."""
    closes = [bar.close for bar in bars]
    result = [False] * len(bars)
    if candidate.family == "hold":
        return [True] * len(bars)
    if candidate.family == "trend":
        fast = sma(closes, candidate.fast)
        slow = sma(closes, candidate.slow)
        for index, close in enumerate(closes):
            if slow[index] is not None:
                result[index] = fast[index] > slow[index] and close > slow[index]
        return result
    if candidate.family == "breakout":
        in_trade = False
        for index, close in enumerate(closes):
            if index >= candidate.fast:
                previous_high = max(bar.high for bar in bars[index - candidate.fast:index])
                previous_low = min(bar.low for bar in bars[index - candidate.slow:index])
                if in_trade and close < previous_low:
                    in_trade = False
                elif not in_trade and close > previous_high:
                    in_trade = True
            result[index] = in_trade
        return result
    if candidate.family == "rsi":
        momentum = rsi(closes, candidate.fast)
        trend = sma(closes, 200)
        exit_level = 60 if candidate.fast == 2 else 55
        in_trade = False
        for index, close in enumerate(closes):
            if momentum[index] is not None and trend[index] is not None:
                if in_trade and (momentum[index] >= exit_level or close < trend[index]):
                    in_trade = False
                elif not in_trade and close > trend[index] and momentum[index] <= candidate.slow:
                    in_trade = True
            result[index] = in_trade
        return result
    if candidate.family == "momentum":
        trend = sma(closes, candidate.slow)
        for index, close in enumerate(closes):
            if index >= candidate.fast and trend[index] is not None:
                result[index] = (close / closes[index - candidate.fast] - 1 > 0.02
                                 and close > trend[index])
        return result
    raise ValueError(f"unknown strategy family: {candidate.family}")


def causal_state(bars: list[Bar], signal_index: int, symbol: str,
                 strategy_name: str) -> dict:
    """Compact Jev input using only the completed signal bar and earlier bars."""
    if signal_index < 200:
        raise ValueError("need 200 completed bars for Jev state")
    closes = [bar.close for bar in bars[signal_index - 199:signal_index + 1]]
    latest = closes[-1]
    returns = {str(hours): round(100 * (latest / closes[-hours - 1] - 1), 4)
               for hours in (1, 6, 24, 72)}
    highest = max(bar.high for bar in bars[signal_index - 23:signal_index + 1])
    lowest = min(bar.low for bar in bars[signal_index - 23:signal_index + 1])
    return {
        "symbol": symbol,
        "strategy": strategy_name,
        "bar_close_utc_ms": bars[signal_index].open_ms + 3_600_000,
        "last_close": round(latest, 8),
        "returns_percent": returns,
        "distance_from_sma_24_percent": round(100 * (latest / (sum(closes[-24:]) / 24) - 1), 4),
        "distance_from_sma_200_percent": round(100 * (latest / (sum(closes) / 200) - 1), 4),
        "range_24h_percent": round(100 * (highest / lowest - 1), 4),
        "rsi_14": round(rsi(closes, 14)[-1], 3),
    }
