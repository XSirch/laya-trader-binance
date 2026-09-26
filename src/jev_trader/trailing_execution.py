"""Execution-delay and adverse-fill sensitivity of the frozen portfolio stop."""

import hashlib
import json
from datetime import datetime, timezone

from .binance_data import HOUR_MS
from .broad_data import load as load_daily
from .broad_execution import evaluate
from .broad_extension import extend
from .broad_hourly import load as load_hourly
from .broad_research import features
from .cli import ROOT, RESULTS
from .trailing_research import PERIODS
from .trailing_stop import TrailingStop


class DelayedPortfolioStop(TrailingStop):
    def __init__(self, distance=.04, delay_hours=0, extra_slippage=0):
        super().__init__("portfolio_pct", distance)
        if delay_hours not in (0, 1, 2, 4) or not 0 <= extra_slippage < 1:
            raise ValueError("invalid execution sensitivity scenario")
        self.delay_hours, self.extra_slippage = delay_hours, extra_slippage
        self.pending, self.current_weights, self.triggers = None, {}, []

    def _fill(self, events, quantities):
        for event in events:
            s = event["symbol"]
            original = event["price"]
            event["price"] *= 1 - self.extra_slippage if quantities[s] > 0 else 1 + self.extra_slippage
            event["observed_open"] = original
            event["extra_slippage"] = self.extra_slippage
        return events

    def at_open(self, timestamp, equity, quantities, bars):
        self.current_weights = {s: q * bars[s][timestamp].open / equity for s, q in quantities.items()}
        if self.pending is not None:
            if timestamp < self.pending["execute_ms"]:
                return []
            pending, self.pending = self.pending, None
            self.portfolio_blocked_at = timestamp
            self.portfolio_peak = None
            events = [{"symbol": s, "price": bars[s][timestamp].open,
                       "reason": "delayed_portfolio_exit", **pending} for s in quantities]
            return self._fill(events, quantities)
        events = super().at_open(timestamp, equity, quantities, bars)
        if not events:
            return []
        record = {"trigger_ms": timestamp, "execute_ms": timestamp + self.delay_hours * HOUR_MS,
                  "threshold_equity": events[0]["threshold_equity"], "trigger_equity": equity}
        self.triggers.append(record)
        if self.delay_hours == 0:
            return self._fill(events, quantities)
        self.pending = record
        # Keep the prior watermark while the irreversible exit decision waits.
        self.portfolio_peak = record["threshold_equity"] / (1 - self.distance)
        return []

    def allowed_targets(self, timestamp, targets):
        if self.pending is not None:
            return dict(self.current_weights)
        return super().allowed_targets(timestamp, targets)

    def during_hour(self, timestamp, equity, quantities, bars):
        if self.pending is not None:
            return []
        return super().during_hour(timestamp, equity, quantities, bars)


def run():
    freeze_path = ROOT / "docs/trailing_candidate_freeze_2026-09-26.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    for name, expected in freeze["source_code_sha256"].items():
        if hashlib.sha256((ROOT / "src/jev_trader" / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"frozen implementation changed: {name}")
    data, _, _ = load_daily()
    hourly, _ = load_hourly(data)
    extend(data, hourly)
    state = features(data)
    results = {}
    for entry_hour in (1, 2):
        for cost in (.0015, .003):
            scenarios = [(f"none_entry{entry_hour}_cost{cost}", None, 0)]
            scenarios += [(f"delay{delay}_entry{entry_hour}_cost{cost}_slip{slip}", delay, slip)
                          for delay in (0, 1, 2, 4) for slip in (0, .0025)]
            for name, delay, slip in scenarios:
                periods = {}
                for period, dates in PERIODS.items():
                    stop = DelayedPortfolioStop(freeze["distance"], delay, slip) if delay is not None else None
                    row = evaluate(hourly, data["fundingRate"], state, freeze["base_rule"], *dates, cost,
                                   delay_hours=entry_hour, trailing=stop)
                    row["stop_triggers"] = stop.triggers if stop else []
                    row["pending_at_terminal"] = stop.pending if stop else None
                    periods[period] = row
                results[name] = periods
                row = periods["combined"]
                print(f"{name}: return={row['return_pct']:.3f}% dd={row['max_drawdown_pct']:.3f}% "
                      f"triggers={len(row['stop_triggers'])}", flush=True)
    # The zero-delay scenario must reproduce the exact frozen baseline metrics.
    prior = json.loads((RESULTS / "trailing_research.json").read_text(encoding="utf-8"))
    for period in PERIODS:
        current = results["delay0_entry1_cost0.0015_slip0"][period]
        original = prior["results"]["portfolio_pct_4pct"][period]["stress"]
        for metric in ("return_pct", "max_drawdown_pct", "fees_pct_initial", "stop_count"):
            if abs(current[metric] - original[metric]) > 1e-10:
                raise ValueError(f"zero-delay baseline changed: {period} {metric}")
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "results": results,
              "freeze_sha256": hashlib.sha256(freeze_path.read_bytes()).hexdigest(),
              "source_code_sha256": hashlib.sha256((ROOT / "src/jev_trader/trailing_execution.py").read_bytes()).hexdigest(),
              "zero_delay_reproduction_verified": True, "deployable": False,
              "limits": ["Sensitivity grid on previously inspected retrospective data.",
                         "Hour-scale delays are stress assumptions, not measurements of actual exchange latency.",
                         "Extra stop slippage is an adverse scenario, not an observed fill.",
                         "Terminal liquidation can precede an outstanding delayed stop; pending state is reported."]}
    (RESULTS / "trailing_execution.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    run()
