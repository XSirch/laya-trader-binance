"""Pure accounting for an observed, simulated futures portfolio.

This module never submits orders. Quotes are observations; fills, fees and
slippage are explicit paper assumptions. An invalid tick raises ValueError and
leaves its input state untouched, including when only one leg cannot be filled.
"""

from copy import deepcopy
import math


FEE_RATE = .001
EXTRA_SLIPPAGE = .0005
MAX_QUOTE_AGE_MS = 30_000
MAX_OBSERVATION_GAP_MS = 65 * 60_000
MAX_TARGET_GROSS = .5


def _number(value, name, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"invalid {name}")
    value = float(value)
    if (not math.isfinite(value) or positive and value <= 0 or
            nonnegative and value < 0):
        raise ValueError(f"invalid {name}")
    return value


def _millis(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"invalid {name}")
    return value


def _distance(value):
    if value is None:
        return None
    value = _number(value, "trailing distance", positive=True)
    if value >= 1:
        raise ValueError("invalid trailing distance")
    return value


def _symbol(value):
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError("invalid symbol")
    return value


def initialize(server_ms, initial_cash=10000.0, trailing_distance=None):
    """Return a flat JSON-serializable paper account at a server timestamp."""
    server_ms = _millis(server_ms, "server timestamp")
    initial_cash = _number(initial_cash, "initial cash", positive=True)
    return {
        "schema_version": 1,
        "mode": "paper",
        "live_orders_enabled": False,
        "initial_ms": server_ms,
        "last_ms": server_ms,
        "initial_equity": initial_cash,
        "equity": initial_cash,
        "positions": {},
        "fees": 0.0,
        "funding_pnl": 0.0,
        "cumulative_price_pnl": 0.0,
        "trailing_distance": _distance(trailing_distance),
        "portfolio_peak": None,
        "assumptions": {"fee_rate": FEE_RATE, "extra_slippage": EXTRA_SLIPPAGE},
        "events": [],
        "history": [],
    }


def _validate_state(state):
    if not isinstance(state, dict) or state.get("schema_version") != 1:
        raise ValueError("invalid paper state")
    if state.get("mode") != "paper" or state.get("live_orders_enabled") is not False:
        raise ValueError("invalid paper mode")
    try:
        _millis(state["last_ms"], "last timestamp")
        initial = _number(state["initial_equity"], "initial equity", positive=True)
        equity = _number(state["equity"], "equity")
        fees = _number(state["fees"], "fees", nonnegative=True)
        funding = _number(state["funding_pnl"], "funding pnl")
        price = _number(state["cumulative_price_pnl"], "price pnl")
        _distance(state["trailing_distance"])
        if not math.isclose(equity, initial + price + funding - fees,
                            rel_tol=1e-12, abs_tol=1e-8):
            raise ValueError("paper equity does not reconcile")
        if state["assumptions"] != {"fee_rate": FEE_RATE, "extra_slippage": EXTRA_SLIPPAGE}:
            raise ValueError("changed paper fill assumptions")
        if not isinstance(state["positions"], dict):
            raise ValueError("invalid positions")
        for symbol, position in state["positions"].items():
            _symbol(symbol)
            quantity = _number(position["quantity"], "position quantity")
            if quantity == 0:
                raise ValueError("zero position must be absent")
            _number(position["mark_price"], "position mark", positive=True)
        if state["positions"]:
            _number(state["portfolio_peak"], "portfolio peak", positive=True)
        elif state["portfolio_peak"] is not None:
            raise ValueError("flat portfolio must reset its peak")
        if not isinstance(state["history"], list) or not isinstance(state["events"], list):
            raise ValueError("invalid paper audit")
    except (KeyError, TypeError) as exc:
        raise ValueError("incomplete paper state") from exc


def _quotes(snapshot, now):
    source = snapshot.get("accepted_quotes")
    if not isinstance(source, dict):
        raise ValueError("missing accepted quotes")
    result = {}
    for symbol, row in source.items():
        _symbol(symbol)
        try:
            bid = _number(row["bidPrice"], "bid price", positive=True)
            ask = _number(row["askPrice"], "ask price", positive=True)
            bid_qty = _number(row["bidQty"], "bid quantity", nonnegative=True)
            ask_qty = _number(row["askQty"], "ask quantity", nonnegative=True)
            quote_ms = _millis(row["quote_time_ms"], "quote timestamp")
            age = _millis(row["age_ms"], "quote age")
        except (KeyError, TypeError) as exc:
            raise ValueError(f"incomplete quote: {symbol}") from exc
        if quote_ms > now:
            raise ValueError(f"future quote: {symbol}")
        if age != now - quote_ms:
            raise ValueError(f"inconsistent quote age: {symbol}")
        if age > MAX_QUOTE_AGE_MS:
            raise ValueError(f"stale quote: {symbol}")
        if ask < bid:
            raise ValueError(f"crossed quote: {symbol}")
        midpoint = bid / 2 + ask / 2
        result[symbol] = {"bidPrice": bid, "askPrice": ask, "bidQty": bid_qty,
                          "askQty": ask_qty, "midpoint": midpoint,
                          "quote_time_ms": quote_ms, "age_ms": age}
    return result


def _funding(snapshot, now):
    rows = snapshot.get("funding")
    if not isinstance(rows, list):
        raise ValueError("missing funding observations")
    seen, result = set(), []
    for row in rows:
        try:
            symbol = _symbol(row["symbol"])
            timestamp = _millis(row["timestamp_ms"], "funding timestamp")
            rate = _number(row["rate"], "funding rate")
            mark = _number(row["mark_price"], "funding mark", positive=True)
        except (KeyError, TypeError) as exc:
            raise ValueError("incomplete funding observation") from exc
        if timestamp > now:
            raise ValueError("future funding observation")
        key = (symbol, timestamp)
        if key in seen:
            raise ValueError(f"duplicate funding: {symbol} {timestamp}")
        seen.add(key)
        result.append({"symbol": symbol, "timestamp_ms": timestamp,
                       "rate": rate, "mark_price": mark})
    return sorted(result, key=lambda row: (row["timestamp_ms"], row["symbol"]))


def _targets(targets):
    if targets is None:
        return None
    if not isinstance(targets, dict):
        raise ValueError("invalid target weights")
    result = {_symbol(symbol): _number(weight, "target weight")
              for symbol, weight in targets.items()}
    if (any(abs(weight) > MAX_TARGET_GROSS + 1e-12 for weight in result.values()) or
            math.fsum(abs(weight) for weight in result.values()) > MAX_TARGET_GROSS + 1e-12):
        raise ValueError("target gross exposure exceeds 0.5")
    return result


def advance(state, snapshot, targets=None):
    """Observe one tick and return a NEW paper state, or raise ValueError.

    ``targets`` maps symbols to signed weights of pre-trade equity. None holds
    quantities; an empty dict closes every leg. Funding in (last_ms, now] is
    applied to the positions held before this tick, before any new fills.
    A trailing trigger closes all legs and suppresses provided targets for this
    tick. Scheduling a later reentry is the caller's responsibility.
    """
    _validate_state(state)
    if not isinstance(snapshot, dict):
        raise ValueError("invalid paper snapshot")
    now = _millis(snapshot.get("server_time_ms"), "server timestamp")
    if now <= state["last_ms"]:
        raise ValueError("nonmonotonic server timestamp")
    if state["positions"] and now - state["last_ms"] > MAX_OBSERVATION_GAP_MS:
        raise ValueError("observation gap exceeds 65 minutes with open positions")
    quotes = _quotes(snapshot, now)
    funding_rows = _funding(snapshot, now)
    desired = _targets(targets)
    required = set(state["positions"])
    missing = required - quotes.keys()
    if missing:
        raise ValueError(f"missing quote: {','.join(sorted(missing))}")

    new = deepcopy(state)
    events = []
    mark_pnl = 0.0
    funding_pnl = 0.0
    fill_pnl = 0.0
    fee_total = 0.0
    for symbol, position in sorted(state["positions"].items()):
        midpoint = quotes[symbol]["midpoint"]
        pnl = position["quantity"] * (midpoint - position["mark_price"])
        mark_pnl += pnl
        new["positions"][symbol]["mark_price"] = midpoint
        events.append({"type": "mark", "timestamp_ms": now, "symbol": symbol,
                       "quantity": position["quantity"], "previous_mark": position["mark_price"],
                       "midpoint": midpoint, "price_pnl": pnl})
    for row in funding_rows:
        if row["timestamp_ms"] <= state["last_ms"]:
            continue
        position = state["positions"].get(row["symbol"])
        if position is None:
            continue
        pnl = -position["quantity"] * row["mark_price"] * row["rate"]
        funding_pnl += pnl
        events.append({"type": "funding", "observed_at_ms": now, **row,
                       "quantity": position["quantity"], "funding_pnl": pnl})

    pre_cost_equity = state["equity"] + mark_pnl + funding_pnl
    _number(pre_cost_equity, "pre-cost equity")
    distance = state["trailing_distance"]
    peak = state["portfolio_peak"]
    trigger = bool(state["positions"] and distance is not None and
                   pre_cost_equity <= peak * (1 - distance))
    if trigger:
        events.append({"type": "portfolio_trailing", "timestamp_ms": now,
                       "observed_equity": pre_cost_equity, "prior_peak": peak,
                       "threshold_equity": peak * (1 - distance),
                       "distance": distance, "targets_suppressed": targets is not None})
        desired = {}
    if desired is not None:
        missing = {symbol for symbol, weight in desired.items() if weight != 0} - quotes.keys()
        if missing:
            raise ValueError(f"missing quote: {','.join(sorted(missing))}")
        if pre_cost_equity <= 0 and any(desired.values()):
            raise ValueError("cannot allocate nonpositive equity")
        quantities = {symbol: weight * pre_cost_equity / quotes[symbol]["midpoint"]
                      for symbol, weight in desired.items() if weight != 0}
        for symbol in sorted(set(new["positions"]) | quantities.keys()):
            old_quantity = new["positions"].get(symbol, {}).get("quantity", 0.0)
            quantity = quantities.get(symbol, 0.0)
            delta = quantity - old_quantity
            if delta == 0:
                continue
            quote = quotes[symbol]
            buy = delta > 0
            observed = quote["askPrice"] if buy else quote["bidPrice"]
            available = quote["askQty"] if buy else quote["bidQty"]
            if abs(delta) > available:
                raise ValueError(f"insufficient top-of-book quantity: {symbol}")
            fill = observed * (1 + EXTRA_SLIPPAGE if buy else 1 - EXTRA_SLIPPAGE)
            pnl = delta * (quote["midpoint"] - fill)
            fee = abs(delta) * fill * FEE_RATE
            fill_pnl += pnl
            fee_total += fee
            events.append({"type": "paper_fill", "timestamp_ms": now, "symbol": symbol,
                           "reason": "portfolio_trailing" if trigger else "explicit_targets",
                           "side": "buy" if buy else "sell", "delta_quantity": delta,
                           "previous_quantity": old_quantity, "new_quantity": quantity,
                           "midpoint": quote["midpoint"], "observed_price": observed,
                           "observed_top_quantity": available, "assumed_fill_price": fill,
                           "assumed_extra_slippage": EXTRA_SLIPPAGE, "fee_rate": FEE_RATE,
                           "fee": fee, "price_pnl": pnl,
                           "quote_time_ms": quote["quote_time_ms"], "age_ms": quote["age_ms"],
                           "sizing_equity": pre_cost_equity})
            if quantity:
                new["positions"][symbol] = {"quantity": quantity, "mark_price": quote["midpoint"]}
            else:
                new["positions"].pop(symbol, None)

    new["fees"] += fee_total
    new["funding_pnl"] += funding_pnl
    new["cumulative_price_pnl"] += mark_pnl + fill_pnl
    new["equity"] = (new["initial_equity"] + new["cumulative_price_pnl"] +
                     new["funding_pnl"] - new["fees"])
    _number(new["equity"], "resulting equity")
    if not new["positions"]:
        new["portfolio_peak"] = None
    elif state["positions"]:
        # A held portfolio reached this observed equity before rebalance costs.
        # Those costs must not loosen its existing trailing watermark.
        new["portfolio_peak"] = max(peak, pre_cost_equity, new["equity"])
    else:
        new["portfolio_peak"] = new["equity"]
    new["last_ms"] = now
    new["events"].extend(events)
    new["history"].append({"timestamp_ms": now, "equity": new["equity"],
                           "pre_cost_equity": pre_cost_equity, "mark_pnl": mark_pnl,
                           "funding_pnl": funding_pnl, "fill_pnl": fill_pnl, "fees": fee_total,
                           "trailing_triggered": trigger, "targets_provided": targets is not None,
                           "gross_notional": sum(abs(p["quantity"]) * p["mark_price"]
                                                 for p in new["positions"].values()),
                           "event_start": len(state["events"]), "event_end": len(new["events"])})
    return new
