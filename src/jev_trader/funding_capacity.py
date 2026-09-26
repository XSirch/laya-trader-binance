"""Offline funding-income index; deliberately not a tradable portfolio backtest.

The index assumes free continuous notional resets, excludes every price/basis
effect and cost, and cannot establish the return or drawdown of a real account.
Positive perpetual funding is income for the hypothetical short futures leg;
negative funding is a debit. No spot leg or margin account is simulated here.
"""

from bisect import bisect_left
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import re


HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS
RULES = ("top5_30", "top5_persistent", "top1_30")


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _integer(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be integer milliseconds")
    return value


def _timestamp(value, name, allow_date=False):
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an integer timestamp or UTC ISO string")
    if allow_date and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        value += "T00:00:00+00:00"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"invalid {name}") from error
    if parsed.utcoffset() != timedelta(0) or parsed.microsecond % 1000:
        raise ValueError(f"{name} must have explicit UTC timezone and millisecond precision")
    return int(parsed.timestamp() * 1000)


def _symbol(value):
    if not isinstance(value, str) or re.fullmatch(r"[A-Z0-9]+", value) is None:
        raise ValueError("invalid symbol")
    return value


def _finite_features(value, path):
    if isinstance(value, Mapping):
        for key, nested in value.items():
            _finite_features(nested, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _finite_features(nested, f"{path}[{index}]")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        _number(value, path)


@dataclass(frozen=True)
class _Funding:
    timestamp_ms: int
    interval_hours: float
    rate: float


def _funding_rows(funding):
    if not isinstance(funding, Mapping):
        raise ValueError("funding must be a symbol mapping")
    output = {}
    for symbol, rows in funding.items():
        _symbol(symbol)
        parsed, seen = [], set()
        for row in rows:
            try:
                timestamp = _integer(row.timestamp_ms, "funding timestamp")
                interval = _number(row.interval_hours, "funding interval_hours")
                rate = _number(row.rate, "funding rate")
            except AttributeError as error:
                raise ValueError("funding rows must expose timestamp_ms, interval_hours, rate") from error
            if interval <= 0:
                raise ValueError("funding interval_hours must be positive")
            if timestamp in seen:
                raise ValueError(f"duplicate funding event for {symbol} at {timestamp}")
            seen.add(timestamp)
            parsed.append(_Funding(timestamp, interval, rate))
        output[symbol] = tuple(sorted(parsed, key=lambda row: row.timestamp_ms))
    return output


def _state_rows(states, funding):
    if not isinstance(states, Mapping):
        raise ValueError("states must be a symbol mapping")
    output = {}
    for symbol, rows in states.items():
        _symbol(symbol)
        if symbol not in funding or not isinstance(rows, Mapping):
            raise ValueError("each state symbol requires funding rows and a timestamp mapping")
        output[symbol] = {}
        for cutoff, row in rows.items():
            _integer(cutoff, "state cutoff")
            if cutoff % DAY_MS or not isinstance(row, Mapping):
                raise ValueError("states require midnight UTC cutoffs and mapping rows")
            observed = _integer(row.get("latest_observed_close_ms"), "latest observed close")
            if observed != cutoff:
                raise ValueError("state latest_observed_close_ms must equal its daily cutoff")
            values = {key: _number(row.get(key), key)
                      for key in ("carry30", "quote_volume20", "volatility")}
            if values["quote_volume20"] < 0 or values["volatility"] < 0:
                raise ValueError("state volume and volatility must be nonnegative")
            # Validate unused numeric indicators too, including nested structures.
            _finite_features(row, symbol)
            output[symbol][cutoff] = values
    return output


def _lifecycle(events):
    output, seen = {}, set()
    for row in events:
        if not isinstance(row, Mapping):
            raise ValueError("lifecycle events must be mappings")
        symbol = _symbol(row.get("symbol"))
        if symbol in seen:
            raise ValueError("duplicate lifecycle symbol")
        seen.add(symbol)
        published = _timestamp(row.get("published_utc"), "published_utc")
        restriction = _timestamp(row.get("new_positions_stop_utc"), "new_positions_stop_utc")
        settlement = row.get("automatic_settlement_utc")
        settlement = None if settlement is None else _timestamp(settlement, "automatic_settlement_utc")
        if settlement is not None and settlement < restriction:
            raise ValueError("automatic settlement must not precede the new-position restriction")
        # A late notice never acts retrospectively, even if its scheduled date is past.
        output[symbol] = {"restricted_ms": max(published, restriction),
                          "settled_ms": None if settlement is None else max(published, settlement),
                          "published_ms": published}
    return output


def _past(rows, times, cutoff, days):
    first = bisect_left(times, cutoff - days * DAY_MS)
    last = bisect_left(times, cutoff)
    window = rows[first:last]
    return {"apr": math.fsum(row.rate for row in window) * 365 / days,
            "coverage_hours": math.fsum(row.interval_hours for row in window),
            "event_count": len(window),
            "last_funding_ms": window[-1].timestamp_ms if window else None}


def _targets(funding, times, states, lifecycle, rule, cutoff, ratio):
    execution = cutoff + HOUR_MS
    ranked, excluded, missing, ineligible = [], [], [], []
    for symbol in sorted(states):
        event = lifecycle.get(symbol)
        if event and event["restricted_ms"] <= execution:
            excluded.append(symbol)
            continue
        row = states[symbol].get(cutoff)
        if row is None:
            missing.append(symbol)
            continue
        if row["quote_volume20"] < 10_000_000 or not .005 <= row["volatility"] <= .15:
            ineligible.append(symbol)
            continue
        past30 = _past(funding[symbol], times[symbol], cutoff, 30)
        past7 = _past(funding[symbol], times[symbol], cutoff, 7)
        if past30["coverage_hours"] < 28 * 24 or past30["apr"] <= 0:
            ineligible.append(symbol)
            continue
        if rule == "top5_persistent" and (past7["coverage_hours"] < 6 * 24 or past7["apr"] <= 0):
            ineligible.append(symbol)
            continue
        score = min(past30["apr"], past7["apr"]) if rule == "top5_persistent" else past30["apr"]
        ranked.append({"symbol": symbol, "ranking_apr": score,
                       "past30_apr": past30["apr"], "past7_apr": past7["apr"],
                       "past30_coverage_hours": past30["coverage_hours"],
                       "past7_coverage_hours": past7["coverage_hours"],
                       "past30_event_count": past30["event_count"],
                       "past7_event_count": past7["event_count"],
                       "last_observed_funding_ms": past30["last_funding_ms"]})
    ranked.sort(key=lambda row: (-row["ranking_apr"], row["symbol"]))
    selected = ranked[:1 if rule == "top1_30" else 5]
    weights = {row["symbol"]: ratio / len(selected) for row in selected}
    return weights, {"cutoff_ms": cutoff, "execution_ms": execution,
                     "selected_weights": weights.copy(), "ranking": ranked,
                     "excluded_lifecycle_symbols": excluded, "missing_state_symbols": missing,
                     "ineligible_symbols": ineligible,
                     "total_notional_ratio": math.fsum(weights.values())}


def evaluate(funding, states, rule, start, end, notional_ratio, lifecycle_events):
    """Calculate a causal, hypothetical short-leg funding-income index.

    The annualized past-rate rank uses the fixed calendar-window denominator:
    sum(rate) * 365 / days. Coverage separately sums the published interval hours
    of actual rows, with observations in [cutoff-window, cutoff). Monday 00:00
    states determine Monday 01:00 allocations. Start is cash; end is exclusive.
    Every simultaneous payment uses the same prepayment index. At allocation or
    lifecycle collisions, credits use min(old, new), debits max(old, new).
    """
    if rule not in RULES:
        raise ValueError("unsupported fixed funding rule")
    ratio = _number(notional_ratio, "notional_ratio")
    if ratio not in (.5, 1.0):
        raise ValueError("notional_ratio must be the frozen 0.5 or 1.0 diagnostic")
    start_ms, end_ms = _timestamp(start, "start", True), _timestamp(end, "end", True)
    if end_ms <= start_ms:
        raise ValueError("end must be after start")
    funding = _funding_rows(funding)
    states = _state_rows(states, funding)
    lifecycle = _lifecycle(lifecycle_events)
    times = {symbol: [row.timestamp_ms for row in rows] for symbol, rows in funding.items()}
    payments = defaultdict(list)
    for symbol, rows in funding.items():
        for row in rows[bisect_left(times[symbol], start_ms):bisect_left(times[symbol], end_ms)]:
            payments[row.timestamp_ms].append((symbol, row.rate))
    rebalances = {}
    cutoff = start_ms // DAY_MS * DAY_MS
    while cutoff + HOUR_MS < start_ms:
        cutoff += DAY_MS
    while cutoff + HOUR_MS < end_ms:
        if datetime.fromtimestamp(cutoff / 1000, timezone.utc).weekday() == 0:
            rebalances[cutoff + HOUR_MS] = cutoff
        cutoff += DAY_MS
    settlements = defaultdict(list)
    for symbol, event in lifecycle.items():
        timestamp = event["settled_ms"]
        if timestamp is not None and start_ms <= timestamp < end_ms:
            settlements[timestamp].append(symbol)
    midnights = set(range((start_ms // DAY_MS + 1) * DAY_MS, end_ms, DAY_MS))
    timeline = sorted(set(payments) | set(rebalances) | set(settlements) | midnights)
    value, peak, max_drawdown = 1.0, 1.0, 0.0
    weights, weekly_audit, lifecycle_audit = {}, [], []
    daily_index = [{"timestamp_ms": start_ms, "index": 1.0, "boundary": "initial_before_events"}]
    credits, debits, applied_count, credit_count, debit_count, collision_count = 0.0, 0.0, 0, 0, 0, 0
    for timestamp in timeline:
        old_weights = weights.copy()
        if timestamp in rebalances:
            weights, audit = _targets(funding, times, states, lifecycle, rule,
                                      rebalances[timestamp], ratio)
            weekly_audit.append(audit)
        for symbol in sorted(settlements.get(timestamp, ())):
            removed = weights.pop(symbol, 0.0)
            lifecycle_audit.append({"symbol": symbol, "effective_ms": timestamp,
                                    "removed_weight": removed})
        contributions = []
        for symbol, rate in sorted(payments.get(timestamp, ())):
            old, new = old_weights.get(symbol, 0.0), weights.get(symbol, 0.0)
            collision = timestamp in rebalances or symbol in settlements.get(timestamp, ())
            applied_weight = (min(old, new) if rate >= 0 else max(old, new)) if collision else new
            if applied_weight == 0 or rate == 0:
                continue
            contribution = value * applied_weight * rate
            contributions.append(contribution)
            applied_count += 1
            collision_count += int(collision)
            if contribution > 0:
                credits += contribution
                credit_count += 1
            else:
                debits += contribution
                debit_count += 1
        value += math.fsum(contributions)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("funding-income index became nonpositive or nonfinite")
        peak = max(peak, value)
        max_drawdown = max(max_drawdown, 1 - value / peak)
        if timestamp in midnights:
            daily_index.append({"timestamp_ms": timestamp, "index": value, "boundary": "daily_after_events"})
    daily_index.append({"timestamp_ms": end_ms, "index": value, "boundary": "terminal_excluding_events"})
    try:
        annualized = math.expm1(math.log(value) * 365 * DAY_MS / (end_ms - start_ms)) * 100
    except OverflowError as error:
        raise ValueError("funding index annualization overflow") from error
    if not math.isfinite(annualized):
        raise ValueError("funding index annualization overflow")
    return {"rule": rule, "start_ms": start_ms, "end_ms": end_ms,
            "notional_ratio": ratio, "initial_funding_index": 1.0, "final_funding_index": value,
            "funding_index_cagr_pct": annualized, "funding_index_return_pct": (value - 1) * 100,
            "funding_index_max_drawdown_pct": max_drawdown * 100,
            "positive_funding_index_contributions": credits,
            "negative_funding_index_contributions": debits,
            "applied_funding_event_count": applied_count,
            "credit_event_count": credit_count, "debit_event_count": debit_count,
            "applied_collision_event_count": collision_count,
            "weekly_rebalance_count": len(weekly_audit),
            "active_weekly_rebalance_count": sum(bool(row["selected_weights"]) for row in weekly_audit),
            "weekly_audit": weekly_audit, "lifecycle_audit": lifecycle_audit, "daily_index": daily_index,
            "goal_achieved": False, "portfolio_drawdown_measured": False,
            "is_trading_backtest": False, "is_net_portfolio_return": False,
            "reserve_cash_fraction_assumption": 1 - ratio,
            "limits": ["Funding-income index only; index drawdown is not portfolio drawdown.",
                       "Free continuous notional reset between payments is idealized.",
                       "No spot prices, basis, fees, slippage, loans, margin or liquidation are modeled.",
                       "A notional ratio of 1.0 leaves no assumed reserve cash.",
                       "Neither the 50% net annual return nor 10% portfolio drawdown target can be approved here."]}
