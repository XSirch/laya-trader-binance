"""Causal hourly trailing levels; no favorable same-candle hindsight."""

import math

from .binance_data import HOUR_MS
from .broad_research import DAY_MS


class TrailingStop:
    def __init__(self, scope, distance, atr_states=None):
        if (scope not in ("position_pct", "position_atr", "portfolio_pct") or
                not math.isfinite(distance) or distance <= 0 or scope.endswith("pct") and distance >= 1):
            raise ValueError("invalid trailing stop design")
        self.scope, self.distance, self.atr_states = scope, distance, atr_states
        self.positions, self.portfolio_peak = {}, None
        self.blocked_at, self.portfolio_blocked_at = {}, None

    def distance_price(self, symbol, watermark, timestamp):
        if self.scope == "position_pct":
            return watermark * self.distance
        # At 00:00 the latest daily indicator is not assumed instantly executable.
        cutoff = (timestamp - HOUR_MS) // DAY_MS * DAY_MS
        try:
            return self.distance * self.atr_states[symbol][cutoff]
        except (KeyError, TypeError):
            raise ValueError(f"ATR unavailable before stop decision: {symbol} {timestamp}")

    def tighten(self, symbol, record, timestamp):
        spread = self.distance_price(symbol, record["watermark"], timestamp)
        proposed = record["watermark"] - record["side"] * spread
        if record["side"] > 0:
            record["level"] = max(record.get("level", proposed), proposed)
        else:
            record["level"] = min(record.get("level", proposed), proposed)

    def at_open(self, timestamp, equity, quantities, bars):
        events = []
        if self.scope == "portfolio_pct":
            if not quantities:
                self.portfolio_peak = None
                return events
            self.portfolio_peak = max(self.portfolio_peak or equity, equity)
            if equity <= self.portfolio_peak * (1 - self.distance):
                self.portfolio_blocked_at = timestamp
                for s, q in quantities.items():
                    events.append({"symbol": s, "price": bars[s][timestamp].open,
                                   "reason": "portfolio_observed_hourly_equity", "threshold_equity": self.portfolio_peak * (1 - self.distance)})
                self.portfolio_peak = None
            return events
        for s in quantities:
            record = self.positions.get(s)
            if record is None:
                continue
            self.tighten(s, record, timestamp)
            price = bars[s][timestamp].open
            if record["side"] * (price - record["level"]) <= 0:
                events.append({"symbol": s, "price": price, "level": record["level"], "reason": "gap_or_open_touch"})
                self.blocked_at[s] = timestamp
                del self.positions[s]
        return events

    def allowed_targets(self, timestamp, targets):
        if self.portfolio_blocked_at == timestamp:
            return {}
        return {s: w for s, w in targets.items() if self.blocked_at.get(s) != timestamp}

    def during_hour(self, timestamp, equity, quantities, bars):
        if self.scope == "portfolio_pct":
            if quantities and self.portfolio_peak is None:
                self.portfolio_peak = equity
            if not quantities:
                self.portfolio_peak = None
            return []
        self.positions = {s: r for s, r in self.positions.items() if s in quantities}
        events = []
        for s, q in quantities.items():
            bar = bars[s][timestamp]
            side = 1 if q > 0 else -1
            if s not in self.positions or self.positions[s]["side"] != side:
                self.positions[s] = {"side": side, "watermark": bar.open}
            record = self.positions[s]
            self.tighten(s, record, timestamp)
            touched = bar.low <= record["level"] if side > 0 else bar.high >= record["level"]
            if touched:
                # An open beyond a newly tightened/new-entry level fills at open.
                price = min(bar.open, record["level"]) if side > 0 else max(bar.open, record["level"])
                events.append({"symbol": s, "price": price, "level": record["level"], "reason": "intrahour_touch"})
                self.blocked_at[s] = timestamp
                del self.positions[s]
            else:
                record["watermark"] = max(record["watermark"], bar.high) if side > 0 else min(record["watermark"], bar.low)
                # This new watermark only affects the next hourly decision.
        return events
