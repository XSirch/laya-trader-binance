"""Fixed trailing-stop grid on the previously frozen multifactor portfolio."""

import hashlib
import json
from datetime import datetime, timezone

from .binance_data import HOUR_MS
from .broad_data import load as load_daily
from .broad_execution import evaluate
from .broad_extension import extend
from .broad_hourly import load as load_hourly
from .broad_research import DAY_MS, features
from .cli import ROOT, RESULTS
from .market_state import wilder
from .trailing_stop import TrailingStop

PERIODS = {"2024": ("2024-01-01", "2025-01-01"), "2025": ("2025-01-01", "2026-01-01"),
           "2026_jan_jul": ("2026-01-01", "2026-08-01"),
           "2026_aug_sep": ("2026-08-01", "2026-09-26"),
           "combined": ("2024-01-01", "2026-09-26")}


def atr_history(data):
    output = {}
    for s, bars in data["klines"].items():
        ranges = [bars[0].high - bars[0].low]
        for prior, current in zip(bars, bars[1:]):
            ranges.append(max(current.high - current.low, abs(current.high - prior.close), abs(current.low - prior.close)))
        output[s] = {bar.open_ms + DAY_MS: value for bar, value in zip(bars, wilder(ranges, 14)) if value is not None}
    return output


def run():
    frozen_path = ROOT / "docs/broad_candidate_freeze_2026-09-26.json"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    for name, expected in frozen["source_code_sha256"].items():
        if hashlib.sha256((ROOT / "src/jev_trader" / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"frozen strategy changed: {name}")
    data, _, _ = load_daily()
    hourly, _ = load_hourly(data)
    sources, overlap, _ = extend(data, hourly)
    state, atr = features(data), atr_history(data)
    configs = [("none", None, None)]
    configs += [(f"{scope}_{int(value * 100)}pct", scope, value)
                for scope in ("position_pct", "portfolio_pct") for value in (.02, .04, .08)]
    configs += [(f"position_atr_{value}", "position_atr", value) for value in (2, 3)]
    results = {}
    for name, scope, distance in configs:
        results[name] = {}
        for period, dates in PERIODS.items():
            results[name][period] = {}
            for cost_name, cost in (("base", .001), ("stress", .0015), ("double_stress", .003)):
                stop = TrailingStop(scope, distance, atr) if scope else None
                m = evaluate(hourly, data["fundingRate"], state, frozen["rule"], *dates, cost, trailing=stop)
                results[name][period][cost_name] = m
        m = results[name]["combined"]["stress"]
        print(f"{name}: return={m['return_pct']:.3f}% dd={m['max_drawdown_pct']:.3f}% "
              f"stops={m['stop_count']} months={m['positive_months']}/{m['months']} cash={m['cash_time_pct']:.2f}%", flush=True)
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "results": results,
              "rule": frozen["rule"], "freeze_sha256": hashlib.sha256(frozen_path.read_bytes()).hexdigest(),
              "protocol_sha256": hashlib.sha256((ROOT / "docs/trailing_stop_protocol_2026-09-26.md").read_bytes()).hexdigest(),
              "source_code_sha256": {name: hashlib.sha256((ROOT / "src/jev_trader" / name).read_bytes()).hexdigest()
                                     for name in ("trailing_stop.py", "trailing_research.py", "broad_execution.py")},
              "rest_source_hashes": [r["sha256"] for r in sources], "overlap": overlap,
              "deployable": False, "limits": ["Retrospective grid; no independent prospective confirmation.",
                  "Position stops use prior completed hourly extrema; exact touch fills plus stated costs remain a liquidity assumption.",
                  "Gaps execute at the observed worse open; losses can exceed the stop distance.",
                  "Portfolio stops monitor observed hourly openings, not a reconstructed simultaneous intrahour equity curve.",
                  "Stopping an individual leg can change beta and net exposure; reentry waits for a later weekly signal."]}
    (RESULTS / "trailing_research.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    run()
