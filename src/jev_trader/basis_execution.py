"""Isolated, segregated-wallet spot/short-perpetual hourly research ledger.

Hourly fills are assumptions, not simultaneous executable quotes. No network,
orders, borrowing, spot collateral credit, or transfers while invested exist.
"""

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math

from .binance_data import HOUR_MS


DAY_MS = 24 * HOUR_MS


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("invalid finite number: " + name)
    return value


def _time(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("invalid timestamp: " + name)
    return value


def _bars(market, symbol, timestamp, held=False):
    rows = []
    for kind in ("spot", "futures", "mark"):
        bar = market[kind][symbol].get(timestamp)
        if bar is None:
            qualifier = "held price" if held else "execution price"
            raise ValueError(f"missing paired {qualifier} {symbol} {kind} at {timestamp}")
        if bar.open_ms != timestamp:
            raise ValueError("paired candle timestamp mismatch")
        values = [_number(getattr(bar, key), key) for key in ("open", "high", "low", "close")]
        op, high, low, close = values
        if not 0 < low <= min(op, close) <= max(op, close) <= high:
            raise ValueError("invalid paired OHLC")
        rows.append(bar)
    return tuple(rows)


def _liquidity(symbol, timestamp, bars):
    for bar in bars[:2]:
        valid_trades = not isinstance(bar.trades, bool) and isinstance(bar.trades, int) and bar.trades > 0
        valid_volume = (not isinstance(bar.volume, bool) and isinstance(bar.volume, (int, float))
                        and math.isfinite(bar.volume) and bar.volume > 0)
        valid_quote = (bar.quote_volume is None or not isinstance(bar.quote_volume, bool)
                       and isinstance(bar.quote_volume, (int, float)) and math.isfinite(bar.quote_volume)
                       and bar.quote_volume > 0)
        if not valid_trades or not valid_volume or not valid_quote:
            raise ValueError(f"unverified paired execution liquidity {symbol} at {timestamp}")


def evaluate(market, states, policy, start_ms, end_ms, spot_cost, future_cost,
             spot_fraction=.5, max_hold_hours=24, portfolio_trailing=None):
    """Replay equal independent buckets; policy receives state and position/None.

    A state at execution t must end exactly at t-HOUR_MS. Missing states do
    not open positions; automatic exits remain active. Funding is never passed
    to policy. Daily maps use string millisecond timestamps, as other replays.
    """
    _time(start_ms, "start_ms")
    _time(end_ms, "end_ms")
    if start_ms % HOUR_MS or end_ms % HOUR_MS or end_ms <= start_ms:
        raise ValueError("basis window requires increasing hourly endpoints")
    if isinstance(max_hold_hours, bool) or not isinstance(max_hold_hours, int) or max_hold_hours <= 0:
        raise ValueError("positive integer max_hold_hours required")
    for name, value in (("spot_cost", spot_cost), ("future_cost", future_cost)):
        if _number(value, name) < 0:
            raise ValueError("negative execution cost")
    if not 0 < _number(spot_fraction, "spot_fraction") < 1:
        raise ValueError("spot_fraction must lie strictly between zero and one")
    if portfolio_trailing is not None and not 0 < _number(portfolio_trailing, "trailing") < 1:
        raise ValueError("invalid portfolio trailing fraction")
    if set(market) != {"spot", "futures", "mark", "funding"} or not market["spot"]:
        raise ValueError("four nonempty paired market groups required")
    symbols = sorted(market["spot"])
    if any(set(market[kind]) != set(symbols) for kind in market):
        raise ValueError("paired market symbol sets differ")
    if set(states) - set(symbols):
        raise ValueError("state symbol absent from paired market")

    payments = defaultdict(list)
    for symbol in symbols:
        previous = None
        for event in market["funding"][symbol]:
            timestamp = _time(event.timestamp_ms, "funding timestamp")
            rate = _number(event.rate, "funding rate")
            interval = _number(event.interval_hours, "funding interval")
            if interval <= 0 or previous is not None and timestamp <= previous:
                raise ValueError("invalid funding interval or nonincreasing events")
            previous = timestamp
            # Ordinary possession is half-open. The nominal terminal hour is
            # additionally uncertain against the close: retain its possible
            # debits on the old quantity, never a credit on a closed position.
            if start_ms <= timestamp < end_ms+HOUR_MS:
                payments[timestamp // HOUR_MS * HOUR_MS].append((symbol, timestamp, rate))

    size = 1 / len(symbols)
    wallets = {s: {"spot_cash": spot_fraction * size, "margin_cash": (1-spot_fraction)*size,
                   "position": None} for s in symbols}
    attribution = {s: {"basis": 0.0, "funding": 0.0, "fees": 0.0} for s in symbols}
    trades, transfers, funding_log, stops, action_log = [], [], [], [], []
    decision_counts, reason_counts = Counter(), Counter()
    decision_hash = hashlib.sha256()
    hourly, daily, snapshots, monthly = [], {}, {}, {}
    peak, drawdown, adverse_peak, adverse_drawdown = 1.0, 0.0, 1.0, 0.0
    stop_peak, month_start = None, 1.0
    stress_events = set()
    entries, traded_notional = 0, 0.0

    def solvent_cash(symbol, context):
        for name in ("spot_cash", "margin_cash"):
            amount = wallets[symbol][name]
            if not math.isfinite(amount) or amount < -1e-12:
                raise ValueError(f"negative cash wallet {symbol} {name} after {context}")

    def value(symbol, bars=None):
        wallet = wallets[symbol]
        amount = wallet["spot_cash"] + wallet["margin_cash"]
        position = wallet["position"]
        if position is not None:
            spot, _, mark = bars
            q = position["quantity"]
            amount += q*spot.open + q*(position["entry_future"]-mark.open)
        return amount

    def observe(equity):
        nonlocal peak, drawdown
        if not math.isfinite(equity) or equity <= 0:
            raise ValueError("nonpositive basis portfolio equity")
        peak = max(peak, equity)
        drawdown = max(drawdown, 1-equity/peak)

    def close(symbol, timestamp, bars, reason):
        nonlocal traded_notional
        _liquidity(symbol, timestamp, bars)
        wallet, position = wallets[symbol], wallets[symbol]["position"]
        spot, future, _ = bars
        q = position["quantity"]
        fee_s, fee_f = q*spot.open*spot_cost, q*future.open*future_cost
        basis = q*((position["entry_future"]-position["entry_spot"])-(future.open-spot.open))
        wallet["spot_cash"] += q*spot.open-fee_s
        wallet["margin_cash"] += q*(position["entry_future"]-future.open)-fee_f
        solvent_cash(symbol, "paired exit")
        wallet["position"] = None
        attribution[symbol]["basis"] += basis
        attribution[symbol]["fees"] += fee_s+fee_f
        traded_notional += q*(spot.open+future.open)
        trades.append({"timestamp_ms": timestamp, "symbol": symbol, "action": "exit", "reason": reason,
                       "quantity": q, "spot_price": spot.open, "future_price": future.open,
                       "spot_fee": fee_s, "future_fee": fee_f, "basis_pnl": basis,
                       "entry_ms": position["entry_ms"]})

    def enter(symbol, timestamp, bars, target_basis, reason):
        nonlocal entries, traded_notional
        _liquidity(symbol, timestamp, bars)
        wallet = wallets[symbol]
        if wallet["position"] is not None:
            raise ValueError("cannot transfer or enter while invested")
        solvent_cash(symbol, "before flat transfer")
        equity = wallet["spot_cash"]+wallet["margin_cash"]
        if equity <= 0:
            raise ValueError("nonpositive realized bucket equity")
        target_cash = spot_fraction*equity
        delta = target_cash-wallet["spot_cash"]
        if delta:
            transfers.append({"timestamp_ms": timestamp, "symbol": symbol,
                              "spot_cash_change": delta, "margin_cash_change": -delta,
                              "realized_equity": equity, "position_quantity": 0.0})
        wallet["spot_cash"], wallet["margin_cash"] = target_cash, equity-target_cash
        spot, future, _ = bars
        q = min(target_cash/(spot.open*(1+spot_cost)), target_cash/future.open)
        fee_s, fee_f = q*spot.open*spot_cost, q*future.open*future_cost
        if q <= 0 or fee_f > wallet["margin_cash"]:
            raise ValueError("insufficient realized cash for paired entry")
        wallet["spot_cash"] -= q*spot.open+fee_s
        wallet["margin_cash"] -= fee_f
        if abs(wallet["spot_cash"]) < 1e-15:
            wallet["spot_cash"] = 0.0
        solvent_cash(symbol, "paired entry")
        wallet["position"] = {"quantity": q, "entry_ms": timestamp, "entry_spot": spot.open,
                              "entry_future": future.open, "target_basis": target_basis}
        attribution[symbol]["fees"] += fee_s+fee_f
        entries += 1
        traded_notional += q*(spot.open+future.open)
        trades.append({"timestamp_ms": timestamp, "symbol": symbol, "action": "enter", "reason": reason,
                       "quantity": q, "spot_price": spot.open, "future_price": future.open,
                       "spot_fee": fee_s, "future_fee": fee_f, "target_basis": target_basis})

    for timestamp in range(start_ms, end_ms+1, HOUR_MS):
        terminal = timestamp == end_ms
        held = {s: wallets[s]["position"] for s in symbols if wallets[s]["position"] is not None}
        bars = {s: _bars(market, s, timestamp, held=True) for s in held}
        old_q = {s: wallets[s]["position"]["quantity"] if s in held else 0.0 for s in symbols}
        before = math.fsum(value(s, bars.get(s)) for s in symbols)
        observe(before)
        adverse_peak = max(adverse_peak, peak)
        adverse_drawdown = max(adverse_drawdown, drawdown, 1-before/adverse_peak)
        if held:
            stop_peak = max(stop_peak if stop_peak is not None else before, before)
        else:
            stop_peak = None
        triggered = bool(held and not terminal and portfolio_trailing is not None
                         and before <= stop_peak*(1-portfolio_trailing))
        if triggered:
            stops.append({"timestamp_ms": timestamp, "kind": "portfolio_trailing", "peak": stop_peak,
                          "equity_before": before, "fraction": portfolio_trailing, "symbols": sorted(held)})
        for symbol in symbols:
            wallet, position = wallets[symbol], wallets[symbol]["position"]
            margin_ratio = None
            if position is not None:
                mark = bars[symbol][2]
                q = position["quantity"]
                margin_ratio = (wallet["margin_cash"]+q*(position["entry_future"]-mark.open))/(q*mark.open)
                if margin_ratio < .10:
                    stress_events.add((timestamp, symbol))
            decision = {"action": "hold", "reason": "unavailable_state"}
            if terminal:
                decision = {"action": "exit" if position else "hold", "reason": "terminal"}
            elif triggered:
                decision = {"action": "exit" if position else "hold", "reason": "portfolio_trailing"}
            elif position and margin_ratio <= .20:
                decision = {"action": "exit", "reason": "preventive_margin"}
            elif position and timestamp-position["entry_ms"] >= max_hold_hours*HOUR_MS:
                decision = {"action": "exit", "reason": "maximum_holding"}
            elif timestamp in states.get(symbol, {}):
                state = states[symbol][timestamp]
                cutoff = _time(state.get("latest_observed_close_ms"), "state cutoff")
                if cutoff != timestamp-HOUR_MS:
                    raise ValueError("basis state requires one full hour after completed close")
                decision = policy(dict(state), dict(position) if position is not None else None)
                if not isinstance(decision, dict) or decision.get("action") not in ("enter", "hold", "exit"):
                    raise ValueError("invalid basis policy action")
                if not isinstance(decision.get("reason"), str) or not decision["reason"]:
                    raise ValueError("basis policy requires a reason")
                decision = dict(decision)
                if decision["action"] == "enter":
                    if position is not None:
                        raise ValueError("basis policy cannot enter an existing position")
                    _number(decision.get("target_basis"), "target_basis")
                    if timestamp+max_hold_hours*HOUR_MS > end_ms:
                        decision = {"action": "hold", "reason": "insufficient_holding_window"}
                elif decision["action"] == "exit" and position is None:
                    raise ValueError("basis policy cannot exit a flat position")
            action, reason = decision["action"], decision["reason"]
            log = {"timestamp_ms": timestamp, "symbol": symbol, **decision}
            decision_hash.update(json.dumps(log, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()+b"\n")
            decision_counts[action] += 1
            reason_counts[reason] += 1
            if action != "hold":
                action_log.append(log)
                if symbol not in bars:
                    bars[symbol] = _bars(market, symbol, timestamp)
                if action == "enter":
                    enter(symbol, timestamp, bars[symbol], decision["target_basis"], reason)
                else:
                    close(symbol, timestamp, bars[symbol], reason)
        positive_credits = defaultdict(float)
        negative_debits = defaultdict(float)
        for symbol, event_ms, rate in payments.get(timestamp, []):
            wallet, position = wallets[symbol], wallets[symbol]["position"]
            new_q = position["quantity"] if position else 0.0
            if not old_q[symbol] and not new_q:
                continue
            if symbol not in bars:
                bars[symbol] = _bars(market, symbol, timestamp)
            mark = bars[symbol][2]
            eligible = min(old_q[symbol], new_q) if rate >= 0 else max(old_q[symbol], new_q)
            price = mark.low if rate >= 0 else mark.high
            payment = eligible*rate*price
            wallet["margin_cash"] += payment
            solvent_cash(symbol, "funding payment")
            attribution[symbol]["funding"] += payment
            positive_credits[symbol] += max(0, payment)
            negative_debits[symbol] += max(0, -payment)
            funding_log.append({"timestamp_ms": event_ms, "accounting_hour_ms": timestamp, "symbol": symbol,
                                "rate": rate, "old_quantity": old_q[symbol], "new_quantity": new_q,
                                "eligible_quantity": eligible, "adverse_mark": price, "payment": payment})
        equity = math.fsum(value(s, bars.get(s)) for s in symbols)
        observe(equity)
        adverse_peak = max(adverse_peak, peak)
        still_held = [s for s in symbols if wallets[s]["position"] is not None]
        if still_held:
            stop_peak = max(stop_peak if stop_peak is not None else before, equity)
        else:
            stop_peak = None
        if not terminal:
            worst, favorable = 0.0, 0.0
            for symbol in symbols:
                wallet, position = wallets[symbol], wallets[symbol]["position"]
                amount = wallet["spot_cash"]+wallet["margin_cash"]-positive_credits[symbol]
                # Extremum order is unknown: credits may precede a favorable
                # peak and debits may follow it. Never use only open peaks as
                # an alleged upper bound for intrahour peak-to-trough loss.
                best = wallet["spot_cash"]+wallet["margin_cash"]+negative_debits[symbol]
                if position:
                    spot, _, mark = bars[symbol]
                    q = position["quantity"]
                    stressed_margin = wallet["margin_cash"]-positive_credits[symbol]+q*(position["entry_future"]-mark.high)
                    if stressed_margin < .10*q*mark.high:
                        stress_events.add((timestamp, symbol))
                    amount += q*spot.low+q*(position["entry_future"]-mark.high)
                    best += q*spot.high+q*(position["entry_future"]-mark.low)
                worst += amount
                favorable += best
            adverse_peak = max(adverse_peak, peak, favorable)
            adverse_drawdown = max(adverse_drawdown, drawdown, 1-worst/adverse_peak)
        # The final liquidation and its fees can fall below a prior possible
        # intrahour peak even though no subsequent terminal-hour path is held.
        adverse_drawdown = max(adverse_drawdown, drawdown, 1-equity/adverse_peak)
        hourly.append([timestamp, equity])
        if timestamp % DAY_MS == 0 or timestamp in (start_ms, end_ms):
            daily[str(timestamp)] = equity
            snapshots[str(timestamp)] = {}
            for symbol in symbols:
                wallet, position = wallets[symbol], wallets[symbol]["position"]
                q = position["quantity"] if position else 0.0
                unrealized = q*(position["entry_future"]-bars[symbol][2].open) if position else 0.0
                snapshots[str(timestamp)][symbol] = {"spot_cash": wallet["spot_cash"], "margin_cash": wallet["margin_cash"],
                    "spot_quantity": q, "short_quantity": q, "position": dict(position) if position else None,
                    "unrealized_perp_pnl": unrealized, "equity": value(symbol, bars.get(symbol))}
        now = datetime.fromtimestamp(timestamp/1000, timezone.utc)
        if timestamp > start_ms and (now.day == 1 and now.hour == 0 or terminal):
            month = datetime.fromtimestamp((timestamp-HOUR_MS)/1000, timezone.utc).strftime("%Y-%m")
            monthly[month] = 100*(equity/month_start-1)
            month_start = equity

    basis = math.fsum(row["basis"] for row in attribution.values())
    fees = math.fsum(row["fees"] for row in attribution.values())
    funding = math.fsum(row["funding"] for row in attribution.values())
    error = equity-(1+basis+funding-fees)
    if abs(error) > 1e-10*max(1, abs(equity)):
        raise ValueError("basis wallet attribution failed reconciliation")
    return {"return_pct": 100*(equity-1), "max_drawdown_pct": 100*drawdown,
            "adverse_intrahour_drawdown_bound_pct": 100*max(adverse_drawdown, drawdown),
            "margin_stress_failures": len(stress_events), "fees_pct_initial": 100*fees,
            "funding_pct_initial": 100*funding, "basis_pnl_pct_initial": 100*basis,
            "entries": entries, "trade_events": trades, "transfer_events": transfers,
            "funding_events": funding_log, "stop_events": stops, "stop_count": len(stops),
            "monthly_returns_pct": monthly, "daily_equity": daily, "hourly_equity": hourly,
            "wallet_snapshots": snapshots, "asset_attribution": {s: {
                "basis_pnl_pct_initial": 100*a["basis"], "funding_pct_initial": 100*a["funding"],
                "fees_pct_initial": 100*a["fees"], "net_pct_initial": 100*(a["basis"]+a["funding"]-a["fees"])}
                for s, a in attribution.items()}, "decision_counts": dict(decision_counts),
            "decision_reason_counts": dict(reason_counts), "decision_digest": decision_hash.hexdigest(),
            "action_decisions": action_log, "traded_notional_multiple_initial": traded_notional,
            "reconciliation_error": error, "execution_assumptions": [
                "Paired hourly opens are assumed fills, not simultaneous executable quotes.",
                "Contemporaneous OHLC and trade counts verify a fill only after the fact.",
                "Terminal-hour funding may debit the old position; closing never earns its positive payment.",
                "Separate cash wallets; no borrowed spot, unrealized-profit transfers, or cross-bucket transfers.",
                "Intrahour loss bounds pair possible favorable peaks with adverse spot-low/mark-high equity; these are not observed paths.",
                "20% preventive margin exit and 10% maintenance stress are research heuristics."]}
