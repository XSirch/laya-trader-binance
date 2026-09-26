"""Causal contract restrictions around the unchanged residual signal policy."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import re

from .binance_data import HOUR_MS
from .residual_policy import ResidualPolicy


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
    automatic_settlement_ms: int | None


def _events(events):
    normalized, seen = [], set()
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("lifecycle events must be mappings from the documented schema")
        symbol = event.get("symbol")
        if not isinstance(symbol, str) or re.fullmatch(r"[A-Z0-9]+", symbol) is None:
            raise ValueError("invalid lifecycle symbol")
        if symbol in seen:
            raise ValueError("duplicate lifecycle symbol")
        published = _utc_ms(event.get("published_utc"), "published_utc")
        restriction = _utc_ms(event.get("new_positions_stop_utc"), "new_positions_stop_utc")
        settlement = (_utc_ms(event["automatic_settlement_utc"], "automatic_settlement_utc")
                      if "automatic_settlement_utc" in event else None)
        if published > restriction or (settlement is not None and restriction > settlement):
            raise ValueError("lifecycle timestamps must follow publication, restriction, settlement order")
        normalized.append(LifecycleEvent(symbol, published, restriction, settlement))
        seen.add(symbol)
    return tuple(sorted(normalized, key=lambda item: item.symbol))


class LifecyclePolicy:
    """Remove restricted contracts only when an execution can know the notice.

    Permitted state rows and the rule are passed unchanged to the supplied
    policy. Removing a retained signal lets that policy apply its own exit
    logic; settlement prices and execution accounting remain outside this class.
    """

    def __init__(self, events, base_policy=None, risk_scale=1, delay_hours=1):
        if isinstance(delay_hours, bool) or not isinstance(delay_hours, int) or delay_hours != 1:
            raise ValueError("lifecycle protocol requires exactly one hour execution delay")
        self._events = _events(events)
        self.base_policy = ResidualPolicy(risk_scale) if base_policy is None else base_policy
        self.lifecycle_audit = []

    @property
    def events(self):
        return self._events

    @property
    def audit(self):
        return self.base_policy.audit

    def __call__(self, states, rule):
        cutoffs = {row["latest_observed_close_ms"] for row in states.values()}
        if len(cutoffs) != 1:
            raise ValueError("one completed daily cutoff required")
        cutoff = cutoffs.pop()
        if isinstance(cutoff, bool) or not isinstance(cutoff, int):
            raise ValueError("daily cutoff must be integer milliseconds")
        execution = cutoff + HOUR_MS
        excluded = {event.symbol for event in self._events
                    if event.symbol in states and event.published_ms <= execution
                    and event.new_positions_stop_ms <= execution}
        permitted = {symbol: row for symbol, row in states.items() if symbol not in excluded}
        weights = self.base_policy(permitted, rule)
        self.lifecycle_audit.append({"cutoff_ms": cutoff, "execution_ms": execution,
                                     "excluded_symbols": sorted(excluded)})
        return weights
