"""Fixed daily pair allocation after a recorded midnight funding event.

The script ranks externally supplied pair forecasts, applies a side-cost-aware
hurdle, and hedges estimated BTC beta. Funding expense uses three repetitions of
the last observed rate as a fixed estimate, never a future realized payment.
"""

from collections.abc import Mapping
import math
import re

from .tree_policy import HOUR_MS, MIN_BTC_BETA, _events, _number, _validate_features


DAY_MS = 24 * HOUR_MS


def eligible_states(states, events):
    """Return causal candidates and a shared policy/prediction eligibility audit."""
    if not isinstance(states, Mapping):
        raise ValueError("states must map symbols to event observations")
    audit = {"decision_ms": None, "day_ms": None, "entry_ms": None, "planned_exit_ms": None,
             "excluded_lifecycle": [], "excluded_liquidity_or_volatility": [],
             "eligible_symbols": [], "reason": "empty_states"}
    if not states:
        return {}, audit
    decisions = set()
    for symbol, row in states.items():
        if not isinstance(symbol, str) or re.fullmatch(r"[A-Z0-9]+", symbol) is None:
            raise ValueError("invalid event state symbol")
        if not isinstance(row, Mapping):
            raise ValueError("event state must be a mapping")
        decision = row.get("latest_observed_close_ms")
        if isinstance(decision, bool) or not isinstance(decision, int) or decision % DAY_MS != HOUR_MS:
            raise ValueError("event decision must be integer milliseconds at UTC 01:00")
        day = decision - HOUR_MS
        event = row.get("event_timestamp_ms")
        if isinstance(event, bool) or not isinstance(event, int) or not day <= event < day + 60_000:
            raise ValueError("recorded funding event must be in the first minute of its UTC day")
        _validate_features(row, symbol)
        for field in ("quote_volume20", "volatility", "beta60", "event.funding_rate"):
            _number(row.get(field), f"{symbol}.{field}")
        decisions.add(decision)
    if len(decisions) != 1:
        raise ValueError("one event decision timestamp required")
    decision = decisions.pop()
    day, entry, end = decision - HOUR_MS, decision + HOUR_MS, decision + 25 * HOUR_MS
    audit.update(decision_ms=decision, day_ms=day, entry_ms=entry, planned_exit_ms=end)
    excluded = {event.symbol for event in events
                if event.published_ms <= decision and event.new_positions_stop_ms <= end}
    current = {}
    for symbol, row in sorted(states.items()):
        if symbol in excluded:
            audit["excluded_lifecycle"].append(symbol)
        elif row["quote_volume20"] < 10_000_000 or not .005 <= row["volatility"] <= .15:
            audit["excluded_liquidity_or_volatility"].append(symbol)
        else:
            current[symbol] = row
    audit["eligible_symbols"] = sorted(current)
    if "BTCUSDT" not in current:
        audit["reason"] = "btc_unavailable"
        return {}, audit
    if abs(current["BTCUSDT"]["beta60"]) <= MIN_BTC_BETA:
        audit["reason"] = "btc_beta_unavailable"
        return {}, audit
    if len(current) < 8:
        audit["reason"] = "insufficient_eligible"
        return {}, audit
    for symbol, row in current.items():
        _number(row["beta60"] / current["BTCUSDT"]["beta60"], f"{symbol}.pair_beta")
    audit["reason"] = "eligible"
    return current, audit


class EventPolicy:
    """Take up to three positive-edge pairs, without gross renormalization."""

    def __init__(self, events, gross_limit=1.0, side_cost=.0015, end_ms=None):
        _number(gross_limit, "gross_limit")
        _number(side_cost, "side_cost")
        if gross_limit not in (1.0, 2.0) or side_cost not in (.0015, .003):
            raise ValueError("gross limit and side cost must use the fixed event scenarios")
        if end_ms is not None and (isinstance(end_ms, bool) or not isinstance(end_ms, int)):
            raise ValueError("end_ms must be integer milliseconds or None")
        self.events = _events(events)
        self.gross_limit, self.side_cost, self.end_ms = float(gross_limit), float(side_cost), end_ms
        self.audit = []

    def __call__(self, states, rule):
        current, eligibility = eligible_states(states, self.events)
        record = {**eligibility, "rule": rule, "gross_limit": self.gross_limit,
                  "side_cost": self.side_cost, "candidates": [], "chosen": [],
                  "final_target_weights": {}, "gross": 0.0, "beta_exposure": 0.0,
                  "excluded_warmup": []}

        def finish(reason, weights=None):
            target = {} if weights is None else weights
            record.update(reason=reason, final_target_weights=dict(target),
                          gross=math.fsum(abs(weight) for weight in target.values()))
            self.audit.append(record)
            return dict(target)

        if not current:
            return finish(eligibility["reason"])
        if self.end_ms is not None and eligibility["planned_exit_ms"] > self.end_ms:
            return finish("planned_exit_after_end")
        predicted = {}
        for symbol, row in current.items():
            prediction = row.get("prediction")
            if prediction is None:
                record["excluded_warmup"].append(symbol)
            else:
                _number(prediction, f"{symbol}.prediction")
                predicted[symbol] = row
        if "BTCUSDT" not in predicted:
            return finish("btc_prediction_unavailable")
        if len(predicted) < 8:
            return finish("insufficient_predictions")
        btc = predicted["BTCUSDT"]
        for symbol, row in sorted(predicted.items()):
            if symbol == "BTCUSDT":
                continue
            prediction = row["prediction"]
            sign = 1.0 if prediction > 0 else -1.0 if prediction < 0 else 0.0
            beta = row["beta60"] / btc["beta60"]
            denominator = 1 + abs(beta)
            adverse = 3 * (max(sign * row["event.funding_rate"], 0.0) / denominator
                           + max(-sign * (beta / denominator) * btc["event.funding_rate"], 0.0))
            hurdle = 2 * self.side_cost + adverse
            edge = abs(prediction) - hurdle
            for name, value in (("adverse_funding", adverse), ("hurdle", hurdle), ("edge", edge)):
                _number(value, name)
            record["candidates"].append({"symbol": symbol, "prediction": prediction, "sign": sign,
                                         "beta": beta, "roundtrip_cost": 2 * self.side_cost,
                                         "adverse_funding": adverse, "hurdle": hurdle, "edge": edge})
        ranked = sorted((row for row in record["candidates"] if row["edge"] > 0),
                        key=lambda row: (-row["edge"], row["symbol"]))[:3]
        if not ranked:
            return finish("below_cost_hurdle")
        budget = self.gross_limit / len(ranked)
        contributions = {}
        for row in ranked:
            alt = row["sign"] * budget / (1 + abs(row["beta"]))
            hedge = -row["beta"] * alt
            contributions.setdefault(row["symbol"], []).append(alt)
            contributions.setdefault("BTCUSDT", []).append(hedge)
            record["chosen"].append({**row, "pair_gross_budget": budget,
                                    "asset_weight": alt, "btc_weight": hedge})
        weights = {symbol: math.fsum(parts) for symbol, parts in sorted(contributions.items())}
        weights = {symbol: weight for symbol, weight in weights.items() if weight != 0}
        gross = math.fsum(abs(weight) for weight in weights.values())
        if not math.isfinite(gross) or gross > self.gross_limit + 1e-12:
            raise ValueError("event pair allocation exceeded its gross limit")
        beta_exposure = math.fsum(weight * predicted[symbol]["beta60"] for symbol, weight in weights.items())
        _number(beta_exposure, "portfolio beta exposure")
        record["beta_exposure"] = beta_exposure
        return finish("positive_pair_edge", weights)
