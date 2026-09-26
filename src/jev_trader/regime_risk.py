"""Causal multifactor exposure control; development-only mechanical selection."""

import hashlib
import json
from datetime import datetime, timezone
from statistics import median

from .broad_data import load as load_daily
from .broad_execution import evaluate
from .broad_extension import extend
from .broad_hourly import load as load_hourly
from .broad_research import sign, target_weights
from .broad_technical import feature_bundle
from .cli import ROOT, RESULTS
from .trailing_stop import TrailingStop
from .trailing_universe import compact

RULE = "blend:low_volatility30+carry30_betahedged"
MODES = ("reference", "volatility", "confluence", "combined")


def mean(values):
    return sum(values) / len(values)


def directional_score(row):
    def value(key):
        return row["technical." + key]
    trend = mean([sign(value("trend.distance_sma_pct." + str(n))) for n in (10, 20, 50, 100, 200)] +
                 [sign(value("trend.distance_ema_pct." + str(n))) for n in (12, 26, 50, 200)] +
                 [sign(value("trend.sma50_slope_5bars_pct")),
                  sign(value("trend.plus_di14") - value("trend.minus_di14"))])
    momentum = mean([sign(value("momentum.rsi14") - 50), sign(value("momentum.macd_pct")),
                     sign(value("momentum.macd_histogram_pct")), sign(value("momentum.stochastic_k14") - 50)])
    participation = mean([sign(value("participation.obv_change20_over_volume")),
                          sign(value("participation.taker_buy_fraction20") - .5),
                          sign(value("participation.distance_vwap20_pct"))])
    structure = mean([sign(value("structure.close_position_in_bar") - .5),
                      sign(value("volatility.bollinger_position") - .5)])
    fibonacci = mean([sign(.5 - value(f"structure.fibonacci.{n}.retracement_fraction")) for n in (60, 180)])
    economic = mean([sign(row["momentum7"]), sign(row["momentum30"]), sign(row["momentum90"]),
                     row["time_series_ensemble"]])
    return mean([trend, momentum, participation, structure, fibonacci, economic])


def scale_for(states, weights, mode):
    if mode not in MODES:
        raise ValueError("unknown risk mode")
    if not weights or mode == "reference":
        return 1.0
    eligible = [v for v in states.values() if v["quote_volume20"] >= 10_000_000
                and .005 <= v["volatility"] <= .15]
    vol = min(1.0, .03 / median(v["volatility"] for v in eligible))
    gross = sum(abs(v) for v in weights.values())
    alignment = sum(w * directional_score(states[s]) for s, w in weights.items()) / gross if gross else 0
    confluence = .25 + .75 * (alignment + 1) / 2
    return vol if mode == "volatility" else confluence if mode == "confluence" else vol * confluence


def risk_policy(mode):
    def policy(states, rule):
        weights = target_weights(states, rule)
        scale = scale_for(states, weights, mode)
        return {s: w * scale for s, w in weights.items()}
    return policy


def select(development):
    valid = [name for name, costs in development.items()
             if costs["stress"].get("status") == "complete" and costs["stress"]["return_pct"] > 0]
    return min(valid, key=lambda n: (-development[n]["stress"]["return_pct"], n)) if valid else None


def run():
    data, _, _ = load_daily()
    hourly, _ = load_hourly(data)
    training, _ = load_hourly(data, "training_hourly_manifest.json")
    for kind in hourly:
        for s in hourly[kind]:
            hourly[kind][s].update(training[kind][s])
    extend(data, hourly)
    states, fields, quality = feature_bundle(data)
    variants = [(f"{mode}_{stop}", mode, stop == "trailing4") for mode in MODES for stop in ("none", "trailing4")]
    def replay(mode, trailing, dates, cost):
        try:
            row = evaluate(hourly, data["fundingRate"], states, RULE, *dates, cost,
                           target_policy=risk_policy(mode), trailing=TrailingStop("portfolio_pct", .04) if trailing else None)
        except ValueError as exc:
            if not str(exc).startswith("unresolved held price"):
                raise
            return {"status": "invalid_execution", "error": str(exc)}
        row["status"] = "complete"
        return row
    development = {name: {label: replay(mode, trailing, ("2022-01-01", "2024-01-01"), cost)
                          for label, cost in (("stress", .0015), ("double_stress", .003))}
                   for name, mode, trailing in variants}
    selected = select(development)
    freeze = {"created_utc": datetime.now(timezone.utc).isoformat(), "selected": selected,
              "development": compact(development), "later_results_evaluated": False,
              "source_sha256": hashlib.sha256((ROOT / "src/jev_trader/regime_risk.py").read_bytes()).hexdigest()}
    selection_path = ROOT / "docs/regime_risk_selection_2026-09-26.json"
    selection_path.write_text(json.dumps(freeze, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("development selection", selected, flush=True)
    periods = {"2024": ("2024-01-01", "2025-01-01"), "2025": ("2025-01-01", "2026-01-01"),
               "2026_jan_jul": ("2026-01-01", "2026-08-01"), "recent": ("2026-08-01", "2026-09-26"),
               "combined": ("2024-01-01", "2026-09-26")}
    results = {}
    for name, mode, trailing in variants:
        results[name] = {"development": development[name]}
        for period, dates in periods.items():
            results[name][period] = {label: replay(mode, trailing, dates, cost)
                                     for label, cost in (("stress", .0015), ("double_stress", .003))}
        print(name, {p: row["stress"].get("return_pct", row["stress"].get("error"))
                     for p, row in results[name].items()}, flush=True)
    report = {"results": results, "selected_on_development": selected, "fields": fields,
              "feature_quality": quality, "deployable": False,
              "source_sha256": freeze["source_sha256"],
              "selection_sha256": hashlib.sha256(selection_path.read_bytes()).hexdigest(),
              "limits": ["Hypothesis introduced after inspecting previous later-period experiments.",
                         "No exposure amplification or direction changes; risk controls cannot manufacture alpha.",
                         "Reference uses complete technical bundle availability, which may restrict economic signals.",
                         "No live execution or prospective confirmation."]}
    path = RESULTS / "regime_risk.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = compact(report)
    summary["full_report_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (ROOT / "docs/regime_risk_2026-09-26.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    run()
