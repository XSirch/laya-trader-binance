"""Hourly global-portfolio replay of a frozen daily-factor hypothesis."""

import hashlib
import json
from datetime import datetime, timezone

from .binance_data import HOUR_MS, utc_ms
from .broad_data import load as load_daily
from .broad_hourly import load as load_hourly
from .broad_research import DAY_MS, features, sign, target_weights
from .cli import ROOT, RESULTS


def evaluate(hourly, funding, states, rule, start, end, side_cost, delay_hours=1, exact_funding_marks=None,
             target_policy=None, settlement_bounds=None, decision_policy=None, trailing=None):
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
    attribution = {s: {"price_pnl": 0.0, "funding_pnl": 0.0, "fees": 0.0} for s in bars}
    exact_count, bound_count, boundary_mark_count = 0, 0, 0
    bounded_settlements = []
    cash_hours, observed_hours, traded_notional, order_changes = 0, 0, 0.0, 0
    stop_events, max_abs_net_weight = [], 0.0

    def execute_stops(events, timestamp, stopped):
        nonlocal equity, fees, traded_notional, order_changes
        for event in events:
            s, price = event["symbol"], event["price"]
            q = quantities.pop(s)
            stopped[s] = q
            pnl = q * (price - previous[s])
            charge = abs(q) * price * side_cost
            equity += pnl - charge
            fees += charge
            attribution[s]["price_pnl"] += pnl
            attribution[s]["fees"] += charge
            traded_notional += abs(q) * price
            order_changes += 1
            stop_events.append({**event, "timestamp_ms": timestamp, "quantity": q, "fee": charge})
    start_ms, end_ms = utc_ms(start), utc_ms(end)
    for timestamp in range(start_ms, end_ms + 1, HOUR_MS):
        settled = {}
        for s, q in list(quantities.items()):
            if timestamp not in bars[s] or timestamp not in marks[s]:
                interval = (settlement_bounds or {}).get((s, timestamp))
                if interval is None:
                    raise ValueError(f"unresolved held price {s} at {timestamp}")
                if not 0 < interval["lower"] <= interval["upper"]:
                    raise ValueError("invalid settlement bounds")
                price = interval["lower"] if q > 0 else interval["upper"]
                pnl = q * (price - previous[s])
                charge = abs(q) * price * side_cost
                equity += pnl - charge
                attribution[s]["price_pnl"] += pnl
                attribution[s]["fees"] += charge
                fees += charge
                traded_notional += abs(q) * price
                order_changes += 1
                bounded_settlements.append({"symbol": s, "timestamp_ms": timestamp, "quantity": q,
                                            "adverse_scenario_price": price, **interval})
                settled[s] = q
                del quantities[s]
                continue
            price = bars[s][timestamp].open
            pnl = q * (price - previous[s])
            equity += pnl
            attribution[s]["price_pnl"] += pnl
            previous[s] = price
        terminal = timestamp == end_ms
        day = timestamp // DAY_MS * DAY_MS
        now = datetime.fromtimestamp(timestamp / 1000, timezone.utc)
        rebalance = now.weekday() == 0 and timestamp - day == delay_hours * HOUR_MS
        old = dict(quantities)
        stopped = {}
        if trailing is not None and not terminal:
            execute_stops(trailing.at_open(timestamp, equity, quantities, bars), timestamp, stopped)
        if rebalance or terminal:
            if equity <= 0:
                raise ValueError("insolvent before decision")
            state = {s: rows[day] for s, rows in states.items() if day in rows}
            policy = target_weights if target_policy is None else target_policy
            targets = policy(state, rule) if not terminal else {}
            decision = None
            if decision_policy is not None and not terminal:
                current_weights = {s: q * bars[s][timestamp].open / equity for s, q in quantities.items()}
                targets, decision = decision_policy(state, targets, current_weights, side_cost)
            if trailing is not None and not terminal:
                targets = trailing.allowed_targets(timestamp, targets)
            for s in targets:
                if timestamp not in bars[s] or bars[s][timestamp].trades <= 0:
                    raise ValueError(f"unverified execution liquidity {s} at {timestamp}")
            initial = equity
            rebalance_fees = 0.0
            for s in sorted(set(quantities) | set(targets)):
                price = bars[s][timestamp].open
                desired = targets.get(s, 0) * initial / price
                if decision is not None and decision["chosen"] == "hold":
                    desired = quantities.get(s, 0)
                charge = abs(desired - quantities.get(s, 0)) * price * side_cost
                delta_notional = abs(desired - quantities.get(s, 0)) * price
                traded_notional += delta_notional
                order_changes += delta_notional > 1e-12
                equity -= charge
                fees += charge
                rebalance_fees += charge
                attribution[s]["fees"] += charge
                entries += bool(desired) and sign(desired) != sign(quantities.get(s, 0))
                if desired:
                    quantities[s], previous[s] = desired, price
                else:
                    quantities.pop(s, None)
            if not terminal:
                audit.append({"execution_ms": timestamp, "latest_input_close_ms": day,
                              "target_weights": targets, "equity_before_cost": initial,
                              "decision": decision, "actual_cost_fraction": rebalance_fees / initial})
        if trailing is not None and not terminal:
            execute_stops(trailing.during_hour(timestamp, equity, quantities, bars), timestamp, stopped)
        # A funding timestamp within the first minute is ambiguous against an
        # hourly open fill. Charge the worse of old/new holdings on collision.
        # Terminal settlement is excluded from this half-open holding period.
        if not terminal:
            observed_hours += 1
            cash_hours += not quantities
            for s, event in events.get(timestamp, []):
                scalar = -quantities.get(s, 0) * event.rate
                if s in settled:
                    scalar = min(scalar, -settled[s] * event.rate)
                if s in stopped:
                    # OHLC cannot establish whether a stop preceded funding in
                    # this hour: charge liabilities and withhold uncertain credits.
                    scalar = min(scalar, -stopped[s] * event.rate)
                if rebalance:
                    scalar = min(scalar, -old.get(s, 0) * event.rate)
                if scalar:
                    mark = marks[s][timestamp]
                    settlement_mark = (exact_funding_marks or {}).get((s, event.timestamp_ms))
                    if settlement_mark is not None:
                        if not mark.low * (1 - 1e-8) <= settlement_mark <= mark.high * (1 + 1e-8):
                            # The exact settlement instant can precede the first
                            # sample of its timestamp's hourly mark candle.
                            prior_mark = marks[s].get(timestamp - HOUR_MS)
                            if (event.timestamp_ms - timestamp >= 60_000 or prior_mark is None or
                                    not prior_mark.low * (1 - 1e-8) <= settlement_mark <= prior_mark.high * (1 + 1e-8)):
                                raise ValueError("settlement mark outside corresponding boundary candle bounds")
                            boundary_mark_count += 1
                        exact_count += 1
                    else:
                        settlement_mark = mark.low if scalar > 0 else mark.high
                        bound_count += 1
                    payment = scalar * settlement_mark
                    equity += payment
                    funding_pnl += payment
                    attribution[s]["funding_pnl"] += payment
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
            max_abs_net_weight = max(max_abs_net_weight, abs(sum(q * bars[s][timestamp].open for s, q in quantities.items()) / equity))
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
            "cash_hours": cash_hours, "observed_hours": observed_hours,
            "cash_time_pct": 100 * cash_hours / observed_hours if observed_hours else 0,
            "traded_notional_multiple_initial": traded_notional, "order_changes": order_changes,
            "stop_events": stop_events, "stop_count": len(stop_events), "max_abs_net_weight": max_abs_net_weight,
            "monthly_returns_pct": monthly, "positive_months": sum(v > 0 for v in monthly.values()),
            "months": len(monthly), "daily_equity": daily, "execution_audit": audit,
            "bounded_settlements": bounded_settlements,
            "funding_observations": {"exact_marks": exact_count, "hourly_bounds": bound_count,
                                     "exact_marks_within_previous_candle_only": boundary_mark_count},
            "asset_attribution_pct_initial": {s: {**{k: 100 * v for k, v in values.items()},
                "net": 100 * (values["price_pnl"] + values["funding_pnl"] - values["fees"])}
                for s, values in attribution.items()}}


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
