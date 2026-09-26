"""Post-screen diversification hypothesis; selection uses development data only."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .broad_data import load
from .broad_research import PERIODS, evaluate, features, passed
from .cli import RESULTS
from .statistics import family_bootstrap


def select_members(candidates):
    representatives = {}
    for name, periods in candidates.items():
        metric = periods["development"]["stress"]
        if metric["unresolved_exits"] or metric["margin_stress_failures"] or metric["return_pct"] <= 0:
            continue
        family = name.removesuffix("_betahedged")
        old = representatives.get(family)
        if old is None or metric["return_pct"] > candidates[old]["development"]["stress"]["return_pct"]:
            representatives[family] = name
    return sorted(representatives.values(), key=lambda name:
                  (-candidates[name]["development"]["stress"]["return_pct"], name))[:2]


def run():
    source = RESULTS / "broad_research.json"
    prior = json.loads(source.read_text(encoding="utf-8"))
    members = select_members(prior["candidates"])
    if len(members) != 2:
        raise ValueError("two positive distinct development families required")
    rule = "blend:" + "+".join(members)
    data, _, _ = load()
    state = features(data)
    results = {period: {cost: evaluate(data, state, rule, *dates, value)
                        for cost, value in (("base", .001), ("stress", .0015), ("double_stress", .003))}
               for period, dates in PERIODS.items()}
    for period, values in results.items():
        m = values["stress"]
        print(f"{period}: {m['return_pct']:.2f}% dd={m['max_drawdown_pct']:.2f}% "
              f"months={m['positive_months']}/{m['months']} pass={passed(m)}", flush=True)
    equities = {name: p["combined"]["stress"]["daily_equity"] for name, p in prior["candidates"].items()}
    equities[rule] = results["combined"]["stress"]["daily_equity"]
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "members": members,
              "weights": [0.5, 0.5], "rule": rule,
              "selection_rule": "Top two distinct positive-return economic families on 2022-2023, choosing each family's best variant first.",
              "design_status": "Hypothesis introduced AFTER viewing broad screen; not preregistered.",
              "results": results,
              "all_historical_gates": all(passed(values["stress"]) for p, values in results.items() if p != "combined"),
              "statistical_diagnostic": family_bootstrap(equities, rule), "deployable": False,
              "source_report_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "source_code_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                     for name in ("broad_combo.py", "broad_research.py", "broad_data.py", "statistics.py")},
              "limits": ["Researcher saw prior later-window results before creating this combination hypothesis.",
                         "Mechanical member selection sees development only; that does not remove research-level selection bias.",
                         "Daily screen requires hourly execution and genuinely new chronological confirmation."]}
    (RESULTS / "broad_combo_research.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"members={members}; all_historical_gates={report['all_historical_gates']}", flush=True)
    return report


if __name__ == "__main__":
    run()
