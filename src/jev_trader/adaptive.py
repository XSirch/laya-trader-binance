"""Causal expert mixtures: use earlier realized net returns, with cash as an expert."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from .cli import RESULTS
from .derivatives_data import load
from .directional import DAY_MS, HOUR_MS, PERIODS, evaluate, passed, signals

POLICIES = (("blend_63d", 63, False), ("blend_126d", 126, False),
            ("abstain_63d", 63, True), ("abstain_126d", 126, True))


def build_adaptive(experts, histories, days, abstain):
    names = sorted(experts)
    symbols = sorted(experts[names[0]])
    timestamps = sorted(experts[names[0]][symbols[0]])
    returns = {}
    for name, history in histories.items():
        ordered = sorted((int(t), value) for t, value in history.items())
        returns[name] = {t: math.log(value / previous) for (_, previous), (t, value)
                         in zip(ordered, ordered[1:])}
    targets = {s: {} for s in symbols}
    audit = []
    for timestamp in timestamps:
        last_known = timestamp - HOUR_MS  # midnight valuation, execution at 01:00
        scores = {}
        for name in names:
            observations = [returns[name].get(last_known - k * DAY_MS) for k in range(days)]
            if any(v is None for v in observations):
                continue
            scale = math.sqrt(sum(v * v for v in observations))
            scores[name] = sum(observations) / scale if scale else 0.0
        # Cash has score zero. Softmax uses a pre-fixed temperature and no
        # parameter tuning on evaluation windows. Cap logits for numeric safety.
        numerators = {name: math.exp(max(-10, min(10, 2 * score))) for name, score in scores.items()}
        if abstain:
            numerators = {name: value for name, value in numerators.items() if scores[name] >= 1.0}
        denominator = 1 + sum(numerators.values())
        weights = {name: value / denominator for name, value in numerators.items()}
        for s in symbols:
            targets[s][timestamp] = sum(weight * experts[name][s][timestamp] for name, weight in weights.items())
        if weights:
            audit.append({"execution_ms": timestamp, "latest_observed_equity_ms": last_known,
                          "cash_weight": 1 / denominator, "weights": weights})
    return targets, audit


def run():
    derivatives, _ = load()
    experts = signals(derivatives["klines"])
    histories = {name: evaluate(derivatives, target, "2023-11-01", "2026-08-01", .0015)["daily_equity"]
                 for name, target in experts.items()}
    results, audits = {}, {}
    for name, days, abstain in POLICIES:
        target, audit = build_adaptive(experts, histories, days, abstain)
        audits[name] = audit
        results[name] = {period: {cost: evaluate(derivatives, target, *dates, value)
                           for cost, value in (("base", .001), ("stress", .0015))}
                         for period, dates in PERIODS.items()}
        results[name]["all_later_gates"] = all(passed(results[name][p]["stress"])
                                              for p in ("calibration", "validation", "confirmation"))
        m = results[name]["combined"]["stress"]
        print(f"{name}: return={m['return_pct']:.2f}% dd={m['max_drawdown_pct']:.2f}% "
              f"months={m['positive_months']}/{m['months']} gates={results[name]['all_later_gates']}", flush=True)
    selected = max(results, key=lambda name: (passed(results[name]["development"]["stress"]),
                                              results[name]["development"]["stress"]["return_pct"]))
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "selected_on_2024": selected,
              "policies": POLICIES, "candidates": results, "deployable": False,
              "source_code_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                     for name in ("adaptive.py", "directional.py", "derivatives_data.py", "binance_data.py")},
              "limits": ["Same reused history; adaptation is causal but not prospective evidence.",
                         "126-day learner is initially in cash until enough history exists.",
                         "Expert weighting is global across the four assets, not tuned per asset."]}
    (RESULTS / "adaptive_research.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (RESULTS / "adaptive_weights.json").write_text(json.dumps(audits, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"selected on development: {selected}", flush=True)
    return report


if __name__ == "__main__":
    run()
