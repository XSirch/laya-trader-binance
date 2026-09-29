"""Paper-only accounting for the fixed C18 USD-M portfolio."""

from __future__ import annotations

from copy import deepcopy
import math


BASE_FEE_RATE = 0.0005
BASE_SLIPPAGE = 0.0005
STRESS_FEE_RATE = 0.001
STRESS_SLIPPAGE = 0.001
MAX_GROSS = 0.5
MAX_GAP_MS = 65 * 60_000


def initialize(server_ms: int, initial_equity: float = 10_000.0) -> dict:
    if type(server_ms) is not int or server_ms < 0:
        raise ValueError("invalid initial server timestamp")
    if not math.isfinite(initial_equity) or initial_equity <= 0:
        raise ValueError("invalid initial paper equity")
    return {
        "schema_version": 1,
        "mode": "paper",
        "live_orders_enabled": False,
        "initial_ms": server_ms,
        "last_ms": server_ms,
        "initial_equity": float(initial_equity),
        "equity": float(initial_equity),
        "peak_equity": float(initial_equity),
        "max_drawdown": 0.0,
        "cumulative_price_pnl": 0.0,
        "funding_pnl": 0.0,
        "fees": 0.0,
        "turnover_notional": 0.0,
        "positions": {},
        "closed_trades": [],
        "history": [],
        "events": [],
        "assumptions": {
            "base_fee_rate_per_side": BASE_FEE_RATE,
            "base_slippage_per_side": BASE_SLIPPAGE,
            "stress_fee_rate_per_side": STRESS_FEE_RATE,
            "stress_slippage_per_side": STRESS_SLIPPAGE,
            "maximum_gross_exposure": MAX_GROSS,
        },
    }


def _finite(value, name, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"invalid {name}")
    value = float(value)
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(f"invalid {name}")
    return value


def _validate_state(state: dict) -> None:
    if not isinstance(state, dict) or state.get("schema_version") != 1:
        raise ValueError("invalid C18 paper account")
    if state.get("mode") != "paper" or state.get("live_orders_enabled") is not False:
        raise ValueError("C18 account is not simulation-only")
    initial = _finite(state.get("initial_equity"), "initial equity", positive=True)
    equity = _finite(state.get("equity"), "equity")
    peak_equity = _finite(state.get("peak_equity"), "peak equity", positive=True)
    max_drawdown = _finite(state.get("max_drawdown"), "maximum drawdown")
    pnl = _finite(state.get("cumulative_price_pnl"), "price pnl")
    funding = _finite(state.get("funding_pnl"), "funding pnl")
    fees = _finite(state.get("fees"), "fees")
    turnover = _finite(state.get("turnover_notional"), "turnover")
    if fees < 0 or turnover < 0 or not math.isclose(equity, initial + pnl + funding - fees,
                                    rel_tol=1e-12, abs_tol=1e-8):
        raise ValueError("C18 paper equity does not reconcile")
    if (peak_equity < max(initial, equity) or not 0 <= max_drawdown < 1
            or not isinstance(state.get("closed_trades"), list)
            or not isinstance(state.get("history"), list)
            or not isinstance(state.get("events"), list)):
        raise ValueError("invalid C18 account history or drawdown")
    if type(state.get("last_ms")) is not int or state["last_ms"] < 0:
        raise ValueError("invalid C18 account timestamp")
    if not isinstance(state.get("positions"), dict):
        raise ValueError("invalid C18 positions")
    for symbol, position in state["positions"].items():
        if not isinstance(symbol, str) or not symbol:
            raise ValueError("invalid C18 position symbol")
        quantity = _finite(position.get("quantity"), "position quantity")
        _finite(position.get("mark_price"), "position mark", positive=True)
        trade = position.get("trade")
        if quantity == 0 or not isinstance(trade, dict):
            raise ValueError("invalid C18 open trade")
        _finite(trade.get("entry_notional"), "trade entry notional", positive=True)
        _finite(trade.get("net_pnl"), "trade net pnl")


def _quotes(snapshot: dict) -> dict:
    source = snapshot.get("accepted_quotes")
    if not isinstance(source, dict):
        raise ValueError("missing C18 accepted quotes")
    result = {}
    for symbol, row in source.items():
        bid = _finite(row.get("bidPrice"), "bid price", positive=True)
        ask = _finite(row.get("askPrice"), "ask price", positive=True)
        if ask < bid:
            raise ValueError(f"crossed C18 quote: {symbol}")
        midpoint = bid / 2 + ask / 2
        result[symbol] = {"bid": bid, "ask": ask, "midpoint": midpoint}
    return result


def _funding(rows, last_ms: int, now_ms: int) -> list[dict]:
    if not isinstance(rows, list):
        raise ValueError("invalid C18 funding rows")
    seen, result = set(), []
    for row in rows:
        symbol = row.get("symbol")
        timestamp = row.get("timestamp_ms")
        if (not isinstance(symbol, str) or not symbol or type(timestamp) is not int
                or timestamp <= last_ms or timestamp > now_ms):
            raise ValueError("invalid C18 funding timestamp or symbol")
        if (symbol, timestamp) in seen:
            raise ValueError("duplicate C18 funding event")
        seen.add((symbol, timestamp))
        result.append({"symbol": symbol, "timestamp_ms": timestamp,
                       "rate": _finite(row.get("rate"), "funding rate"),
                       "mark_price": _finite(row.get("mark_price"), "funding mark", positive=True)})
    return sorted(result, key=lambda row: (row["timestamp_ms"], row["symbol"]))


def _targets(targets):
    if targets is None:
        return None
    if not isinstance(targets, dict):
        raise ValueError("invalid C18 target weights")
    result = {}
    for symbol, weight in targets.items():
        if not isinstance(symbol, str) or not symbol:
            raise ValueError("invalid C18 target symbol")
        result[symbol] = _finite(weight, "target weight")
    if (any(abs(weight) > MAX_GROSS + 1e-12 for weight in result.values())
            or math.fsum(abs(weight) for weight in result.values()) > MAX_GROSS + 1e-12):
        raise ValueError("C18 target gross exceeds 0.5")
    return result


def _new_trade(symbol: str, direction: int, now_ms: int, midpoint: float, quantity: float) -> dict:
    return {
        "trade_id": f"{symbol}:{now_ms}:{direction}",
        "symbol": symbol,
        "direction": direction,
        "entry_ms": now_ms,
        "entry_notional": abs(quantity) * midpoint,
        "net_pnl": 0.0,
        "price_pnl": 0.0,
        "funding_pnl": 0.0,
        "fees": 0.0,
        "rebalance_count": 0,
    }


def _allocate_fill(trade: dict, fill_pnl: float, fee: float, ratio: float = 1.0) -> None:
    trade["price_pnl"] += fill_pnl * ratio
    trade["fees"] += fee * ratio
    trade["net_pnl"] += (fill_pnl - fee) * ratio
    trade["rebalance_count"] += 1


def _close_trade(trade: dict, now_ms: int, reason: str) -> dict:
    row = {**trade, "exit_ms": now_ms, "exit_reason": reason,
           "net_return_on_entry_notional": trade["net_pnl"] / trade["entry_notional"]}
    if not math.isfinite(row["net_return_on_entry_notional"]):
        raise ValueError("non-finite C18 trade return")
    return row


def advance(state: dict, snapshot: dict, targets=None, *, fee_rate: float, slippage: float) -> dict:
    """Return a new paper account after one observed quote/funding tick."""
    _validate_state(state)
    now_ms = snapshot.get("server_time_ms")
    if type(now_ms) is not int or now_ms <= state["last_ms"]:
        raise ValueError("nonmonotonic C18 paper timestamp")
    if state["positions"] and now_ms - state["last_ms"] > MAX_GAP_MS:
        raise ValueError("C18 observation gap exceeds 65 minutes with open positions")
    fee_rate = _finite(fee_rate, "fee rate")
    slippage = _finite(slippage, "slippage")
    if fee_rate < 0 or slippage < 0 or slippage >= 1:
        raise ValueError("invalid C18 execution costs")
    quotes = _quotes(snapshot)
    funding_rows = _funding(snapshot.get("funding"), state["last_ms"], now_ms)
    desired = _targets(targets)
    if set(state["positions"]) - quotes.keys():
        raise ValueError("open C18 position lacks a fresh quote")
    if desired is not None and set(desired) - quotes.keys():
        raise ValueError("C18 target lacks a fresh quote")

    new = deepcopy(state)
    events = []
    mark_pnl = 0.0
    funding_pnl = 0.0
    fill_pnl = 0.0
    fee_total = 0.0
    turnover = 0.0

    for symbol, position in sorted(state["positions"].items()):
        midpoint = quotes[symbol]["midpoint"]
        pnl = position["quantity"] * (midpoint - position["mark_price"])
        mark_pnl += pnl
        new["positions"][symbol]["mark_price"] = midpoint
        new["positions"][symbol]["trade"]["price_pnl"] += pnl
        new["positions"][symbol]["trade"]["net_pnl"] += pnl
        events.append({"type": "mark", "timestamp_ms": now_ms, "symbol": symbol,
                       "quantity": position["quantity"], "midpoint": midpoint, "price_pnl": pnl})

    for row in funding_rows:
        position = state["positions"].get(row["symbol"])
        if position is None:
            continue
        pnl = -position["quantity"] * row["mark_price"] * row["rate"]
        funding_pnl += pnl
        new["positions"][row["symbol"]]["trade"]["funding_pnl"] += pnl
        new["positions"][row["symbol"]]["trade"]["net_pnl"] += pnl
        events.append({"type": "funding", "observed_at_ms": now_ms, **row,
                       "quantity": position["quantity"], "funding_pnl": pnl})

    pre_cost_equity = state["equity"] + mark_pnl + funding_pnl
    if not math.isfinite(pre_cost_equity) or (pre_cost_equity <= 0 and desired and any(desired.values())):
        raise ValueError("invalid C18 pre-cost equity")
    if desired is not None:
        quantities = {symbol: weight * pre_cost_equity / quotes[symbol]["midpoint"]
                      for symbol, weight in desired.items() if weight != 0}
        for symbol in sorted(set(new["positions"]) | quantities.keys()):
            old_position = new["positions"].get(symbol)
            old_quantity = old_position["quantity"] if old_position else 0.0
            new_quantity = quantities.get(symbol, 0.0)
            delta = new_quantity - old_quantity
            if delta == 0:
                continue
            quote = quotes[symbol]
            buy = delta > 0
            observed_price = quote["ask"] if buy else quote["bid"]
            fill_price = observed_price * (1 + slippage if buy else 1 - slippage)
            pnl = delta * (quote["midpoint"] - fill_price)
            fee = abs(delta) * fill_price * fee_rate
            fill_pnl += pnl
            fee_total += fee
            turnover += abs(delta) * quote["midpoint"]

            old_direction = 1 if old_quantity > 0 else -1 if old_quantity < 0 else 0
            new_direction = 1 if new_quantity > 0 else -1 if new_quantity < 0 else 0
            reversal = bool(old_position and new_quantity and old_direction != new_direction)
            closing = bool(old_position and (new_quantity == 0 or reversal))
            opening = bool(new_quantity and (not old_position or reversal))

            if old_position:
                close_ratio = abs(old_quantity) / abs(delta) if reversal else 1.0
                _allocate_fill(old_position["trade"], pnl, fee, close_ratio)
                if closing:
                    row = _close_trade(old_position["trade"], now_ms, "weekly_target_change_or_cash")
                    new["closed_trades"].append(row)
                    events.append({"type": "trade_closed", **row})

            if new_quantity == 0:
                new["positions"].pop(symbol, None)
            elif reversal:
                open_ratio = abs(new_quantity) / abs(delta)
                trade = _new_trade(symbol, new_direction, now_ms, quote["midpoint"], new_quantity)
                _allocate_fill(trade, pnl, fee, open_ratio)
                new["positions"][symbol] = {"quantity": new_quantity, "mark_price": quote["midpoint"],
                                            "trade": trade}
            elif opening:
                trade = _new_trade(symbol, new_direction, now_ms, quote["midpoint"], new_quantity)
                _allocate_fill(trade, pnl, fee)
                new["positions"][symbol] = {"quantity": new_quantity, "mark_price": quote["midpoint"],
                                            "trade": trade}
            else:
                new["positions"][symbol]["quantity"] = new_quantity
                _allocate_fill(new["positions"][symbol]["trade"], pnl, fee)

            events.append({"type": "paper_fill", "timestamp_ms": now_ms, "symbol": symbol,
                           "side": "buy" if buy else "sell", "delta_quantity": delta,
                           "new_quantity": new_quantity, "midpoint": quote["midpoint"],
                           "observed_price": observed_price, "assumed_fill_price": fill_price,
                           "fee_rate": fee_rate, "fee": fee, "assumed_slippage": slippage,
                           "price_pnl": pnl})

    new["cumulative_price_pnl"] += mark_pnl + fill_pnl
    new["funding_pnl"] += funding_pnl
    new["fees"] += fee_total
    new["turnover_notional"] += turnover
    new["equity"] = (new["initial_equity"] + new["cumulative_price_pnl"]
                     + new["funding_pnl"] - new["fees"])
    if not math.isfinite(new["equity"]):
        raise ValueError("non-finite C18 paper equity")
    new["peak_equity"] = max(state["peak_equity"], new["equity"])
    new["max_drawdown"] = max(state["max_drawdown"],
                              1 - new["equity"] / new["peak_equity"])
    gross = math.fsum(abs(position["quantity"]) * position["mark_price"]
                      for position in new["positions"].values())
    if gross > MAX_GROSS * max(pre_cost_equity, 0) + 1e-8:
        raise ValueError("C18 paper gross exposure exceeds the fixed cap")
    new["last_ms"] = now_ms
    new["events"] = events
    _validate_state(new)
    return new
