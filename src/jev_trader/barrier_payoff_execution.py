"""Pure barrier labels and a paid BTC spot ledger; no data or network access.

Barriers use the entry open times a known ATR fraction. Intrabar fills are
assumptions with unknown timestamps, never evidence of executable quotes.
"""

from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import json
import math

from .binance_data import HOUR_MS


MAX_HOURS = 8
DAY_MS = 24 * HOUR_MS
ATR_FIELD = "spot.volatility.atr14_pct"
MODES = ("forecast", "always", "buy_hold")


class ExecutionUnavailable(ValueError):
    """Observed candle absence/quality prevents an honest simulated fill/path."""


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("invalid finite number: " + name)
    return value


def _time(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value % HOUR_MS:
        raise ValueError("invalid hourly timestamp: " + name)
    return value


def _parameters(entry_price, atr_fraction, entry_ms, max_hours):
    _time(entry_ms, "entry_ms")
    if _number(entry_price, "entry_price") <= 0:
        raise ValueError("entry price must be positive")
    if not 0 < _number(atr_fraction, "atr_fraction") < 1:
        raise ValueError("ATR fraction must be positive and below one")
    if isinstance(max_hours, bool) or not isinstance(max_hours, int) or max_hours < 1:
        raise ValueError("max_hours must be a positive integer")
    return {"stop": entry_price * (1 - atr_fraction), "target": entry_price * (1 + 2 * atr_fraction)}


def _validate_bar(bar, timestamp):
    if getattr(bar, "open_ms", None) != timestamp:
        raise ExecutionUnavailable("invalid execution: spot candle timestamp mismatch")
    values = [getattr(bar, key, None) for key in ("open", "high", "low", "close")]
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in values):
        raise ExecutionUnavailable(f"invalid execution: nonfinite spot OHLC at {timestamp}")
    opening, high, low, close = values
    if not 0 < low <= min(opening, close) <= max(opening, close) <= high:
        raise ExecutionUnavailable(f"invalid execution: invalid spot OHLC at {timestamp}")
    trades, volume, quote = (getattr(bar, key, None) for key in ("trades", "volume", "quote_volume"))
    if (isinstance(trades, bool) or not isinstance(trades, int) or trades <= 0
            or isinstance(volume, bool) or not isinstance(volume, (int, float))
            or not math.isfinite(volume) or volume <= 0
            or quote is not None and (isinstance(quote, bool) or not isinstance(quote, (int, float))
                                      or not math.isfinite(quote) or quote <= 0)):
        raise ExecutionUnavailable(f"invalid execution: unverified spot liquidity at {timestamp}")
    return bar


def _bar(spot, timestamp):
    bar = spot.get(timestamp)
    if bar is None:
        raise ExecutionUnavailable(f"invalid execution: missing spot price at {timestamp}")
    return _validate_bar(bar, timestamp)


def assess_bar(entry_price, atr_fraction, entry_ms, currentbar, max_hours=MAX_HOURS):
    """Return this bar's first assumed exit, or None, without any future access.

    Current-bar volume validates quality after the fact. It is not an entry
    eligibility filter. Open barriers precede the deadline; intrabar barriers
    never follow an open exit. An ambiguous intrabar candle exits at the stop.
    """
    barriers = _parameters(entry_price, atr_fraction, entry_ms, max_hours)
    timestamp = _time(getattr(currentbar, "open_ms", None), "bar open")
    deadline = entry_ms + max_hours * HOUR_MS
    if timestamp < entry_ms or timestamp > deadline:
        raise ValueError("bar outside episode horizon")
    _validate_bar(currentbar, timestamp)
    if timestamp == entry_ms and currentbar.open != entry_price:
        raise ValueError("episode entry price differs from entry open")
    stop, target = barriers["stop"], barriers["target"]
    phase, reason, price, ambiguous = "open", None, None, False
    if currentbar.open <= stop:
        reason, price = "stop_open", currentbar.open
    elif currentbar.open >= target:
        reason, price = "target_open", target
    elif timestamp == deadline:
        reason, price = "timeout", currentbar.open
    elif currentbar.low <= stop:
        phase, reason, price = "intrabar", "stop", stop
        ambiguous = currentbar.high >= target
    elif currentbar.high >= target:
        phase, reason, price = "intrabar", "target", target
    if reason is None:
        return None
    return {"exit_bar_open_ms": timestamp, "exit_phase": phase, "exit_price": price,
            "reason": reason, "available_ms": timestamp + HOUR_MS,
            "ambiguous_bar": ambiguous}


def episode(spot, execution_ms, atr_fraction, *, max_hours=MAX_HOURS):
    """Construct a hypothetical gross label, with outcome/quality availability.

    Missing or invalid observed data returns unavailable, rather than silently
    skipping a bar. Bad API parameters raise. Even an open exit is available
    only at its candle's close, when that candle's quality can be assessed.
    Availability is not necessarily monotonic in execution time.
    """
    if not isinstance(spot, Mapping):
        raise ValueError("spot must be a timestamp mapping")
    _parameters(1., atr_fraction, execution_ms, max_hours)
    result = {"status": "unavailable", "execution_ms": execution_ms, "entry_ms": execution_ms,
              "entry_price": None, "atr_fraction": atr_fraction, "barriers": None,
              "gross_return": None, "exit_bar_open_ms": None, "exit_phase": None,
              "exit_price": None, "available_ms": None, "ambiguous_bar": False}
    for timestamp in range(execution_ms, execution_ms + (max_hours + 1) * HOUR_MS, HOUR_MS):
        try:
            bar = _bar(spot, timestamp)
            if timestamp == execution_ms:
                result["entry_price"] = bar.open
                result["barriers"] = _parameters(bar.open, atr_fraction, execution_ms, max_hours)
            outcome = assess_bar(result["entry_price"], atr_fraction, execution_ms, bar, max_hours)
        except ExecutionUnavailable as error:
            result.update(reason=str(error), failed_bar_open_ms=timestamp)
            return result
        if outcome is not None:
            result.update(outcome, status="complete", gross_return=outcome["exit_price"] / result["entry_price"] - 1)
            return result
    raise AssertionError("deadline must close every valid episode")


def _context(signal, state, timestamp):
    if not isinstance(signal, Mapping):
        raise ValueError("signal must be a mapping")
    cutoff = _time(signal.get("latest_observed_close_ms"), "signal cutoff")
    if cutoff != timestamp - HOUR_MS:
        raise ValueError("signal requires one full hour after completed close")
    prediction = _number(signal.get("prediction"), "prediction")
    digest = signal.get("context_sha256")
    if (not isinstance(digest, str) or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)):
        raise ValueError("signal requires a lowercase SHA256 context digest")
    forecast = {"prediction": prediction, "latest_observed_close_ms": cutoff, "context_sha256": digest}
    if state is None:
        return forecast, None
    if not isinstance(state, Mapping):
        raise ValueError("state must be a mapping")
    _time(state.get("execution_ms"), "state execution time")
    _time(state.get("latest_observed_close_ms"), "state cutoff")
    if (state.get("execution_ms") != timestamp or state.get("latest_observed_close_ms") != cutoff
            or state.get("context_sha256") != digest):
        raise ValueError("state and signal context mismatch")
    atr_pct = state.get(ATR_FIELD)
    if atr_pct is None:
        return forecast, None
    atr = _number(atr_pct, ATR_FIELD) / 100
    _parameters(1., atr, timestamp, MAX_HOURS)
    return forecast, atr


def evaluate(spot, signals, states, *, start_ms, end_ms, side_cost, allocation, mode):
    """Run one fixed-quantity position, using only current-bar execution logic.

    The known terminal horizon excludes new barrier entries with less than
    eight hours left. buy_hold instead ignores barriers and exits terminally.
    All modes require the same forecast/state eligibility and causal context.
    Future path/quality can invalidate a run, never retroactively avoid a trade.
    """
    _time(start_ms, "start_ms")
    _time(end_ms, "end_ms")
    if end_ms <= start_ms:
        raise ValueError("increasing hourly execution endpoints required")
    if not 0 <= _number(side_cost, "side_cost") < 1:
        raise ValueError("side_cost must be nonnegative and below one")
    if _number(allocation, "allocation") not in (.5, 1.):
        raise ValueError("allocation must be one half or one")
    if mode not in MODES:
        raise ValueError("unknown barrier payoff mode")
    if any(not isinstance(value, Mapping) for value in (spot, signals, states)):
        raise ValueError("spot, signals and states must be timestamp mappings")
    for timestamp in signals:
        _time(timestamp, "signal execution time")

    cash, quantity, entry_price, entry_ms, entry_atr = 1., 0., None, None, None
    fees, price_pnl, turnover, entries, exposure_hours = 0., 0., 0., 0, 0
    peak, drawdown, adverse_peak, adverse_drawdown, month_start = 1., 0., 1., 0., 1.
    trades, stops, actions, traces, hourly, valuations = [], [], [], [], [], []
    daily, wallets, monthly = {}, {}, {}
    decisions, reasons = Counter(), Counter()
    digest = hashlib.sha256()
    hurdle = 2 * side_cost / (1 - side_cost)

    def equity_at(price=None):
        return cash + quantity * price if quantity else cash

    def observe(equity, timestamp, phase, kind, mark_price=None):
        nonlocal peak, drawdown, adverse_peak, adverse_drawdown
        if not math.isfinite(equity) or equity <= 0:
            raise ValueError("invalid execution: nonpositive spot equity")
        peak = max(peak, equity)
        drawdown = max(drawdown, 1 - equity / peak)
        adverse_peak = max(adverse_peak, peak)
        adverse_drawdown = max(adverse_drawdown, drawdown, 1 - equity / adverse_peak)
        valuations.append({"bar_open_ms": timestamp, "phase": phase,
                           "timestamp_ms": None if phase == "intrabar" else timestamp + (HOUR_MS if phase == "close" else 0),
                           "kind": kind, "equity": equity, "cash": cash, "quantity": quantity,
                           "mark_price": mark_price})

    def fill(timestamp, phase, action, price, reason, atr=None, ambiguous=False):
        nonlocal cash, quantity, entry_price, entry_ms, entry_atr, fees, price_pnl, turnover, entries
        before, cash_before, quantity_before = equity_at(price), cash, quantity
        observe(before, timestamp, phase, "before_" + action, price)
        if action == "enter":
            quantity = allocation * before / (price * (1 + side_cost))
            entry_price, entry_ms, entry_atr = price, timestamp, atr
            traded_quantity, realized = quantity, 0.
            notional = quantity * price
            charge = notional * side_cost
            cash -= notional + charge
            if abs(cash) < 1e-15:
                cash = 0.
            entries += 1
        else:
            traded_quantity = quantity
            notional, realized = quantity * price, quantity * (price - entry_price)
            charge = notional * side_cost
            cash += notional - charge
            price_pnl += realized
            quantity = 0.
        fees += charge
        turnover += notional
        if not math.isfinite(cash) or cash < -1e-12:
            raise ValueError("invalid execution: negative cash in paid spot wallet")
        after = equity_at(price)
        event = {"bar_open_ms": timestamp, "phase": phase,
                 "timestamp_ms": timestamp if phase == "open" else None,
                 "action": action, "reason": reason, "quantity": traded_quantity, "price": price,
                 "notional": notional, "fee": charge, "price_pnl": realized,
                 "entry_ms": entry_ms, "entry_price": entry_price, "atr_fraction": entry_atr,
                 "cash_before": cash_before, "cash_after": cash,
                 "quantity_before": quantity_before, "quantity_after": quantity,
                 "equity_before": before, "equity_after": after, "ambiguous_bar": ambiguous}
        trades.append(event)
        if reason in ("stop", "stop_open"):
            stops.append(dict(event))
        if action == "exit":
            entry_price, entry_ms, entry_atr = None, None, None
        observe(after, timestamp, phase, "after_" + action, price)

    for timestamp in range(start_ms, end_ms + 1, HOUR_MS):
        terminal, exited_open = timestamp == end_ms, False
        bar = _bar(spot, timestamp) if quantity else None
        observe(equity_at(bar.open if bar is not None else None), timestamp, "open", "open",
                bar.open if bar is not None else None)
        outcome = None
        action, reason, forecast, atr = "hold", "unavailable_forecast", None, None
        raw, effective, cap = None, None, None
        quantity_before = quantity
        if quantity:
            if terminal:
                # Forced endpoint exit is at the actual open, with its fee.
                # A barrier deadline at this same open still uses its kernel,
                # preserving label/execution price parity at the endpoint.
                outcome = (assess_bar(entry_price, entry_atr, entry_ms, bar)
                           if mode != "buy_hold" else None)
                if outcome is None or outcome["exit_phase"] != "open":
                    outcome = {"exit_phase": "open", "exit_price": bar.open, "reason": "terminal", "ambiguous_bar": False}
            elif mode != "buy_hold":
                outcome = assess_bar(entry_price, entry_atr, entry_ms, bar)
            if outcome is not None and outcome["exit_phase"] == "open":
                action, reason = "exit", outcome["reason"]
                fill(timestamp, "open", "exit", outcome["exit_price"], reason)
                exited_open = True

        # Only the already-known signal/state and horizon select an entry.
        # Current OHLC/volume validation below cannot turn a bad fill into cash.
        if terminal:
            reason = reason if exited_open else "terminal"
        elif exited_open:
            pass
        elif quantity:
            reason = "position_maintained"
        elif timestamp in signals:
            forecast, atr = _context(signals[timestamp], states.get(timestamp), timestamp)
            raw = forecast["prediction"]
            if atr is None:
                reason = "unavailable_atr"
            elif mode != "buy_hold" and timestamp + MAX_HOURS * HOUR_MS > end_ms:
                reason = "insufficient_terminal_horizon"
            else:
                cap = 2 * atr
                effective = min(raw, cap) if mode == "forecast" else raw
                if mode == "forecast" and cap <= hurdle:
                    reason = "barrier_upside_below_cost"
                elif mode == "forecast" and effective <= hurdle:
                    reason = "forecast_below_cost"
                else:
                    action = "enter"
                    reason = "above_round_trip_cost" if mode == "forecast" else "eligible_control"

        record = {"bar_open_ms": timestamp, "timestamp_ms": timestamp, "phase": "open",
                  "action": action, "reason": reason, "forecast": forecast,
                  "raw_prediction": raw, "effective_prediction": effective,
                  "payoff_cap": cap, "hurdle": hurdle, "atr_fraction": atr,
                  "quantity_before": quantity_before}
        traces.append(record)
        decisions[action] += 1
        reasons[reason] += 1
        digest.update(json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n")
        if action != "hold":
            actions.append(record)
        if action == "enter":
            bar = _bar(spot, timestamp)
            fill(timestamp, "open", "enter", bar.open, reason, atr)
            outcome = assess_bar(entry_price, entry_atr, entry_ms, bar) if mode != "buy_hold" else None

        # Regular boundary samples are after open actions, before this bar's
        # unknown intrabar path. Closes and intrabar fills live in valuations.
        equity = equity_at(bar.open if bar is not None else None)
        hourly.append([timestamp, equity])
        if timestamp % DAY_MS == 0 or timestamp in (start_ms, end_ms):
            daily[str(timestamp)] = equity
            wallets[str(timestamp)] = {"cash": cash, "quantity": quantity, "entry_ms": entry_ms,
                                       "entry_price": entry_price, "equity": equity,
                                       "unrealized_price_pnl": quantity * (bar.open - entry_price) if quantity else 0.}
        now = datetime.fromtimestamp(timestamp / 1000, timezone.utc)
        if timestamp > start_ms and (now.day == 1 and now.hour == 0 or terminal):
            month = datetime.fromtimestamp((timestamp - HOUR_MS) / 1000, timezone.utc).strftime("%Y-%m")
            monthly[month] = 100 * (equity / month_start - 1)
            month_start = equity

        if not terminal:
            if quantity:
                exposure_hours += 1
                # A full exposed bar is retained even if exit was intrabar.
                # This is a pessimistic delayed-exit stress, not a path claim.
                favorable, adverse = cash + quantity * bar.high, cash + quantity * bar.low
                adverse_peak = max(adverse_peak, peak, favorable)
                adverse_drawdown = max(adverse_drawdown, drawdown, 1 - adverse / adverse_peak)
                if outcome is not None:
                    if outcome["exit_phase"] != "intrabar":
                        raise AssertionError("unprocessed open exit")
                    fill(timestamp, "intrabar", "exit", outcome["exit_price"], outcome["reason"],
                         ambiguous=outcome["ambiguous_bar"])
            observe(equity_at(bar.close if bar is not None else None), timestamp, "close", "close",
                    bar.close if quantity else None)

    error = equity - (1 + price_pnl - fees)
    if quantity or abs(error) > 1e-10 * max(1, abs(equity)):
        raise ValueError("invalid execution: paid spot terminal reconciliation failed")
    hours = (end_ms - start_ms) // HOUR_MS
    return {"return_pct": 100 * (equity - 1), "max_drawdown_pct": 100 * drawdown,
            "adverse_intrahour_drawdown_bound_pct": 100 * max(adverse_drawdown, drawdown),
            "entries": entries, "trade_events": trades, "stop_events": stops, "stop_count": len(stops),
            "fees_pct_initial": 100 * fees, "price_pnl_pct_initial": 100 * price_pnl,
            "turnover": turnover, "traded_notional_multiple_initial": turnover,
            "hourly_equity": hourly, "daily_equity": daily, "monthly_returns_pct": monthly,
            "wallet_snapshots": wallets, "valuation_points": valuations,
            "decision_counts": dict(decisions), "decision_reason_counts": dict(reasons),
            "decision_digest": digest.hexdigest(), "action_decisions": actions, "decision_trace": traces,
            "exposure_hours": exposure_hours, "observed_hours": hours, "cash_hours": hours - exposure_hours,
            "reconciliation_error": error,
            "execution_assumptions": [
                "Paid BTC spot only; one fixed quantity, no borrowing, funding, margin, JEV or orders.",
                "Fixed entry-relative ATR barriers: stop minus one ATR, target plus two ATR, eight-hour deadline.",
                "Open gaps stop at the worse open; targets fill at their level without extra favorable gap gain.",
                "Both intrabar barriers touched means stop first; fills and costs are unverified assumptions.",
                "Intrabar fills have a bar identifier but no exact execution timestamp.",
                "Positive trade count and volumes validate every exposed candle after the fact.",
                "Drawdown samples opens, closes and before/after fills; it cannot prove a real account limit.",
                "The adverse bound retains full exposed-bar extremes, even after assumed intrabar exits: delayed-exit stress.",
                "Bars exited at their open add no subsequent extremes; prior possible peaks persist through fees.",
                "Daily/monthly boundary valuations follow open actions; all final positions close with fees.",
                "Forecast gate caps raw prediction at the known two-ATR maximum, then requires strict exact cost breakeven."]}
