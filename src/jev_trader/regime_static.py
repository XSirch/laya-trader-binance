"""Development-fixed exposure benchmarks for dynamic risk policies."""

import hashlib
import json

from .binance_data import utc_ms
from .broad_data import load as load_daily
from .broad_execution import evaluate
from .broad_extension import extend
from .broad_hourly import load as load_hourly
from .broad_research import target_weights
from .broad_technical import feature_bundle
from .cli import ROOT, RESULTS
from .regime_risk import RULE
from .statistics import family_bootstrap
from .trailing_stop import TrailingStop
from .trailing_universe import compact


def gross(row):
    return sum(abs(v) for v in row["target_weights"].values())


def development_scale(candidate, reference):
    if not candidate or [r["execution_ms"] for r in candidate] != [r["execution_ms"] for r in reference]:
        raise ValueError("development decision calendars differ or are empty")
    for row in candidate + reference:
        if not utc_ms("2022-01-01") <= row["execution_ms"] < utc_ms("2024-01-01"):
            raise ValueError("scale calibration outside development")
    denominator = sum(gross(r) for r in reference)
    if denominator <= 0:
        raise ValueError("zero reference exposure")
    result = sum(gross(r) for r in candidate) / denominator
    if not 0 < result <= 1 + 1e-12:
        raise ValueError("invalid non-amplifying scale")
    return min(1.0, result)


def constant_policy(scale):
    if not 0 < scale <= 1:
        raise ValueError("invalid constant scale")
    def policy(states, rule):
        return {s: w * scale for s, w in target_weights(states, rule).items()}
    return policy


def run():
    path = RESULTS / "regime_risk.json"
    prior = json.loads(path.read_text(encoding="utf-8"))
    rows = prior["results"]
    reference = rows["reference_none"]["development"]["stress"]["execution_audit"]
    scales = {mode: development_scale(rows[f"{mode}_none"]["development"]["stress"]["execution_audit"], reference)
              for mode in ("volatility", "confluence", "combined")}
    print("development-only scales", scales, flush=True)
    data, _, _ = load_daily()
    hourly, _ = load_hourly(data)
    training, _ = load_hourly(data, "training_hourly_manifest.json")
    for kind in hourly:
        for s in hourly[kind]:
            hourly[kind][s].update(training[kind][s])
    extend(data, hourly)
    states, _, _ = feature_bundle(data)
    periods = {"development": ("2022-01-01", "2024-01-01"),
               "2024": ("2024-01-01", "2025-01-01"), "2025": ("2025-01-01", "2026-01-01"),
               "2026_jan_jul": ("2026-01-01", "2026-08-01"), "recent": ("2026-08-01", "2026-09-26"),
               "combined": ("2024-01-01", "2026-09-26")}
    results, comparisons, paths = {}, {}, {}
    for mode, scale in scales.items():
        for stop in ("none", "trailing4"):
            key = f"{mode}_{stop}"
            results[key], comparisons[key] = {}, {}
            for period, dates in periods.items():
                results[key][period], comparisons[key][period] = {}, {}
                for cost_name, cost in (("stress", .0015), ("double_stress", .003)):
                    row = evaluate(hourly, data["fundingRate"], states, RULE, *dates, cost,
                                   target_policy=constant_policy(scale),
                                   trailing=TrailingStop("portfolio_pct", .04) if stop == "trailing4" else None)
                    dynamic = rows[key][period][cost_name]
                    results[key][period][cost_name] = row
                    comparison = {metric + "_dynamic_minus_static": dynamic[metric] - row[metric]
                                  for metric in ("return_pct", "max_drawdown_pct", "fees_pct_initial")}
                    for label, values in (("dynamic", dynamic), ("static", row)):
                        audit = values["execution_audit"]
                        comparison[label + "_mean_target_gross"] = sum(gross(r) for r in audit) / len(audit)
                    comparisons[key][period][cost_name] = comparison
                    if period == "development" and stop == "none":
                        if abs(comparison["dynamic_mean_target_gross"] - comparison["static_mean_target_gross"]) > 1e-10:
                            raise AssertionError("development exposure mismatch")
                    if period == "combined" and cost_name == "stress":
                        if set(dynamic["daily_equity"]) != set(row["daily_equity"]):
                            raise AssertionError("paired equity calendars differ")
                        paths[key] = {t: v / row["daily_equity"][t] for t, v in dynamic["daily_equity"].items()}
            print(key, comparisons[key]["combined"]["stress"], flush=True)
    diagnostics = {}
    for name in paths:
        value = family_bootstrap(paths, name)
        value.pop("cash_benchmark_return")
        value["benchmark"] = "Matched static-exposure portfolio; metrics describe relative wealth."
        diagnostics[name] = value
    report = {"scales": scales, "results": results, "comparisons": comparisons,
              "paired_diagnostics": diagnostics, "prior_selection_unchanged": prior["selected_on_development"],
              "prior_report_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "source_sha256": hashlib.sha256((ROOT / "src/jev_trader/regime_static.py").read_bytes()).hexdigest(),
              "deployable": False,
              "limits": ["Exposure matched in development only; later mean exposure can differ.",
                         "Ex-post diagnostic after inspecting earlier dynamic policy results.",
                         "Six-pair bootstrap correction does not cover the entire historical search."]}
    output = RESULTS / "regime_static.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = compact(report)
    summary["full_report_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    (ROOT / "docs/regime_static_2026-09-26.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    run()
