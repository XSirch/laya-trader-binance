"""Loss-distribution diagnostics for fixed candidates, without refitting signals."""

import hashlib
import json
import math
import random
from datetime import datetime, timezone

from .binance_data import utc_ms
from .cli import ROOT, RESULTS
from .statistics import family_bootstrap

DAY_MS = 86_400_000


def daily_returns(equity):
    rows = sorted((int(t), v) for t, v in equity.items())
    if len(rows) < 2 or any(not math.isfinite(v) or v <= 0 for _, v in rows):
        raise ValueError("equity must contain at least two finite positive observations")
    if any(b - a != DAY_MS for (a, _), (b, _) in zip(rows, rows[1:])):
        raise ValueError("equity calendar must be consecutive daily observations")
    return [(t, math.log(b / a)) for (_, a), (t, b) in zip(rows, rows[1:])]


def rolling_summary(logreturns, horizon):
    if horizon < 1 or len(logreturns) < horizon or any(not math.isfinite(v) for v in logreturns):
        raise ValueError("invalid rolling return window")
    total = sum(logreturns[:horizon])
    sums = [total]
    for i in range(horizon, len(logreturns)):
        total += logreturns[i] - logreturns[i - horizon]
        sums.append(total)
    return {"windows": len(sums), "positive_windows": sum(v > 0 for v in sums),
            "worst_return_pct": 100 * math.expm1(min(sums)),
            "best_return_pct": 100 * math.expm1(max(sums)),
            "overlapping_windows_are_dependent": True}


def path_metrics(logreturns):
    level, peak, drawdown, underwater, longest = 0.0, 0.0, 0.0, 0, 0
    for value in logreturns:
        level += value
        if level >= peak - 1e-12:
            peak, underwater = max(peak, level), 0
        else:
            underwater += 1
            longest = max(longest, underwater)
        drawdown = max(drawdown, -math.expm1(level - peak))
    return {"days": len(logreturns), "return_pct": 100 * math.expm1(level),
            "annualized_geometric_return_pct": 100 * math.expm1(level * 365 / len(logreturns)),
            "max_daily_drawdown_pct": 100 * drawdown,
            "longest_underwater_days": longest, "terminal_underwater_days": underwater,
            "rolling": {str(n): rolling_summary(logreturns, n) for n in (30, 90, 180, 365) if len(logreturns) >= n}}


def percentiles(values):
    ordered = sorted(values)
    return {label: ordered[min(len(ordered) - 1, int(p * len(ordered)))]
            for label, p in (("p05", .05), ("p50", .5), ("p95", .95))}


def block_scenarios(logreturns, horizon, observed_log_return, block_days=30, draws=2000, seed=1907):
    if (block_days < 1 or len(logreturns) < 2 * block_days or horizon < 1 or draws < 100
            or any(not math.isfinite(v) for v in logreturns) or not math.isfinite(observed_log_return)):
        raise ValueError("invalid block-scenario inputs")
    rng, returns, drawdowns = random.Random(seed), [], []
    loss_count, tail_count = 0, 0
    for _ in range(draws):
        level, peak, drawdown, generated = 0.0, 0.0, 0.0, 0
        while generated < horizon:
            start = rng.randrange(len(logreturns))
            count = min(block_days, horizon - generated)
            for i in range(count):
                level += logreturns[(start + i) % len(logreturns)]
                peak = max(peak, level)
                drawdown = max(drawdown, -math.expm1(level - peak))
            generated += count
        returns.append(100 * math.expm1(level))
        drawdowns.append(100 * drawdown)
        loss_count += level < 0
        tail_count += level <= observed_log_return
    return {"calibration_days": len(logreturns), "horizon_days": horizon,
            "block_days": block_days, "draws": draws, "seed": seed,
            "loss_frequency": loss_count / draws, "at_or_below_observed_frequency": tail_count / draws,
            "return_percentiles_pct": percentiles(returns), "drawdown_percentiles_pct": percentiles(drawdowns),
            "interpretation": "Conditional empirical scenario frequencies, not calibrated future probabilities."}


def run():
    source = RESULTS / "trailing_research.json"
    prior = json.loads(source.read_text(encoding="utf-8"))
    cutoff = utc_ms("2026-08-01")
    results = {}
    calibration_paths = {
        cost: {name: {t: v for t, v in prior["results"][name]["combined"][cost]["daily_equity"].items()
                      if int(t) <= cutoff} for name in ("none", "portfolio_pct_4pct")}
        for cost in ("stress", "double_stress")}
    for name in ("none", "portfolio_pct_4pct"):
        results[name] = {}
        for cost in ("stress", "double_stress"):
            original = prior["results"][name]["combined"][cost]
            dated = daily_returns(original["daily_equity"])
            calibration = [v for t, v in dated if t <= cutoff]
            recent = [v for t, v in dated if t > cutoff]
            if len(recent) != (max(t for t, _ in dated) - cutoff) // DAY_MS:
                raise ValueError("recent calendar mismatch")
            row = {"calibration_last_return_end_ms": cutoff,
                   "recent_first_return_end_ms": min(t for t, _ in dated if t > cutoff),
                   "calibration": path_metrics(calibration), "recent_continuous": path_metrics(recent),
                   "full": path_metrics([v for _, v in dated]),
                   "historical_recent_length_windows": rolling_summary(calibration, len(recent)),
                   "original_hourly_max_drawdown_pct": original["max_drawdown_pct"],
                   "scenarios": {str(block): block_scenarios(calibration, len(recent), sum(recent), block, 5000)
                                 for block in (14, 30, 60)}}
            estimate = family_bootstrap(calibration_paths[cost], name, draws=5000)
            row["calibration_growth_interval"] = {
                "annualized_geometric_return_95_interval_pct": estimate["selected_annualized_geometric_return_95_interval_pct"],
                "block_days": 30, "draws": 5000,
                "interpretation": "Individual retrospective bootstrap interval; not adjusted for research selection."}
            if abs(row["full"]["return_pct"] - original["return_pct"]) > 1e-8:
                raise AssertionError("daily path does not reconcile with net return")
            results[name][cost] = row
            print(name, cost, "recent", row["recent_continuous"]["return_pct"],
                  "loss_frequency", row["scenarios"]["30"]["loss_frequency"],
                  "tail_frequency", row["scenarios"]["30"]["at_or_below_observed_frequency"], flush=True)
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "results": results, "deployable": False,
              "source_report_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "source_code_sha256": hashlib.sha256((ROOT / "src/jev_trader/consistency.py").read_bytes()).hexdigest(),
              "protocol_sha256": hashlib.sha256((ROOT / "docs/consistency_protocol_2026-09-26.md").read_bytes()).hexdigest(),
              "candidate_selection_changed": False,
              "limits": ["Neither historical segment is prospectively unseen to the researcher.",
                         "Scenario frequencies assume dependence and regimes resemble calibration history.",
                         "Recent segment continues the combined portfolio; independent-start replay differs.",
                         "Daily timestamps follow events in the midnight hour; terminal sample includes liquidation fees.",
                         "Daily samples omit within-day drawdown and execution liquidity.",
                         "Loss compatibility is not proof of positive expectancy or sustainable future profits."]}
    (ROOT / "docs/consistency_2026-09-26.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    run()
