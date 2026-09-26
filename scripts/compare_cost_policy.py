"""Compare unchanged forecasts under weekly targets and cost-aware decisions."""

import hashlib
import json
from pathlib import Path

from jev_trader.statistics import family_bootstrap

ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    curves, development, comparisons, sources, invalid = {}, {}, {}, {}, []
    for family in ("economic", "technical", "nonlinear"):
        stem = "broad_prediction" if family == "economic" else f"broad_{family}_prediction"
        stem += "_settlement_bounds"
        pair = {}
        for policy, suffix in (("weekly", ""), ("cost_aware", "_cost_policy")):
            path = ROOT / "results" / f"{stem}{suffix}.json"
            pair[policy] = json.loads(path.read_text(encoding="utf-8"))
            sources[f"{family}/{policy}"] = {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        if (pair["weekly"]["training_audits"] != pair["cost_aware"]["training_audits"] or
                pair["weekly"]["prediction_scores"] != pair["cost_aware"]["prediction_scores"]):
            raise ValueError(f"forecast evidence differs between policies: {family}")
        for name in pair["weekly"]["results"]:
            if name == "zero":
                curves.setdefault("cash", pair["weekly"]["results"][name]["combined"]["stress"]["daily_equity"])
                development["cash"] = 0
                continue
            key = f"{family}/{name}"
            comparison = {}
            for policy in pair:
                periods = pair[policy]["results"][name]
                row = periods["combined"]["stress"]
                variant = f"{key}/{policy}"
                if row["status"] not in ("complete", "bounded_settlement_scenario"):
                    invalid.append(variant)
                    comparison[policy] = row
                    continue
                curves[variant] = row["daily_equity"]
                development[variant] = periods["development"]["stress"]["return_pct"]
                comparison[policy] = {k: v for k, v in row.items() if k not in ("daily_equity", "execution_audit")}
                comparison[policy]["period_returns_pct"] = {
                    p: metrics["stress"].get("return_pct") for p, metrics in periods.items()}
                if policy == "cost_aware":
                    actions = {}
                    maximum_error = 0.0
                    for audit in row["execution_audit"]:
                        decision = audit["decision"]
                        actions[decision["chosen"]] = actions.get(decision["chosen"], 0) + 1
                        maximum_error = max(maximum_error, abs(audit["actual_cost_fraction"] - decision["expected_cost_fraction"]))
                    comparison[policy]["action_counts"] = actions
                    comparison[policy]["max_cost_accounting_error"] = maximum_error
                    if maximum_error > 1e-10:
                        raise ValueError("forecast cost does not reconcile with execution accounting")
            comparisons[key] = comparison
    selected = max(development, key=development.get)
    diagnostic = (family_bootstrap(curves, selected) if not invalid else
                  {"status": "incomplete_joint_family", "invalid_variants": invalid})
    report = {"sources": sources, "comparisons": comparisons, "forecasts_identical_verified": True,
              "selected_on_development_including_cash": selected, "development_returns_pct": development,
              "statistical_diagnostic": diagnostic, "deployable": False,
              "limits": ["Retrospective decision-policy hypothesis introduced after inspecting prior outcomes.",
                         "Statistics are conditional on settlement bounds, not actual settlement transaction records.",
                         "37 members cover these policies and forecast families, not all previous research attempts."]}
    target = ROOT / "docs/cost_policy_comparison_2026-09-26.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("selected", selected)
    print(json.dumps(diagnostic, indent=2))
    for name, pair in comparisons.items():
        row = pair["cost_aware"]
        print(name, row.get("return_pct"), "cash", row.get("cash_time_pct"), "actions", row.get("action_counts"))
