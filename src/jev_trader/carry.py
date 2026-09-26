"""Collateralized spot/perpetual funding carry with two-leg cash accounting."""

from __future__ import annotations

import bisect
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from .binance_data import HOUR_MS, load_cached_range, utc_ms
from .cli import DATA_ROOT, FIRST, LAST, RESULTS, SYMBOLS, _fingerprint
from .derivatives_data import load as load_derivatives

DAY_MS = 24 * HOUR_MS
CANDIDATES = ("always", "positive_30d", "hysteresis_8pct", "hurdle_15pct")
WINDOWS = {"development": ("2024-01-01", "2025-01-01"),
           "calibration": ("2025-01-01", "2025-07-01"),
           "validation": ("2025-07-01", "2026-01-01"),
           "confirmation": ("2026-01-01", "2026-08-01"),
           "combined": ("2025-01-01", "2026-08-01")}
COSTS = {"base": (.0015, .001), "stress": (.0025, .0015), "double_stress": (.005, .003)}


def annualized_past_funding(rows, timestamp):
    # Strictly before execution; rates paid at this very boundary are excluded.
    times = [row.timestamp_ms for row in rows]
    start = bisect.bisect_left(times, timestamp - 30 * DAY_MS)
    stop = bisect.bisect_left(times, timestamp)
    selected = rows[start:stop]
    coverage_hours = sum(row.interval_hours for row in selected)
    if coverage_hours < 28 * 24:
        return None
    return sum(row.rate for row in selected) * 365 / 30


def target_for(rule, annualized, prior_active):
    if annualized is None:
        return False
    if rule == "always":
        return True
    if rule == "positive_30d":
        return annualized > 0
    if rule == "hysteresis_8pct":
        return annualized > 0 if prior_active else annualized >= .08
    if rule == "hurdle_15pct":
        return annualized >= .15
    raise ValueError("unknown carry rule")


def prepare(spot, derivatives):
    # This study starts after the documented March 2023 spot gap.
    result = {}
    for symbol, bars in spot.items():
        futures = {b.open_ms: b for b in derivatives["klines"][symbol]}
        mark = {b.open_ms: b for b in derivatives["markPriceKlines"][symbol]}
        relevant = [b for b in bars if b.open_ms >= utc_ms("2023-04-01")]
        if any(b.open_ms not in futures or b.open_ms not in mark for b in relevant):
            raise ValueError(f"missing paired futures/mark candle: {symbol}")
        if any(b.open_ms - a.open_ms != HOUR_MS for a, b in zip(relevant, relevant[1:])):
            raise ValueError("incomplete spot hourly calendar")
        funding = {}
        for row in derivatives["fundingRate"][symbol]:
            hour = row.timestamp_ms // HOUR_MS * HOUR_MS
            if hour in funding:
                raise ValueError("multiple settlements in one hour")
            funding[hour] = row
        # All rate decisions are computed once, before any strategy evaluation.
        rates = {b.open_ms: annualized_past_funding(derivatives["fundingRate"][symbol], b.open_ms)
                 for b in relevant if b.open_ms % DAY_MS == 0
                 and datetime.fromtimestamp(b.open_ms / 1000, timezone.utc).weekday() == 0}
        result[symbol] = {"spot": relevant, "futures": futures, "mark": mark,
                          "funding": funding, "past_annualized": rates}
    return result


def evaluate(data, rule, start, end, spot_cost, future_cost, allocation=.25):
    if not 0 < allocation <= .5 or min(spot_cost, future_cost) < 0:
        raise ValueError("invalid carry allocation/cost")
    start_ms, end_ms = utc_ms(start), utc_ms(end)
    symbols = sorted(data)
    if not symbols:
        raise ValueError("empty universe")
    first = data[symbols[0]]["spot"]
    timeline = [b.open_ms for b in first if start_ms <= b.open_ms <= end_ms]
    if not timeline or timeline[0] != start_ms or timeline[-1] != end_ms:
        raise ValueError("incomplete carry window")
    spot = {s: {b.open_ms: b for b in data[s]["spot"]} for s in symbols}
    cash = {s: 1.0 for s in symbols}
    quantity = {s: 0.0 for s in symbols}
    active = {s: False for s in symbols}
    previous_future = {s: data[s]["futures"][start_ms].open for s in symbols}
    path = []
    funding_income = fees = 0.0
    paid_events = exposed_hours = entries = adjustments = margin_breaches = 0
    min_margin_ratio = float("inf")
    turnover = 0.0
    for timestamp in timeline:
        values = []
        for s in symbols:
            item = data[s]
            sb, fb, mb = spot[s][timestamp], item["futures"][timestamp], item["mark"][timestamp]
            q = quantity[s]
            previous_q = q
            # Short linear contract P&L. Marking in USDT does not create cash
            # available to buy additional spot beyond this same wallet balance.
            cash[s] += q * (previous_future[s] - fb.open)
            previous_future[s] = fb.open
            is_end = timestamp == end_ms
            should_rebalance = timestamp in item["past_annualized"]
            if should_rebalance and not is_end:
                active[s] = target_for(rule, item["past_annualized"][timestamp], active[s])
            if is_end or should_rebalance:
                equity = cash[s] + q * sb.open
                desired = allocation * equity / sb.open if active[s] and not is_end else 0.0
                delta = desired - q
                charge = abs(delta) * (sb.open * spot_cost + fb.open * future_cost)
                cash[s] -= delta * sb.open + charge
                fees += charge / len(symbols)
                turnover += abs(delta) * (sb.open + fb.open) / len(symbols)
                if not q and desired:
                    entries += 1
                if abs(delta) > 1e-12:
                    adjustments += 1
                quantity[s] = q = desired
            if (timestamp in item["funding"]
                    and item["funding"][timestamp].timestamp_ms < end_ms):
                rate = item["funding"][timestamp].rate
                # If rebalance and settlement share an hour, conservatively
                # credit only retained quantity and charge the larger quantity.
                eligible = min(previous_q, q) if rate >= 0 else max(previous_q, q)
                payment = eligible * mb.open * rate
                cash[s] += payment
                funding_income += payment / len(symbols)
                paid_events += bool(eligible)
            if q and not is_end:
                # Stress isolated futures collateral at the observed mark high.
                stressed_wallet = cash[s] + q * (fb.open - mb.high)
                notional = q * mb.high
                margin_ratio = stressed_wallet / notional
                min_margin_ratio = min(min_margin_ratio, margin_ratio)
                margin_breaches += margin_ratio < .10
                exposed_hours += 1
            value = cash[s] + q * sb.open
            if value <= 0:
                raise ValueError("nonpositive carry equity")
            values.append(value)
        path.append((timestamp, sum(values) / len(values)))
    # Include initial unit equity so initial fees count toward drawdown.
    peak, drawdown = 1.0, 0.0
    for _, value in path:
        peak = max(peak, value)
        drawdown = max(drawdown, 1 - value / peak)
    monthly, prior = {}, 1.0
    for i in range(1, len(path)):
        month = datetime.fromtimestamp(path[i - 1][0] / 1000, timezone.utc).strftime("%Y-%m")
        next_month = datetime.fromtimestamp(path[i][0] / 1000, timezone.utc).strftime("%Y-%m")
        if month != next_month or i == len(path) - 1:
            monthly[month] = 100 * (path[i][1] / prior - 1)
            prior = path[i][1]
    return {
        "start": start, "end": end, "return_pct": 100 * (path[-1][1] - 1),
        "max_drawdown_pct": 100 * drawdown, "monthly_returns_pct": monthly,
        "positive_months": sum(v > 0 for v in monthly.values()), "months": len(monthly),
        "entries": entries, "adjustments": adjustments, "settlements_while_exposed": paid_events,
        "average_exposure_days_per_asset": exposed_hours / 24 / len(symbols),
        "funding_income_pct_initial": 100 * funding_income, "fees_pct_initial": 100 * fees,
        "basis_pnl_pct_initial": 100 * (path[-1][1] - 1 - funding_income + fees),
        "turnover_gross_initial_capital": turnover,
        "minimum_intrahour_margin_ratio": min_margin_ratio if math.isfinite(min_margin_ratio) else None,
        "hours_below_10pct_margin": margin_breaches,
        "symbol_returns_pct": {s: 100 * (cash[s] - 1) for s in symbols},
    }


def passes(result):
    return (result["return_pct"] > 0 and result["max_drawdown_pct"] <= 10
            and result["positive_months"] >= math.ceil(2 * result["months"] / 3)
            and result["average_exposure_days_per_asset"] >= 60
            and result["hours_below_10pct_margin"] == 0)


def run():
    spot, spot_manifest = load_cached_range(SYMBOLS, FIRST, LAST, DATA_ROOT)
    derivatives, derivative_manifest = load_derivatives()
    data = prepare(spot, derivatives)
    print("paired spot/future/mark prices and causal past funding ready", flush=True)
    candidates = {}
    for rule in CANDIDATES:
        candidates[rule] = {"development": {cost: evaluate(data, rule, *WINDOWS["development"], *fees)
                            for cost, fees in COSTS.items()}}
    selected = max(CANDIDATES, key=lambda name: (passes(candidates[name]["development"]["stress"]),
                                               candidates[name]["development"]["stress"]["return_pct"]))
    # Once selected on development, inspect all rules later only as exploratory diagnostics.
    for rule in CANDIDATES:
        for window, dates in WINDOWS.items():
            if window != "development":
                candidates[rule][window] = {cost: evaluate(data, rule, *dates, *fees) for cost, fees in COSTS.items()}
        candidates[rule]["all_later_gates"] = all(passes(candidates[rule][window]["stress"])
                            for window in ("calibration", "validation", "confirmation"))
        m = candidates[rule]["combined"]["stress"]
        print(f"{rule}: return={m['return_pct']:.3f}% drawdown={m['max_drawdown_pct']:.3f}% "
              f"months={m['positive_months']}/{m['months']} gates={candidates[rule]['all_later_gates']}", flush=True)
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "spot_manifest_sha256": _fingerprint(spot_manifest),
        "derivatives_manifest_sha256": hashlib.sha256(json.dumps(
            [{k: r[k] for k in ("kind", "symbol", "month", "sha256")} for r in derivative_manifest],
            sort_keys=True).encode()).hexdigest(),
        "source_code_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                               for name in ("carry.py", "derivatives_data.py", "binance_data.py")},
        "design": {"per_leg_allocation": .25, "rebalancing": "Monday 00:00 UTC",
                   "lookback_days": 30, "costs": COSTS, "windows": WINDOWS,
                   "maintenance_stress_ratio": .10},
        "selected_on_2024": selected, "candidates": candidates,
        "deployable": False,
        "limits": ["Past funding does not guarantee future funding.",
                   "Two-leg next-open fills and slippage are assumed, not executable quotes.",
                   "Funding payment uses mark open for settlement occurring within the first minute.",
                   "At rebalance/settlement collisions, positive funding uses min(old,new) quantity; negative uses max.",
                   "10% maintenance buffer is a stress proxy, not exact exchange liquidation tiers.",
                   "Spot collateral cannot be spent twice; no borrowing or yield on free cash.",
                   "Account eligibility, venue risk, taxes, ADL and transfer limitations remain unverified.",
                   "Previously inspected historical periods are not prospective evidence."],
    }
    path = RESULTS / "carry_research.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"selected on development: {selected}; report: {path}", flush=True)
    return report


if __name__ == "__main__":
    run()
