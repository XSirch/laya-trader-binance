"""Paid BTC spot long/cash research ledger with causal forecast decisions.

This module only consumes supplied data. Hourly open fills and their cost are
simulation assumptions; contemporaneous volume validates fills after the fact.
"""

from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import json
import math

from .binance_data import HOUR_MS


DAY_MS = 24 * HOUR_MS
MODES = ("sign", "cost_band", "buy_hold")


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("invalid finite number: " + name)
    return value


def _time(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value % HOUR_MS:
        raise ValueError("invalid hourly timestamp: " + name)
    return value


def _bar(spot, timestamp, *, held):
    bar = spot.get(timestamp)
    if bar is None:
        raise ValueError(f"missing {'held' if held else 'execution'} spot price at {timestamp}")
    if getattr(bar, "open_ms", None) != timestamp:
        raise ValueError("spot candle timestamp mismatch")
    opening, high, low, close = [_number(getattr(bar, key, None), key)
                                 for key in ("open", "high", "low", "close")]
    if not 0 < low <= min(opening, close) <= max(opening, close) <= high:
        raise ValueError("invalid spot OHLC")
    return bar


def _liquidity(bar, timestamp):
    trades, volume = getattr(bar, "trades", None), getattr(bar, "volume", None)
    quote = getattr(bar, "quote_volume", None)
    if (isinstance(trades, bool) or not isinstance(trades, int) or trades <= 0
            or isinstance(volume, bool) or not isinstance(volume, (int, float))
            or not math.isfinite(volume) or volume <= 0
            or quote is not None and (isinstance(quote, bool) or not isinstance(quote, (int, float))
                                      or not math.isfinite(quote) or quote <= 0)):
        raise ValueError(f"unverified spot execution liquidity at {timestamp}")


def _forecast(row, timestamp):
    if not isinstance(row, Mapping):
        raise ValueError("forecast must be a mapping")
    cutoff = _time(row.get("latest_observed_close_ms"), "forecast cutoff")
    if cutoff != timestamp - HOUR_MS:
        raise ValueError("forecast requires one full hour after completed close")
    prediction = _number(row.get("prediction"), "prediction")
    digest = row.get("context_sha256")
    if (not isinstance(digest, str) or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)):
        raise ValueError("forecast requires a lowercase SHA256 context digest")
    return {"prediction": prediction, "latest_observed_close_ms": cutoff, "context_sha256": digest}


def evaluate(spot, forecasts, *, start_ms, end_ms, side_cost, allocation, mode, trailing=None):
    """Simulate one paid long position at a time, never rebalance its quantity.

    Forecasts belong to execution hours and must use a completed close exactly
    one hour earlier. Missing forecasts retain the current position. The
    buy_hold benchmark buys on its first available forecast, regardless of
    sign, and has no trailing variant. All positions close at the terminal open.
    """
    _time(start_ms, "start_ms")
    _time(end_ms, "end_ms")
    if end_ms <= start_ms:
        raise ValueError("increasing hourly execution endpoints required")
    if not 0 <= _number(side_cost, "side_cost") < 1:
        raise ValueError("side_cost must be nonnegative and below one")
    if _number(allocation, "allocation") not in (.5, 1.0):
        raise ValueError("allocation must be one half or one")
    if mode not in MODES:
        raise ValueError("unknown hourly forecast mode")
    if trailing is not None and not 0 < _number(trailing, "trailing") < 1:
        raise ValueError("invalid trailing fraction")
    if mode == "buy_hold" and trailing is not None:
        raise ValueError("buy_hold benchmark does not have a trailing variant")
    if not isinstance(spot, Mapping) or not isinstance(forecasts, Mapping):
        raise ValueError("spot and forecasts must be timestamp mappings")
    for timestamp in forecasts:
        _time(timestamp, "forecast execution time")

    cash, quantity, entry_price, entry_ms = 1.0, 0.0, None, None
    fees, price_pnl, turnover, entries, exposure_hours = 0.0, 0.0, 0.0, 0, 0
    peak, drawdown, adverse_peak, adverse_drawdown = 1.0, 0.0, 1.0, 0.0
    stop_peak, month_start = None, 1.0
    trades, stops, actions, hourly = [], [], [], []
    daily, wallets, monthly = {}, {}, {}
    decisions, reasons = Counter(), Counter()
    digest = hashlib.sha256()

    def equity_at(bar=None):
        return cash + quantity * bar.open if quantity else cash

    def observe(equity):
        nonlocal peak, drawdown, adverse_peak, adverse_drawdown
        if not math.isfinite(equity) or equity <= 0:
            raise ValueError("nonpositive hourly spot equity")
        peak = max(peak, equity)
        drawdown = max(drawdown, 1 - equity / peak)
        adverse_peak = max(adverse_peak, peak)
        adverse_drawdown = max(adverse_drawdown, drawdown, 1 - equity / adverse_peak)

    for timestamp in range(start_ms, end_ms + 1, HOUR_MS):
        terminal = timestamp == end_ms
        bar = _bar(spot, timestamp, held=True) if quantity else None
        before = equity_at(bar)
        observe(before)
        # Terminal forecasts never enter the policy or its clock. They cannot
        # create a position that is closed immediately at the same endpoint.
        forecast = _forecast(forecasts[timestamp], timestamp) if not terminal and timestamp in forecasts else None
        if quantity:
            stop_peak = max(stop_peak if stop_peak is not None else before, before)
        else:
            stop_peak = None
        triggered = bool(quantity and not terminal and trailing is not None
                         and before <= stop_peak * (1 - trailing))
        action, reason = "hold", "unavailable_forecast"
        if terminal:
            action, reason = ("exit" if quantity else "hold"), "terminal"
        elif triggered:
            action, reason = "exit", "portfolio_trailing"
            stops.append({"timestamp_ms": timestamp, "kind": "portfolio_trailing",
                          "peak": stop_peak, "equity_before": before,
                          "threshold_equity": stop_peak * (1 - trailing), "fraction": trailing})
        elif forecast is not None:
            prediction = forecast["prediction"]
            if mode == "buy_hold":
                action, reason = ("hold", "buy_hold_maintain") if quantity else ("enter", "first_forecast")
            elif mode == "sign":
                if prediction > 0:
                    action, reason = ("hold" if quantity else "enter"), "positive_forecast"
                else:
                    action, reason = ("exit" if quantity else "hold"), "nonpositive_forecast"
            elif prediction > 2 * side_cost:
                action, reason = ("hold" if quantity else "enter"), "above_cost_band"
            elif prediction < -2 * side_cost:
                action, reason = ("exit" if quantity else "hold"), "below_cost_band"
            else:
                action, reason = "hold", "inside_cost_band"

        record = {"timestamp_ms": timestamp, "action": action, "reason": reason,
                  "forecast": forecast, "quantity_before": quantity}
        decisions[action] += 1
        reasons[reason] += 1
        digest.update(json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n")
        if action != "hold":
            actions.append(record)
            if bar is None:
                bar = _bar(spot, timestamp, held=False)
            _liquidity(bar, timestamp)
            if action == "enter":
                quantity = allocation * before / (bar.open * (1 + side_cost))
                entry_price, entry_ms = bar.open, timestamp
                notional = quantity * bar.open
                charge = notional * side_cost
                cash -= notional + charge
                if abs(cash) < 1e-15:
                    cash = 0.0
                entries += 1
                realized = 0.0
                # The initial capital before entry costs is part of this
                # holding episode's peak, rather than disappearing on entry.
                stop_peak = before
                traded_quantity = quantity
            else:
                traded_quantity = quantity
                notional = quantity * bar.open
                charge = notional * side_cost
                realized = quantity * (bar.open - entry_price)
                price_pnl += realized
                cash += notional - charge
                quantity = 0.0
                stop_peak = None
            fees += charge
            turnover += notional
            if not math.isfinite(cash) or cash < -1e-12:
                raise ValueError("negative cash in paid spot wallet")
            after = equity_at(bar)
            trades.append({"timestamp_ms": timestamp, "action": action, "reason": reason,
                           "quantity": traded_quantity, "price": bar.open, "fee": charge,
                           "price_pnl": realized, "entry_ms": entry_ms,
                           "equity_before": before, "equity_after": after, "cash_after": cash})
            if action == "exit":
                entry_price, entry_ms = None, None
        equity = equity_at(bar)
        observe(equity)
        if quantity:
            stop_peak = max(stop_peak if stop_peak is not None else before, equity)
        if not terminal and quantity:
            exposure_hours += 1
            favorable, worst = cash + quantity * bar.high, cash + quantity * bar.low
            # Unknown extreme order permits high before low. Retain that
            # possible peak for all later opens, exits and terminal fees.
            adverse_peak = max(adverse_peak, peak, favorable)
            adverse_drawdown = max(adverse_drawdown, drawdown, 1 - worst / adverse_peak)
        adverse_drawdown = max(adverse_drawdown, drawdown, 1 - equity / adverse_peak)
        hourly.append([timestamp, equity])
        if timestamp % DAY_MS == 0 or timestamp in (start_ms, end_ms):
            daily[str(timestamp)] = equity
            wallets[str(timestamp)] = {"cash": cash, "quantity": quantity, "entry_ms": entry_ms,
                                       "entry_price": entry_price, "equity": equity,
                                       "unrealized_price_pnl": quantity * (bar.open - entry_price) if quantity else 0.0}
        now = datetime.fromtimestamp(timestamp / 1000, timezone.utc)
        if timestamp > start_ms and (now.day == 1 and now.hour == 0 or terminal):
            month = datetime.fromtimestamp((timestamp - HOUR_MS) / 1000, timezone.utc).strftime("%Y-%m")
            monthly[month] = 100 * (equity / month_start - 1)
            month_start = equity

    error = equity - (1 + price_pnl - fees)
    if quantity or abs(error) > 1e-10 * max(1, abs(equity)):
        raise ValueError("paid spot wallet failed terminal reconciliation")
    hours = (end_ms - start_ms) // HOUR_MS
    return {"return_pct": 100 * (equity - 1), "max_drawdown_pct": 100 * drawdown,
            "adverse_intrahour_drawdown_bound_pct": 100 * max(adverse_drawdown, drawdown),
            "entries": entries, "trade_events": trades, "stop_events": stops, "stop_count": len(stops),
            "fees_pct_initial": 100 * fees, "price_pnl_pct_initial": 100 * price_pnl,
            "turnover": turnover, "traded_notional_multiple_initial": turnover,
            "hourly_equity": hourly, "daily_equity": daily, "monthly_returns_pct": monthly,
            "wallet_snapshots": wallets, "decision_counts": dict(decisions),
            "decision_reason_counts": dict(reasons), "decision_digest": digest.hexdigest(),
            "action_decisions": actions, "exposure_hours": exposure_hours, "observed_hours": hours,
            "cash_hours": hours - exposure_hours, "reconciliation_error": error,
            "execution_assumptions": [
                "Paid BTC spot only; no borrowing, funding, margin credit, JEV or orders.",
                "Hourly open fills and proportional costs are assumptions, not executable quote evidence.",
                "Positive trade count, base volume and quote volume when supplied validate fills after the fact.",
                "Trailing observes opens; costs and price gaps can exceed its distance.",
                "Intrahour bound combines possible favorable peaks and adverse lows, not an observed path.",
                "Daily and monthly boundary valuations follow actions assigned to that hourly open."]}
