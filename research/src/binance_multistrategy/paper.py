"""Event-driven PAPER execution only; no connections or exchange orders.

Protective stops/targets react to every received price. The trailing level is
updated once per closed minute, matching the historical model. A transport must
supply validated prices, candle closures and exact funding settlement events.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import pandas as pd
from .config import ResearchConfig
from .data import utc_timestamp
from .simulation import ratchet_stop


@dataclass(frozen=True)
class PaperSignal:
    signal_id: str
    symbol: str
    side: int
    signal_time: str
    stop_distance: float
    target_r: float
    trail_activation_r: float
    trail_distance_r: float
    max_hold_minutes: int
    strategy: str


class PaperBroker:
    """One global paper position. 'balance' is equity basis, not Spot free cash."""
    def __init__(self, config: ResearchConfig, initial_equity: float = 10_000):
        if not math.isfinite(initial_equity) or initial_equity <= 0:
            raise ValueError("Invalid initial_equity")
        self.config = config
        self.balance = float(initial_equity)
        self.pending: dict | None = None
        self.position: dict | None = None
        self.seen_signals: set[str] = set()
        self.seen_funding: set[str] = set()
        self.events: list[dict] = []
        self.last_quote: dict[str, str] = {}

    def submit(self, signal: PaperSignal) -> bool:
        if signal.side not in {-1, 1} or (self.config.market == "spot" and signal.side < 0):
            raise ValueError("Spot cannot open a short")
        numeric = [signal.stop_distance, signal.target_r, signal.trail_activation_r, signal.trail_distance_r]
        if any(not math.isfinite(v) or v <= 0 for v in numeric) or signal.max_hold_minutes < 1:
            raise ValueError("Invalid bracket parameters")
        if not signal.signal_id or not signal.symbol:
            raise ValueError("signal_id and symbol required")
        utc_timestamp(signal.signal_time)
        if signal.signal_id in self.seen_signals:
            return False
        if self.pending is not None or self.position is not None:
            return False
        self.pending = asdict(signal)
        self.seen_signals.add(signal.signal_id)
        return True

    def on_price(self, symbol: str, price: float, timestamp: str) -> None:
        t = utc_timestamp(timestamp)
        if not math.isfinite(price) or price <= 0:
            raise ValueError("Invalid market price")
        if symbol in self.last_quote and t < utc_timestamp(self.last_quote[symbol]):
            return  # Out-of-order input cannot rewrite the position's past.
        self.last_quote[symbol] = str(t)
        if self.position and self.position["symbol"] == symbol:
            p, side = self.position, self.position["side"]
            stop_hit = side * (price - p["stop"]) <= 0
            target_hit = side * (price - p["target"]) >= 0
            expired = t >= utc_timestamp(p["entry_time"]) + pd.Timedelta(minutes=p["max_hold_minutes"])
            if stop_hit or target_hit or expired:
                self._close(price, t, "stop" if stop_hit else "target" if target_hit else "time_stop")
                return
            p["best"] = max(p["best"], price) if side == 1 else min(p["best"], price)
        if not self.pending or self.pending["symbol"] != symbol:
            return
        signal = self.pending
        signal_time = utc_timestamp(signal["signal_time"])
        if t < signal_time:
            return
        if t > signal_time + pd.Timedelta(minutes=1):
            self.events.append({"event": "signal_expired", "time": str(t), "signal_id": signal["signal_id"]})
            self.pending = None
            return
        side = signal["side"]
        entry = price * (1 + side * self.config.slippage_bps / 10_000)
        fraction = signal["stop_distance"] / entry
        if not self.config.min_stop_fraction <= fraction <= self.config.max_stop_fraction:
            self.events.append({"event": "entry_rejected", "reason": "stop_fraction", "time": str(t)})
            self.pending = None
            return
        friction = 2 * (self.config.fee_bps + self.config.slippage_bps) / 10_000
        exposure = min(self.config.max_notional_equity, self.config.risk_fraction / (fraction + friction))
        qty = self.balance * exposure / entry
        fee = qty * entry * self.config.fee_bps / 10_000
        if self.balance <= 0 or qty <= 0:
            self.pending = None
            return
        self.balance -= fee
        self.position = {**signal, "entry_price": entry, "entry_time": str(t), "quantity": qty,
                         "entry_fee": fee, "funding_paid": 0.0, "best": entry,
                         "stop": entry - side * signal["stop_distance"],
                         "target": entry + side * signal["stop_distance"] * signal["target_r"]}
        self.pending = None
        self.events.append({"event": "paper_entry", "time": str(t), "symbol": symbol, "side": side,
                            "price": entry, "quantity": qty, "fee": fee, "signal_id": signal["signal_id"]})

    def on_minute_closed(self, timestamp: str) -> None:
        t = utc_timestamp(timestamp)
        if not self.position or t <= utc_timestamp(self.position["entry_time"]):
            return
        p = self.position
        # Only observed post-entry ticks contribute to best, not pre-entry candle extrema.
        p["stop"] = ratchet_stop(p["side"], p["entry_price"], p["stop"], p["best"],
                                  p["stop_distance"], p["trail_activation_r"], p["trail_distance_r"])
        self.events.append({"event": "paper_trail_update", "time": str(t), "stop": p["stop"]})

    def on_funding(self, event_id: str, symbol: str, rate: float, mark_price: float, timestamp: str) -> None:
        t = utc_timestamp(timestamp)
        if not math.isfinite(rate) or not math.isfinite(mark_price) or abs(rate) > .1 or mark_price <= 0:
            raise ValueError("Invalid funding event")
        if self.config.market != "usd_m" or event_id in self.seen_funding:
            return
        self.seen_funding.add(event_id)
        if not self.position or self.position["symbol"] != symbol or t <= utc_timestamp(self.position["entry_time"]):
            return
        p = self.position
        amount = p["side"] * p["quantity"] * mark_price * rate
        self.balance -= amount
        p["funding_paid"] += amount
        self.events.append({"event": "paper_funding", "time": str(t), "event_id": event_id, "amount": amount})

    def _close(self, price: float, timestamp: pd.Timestamp, reason: str) -> None:
        p = self.position
        if p is None:
            return
        side = p["side"]
        fill = price * (1 - side * self.config.slippage_bps / 10_000)
        fee = p["quantity"] * fill * self.config.fee_bps / 10_000
        gross = side * p["quantity"] * (fill - p["entry_price"])
        self.balance += gross - fee
        self.events.append({"event": "paper_exit", "time": str(timestamp), "symbol": p["symbol"],
                            "side": "SELL" if side == 1 else "BUY", "price": fill, "reason": reason,
                            "net_pnl": gross - fee - p["entry_fee"] - p["funding_paid"],
                            "balance": self.balance, "signal_id": p["signal_id"]})
        self.position = None

    def save(self, path: Path) -> None:
        state = {"schema": 1, "config": self.config.to_dict(), "balance": self.balance,
                 "pending": self.pending, "position": self.position,
                 "seen_signals": sorted(self.seen_signals), "seen_funding": sorted(self.seen_funding),
                 "events": self.events, "last_quote": self.last_quote}
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(state, allow_nan=False, indent=2), encoding="utf-8")
        temp.replace(path)

    @staticmethod
    def load(path: Path) -> "PaperBroker":
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("schema") != 1:
            raise ValueError("Unknown paper-state schema")
        broker = PaperBroker(ResearchConfig(**state["config"]))
        for field in ["balance", "pending", "position", "events", "last_quote"]:
            setattr(broker, field, state[field])
        broker.seen_signals = set(state["seen_signals"])
        broker.seen_funding = set(state["seen_funding"])
        return broker
