"""Hourly-marked, unleveraged long/cash replay for fixed eight-hour signals."""

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math

from .binance_data import HOUR_MS
from .lagged_flow_prediction import HORIZON_HOURS, INTERVAL_HOURS, MODELS, SYMBOLS, _valid_price_bar

DAY_MS = 24 * HOUR_MS
MODES = (*MODELS, "always", "buy_hold")


class ExecutionUnavailable(ValueError):
    """Observed candle quality prevents an honest simulated fill or mark."""


def _time(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value % (INTERVAL_HOURS * HOUR_MS):
        raise ValueError("invalid eight-hour UTC timestamp: " + name)
    return value


def _fill_bar(spot, symbol, timestamp):
    bar = spot[symbol].get(timestamp)
    if not _valid_price_bar(bar, timestamp):
        raise ExecutionUnavailable(f"invalid {symbol} execution OHLC at {timestamp}")
    trades, volume = getattr(bar, "trades", None), getattr(bar, "volume", None)
    quote = getattr(bar, "quote_volume", None)
    if (isinstance(trades, bool) or not isinstance(trades, int) or trades <= 0
            or isinstance(volume, bool) or not isinstance(volume, (int, float))
            or not math.isfinite(volume) or volume <= 0
            or quote is not None and (isinstance(quote, bool) or not isinstance(quote, (int, float))
                                      or not math.isfinite(quote) or quote <= 0)):
        raise ExecutionUnavailable(f"unverified {symbol} execution liquidity at {timestamp}")
    return bar


def _signal(predictions, key, symbol, timestamp):
    row = predictions.get(key)
    if not isinstance(row, dict):
        return None
    cutoff = row.get("latest_observed_close_ms")
    value = row.get("prediction")
    digest = row.get("context_sha256")
    if cutoff != timestamp - HOUR_MS or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("signal has invalid cutoff or prediction")
    if row.get("symbol", symbol) != symbol:
        raise ValueError("signal asset differs from execution asset")
    if (not isinstance(digest, str) or len(digest) != 64
            or any(ch not in "0123456789abcdef" for ch in digest)):
        raise ValueError("signal requires a lowercase context digest")
    return {"prediction": float(value), "latest_observed_close_ms": cutoff,
            "context_sha256": digest}


def evaluate(spot, event_symbols, signals, *, start_ms, end_ms, side_cost, mode):
    """Evaluate 25%-per-asset decisions, closing each position after eight hours."""
    _time(start_ms, "start_ms")
    _time(end_ms, "end_ms")
    if end_ms <= start_ms or (end_ms - start_ms) % (INTERVAL_HOURS * HOUR_MS):
        raise ValueError("period endpoints must span whole eight-hour blocks")
    if isinstance(side_cost, bool) or not isinstance(side_cost, (int, float)) or not 0 <= side_cost < 1:
        raise ValueError("side_cost must be nonnegative and below one")
    if mode not in MODES:
        raise ValueError("unknown lagged-flow execution mode")
    if not isinstance(spot, dict) or set(spot) != set(SYMBOLS):
        raise ValueError("spot map must contain the four frozen symbols")
    if not isinstance(event_symbols, dict) or not isinstance(signals, dict):
        raise ValueError("events and signals must be mappings")

    cash, quantity, entry_price, entry_ms = 1.0, {}, {}, {}
    fees = price_pnl = turnover = 0.0
    entries = 0
    peak = adverse_peak = 1.0
    drawdown = adverse_drawdown = 0.0
    hourly, daily, monthly, actions = [], {}, {}, []
    decisions, reasons = Counter(), Counter()
    digest = hashlib.sha256()
    month_start_equity = 1.0
    asset_exposure_hours = 0

    def equity_at(timestamp):
        return cash + math.fsum(quantity.get(symbol, 0.0) * spot[symbol][timestamp].open
                                for symbol in SYMBOLS if quantity.get(symbol))

    def observe(equity):
        nonlocal peak, drawdown
        if not math.isfinite(equity) or equity <= 0:
            raise ValueError("nonpositive portfolio equity")
        peak = max(peak, equity)
        drawdown = max(drawdown, 1 - equity / peak)

    interval_ms = INTERVAL_HOURS * HOUR_MS
    threshold = 2 * side_cost / (1 - side_cost)
    for timestamp in range(start_ms, end_ms + 1, interval_ms):
        terminal = timestamp == end_ms
        current_bars = {symbol: _fill_bar(spot, symbol, timestamp)
                        for symbol in SYMBOLS if quantity.get(symbol)}
        before = cash + math.fsum(quantity[symbol] * current_bars[symbol].open
                                  for symbol in quantity)
        observe(before)
        # Fixed-horizon positions close before the next decision at the same open.
        for symbol in SYMBOLS:
            if not quantity.get(symbol):
                continue
            if mode == "buy_hold" and not terminal:
                continue
            bar = current_bars[symbol]
            notional = quantity[symbol] * bar.open
            charge = notional * side_cost
            realized = quantity[symbol] * (bar.open - entry_price[symbol])
            cash += notional - charge
            fees += charge
            turnover += notional
            price_pnl += realized
            record = {"timestamp_ms": timestamp, "symbol": symbol, "action": "exit",
                "reason": "eight_hour_horizon", "quantity": quantity[symbol],
                "price": bar.open, "fee": charge, "price_pnl": realized,
                "entry_ms": entry_ms[symbol]}
            actions.append(record)
            decisions["exit"] += 1
            digest.update(json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n")
            quantity.pop(symbol)
            entry_price.pop(symbol)
            entry_ms.pop(symbol)
            current_bars.pop(symbol, None)
        after_exits = cash + math.fsum(quantity[symbol] * current_bars[symbol].open
                                       for symbol in quantity)
        observe(after_exits)

        entrants = []
        if not terminal and mode != "buy_hold":
            for symbol in SYMBOLS:
                eligible = symbol in event_symbols.get(timestamp, ())
                signal = _signal(signals, (timestamp, symbol), symbol, timestamp) if eligible and mode in MODELS else None
                if mode == "always":
                    enter, reason = eligible, "eligible_control"
                elif signal is None:
                    enter, reason = False, "unavailable_forecast"
                elif signal["prediction"] <= threshold:
                    enter, reason = False, "forecast_below_round_trip_cost"
                else:
                    enter, reason = True, "above_round_trip_cost"
                decisions["enter_candidate" if enter else "skip_candidate"] += 1
                reasons[reason] += 1
                audit = {"timestamp_ms": timestamp, "symbol": symbol,
                    "prediction": None if signal is None else signal["prediction"],
                    "threshold": threshold, "action": "enter" if enter else "skip",
                    "reason": reason, "context_sha256": None if signal is None else signal["context_sha256"]}
                digest.update(json.dumps(audit, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n")
                if enter:
                    entrants.append((symbol, signal))
        elif not terminal and mode == "buy_hold" and timestamp == start_ms:
            entrants = [(symbol, None) for symbol in SYMBOLS]

        # Fix all four stakes from the same pre-entry equity, capped at one
        # quarter each. Fewer qualifying assets leave the balance in cash.
        equity_for_sizing = after_exits
        for symbol, signal in entrants:
            bar = current_bars.get(symbol)
            if bar is None:
                bar = _fill_bar(spot, symbol, timestamp)
                current_bars[symbol] = bar
            stake = equity_for_sizing * 0.25
            units = stake / (bar.open * (1 + side_cost))
            notional = units * bar.open
            charge = notional * side_cost
            cash -= notional + charge
            if abs(cash) < 1e-14:
                cash = 0.0
            quantity[symbol] = units
            entry_price[symbol] = bar.open
            entry_ms[symbol] = timestamp
            fees += charge
            turnover += notional
            entries += 1
            record = {"timestamp_ms": timestamp, "symbol": symbol, "action": "enter",
                "reason": "eligible_signal", "quantity": units, "price": bar.open,
                "fee": charge, "price_pnl": 0.0, "entry_ms": timestamp,
                "prediction": None if signal is None else signal["prediction"]}
            actions.append(record)
            decisions["enter"] += 1
            digest.update(json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n")
        current_equity = equity_at(timestamp)
        observe(current_equity)
        hourly.append([timestamp, current_equity])
        time = datetime.fromtimestamp(timestamp / 1000, timezone.utc)
        if timestamp % DAY_MS == 0 or timestamp in (start_ms, end_ms):
            daily[str(timestamp)] = current_equity
        if timestamp > start_ms and time.day == 1 and time.hour == 0:
            previous = datetime.fromtimestamp((timestamp - HOUR_MS) / 1000, timezone.utc).strftime("%Y-%m")
            monthly[previous] = 100 * (after_exits / month_start_equity - 1)
            month_start_equity = after_exits
        if timestamp == end_ms and not (timestamp > start_ms and time.day == 1 and time.hour == 0):
            previous = datetime.fromtimestamp((timestamp - HOUR_MS) / 1000, timezone.utc).strftime("%Y-%m")
            monthly[previous] = 100 * (after_exits / month_start_equity - 1)

        # Mark all held paths hourly. Each OHLC bar has unknown intrabar order;
        # the bound allows every high before every low and is intentionally adverse.
        block_end = min(timestamp + interval_ms, end_ms)
        for hour_open in range(timestamp, block_end, HOUR_MS):
            if hour_open == timestamp:
                bars = current_bars
            else:
                bars = {}
                for symbol in SYMBOLS:
                    if quantity.get(symbol):
                        bar = spot[symbol].get(hour_open)
                        if not _valid_price_bar(bar, hour_open):
                            raise ExecutionUnavailable(f"missing/invalid held {symbol} OHLC at {hour_open}")
                        bars[symbol] = bar
            asset_exposure_hours += len(bars)
            open_equity = cash + math.fsum(quantity[symbol] * bars[symbol].open for symbol in bars)
            observe(open_equity)
            favorable = cash + math.fsum(quantity[symbol] * bars[symbol].high for symbol in bars)
            worst = cash + math.fsum(quantity[symbol] * bars[symbol].low for symbol in bars)
            adverse_peak = max(adverse_peak, peak, favorable)
            adverse_drawdown = max(adverse_drawdown, drawdown, 1 - worst / adverse_peak)
            if hour_open != timestamp:
                hourly.append([hour_open, open_equity])

    # Every modeled episode has its terminal open and is closed above.
    if quantity:
        raise ValueError("terminal horizon left an open position")
    final = cash
    reconciliation = final - (1 + price_pnl - fees)
    if abs(reconciliation) > 1e-10 * max(1, abs(final)):
        raise ValueError("portfolio ledger did not reconcile")
    hours = (end_ms - start_ms) // HOUR_MS
    return {"return_pct": 100 * (final - 1), "max_drawdown_pct": 100 * drawdown,
        "adverse_intrahour_drawdown_bound_pct": 100 * max(drawdown, adverse_drawdown),
        "entries": entries, "exits": sum(action["action"] == "exit" for action in actions),
        "fees_pct_initial": 100 * fees, "price_pnl_pct_initial": 100 * price_pnl,
        "turnover_multiple_initial": turnover, "hourly_equity": hourly,
        "daily_equity": daily, "monthly_returns_pct": monthly,
        "decision_counts": dict(decisions), "decision_reason_counts": dict(reasons),
        "decision_digest": digest.hexdigest(), "action_decisions": actions,
        "asset_exposure_hours": asset_exposure_hours,
        "asset_cash_hours": len(SYMBOLS) * hours - asset_exposure_hours,
        "observed_hours": hours, "reconciliation_error": reconciliation,
        "terminal_equity": final,
        "execution_assumptions": ["Spot long/cash only; no leverage, borrowing, futures PnL, funding or real orders.",
            "Hourly OHLC marks are bounds, not an observed intrabar path or executable quote.",
            "Entry and exit liquidity is checked after the fact; it does not prove historical point-in-time execution."]}
