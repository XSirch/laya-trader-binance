"""Hourly global-portfolio replay of a frozen daily-factor hypothesis."""

import hashlib
import json
from datetime import datetime, timezone

from .binance_data import HOUR_MS, utc_ms
from .broad_data import load as load_daily
from .broad_hourly import load as load_hourly
from .broad_research import DAY_MS, features, sign, target_weights
from .cli import ROOT, RESULTS


def evaluate(hourly, funding, states, rule, start, end, side_cost, delay_hours=1):
    if delay_hours not in (1, 2):
        raise ValueError("execution delay must match frozen experiment")
    bars, marks = hourly["klines"], hourly["markPriceKlines"]
    events = {}
    for s, rows in funding.items():
        for row in rows:
            events.setdefault(row.timestamp_ms // HOUR_MS * HOUR_MS, []).append((s, row))
    equity, fees, funding_pnl = 1.0, 0.0, 0.0
    quantities, previous = {}, {}
    peak, drawdown, intrahour_drawdown = 1.0, 0.0, 0.0
    margin_failures, entries = 0, 0
    daily, audit, monthly = {}, [], {}
    month_start = 1.0
    start_ms, end_ms = utc_ms(start), utc_ms(end)
    for timestamp in range(start_ms, end_ms + 1, HOUR_MS):
        for s, q in quantities.items():
            if timestamp not in bars[s] or timestamp not in marks[s]:
                raise ValueError(f"unresolved held price {s} at {timestamp}")
            price = bars[s][timestamp].open
            equity += q * (price - previous[s])
            previous[s] = price
        terminal = timestamp == end_ms
        day = timestamp // DAY_MS * DAY_MS
        now = datetime.fromtimestamp(timestamp / 1000, timezone.utc)
        rebalance = now.weekday() == 0 and timestamp - day == delay_hours * HOUR_MS
        old = dict(quantities)
        if rebalance or terminal:
            state = {s: rows[day] for s, rows in states.items() if day in rows}
            targets = target_weights(state, rule) if not terminal else {}
            for s in targets:
                if timestamp not in bars[s] or bars[s][timestamp].trades <= 0:
                    raise ValueError(f"unverified execution liquidity {s} at {timestamp}")
            initial = equity
            for s in sorted(set(quantities) | set(targets)):
                price = bars[s][timestamp].open
                desired = targets.get(s, 0) * initial / price
                charge = abs(desired - quantities.get(s, 0)) * price * side_cost
                equity -= charge
                fees += charge
                entries += bool(desired) and sign(desired) != sign(quantities.get(s, 0))
                if desired:
                    quantities[s], previous[s] = desired, price
                else:
                    quantities.pop(s, None)
            if not terminal:
                audit.append({"execution_ms": timestamp, "latest_input_close_ms": day,
                              "target_weights": targets, "equity_before_cost": initial})
        # A funding timestamp within the first minute is ambiguous against an
        # hourly open fill. Charge the worse of old/new holdings on collision.
        # Terminal settlement is excluded from this half-open holding period.
        if not terminal:
            for s, event in events.get(timestamp, []):
                scalar = -quantities.get(s, 0) * event.rate
                if rebalance:
                    scalar = min(scalar, -old.get(s, 0) * event.rate)
                if scalar:
                    mark = marks[s][timestamp]
                    payment = scalar * (mark.low if scalar > 0 else mark.high)
                    equity += payment
                    funding_pnl += payment
        peak = max(peak, equity)
        drawdown = max(drawdown, 1 - equity / peak)
        if not terminal:
            # Simultaneous adverse mark extremes are a stress bound, not a
            # reconstruction of the within-hour portfolio price path.
            worst, notional = equity, 0.0
            for s, q in quantities.items():
                mark = marks[s][timestamp]
                worst += q * ((mark.low if q > 0 else mark.high) - bars[s][timestamp].open)
                notional += abs(q) * mark.high
            intrahour_drawdown = max(intrahour_drawdown, 1 - worst / peak)
            margin_failures += worst < .10 * notional
        if equity <= 0:
            raise ValueError("insolvent hourly portfolio")
        if timestamp % DAY_MS == 0 or terminal:
            daily[str(timestamp)] = equity
        if timestamp > start_ms and (now.day == 1 and now.hour == 0 or terminal):
            preceding = datetime.fromtimestamp((timestamp - HOUR_MS) / 1000, timezone.utc).strftime("%Y-%m")
            monthly[preceding] = 100 * (equity / month_start - 1)
            month_start = equity
    return {"return_pct": 100 * (equity - 1), "max_drawdown_pct": 100 * drawdown,
            "adverse_intrahour_drawdown_bound_pct": 100 * intrahour_drawdown,
            "fees_pct_initial": 100 * fees, "funding_pct_initial": 100 * funding_pnl,
            "entries": entries, "rebalances": len(audit), "margin_stress_failures": margin_failures,
            "monthly_returns_pct": monthly, "positive_months": sum(v > 0 for v in monthly.values()),
            "months": len(monthly), "daily_equity": daily, "execution_audit": audit}


def run():
    frozen_path = ROOT / "docs/broad_candidate_freeze_2026-09-26.json"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    for name, expected in frozen["source_code_sha256"].items():
        path = ROOT / "src/jev_trader" / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"frozen strategy source changed: {name}")
    data, _, _ = load_daily()
    hourly, sources = load_hourly(data)
    states = features(data)
    results = {}
    for delay in frozen["delay_sensitivity_hours"]:
        for cost in frozen["costs_per_side"]:
            key = f"delay{delay}_cost{cost}"
            result = evaluate(hourly, data["fundingRate"], states, frozen["rule"],
                              *frozen["historical_execution_window"], cost, delay)
            results[key] = result
            print(f"{key}: return={result['return_pct']:.3f}% dd={result['max_drawdown_pct']:.3f}% "
                  f"positive_months={result['positive_months']}/{result['months']}", flush=True)
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "results": results,
              "freeze_sha256": hashlib.sha256(frozen_path.read_bytes()).hexdigest(),
              "execution_code_sha256": {name: hashlib.sha256((ROOT / "src/jev_trader" / name).read_bytes()).hexdigest()
                                         for name in ("broad_execution.py", "broad_hourly.py")},
              "source_manifest_sha256": hashlib.sha256(json.dumps(
                  [{k: v for k, v in row.items() if k != "path"} for row in sources], sort_keys=True).encode()).hexdigest(),
              "hourly_source_count": len(sources), "deployable": False,
              "limits": ["Funding marks bounded by hourly extremes, not exact settlement marks.",
                         "Historical replay, not a prospective or live execution result.",
                         "Margin stress bound is not exchange liquidation accounting."]}
    (RESULTS / "broad_execution.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    run()
