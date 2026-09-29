"""Causal sweep/reclaim features and barrier outcomes for a long-only study."""

from __future__ import annotations

import math

from .binance_data import HOUR_MS

SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
FEATURES = (
    "sweep_depth_atr", "reclaim_depth_atr", "prior_range_atr",
    "signal_range_atr", "signal_close_location", "lower_wick_share",
    "atr_fraction", "realized_volatility_24h", "return_6h", "return_24h",
    "return_72h", "btc_return_6h", "btc_return_24h", "btc_return_72h",
    "relative_quote_volume_24h", "taker_imbalance_event",
    "taker_imbalance_24h", "volume_poc_distance_atr", "volume_poc_share",
    "asset_is_BTCUSDT", "asset_is_ETHUSDT", "asset_is_BNBUSDT",
    "asset_is_SOLUSDT",
)
HORIZON_HOURS = 24
STOP_BUFFER_ATR = 0.10
TARGET_R = 2.0
MAX_RISK_ATR = 2.0
EVENT_COOLDOWN_HOURS = 24


def _finite(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


def _true_range(bar, previous_close):
    return max(bar.high - bar.low, abs(bar.high - previous_close),
               abs(bar.low - previous_close))


def _volume_profile(bars, atr, close):
    lows = [bar.low for bar in bars]
    highs = [bar.high for bar in bars]
    low, high = min(lows), max(highs)
    if high <= low:
        return 0.0, 0.0
    bins = [0.0] * 24
    width = (high - low) / len(bins)
    for bar in bars:
        typical = (bar.high + bar.low + bar.close) / 3.0
        index = min(len(bins) - 1, max(0, int((typical - low) / width)))
        bins[index] += float(bar.quote_volume)
    total = math.fsum(bins)
    if total <= 0:
        return 0.0, 0.0
    poc_index = max(range(len(bins)), key=bins.__getitem__)
    poc_price = low + (poc_index + 0.5) * width
    return (close - poc_price) / atr, bins[poc_index] / total


def _features(symbol, i, bars, by_time, btc_by_time):
    current = bars[i]
    previous = bars[i - 24:i]
    history = bars[i - 72:i]
    expected = [current.open_ms - offset * HOUR_MS for offset in range(72, -1, -1)]
    actual = [bar.open_ms for bar in history] + [current.open_ms]
    if actual != expected:
        return None
    if any(bar.quote_volume is None or bar.taker_buy_base is None
           for bar in (*previous, *history, current)):
        return None
    if current.volume <= 0 or math.fsum(bar.volume for bar in previous) <= 0:
        return None
    for bars_by_time in (by_time, btc_by_time):
        if any(timestamp not in bars_by_time for timestamp in expected):
            return None

    support = min(bar.low for bar in previous)
    if not (current.low < support and current.close > support):
        return None
    atr_bars = bars[i - 14:i + 1]
    if len(atr_bars) != 15:
        return None
    atr = math.fsum(_true_range(atr_bars[j], atr_bars[j - 1].close)
                    for j in range(1, len(atr_bars))) / 14.0
    if not _finite(atr) or atr <= 0:
        return None
    candle_range = current.high - current.low
    if candle_range <= 0:
        return None

    def returns(series, period):
        prior = series[i - period]
        return series[i].close / prior.close - 1.0

    btc_current = btc_by_time[current.open_ms]
    btc_series = btc_by_time

    def btc_return(period):
        prior = btc_series[current.open_ms - period * HOUR_MS]
        return btc_current.close / prior.close - 1.0

    quote_mean = math.fsum(float(bar.quote_volume) for bar in previous) / len(previous)
    imbalance_24 = 2 * math.fsum(float(bar.taker_buy_base) for bar in previous) / math.fsum(
        float(bar.volume) for bar in previous) - 1.0
    realized = math.sqrt(math.fsum(
        math.log(bars[j].close / bars[j - 1].close) ** 2
        for j in range(i - 23, i + 1)))
    poc_distance, poc_share = _volume_profile(history, atr, current.close)
    features = {
        "sweep_depth_atr": (support - current.low) / atr,
        "reclaim_depth_atr": (current.close - support) / atr,
        "prior_range_atr": (max(bar.high for bar in previous)
                            - min(bar.low for bar in previous)) / atr,
        "signal_range_atr": candle_range / atr,
        "signal_close_location": (current.close - current.low) / candle_range,
        "lower_wick_share": (min(current.open, current.close) - current.low) / candle_range,
        "atr_fraction": atr / current.close,
        "realized_volatility_24h": realized,
        "return_6h": returns(bars, 6),
        "return_24h": returns(bars, 24),
        "return_72h": returns(bars, 72),
        "btc_return_6h": btc_return(6),
        "btc_return_24h": btc_return(24),
        "btc_return_72h": btc_return(72),
        "relative_quote_volume_24h": float(current.quote_volume) / quote_mean,
        "taker_imbalance_event": 2 * float(current.taker_buy_base) / current.volume - 1.0,
        "taker_imbalance_24h": imbalance_24,
        "volume_poc_distance_atr": poc_distance,
        "volume_poc_share": poc_share,
    }
    features.update({f"asset_is_{asset}": float(asset == symbol) for asset in SYMBOLS})
    values = [features[name] for name in FEATURES]
    if not all(_finite(value) for value in values):
        return None
    return features, atr, support


def _trade_outcome(event, bars_by_time):
    signal_low, atr = event["signal_low"], event["atr"]
    stop = signal_low - STOP_BUFFER_ATR * atr
    wait_ms = event["entry_ms"] - HOUR_MS
    wait_bar = bars_by_time.get(wait_ms)
    entry_bar = bars_by_time.get(event["entry_ms"])
    if wait_bar is None or entry_bar is None:
        return None
    if wait_bar.low <= stop:
        return None
    entry = entry_bar.open
    risk = entry - stop
    if risk <= 0 or risk / entry > MAX_RISK_ATR * atr / entry:
        return None
    target = entry + TARGET_R * risk
    horizon_exit_ms = event["entry_ms"] + HORIZON_HOURS * HOUR_MS
    for timestamp in range(event["entry_ms"], horizon_exit_ms, HOUR_MS):
        bar = bars_by_time.get(timestamp)
        if bar is None:
            return None
        stop_touched = bar.low <= stop
        target_touched = bar.high >= target
        if stop_touched and target_touched:
            exit_price, reason = (bar.open if bar.open < stop else stop), "stop_first_same_bar"
        elif bar.open <= stop:
            exit_price, reason = bar.open, "stop_gap"
        elif bar.open >= target:
            exit_price, reason = bar.open, "target_gap"
        elif stop_touched:
            exit_price, reason = stop, "stop"
        elif target_touched:
            exit_price, reason = target, "target"
        else:
            continue
        return {
            "entry_price": entry, "stop_price": stop, "target_price": target,
            "risk_fraction": risk / entry, "exit_price": exit_price,
            "exit_ms": timestamp, "available_ms": timestamp + HOUR_MS,
            "reason": reason, "gross_return_fraction": exit_price / entry - 1.0,
            "gross_R": (exit_price - entry) / risk,
        }
    exit_bar = bars_by_time.get(horizon_exit_ms)
    if exit_bar is None:
        return None
    return {
        "entry_price": entry, "stop_price": stop, "target_price": target,
        "risk_fraction": risk / entry, "exit_price": exit_bar.open,
        "exit_ms": horizon_exit_ms, "available_ms": horizon_exit_ms + HOUR_MS,
        "reason": "time_exit_24h", "gross_return_fraction": exit_bar.open / entry - 1.0,
        "gross_R": (exit_bar.open - entry) / risk,
    }


def build_events(market):
    """Build 24-hour-low sweeps, causal features, and complete barrier labels."""
    if set(market) != set(SYMBOLS):
        raise ValueError("market must contain the frozen four-asset spot universe")
    by_time = {symbol: {bar.open_ms: bar for bar in market[symbol]} for symbol in SYMBOLS}
    btc = by_time["BTCUSDT"]
    result, excluded = [], {"feature_or_history": 0, "cooldown": 0,
                            "invalidated_or_incomplete_trade": 0}
    last_signal = {symbol: None for symbol in SYMBOLS}
    for symbol in SYMBOLS:
        bars = market[symbol]
        own_by_time = by_time[symbol]
        for i in range(72, len(bars) - HORIZON_HOURS - 2):
            current = bars[i]
            built = _features(symbol, i, bars, own_by_time, btc)
            if built is None:
                excluded["feature_or_history"] += 1
                continue
            features, atr, support = built
            if current.low >= support or current.close <= support:
                continue
            signal_ms = current.open_ms
            if (last_signal[symbol] is not None
                    and signal_ms - last_signal[symbol] < EVENT_COOLDOWN_HOURS * HOUR_MS):
                excluded["cooldown"] += 1
                continue
            last_signal[symbol] = signal_ms
            event = {"symbol": symbol, "signal_ms": signal_ms,
                "signal_close_ms": signal_ms + HOUR_MS,
                "entry_ms": signal_ms + 2 * HOUR_MS,
                "signal_low": current.low, "atr": atr, "support24": support,
                "features": features}
            outcome = _trade_outcome(event, own_by_time)
            if outcome is None:
                excluded["invalidated_or_incomplete_trade"] += 1
                continue
            result.append({**event, **outcome})
    result.sort(key=lambda event: (event["entry_ms"], event["symbol"]))
    return result, excluded
