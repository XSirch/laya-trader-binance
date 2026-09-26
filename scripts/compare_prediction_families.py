"""Joint dependent-bootstrap diagnostic for all completed forecast families."""

import hashlib
import json
from pathlib import Path

from jev_trader.statistics import family_bootstrap

ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    curves, development, sources = {}, {}, {}
    for family in ("economic", "technical", "nonlinear"):
        stem = "broad_prediction" if family == "economic" else f"broad_{family}_prediction"
        path = ROOT / "results" / f"{stem}_settlement_bounds.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        sources[family] = {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for name, periods in report["results"].items():
            if name == "zero":
                if "cash" not in curves:
                    curves["cash"] = periods["combined"]["stress"]["daily_equity"]
                    development["cash"] = 0
                continue
            row = periods["combined"]["stress"]
            if row["status"] not in ("complete", "bounded_settlement_scenario"):
                raise ValueError("joint family has incomplete execution; do not silently drop it")
            key = f"{family}/{name}"
            curves[key] = row["daily_equity"]
            development[key] = periods["development"]["stress"]["return_pct"]
    selected = max(development, key=development.get)
    diagnostic = family_bootstrap(curves, selected)
    report = {"sources": sources, "development_returns_pct": development,
              "selected_on_development_including_cash": selected,
              "statistical_diagnostic": diagnostic, "deployable": False,
              "limits": ["Conditional on documented settlement price bounds, not observed settlement transactions.",
                         "Contains 18 forecast variants plus cash; does not correct every earlier research hypothesis.",
                         "Families were designed sequentially after inspecting prior outcomes; this is retrospective."]}
    target = ROOT / "docs/prediction_families_comparison_2026-09-26.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(diagnostic, indent=2))
