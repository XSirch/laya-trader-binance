"""Predeclared broad-cohort factor screening with explicit data/exit limitations."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from .binance_data import utc_ms
from .broad_data import load, CACHE
from .cli import RESULTS
from .market_state import ema
from .statistics import family_bootstrap

DAY_MS = 86_400_000
FACTORS = ("momentum7", "momentum30", "momentum90", "momentum90_skip7",
           "reversal1", "reversal7", "carry30", "low_volatility30", "taker_flow20",
           "rank_blend", "quality_momentum", "time_series_ensemble")
VARIANTS = FACTORS + tuple(name + "_betahedged" for name in FACTORS)
PERIODS = {"development": ("2022-01-01", "2024-01-01"),
           "validation_2024": ("2024-01-01", "2025-01-01"),
           "calibration_2025h1": ("2025-01-01", "2025-07-01"),
           "validation_2025h2": ("2025-07-01", "2026-01-01"),
           "confirmation_2026": ("2026-01-01", "2026-08-01"),
           "combined": ("2024-01-01", "2026-08-01")}


def sign(value):
    return 1 if value > 0 else -1 if value < 0 else 0


def features(data):
    result = {}
    bitcoin = data["klines"]["BTCUSDT"] if "BTCUSDT" in data["klines"] else next(iter(data["klines"].values()))
    btc_returns = {b.open_ms: math.log(b.close / a.close) for a, b in zip(bitcoin, bitcoin[1:])
                   if b.open_ms - a.open_ms == DAY_MS}
    for symbol, bars in data["klines"].items():
        funding = data["fundingRate"][symbol]
        f_index = 0
        last_rates = []
        closes = [b.close for b in bars]
        averages = {n: ema(closes, n) for n in (8, 16, 32, 64, 128)}
        output = {}
        for i, bar in enumerate(bars):
            close_ms = bar.open_ms + DAY_MS
            while f_index < len(funding) and funding[f_index].timestamp_ms < close_ms:
                last_rates.append(funding[f_index])
                f_index += 1
            last_rates = [r for r in last_rates if r.timestamp_ms >= close_ms - 30 * DAY_MS]
            if i < 200 or bars[i - 200].open_ms != bar.open_ms - 200 * DAY_MS:
                continue
            coverage = sum(r.interval_hours for r in last_rates)
            if coverage < 28 * 24:
                continue
            daily_changes = [math.log(closes[j] / closes[j - 1]) for j in range(i - 29, i + 1)]
            average = sum(daily_changes) / 30
            vol = math.sqrt(sum((v - average) ** 2 for v in daily_changes) / 30)
            recent = bars[i - 19:i + 1]
            base_volume = sum(b.volume for b in recent)
            quote_volume = sum(b.quote_volume for b in recent) / 20
            flow = sum(b.taker_buy_base for b in recent) / base_volume if base_volume else .5
            asset60 = [math.log(closes[j] / closes[j - 1]) for j in range(i - 59, i + 1)]
            btc60 = [btc_returns[bars[j].open_ms] for j in range(i - 59, i + 1)]
            ma, mb = sum(asset60) / 60, sum(btc60) / 60
            variance = sum((v - mb) ** 2 for v in btc60)
            beta = sum((a - ma) * (b - mb) for a, b in zip(asset60, btc60)) / variance if variance else 1
            output[close_ms] = {
                "beta60": .75 * max(.25, min(3, beta)) + .25,
                "quote_volume20": quote_volume, "momentum7": closes[i] / closes[i - 7] - 1,
                "momentum30": closes[i] / closes[i - 30] - 1,
                "momentum90": closes[i] / closes[i - 90] - 1,
                "momentum90_skip7": closes[i - 7] / closes[i - 90] - 1,
                "reversal1": -(closes[i] / closes[i - 1] - 1),
                "reversal7": -(closes[i] / closes[i - 7] - 1),
                "carry30": -sum(r.rate for r in last_rates) * 365 / 30,
                "low_volatility30": -vol, "volatility": vol,
                "taker_flow20": flow - .5,
                "time_series_ensemble": sum(sign(averages[a][i] - averages[b][i])
                                             for a, b in ((8, 32), (16, 64), (32, 128))) / 3,
                "latest_observed_close_ms": close_ms,
            }
        result[symbol] = output
    return result


def target_weights(states, factor):
    if factor.startswith("blend:"):
        members = factor.removeprefix("blend:").split("+")
        combined = {}
        for member in members:
            for symbol, weight in target_weights(states, member).items():
                combined[symbol] = combined.get(symbol, 0) + weight / len(members)
        return combined
    if factor.endswith("_betahedged"):
        weights = target_weights(states, factor.removesuffix("_betahedged"))
        if not weights or "BTCUSDT" not in states or states["BTCUSDT"]["quote_volume20"] < 10_000_000:
            return {}
        beta = sum(value * states[s]["beta60"] for s, value in weights.items())
        weights["BTCUSDT"] = weights.get("BTCUSDT", 0) - beta / states["BTCUSDT"]["beta60"]
        gross = sum(abs(value) for value in weights.values())
        scale = min(1, .5 / gross) if gross else 0
        return {s: value * scale for s, value in weights.items()}
    # Eligibility is based on already completed candles and their past turnover.
    eligible = {s: f for s, f in states.items() if f["quote_volume20"] >= 10_000_000
                and .005 <= f["volatility"] <= .15}
    if len(eligible) < 8:
        return {}
    if factor == "time_series_ensemble":
        raw = {s: f[factor] / max(f["volatility"], .01) for s, f in eligible.items()}
        total = sum(abs(v) for v in raw.values())
        return {s: max(-.10, min(.10, .5 * v / total)) for s, v in raw.items()} if total else {}
    if factor in ("rank_blend", "quality_momentum"):
        groups = ("momentum30", "carry30", "low_volatility30", "taker_flow20") if factor == "rank_blend" else (
            "momentum30", "low_volatility30", "taker_flow20")
        score = {s: 0.0 for s in eligible}
        for group in groups:
            ranked = sorted(eligible, key=lambda s: (eligible[s][group], s))
            for index, symbol in enumerate(ranked):
                score[symbol] += index / (len(ranked) - 1) / len(groups)
    else:
        score = {s: f[factor] for s, f in eligible.items()}
    ranked = sorted(score, key=lambda s: (score[s], s))
    count = max(2, len(ranked) // 5)
    # Equal dollars on both sides; 50% gross, 0% net at rebalance.
    amount = .25 / count
    return {**{s: -amount for s in ranked[:count]}, **{s: amount for s in ranked[-count:]}}


def evaluate(data, state, factor, start, end, side_cost):
    start_ms, end_ms = utc_ms(start), utc_ms(end)
    bars = {s: {b.open_ms: b for b in values} for s, values in data["klines"].items()}
    marks = {s: {b.open_ms: b for b in values} for s, values in data["markPriceKlines"].items()}
    fund = {s: {} for s in bars}
    for s, rows in data["fundingRate"].items():
        for row in rows:
            fund[s].setdefault(row.timestamp_ms // DAY_MS * DAY_MS, []).append(row)
    quantity, previous_price = {}, {}
    equity, fees, funding_pnl = 1.0, 0.0, 0.0
    entries, rebalances, margin_failures = 0, 0, 0
    path, unresolved, audit = [], [], []
    for timestamp in range(start_ms, end_ms + 1, DAY_MS):
        for s in list(quantity):
            q = quantity[s]
            if timestamp not in bars[s]:
                prior = bars[s].get(timestamp - DAY_MS)
                if prior is None:
                    raise ValueError("cannot value unresolved disappearance")
                # Explicit diagnostic scenario, never validated as an actual fill.
                equity += q * (prior.close - previous_price[s])
                charge = abs(q) * prior.close * (side_cost + .02)
                equity -= charge
                fees += charge
                unresolved.append({"symbol": s, "missing_at_ms": timestamp,
                                   "quantity": q, "proxy_close": prior.close,
                                   "extra_adverse_exit_fraction": .02})
                del quantity[s]
                continue
            current = bars[s][timestamp].open
            equity += q * (current - previous_price[s])
            previous_price[s] = current
        path.append((timestamp, equity))
        terminal = timestamp == end_ms
        is_rebalance = (factor.startswith("reversal1") or datetime.fromtimestamp(timestamp / 1000, timezone.utc).weekday() == 0)
        old_q = dict(quantity)
        if is_rebalance or terminal:
            current_state = {s: values[timestamp] for s, values in state.items() if timestamp in values}
            targets = target_weights(current_state, factor) if not terminal else {}
            if any(s not in bars or timestamp not in bars[s] for s in targets):
                # Unavailability becomes observable now, not used to rank yesterday.
                targets = {s: value for s, value in targets.items() if timestamp in bars[s]}
            starting_equity = equity
            for s in sorted(set(quantity) | set(targets)):
                price = bars[s][timestamp].open
                desired = targets.get(s, 0) * starting_equity / price
                previous = quantity.get(s, 0)
                charge = abs(desired - previous) * price * side_cost
                equity -= charge
                fees += charge
                entries += bool(desired) and sign(desired) != sign(previous)
                if desired:
                    quantity[s], previous_price[s] = desired, price
                else:
                    quantity.pop(s, None)
            rebalances += not terminal
            if not terminal:
                audit.append({"execution_ms": timestamp, "latest_input_close_ms": max(
                    (f["latest_observed_close_ms"] for f in current_state.values()), default=None),
                    "eligible_assets": len(current_state), "gross_weight": sum(abs(v) for v in targets.values()),
                    "net_weight": sum(targets.values())})
        if terminal:
            path[-1] = (timestamp, equity)
            break
        # Funding is accrued AFTER the current decision, using adverse mark-price
        # bounds because the daily screen cannot resolve intraday settlement marks.
        worst_equity = equity
        worst_notional = 0
        for s, q in quantity.items():
            bar = bars[s][timestamp]
            mark = marks[s][timestamp]
            worst_equity += q * ((bar.low if q > 0 else bar.high) - bar.open)
            worst_notional += abs(q) * mark.high
        for s in set(old_q) | set(quantity):
            if timestamp not in marks[s]:
                continue
            mark = marks[s][timestamp]
            for event in fund[s].get(timestamp, []):
                scalar = -quantity.get(s, 0) * event.rate
                if event.timestamp_ms - timestamp < 60_000:
                    scalar = min(scalar, -old_q.get(s, 0) * event.rate)
                payment = scalar * (mark.low if scalar >= 0 else mark.high)
                equity += payment
                funding_pnl += payment
                worst_equity += min(payment, 0)
        margin_failures += worst_equity < .10 * worst_notional
        if equity <= 0:
            raise ValueError("insolvent broad portfolio")
    peak, drawdown = 1.0, 0.0
    for _, value in path:
        peak = max(peak, value)
        drawdown = max(drawdown, 1 - value / peak)
    monthly, prior = {}, 1.0
    for i in range(1, len(path)):
        month = datetime.fromtimestamp(path[i - 1][0] / 1000, timezone.utc).strftime("%Y-%m")
        after = datetime.fromtimestamp(path[i][0] / 1000, timezone.utc).strftime("%Y-%m")
        if month != after or i == len(path) - 1:
            monthly[month] = 100 * (path[i][1] / prior - 1)
            prior = path[i][1]
    return {"return_pct": 100 * (equity - 1), "max_drawdown_pct": 100 * drawdown,
            "positive_months": sum(value > 0 for value in monthly.values()), "months": len(monthly),
            "monthly_returns_pct": monthly, "entries": entries, "rebalances": rebalances,
            "fees_pct_initial": 100 * fees, "funding_pct_initial": 100 * funding_pnl,
            "unresolved_exits": unresolved, "margin_stress_failures": margin_failures,
            "execution_audit": audit, "daily_equity": {str(t): v for t, v in path}}


def passed(m):
    return (m["return_pct"] > 0 and m["positive_months"] >= math.ceil(2 * m["months"] / 3)
            and m["max_drawdown_pct"] <= 15 and not m["unresolved_exits"]
            and not m["margin_stress_failures"] and m["entries"] >= 12)


def run():
    data, sources, cohort = load()
    state = features(data)
    results = {}
    for name in VARIANTS:
        results[name] = {"development": {cost: evaluate(data, state, name, *PERIODS["development"], value)
                         for cost, value in (("base", .001), ("stress", .0015))}}
    selected = max(VARIANTS, key=lambda n: (passed(results[n]["development"]["stress"]),
                                          results[n]["development"]["stress"]["return_pct"]))
    for name in VARIANTS:
        for period, dates in PERIODS.items():
            if period != "development":
                results[name][period] = {cost: evaluate(data, state, name, *dates, value)
                                        for cost, value in (("base", .001), ("stress", .0015))}
        results[name]["all_later_gates"] = all(passed(results[name][p]["stress"])
                                               for p in PERIODS if p not in ("development", "combined"))
        m = results[name]["combined"]["stress"]
        print(f"{name}: return={m['return_pct']:.2f}% dd={m['max_drawdown_pct']:.2f}% "
              f"months={m['positive_months']}/{m['months']} unresolved_exits={len(m['unresolved_exits'])} "
              f"gates={results[name]['all_later_gates']}", flush=True)
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "cohort": cohort,
              "data_quality": json.loads((CACHE / "data_quality.json").read_text(encoding="utf-8")),
              "selected_on_2022_2023": selected, "candidates": results, "deployable": False,
              "source_code_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                     for name in ("broad_data.py", "broad_research.py", "derivatives_data.py", "binance_data.py", "statistics.py")},
              "source_manifest_sha256": hashlib.sha256(json.dumps(
                  [{k: row[k] for k in ("kind", "symbol", "month", "sha256")} for row in sources], sort_keys=True).encode()).hexdigest(),
              "design": {"factors": VARIANTS, "periods": PERIODS, "gross_target": .5,
                         "minimum_past_daily_quote_volume": 10_000_000,
                         "minimum_eligible_assets": 8, "costs_per_side": {"base": .001, "stress": .0015}},
              "limits": ["Daily screening, not verified hourly execution or prospective evidence.",
                         "Missing-trading exits use an explicitly unresolved prior-close/2% adverse proxy; never approved.",
                         "Funding uses adverse daily mark bounds, not actual settlement marks.",
                         "The historical cohort avoids filtering survivors but archive availability is still a proxy for listing history.",
                         "A 10% margin stress is not actual liquidation accounting.",
                         "Previously inspected 2025-2026 periods remain exploratory."]}
    report["statistical_diagnostic"] = family_bootstrap(
        {name: periods["combined"]["stress"]["daily_equity"] for name, periods in results.items()}, selected)
    (RESULTS / "broad_research.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"development selection: {selected}", flush=True)
    return report


if __name__ == "__main__":
    run()
