"""Deterministic portfolio decisions from externally supplied weekly forecasts.

Predictions are seven-day cross-section-relative price forecasts, not probabilities.
The alpha hurdle is not a calibrated forecast of total portfolio P&L: the BTC
beta hedge may leave nonzero net dollar exposure to the unknown common return.
The historical carry30 feature is annualized funding RETURN to a long position,
so negative weight times carry is the adverse funding expense estimate.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
import math
import re


HOUR_MS = 3_600_000
ROUNDTRIP_COST = .003
MIN_BTC_BETA = 1e-8


def _utc_ms(value, field):
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an explicit UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"invalid {field} timestamp") from error
    if parsed.utcoffset() != timedelta(0) or parsed.microsecond % 1000:
        raise ValueError(f"{field} must be UTC with millisecond precision")
    return int(parsed.timestamp() * 1000)


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    symbol: str
    published_ms: int
    new_positions_stop_ms: int


def _events(events):
    output, seen = [], set()
    for event in events:
        if not isinstance(event, Mapping):
            raise ValueError("lifecycle events must be mappings")
        symbol = event.get("symbol")
        if not isinstance(symbol, str) or re.fullmatch(r"[A-Z0-9]+", symbol) is None:
            raise ValueError("invalid lifecycle symbol")
        if symbol in seen:
            raise ValueError("duplicate lifecycle symbol")
        published = _utc_ms(event.get("published_utc"), "published_utc")
        stop = _utc_ms(event.get("new_positions_stop_utc"), "new_positions_stop_utc")
        settlement = (_utc_ms(event["automatic_settlement_utc"], "automatic_settlement_utc")
                      if "automatic_settlement_utc" in event else None)
        if published > stop or (settlement is not None and stop > settlement):
            raise ValueError("lifecycle timestamps must follow publication, restriction, settlement order")
        output.append(LifecycleEvent(symbol, published, stop))
        seen.add(symbol)
    return tuple(sorted(output, key=lambda event: event.symbol))


def _number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f"{field} must be a finite number")
    return value


def _validate_features(value, field):
    """Reject nonfinite inputs even if a row will not be selected this week."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            _validate_features(item, f"{field}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_features(item, f"{field}[{index}]")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        _number(value, field)


class TreePolicy:
    """Rank forecasts, neutralize estimated BTC beta, then apply a cost hurdle.

    The policy never retains a previous target: a failed decision returns cash.
    Execution, position accounting, realized fees and trailing stops belong to
    the replay engine. ``audit`` contains one record per valid invocation.
    """

    def __init__(self, events, gross_limit=1.0):
        _number(gross_limit, "gross_limit")
        if gross_limit not in (1.0, 2.0):
            raise ValueError("gross_limit must be the fixed value 1 or 2")
        self.gross_limit = float(gross_limit)
        self._events = _events(events)
        self.audit = []

    @property
    def events(self):
        return self._events

    def __call__(self, states, rule):
        if not isinstance(states, Mapping):
            raise ValueError("states must be a symbol-to-feature mapping")
        record = {"cutoff_ms": None, "execution_ms": None, "rule": rule,
                  "eligible_count": 0, "excluded_lifecycle": [], "excluded_warmup": [],
                  "excluded_liquidity_or_volatility": [], "raw_proposed_weights": {},
                  "hedged_proposed_weights": {}, "final_target_weights": {},
                  "expected_alpha": 0.0, "roundtrip_cost": 0.0, "adverse_carry": 0.0,
                  "hurdle_pass": False, "proposed_gross": 0.0, "gross": 0.0,
                  "centered_predictions": {}}

        def finish(reason, weights=None):
            target = {} if weights is None else weights
            record.update(reason=reason, final_target_weights=dict(target),
                          gross=math.fsum(abs(weight) for weight in target.values()))
            self.audit.append(record)
            return dict(target)

        if not states:
            return finish("empty_states")

        cutoffs = set()
        for symbol, row in states.items():
            if not isinstance(symbol, str) or re.fullmatch(r"[A-Z0-9]+", symbol) is None:
                raise ValueError("invalid state symbol")
            if not isinstance(row, Mapping):
                raise ValueError(f"{symbol} state must be a mapping")
            cutoff = row.get("latest_observed_close_ms")
            if isinstance(cutoff, bool) or not isinstance(cutoff, int):
                raise ValueError("daily cutoff must be integer milliseconds")
            cutoffs.add(cutoff)
            _validate_features(row, symbol)
            for field in ("quote_volume20", "volatility", "beta60", "carry30"):
                _number(row.get(field), f"{symbol}.{field}")
            if row.get("prediction") is not None:
                _number(row["prediction"], f"{symbol}.prediction")
        if len(cutoffs) != 1:
            raise ValueError("one completed daily cutoff required")
        cutoff = cutoffs.pop()
        execution = cutoff + HOUR_MS
        record.update(cutoff_ms=cutoff, execution_ms=execution)
        excluded = {event.symbol for event in self._events if event.symbol in states
                    and event.published_ms <= execution and event.new_positions_stop_ms <= execution}
        record["excluded_lifecycle"] = sorted(excluded)
        eligible = {}
        for symbol, row in sorted(states.items()):
            if symbol in excluded:
                continue
            if row.get("prediction") is None:
                record["excluded_warmup"].append(symbol)
            elif row["quote_volume20"] < 10_000_000 or not .005 <= row["volatility"] <= .15:
                record["excluded_liquidity_or_volatility"].append(symbol)
            else:
                eligible[symbol] = row
        record["eligible_count"] = len(eligible)
        if "BTCUSDT" not in eligible:
            return finish("btc_unavailable")
        if abs(eligible["BTCUSDT"]["beta60"]) <= MIN_BTC_BETA:
            return finish("btc_beta_unavailable")
        if len(eligible) < 8:
            return finish("insufficient_eligible")

        predictions = [row["prediction"] for row in eligible.values()]
        try:
            average = math.fsum(value / len(predictions) for value in predictions)
            centered = {symbol: row["prediction"] - average for symbol, row in eligible.items()}
            for value in centered.values():
                _number(value, "centered prediction")
            record["centered_predictions"] = centered
            if min(predictions) == max(predictions):
                return finish("identical_predictions")
            ranked = sorted(eligible, key=lambda symbol: (centered[symbol], symbol))
            count = max(2, len(eligible) // 5)
            weights = {}
            for side, symbols in ((1.0, ranked[-count:]), (-1.0, ranked[:count])):
                denominator = math.fsum(1.0 / eligible[symbol]["volatility"] for symbol in symbols)
                for symbol in symbols:
                    weights[symbol] = side * self.gross_limit / 2 / denominator / eligible[symbol]["volatility"]
            record["raw_proposed_weights"] = dict(sorted(weights.items()))
            beta = math.fsum(weight * eligible[symbol]["beta60"] for symbol, weight in weights.items())
            weights["BTCUSDT"] = weights.get("BTCUSDT", 0.0) - beta / eligible["BTCUSDT"]["beta60"]
            for value in weights.values():
                _number(value, "hedged weight")
            gross = math.fsum(abs(value) for value in weights.values())
            if gross <= 0:
                return finish("zero_hedged_gross")
            scale = min(1.0, self.gross_limit / gross)
            weights = {symbol: value * scale for symbol, value in sorted(weights.items()) if value != 0}
            gross = math.fsum(abs(value) for value in weights.values())
            if gross > self.gross_limit:
                correction = math.nextafter(self.gross_limit / gross, 0.0)
                weights = {symbol: value * correction for symbol, value in weights.items()}
                gross = math.fsum(abs(value) for value in weights.values())
            record["hedged_proposed_weights"] = dict(weights)
            alpha = math.fsum(weight * eligible[symbol]["prediction"] for symbol, weight in weights.items())
            adverse = math.fsum(max(-weight * eligible[symbol]["carry30"], 0.0) * 7 / 365
                                for symbol, weight in weights.items())
            fees = ROUNDTRIP_COST * gross
            for name, value in (("expected_alpha", alpha), ("adverse_carry", adverse),
                                ("roundtrip_cost", fees), ("proposed_gross", gross)):
                _number(value, name)
                record[name] = value
        except OverflowError as error:
            raise ValueError("nonfinite portfolio arithmetic") from error
        record["hurdle_pass"] = alpha > fees + adverse
        return finish("hurdle_pass" if record["hurdle_pass"] else "below_cost_hurdle",
                      weights if record["hurdle_pass"] else None)
