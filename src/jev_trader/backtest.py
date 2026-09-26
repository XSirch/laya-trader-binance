"""Next-open spot execution with explicit one-way costs and equal capital sleeves."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .binance_data import Bar, utc_ms


@dataclass
class WindowResult:
    start: str
    end: str
    return_pct: float
    max_drawdown_pct: float
    trades: int
    positive_months: int
    months: int
    monthly_returns_pct: dict[str, float]
    symbol_returns_pct: dict[str, float]


def _month(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).strftime("%Y-%m")


def evaluate_window(frames: dict[str, list[Bar]], signals: dict[str, list[bool]],
                    start: str, end: str, side_cost: float) -> WindowResult:
    """Flat at each window start/end. Signals at t-1 act at open t."""
    if not (0 <= side_cost < 1):
        raise ValueError("invalid one-way cost")
    start_ms, end_ms = utc_ms(start), utc_ms(end)
    symbols = sorted(frames)
    if not symbols:
        raise ValueError("empty symbol universe")
    window_indices: dict[str, list[int]] = {}
    for symbol in symbols:
        bars = frames[symbol]
        if len(bars) != len(signals[symbol]):
            raise ValueError(f"signal length mismatch: {symbol}")
        indices = [i for i, bar in enumerate(bars[:-1])
                   if start_ms <= bar.open_ms < end_ms]
        if not indices or indices[0] == 0 or bars[indices[-1] + 1].open_ms != end_ms:
            raise ValueError(f"incomplete window or warmup for {symbol} {start}:{end}")
        if indices != list(range(indices[0], indices[-1] + 1)):
            raise ValueError(f"noncontiguous window: {symbol}")
        window_indices[symbol] = indices
    timeline = [frames[symbols[0]][i].open_ms for i in window_indices[symbols[0]]]
    if any([frames[symbol][i].open_ms for i in window_indices[symbol]] != timeline
           for symbol in symbols[1:]):
        raise ValueError("symbols have different window timestamps")

    equity = {symbol: 1.0 for symbol in symbols}
    position = {symbol: False for symbol in symbols}
    trades = 0
    portfolio_path = [(timeline[0], 1.0)]
    for offset, timestamp in enumerate(timeline):
        for symbol in symbols:
            i = window_indices[symbol][offset]
            desired = signals[symbol][i - 1]
            if desired and not position[symbol]:
                trades += 1
            bar, next_bar = frames[symbol][i:i + 2]
            raw_return = next_bar.open / bar.open - 1
            turnover = int(desired != position[symbol])
            factor = 1 + (raw_return if desired else 0) - turnover * side_cost
            if factor <= 0:
                raise ValueError("nonpositive equity factor")
            equity[symbol] *= factor
            position[symbol] = desired
        portfolio_path.append((frames[symbols[0]][window_indices[symbols[0]][offset] + 1].open_ms,
                               sum(equity.values()) / len(symbols)))
    for symbol in symbols:
        if position[symbol]:
            equity[symbol] *= 1 - side_cost
    portfolio_path[-1] = (end_ms, sum(equity.values()) / len(symbols))

    peak = 1.0
    drawdown = 0.0
    for _, value in portfolio_path:
        peak = max(peak, value)
        drawdown = max(drawdown, 1 - value / peak)
    monthly = {}
    prior = 1.0
    for index in range(1, len(portfolio_path)):
        period = _month(portfolio_path[index - 1][0])
        is_last = index == len(portfolio_path) - 1
        next_period = _month(portfolio_path[index][0])
        if period != next_period or is_last:
            current = portfolio_path[index][1]
            monthly[period] = 100 * (current / prior - 1)
            prior = current
    return WindowResult(start, end, 100 * (portfolio_path[-1][1] - 1),
                        100 * drawdown, trades,
                        sum(value > 0 for value in monthly.values()), len(monthly),
                        monthly, {symbol: 100 * (value - 1) for symbol, value in equity.items()})
