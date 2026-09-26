"""Paired diagnostics of incremental trailing performance, without refitting."""

import hashlib
import json
import math
from pathlib import Path

from jev_trader.statistics import family_bootstrap

ROOT = Path(__file__).resolve().parents[1]


def relative_path(candidate, reference):
    if set(candidate) != set(reference):
        raise ValueError("paired calendars differ")
    if any(not math.isfinite(x) or x <= 0 for p in (candidate, reference) for x in p.values()):
        raise ValueError("paired equities must be finite and positive")
    return {t: candidate[t] / reference[t] for t in candidate}


def run():
    source = ROOT / "results/trailing_research.json"
    report = json.loads(source.read_text(encoding="utf-8"))
    rows = {k: v["combined"]["stress"] for k, v in report["results"].items()}
    base, selected = rows["none"], rows["portfolio_pct_4pct"]
    paths = {k: relative_path(v["daily_equity"], base["daily_equity"]) for k, v in rows.items()}
    diagnostics = {str(block): family_bootstrap(paths, "portfolio_pct_4pct", block_days=block)
                   for block in (14, 30, 60, 90)}
    for diagnostic in diagnostics.values():
        diagnostic.pop("cash_benchmark_return")
        diagnostic["benchmark"] = "No-stop portfolio; annualized metrics describe relative wealth, not cash excess or arithmetic alpha."
    ordered = sorted(paths["portfolio_pct_4pct"].items(), key=lambda x: int(x[0]))
    increments = sorted(((t, math.log(v / prior)) for (_, prior), (t, v) in zip(ordered, ordered[1:])),
                        key=lambda x: x[1], reverse=True)
    total_log = sum(v for _, v in increments)
    months = {m: 100 * ((1 + value / 100) / (1 + base["monthly_returns_pct"][m] / 100) - 1)
              for m, value in selected["monthly_returns_pct"].items()}
    attribution = {s: v["net"] - base["asset_attribution_pct_initial"][s]["net"]
                   for s, v in selected["asset_attribution_pct_initial"].items()}
    delta = selected["return_pct"] - base["return_pct"]
    if abs(sum(attribution.values()) - delta) > 1e-8:
        raise ValueError("incremental attribution does not reconcile")
    output = {
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "analysis_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "deployable": False,
        "paired_bootstrap_by_block_days": diagnostics,
        "aggregate_return_difference_pp": delta,
        "relative_wealth_gain_pct": 100 * math.expm1(total_log),
        "monthly_relative_returns_pct": months,
        "months_outperforming": sum(v > 1e-10 for v in months.values()),
        "months_underperforming": sum(v < -1e-10 for v in months.values()),
        "asset_incremental_attribution_pp": attribution,
        "best_incremental_days": increments[:10],
        "relative_gain_after_zeroing_best_incremental_days_pct": {
            str(n): 100 * math.expm1(total_log - sum(v for _, v in increments[:n]))
            for n in (1, 3, 5, 10)
        },
        "limits": [
            "Paired relative equity is a diagnostic, not a separately tradable strategy.",
            "Zeroing selected historical increments is an ex-post concentration diagnostic, not a simulated executable portfolio.",
            "Asset attribution differences include changed exposure and compounding; removing an asset requires a new replay.",
            "Bootstrap adjusts only nine trailing variants, not the full prior research history.",
            "All observations were previously inspected; no prospective confirmation.",
        ],
    }
    target = ROOT / "docs/trailing_increment_2026-09-26.json"
    target.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in output.items() if k not in ("monthly_relative_returns_pct", "best_incremental_days")}, indent=2))


if __name__ == "__main__":
    run()
