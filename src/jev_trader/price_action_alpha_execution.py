"""Hourly Spot portfolio replay for the independent price-action hypothesis."""

from collections import Counter
from datetime import datetime, timezone
import math

from .binance_data import HOUR_MS
from .price_action_alpha import HORIZON_HOURS, SYMBOLS

HORIZON_MS = HORIZON_HOURS * HOUR_MS


def replay(market, events, predictions, *, start_ms, end_ms, side_cost, mode):
    """Replay event-gated, all-event, equal-weight hold, or cash controls."""
    if mode not in {"ml_gated", "all_sweeps", "buy_hold", "cash"}:
        raise ValueError("unknown price-action replay mode")
    if not (0 <= side_cost < 1) or end_ms <= start_ms:
        raise ValueError("invalid period or side cost")
    bars = {symbol: {bar.open_ms: bar for bar in market[symbol]} for symbol in SYMBOLS}
    candidates = {}
    for event in events:
        if start_ms <= event["entry_ms"] <= end_ms - HORIZON_MS:
            candidates.setdefault(event["entry_ms"], {})[event["symbol"]] = event

    cash = 1.0
    positions = {}
    fees = price_pnl = turnover = 0.0
    actions, trades = [], []
    reasons = Counter()
    peak = adverse_peak = 1.0
    drawdown = adverse_drawdown = 0.0
    daily_equity, curve = {}, []
    event_total = sum(len(by_symbol) for by_symbol in candidates.values())

    def portfolio_value(timestamp, price_field="open"):
        return cash + math.fsum(position["quantity"] * getattr(
            bars[symbol][timestamp], price_field) for symbol, position in positions.items())

    def observe(value):
        nonlocal peak, drawdown
        if not math.isfinite(value) or value <= 0:
            raise ValueError("nonpositive price-action portfolio equity")
        peak = max(peak, value)
        drawdown = max(drawdown, 1.0 - value / peak)

    def close_position(symbol, timestamp, price, reason):
        nonlocal cash, fees, price_pnl, turnover
        position = positions.pop(symbol)
        quantity = position["quantity"]
        notional = quantity * price
        charge = notional * side_cost
        pnl = quantity * (price - position["entry_price"])
        cash += notional - charge
        fees += charge
        price_pnl += pnl
        turnover += notional
        net_pnl = pnl - charge - position["entry_fee"]
        trade = {"symbol": symbol, "entry_ms": position["entry_ms"],
            "exit_ms": timestamp, "entry_price": position["entry_price"],
            "exit_price": price, "stop_price": position.get("stop_price"),
            "target_price": position.get("target_price"), "reason": reason,
            "prediction_gross_R": position.get("prediction_gross_R"),
            "gross_R": ((price - position["entry_price"]) / position["risk"]
                        if position.get("risk") else None),
            "net_pnl_initial_equity": net_pnl, "exit_fee": charge,
            "entry_fee": position["entry_fee"]}
        trades.append(trade)
        actions.append({"action": "exit", **trade})
        reasons[reason] += 1

    def enter(symbol, timestamp, event, prediction_row, sizing_equity):
        nonlocal cash, fees, turnover
        bar = bars[symbol][timestamp]
        stop, target = event["stop_price"], event["target_price"]
        entry = bar.open
        # The outcome builder uses this same open as entry. A mismatch means
        # the simulated signal and the execution tape no longer agree.
        if not math.isclose(entry, event["entry_price"], rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("frozen entry open differs from event construction")
        stake = min(0.25 * sizing_equity, cash / (1.0 + side_cost))
        if stake <= 0:
            reasons["insufficient_cash"] += 1
            return
        quantity = stake / entry
        notional = quantity * entry
        entry_fee = notional * side_cost
        cash -= notional + entry_fee
        fees += entry_fee
        turnover += notional
        positions[symbol] = {"entry_ms": timestamp, "entry_price": entry,
            "quantity": quantity, "stop_price": stop, "target_price": target,
            "risk": entry - stop, "entry_fee": entry_fee,
            "prediction_gross_R": (None if prediction_row is None
                                   else prediction_row["predicted_gross_R"])}
        actions.append({"action": "enter", "symbol": symbol,
            "entry_ms": timestamp, "entry_price": entry, "quantity": quantity,
            "entry_fee": entry_fee, "prediction_gross_R": positions[symbol]["prediction_gross_R"],
            "reason": mode})
        reasons["entry"] += 1

    interval = range(start_ms, end_ms + 1, HOUR_MS)
    for timestamp in interval:
        # Every open position must have an hourly bar throughout its holding period.
        for symbol in list(positions):
            if timestamp not in bars[symbol]:
                raise ValueError(f"missing hourly mark for held {symbol} at {timestamp}")

        observe(portfolio_value(timestamp))
        # Time exits and price gaps are known at the open, before new entries.
        for symbol in list(positions):
            position = positions[symbol]
            bar = bars[symbol][timestamp]
            if mode == "buy_hold":
                continue
            if timestamp >= position["entry_ms"] + HORIZON_MS:
                close_position(symbol, timestamp, bar.open, "time_exit_24h")
                continue
            if bar.open <= position["stop_price"]:
                close_position(symbol, timestamp, bar.open, "stop_gap")
            elif bar.open >= position["target_price"]:
                close_position(symbol, timestamp, bar.open, "target_gap")

        if timestamp == end_ms:
            for symbol in list(positions):
                close_position(symbol, timestamp, bars[symbol][timestamp].open,
                               "period_end_buy_hold" if mode == "buy_hold" else "period_end")

        if mode == "buy_hold" and timestamp == start_ms:
            equity_before = portfolio_value(timestamp)
            for symbol in SYMBOLS:
                if timestamp not in bars[symbol]:
                    raise ValueError("buy-hold start lacks an asset candle")
                entry = bars[symbol][timestamp].open
                stake = min(0.25 * equity_before, cash / (1.0 + side_cost))
                if stake <= 0:
                    continue
                quantity = stake / entry
                notional = quantity * entry
                charge = notional * side_cost
                cash -= notional + charge
                fees += charge
                turnover += notional
                positions[symbol] = {"entry_ms": timestamp, "entry_price": entry,
                    "quantity": quantity, "stop_price": None,
                    "target_price": None, "risk": None, "entry_fee": charge,
                    "prediction_gross_R": None}
                actions.append({"action": "enter", "symbol": symbol,
                    "entry_ms": timestamp, "entry_price": entry, "quantity": quantity,
                    "entry_fee": charge, "reason": "buy_hold"})
                reasons["entry"] += 1
        elif mode in {"ml_gated", "all_sweeps"}:
            by_symbol = candidates.get(timestamp, {})
            equity_before = portfolio_value(timestamp)
            for symbol in SYMBOLS:
                event = by_symbol.get(symbol)
                if event is None:
                    continue
                if symbol in positions:
                    reasons["position_already_open"] += 1
                    continue
                prediction_row = predictions.get((timestamp, symbol))
                if mode == "ml_gated":
                    risk_fraction = event["risk_fraction"]
                    if prediction_row is None:
                        reasons["model_not_ready"] += 1
                        continue
                    if prediction_row["predicted_gross_R"] * risk_fraction <= 2 * side_cost:
                        reasons["expected_gross_below_round_trip_cost"] += 1
                        continue
                enter(symbol, timestamp, event, prediction_row, equity_before)

        # Resolve barriers for the part of this hourly candle after its open.
        live_before_intrabar = list(positions)
        intrahour_high = cash + math.fsum(positions[symbol]["quantity"]
            * bars[symbol][timestamp].high for symbol in live_before_intrabar)
        intrahour_worst = cash + math.fsum(positions[symbol]["quantity"]
            * bars[symbol][timestamp].low for symbol in live_before_intrabar)
        adverse_peak = max(adverse_peak, peak, intrahour_high)
        adverse_drawdown = max(adverse_drawdown, drawdown,
                               1.0 - intrahour_worst / adverse_peak)
        for symbol in live_before_intrabar:
            bar, position = bars[symbol][timestamp], positions[symbol]
            if position.get("risk") is None:
                continue
            stop_touched = bar.low <= position["stop_price"]
            target_touched = bar.high >= position["target_price"]
            if stop_touched and target_touched:
                fill = bar.open if bar.open < position["stop_price"] else position["stop_price"]
                close_position(symbol, timestamp, fill, "stop_first_same_bar")
            elif stop_touched:
                close_position(symbol, timestamp, position["stop_price"], "stop")
            elif target_touched:
                close_position(symbol, timestamp, position["target_price"], "target")

        close_value = cash + math.fsum(positions[symbol]["quantity"] * bars[symbol][timestamp].close
                                       for symbol in positions)
        observe(close_value)
        curve.append([timestamp, close_value])
        utc = datetime.fromtimestamp(timestamp / 1000, timezone.utc)
        if timestamp % (24 * HOUR_MS) == 0:
            daily_equity[utc.strftime("%Y-%m-%d")] = close_value

    if positions:
        raise ValueError("price-action replay ended with an open position")
    final = cash
    reconciliation = final - (1.0 + price_pnl - fees)
    if abs(reconciliation) > 1e-10 * max(1.0, abs(final)):
        raise ValueError("price-action ledger did not reconcile")
    annual = {}
    curve_by_year = {}
    for timestamp, equity in curve:
        year = datetime.fromtimestamp(timestamp / 1000, timezone.utc).year
        curve_by_year.setdefault(year, []).append((timestamp, equity))
    for year, points in curve_by_year.items():
        beginning = points[0][1]
        ending = points[-1][1]
        annual[str(year)] = 100 * (ending / beginning - 1.0)
    days = max(1.0, (end_ms - start_ms) / (24 * HOUR_MS))
    cagr = 100 * (final ** (365.25 / days) - 1.0) if final > 0 else -100.0
    return {"mode": mode, "period": "retrospective_walk_forward",
        "side_cost": side_cost, "return_pct": 100 * (final - 1.0),
        "descriptive_annualized_cagr_pct": cagr,
        "max_drawdown_pct": 100 * drawdown,
        "adverse_intrahour_drawdown_bound_pct": 100 * max(drawdown, adverse_drawdown),
        "entries": sum(action["action"] == "enter" for action in actions),
        "exits": sum(action["action"] == "exit" for action in actions),
        "price_pnl_pct_initial": 100 * price_pnl, "fees_pct_initial": 100 * fees,
        "turnover_multiple_initial": turnover, "daily_equity": daily_equity,
        "hourly_equity": curve, "annual_returns_pct": annual,
        "decision_reasons": dict(reasons), "event_count": event_total,
        "actions": actions, "trades": trades,
        "reconciliation_error": reconciliation, "terminal_equity": final,
        "execution_assumptions": [
            "Spot long/cash only, no leverage, no shorts and no live orders.",
            "Entry is the next open after one full hourly delay; stop/target uses OHLC with stop-first same-bar ordering.",
            "Fixed side costs are assumptions; hourly OHLC does not establish historical executable fills.",
            "Events with incomplete historical execution paths are excluded from both training and execution." ]}
