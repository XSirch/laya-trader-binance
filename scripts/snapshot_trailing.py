"""Save compact trailing evidence and its selection-adjusted diagnostic."""

import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

from jev_trader.statistics import family_bootstrap

ROOT = Path(__file__).resolve().parents[1]


def compact(value):
    if isinstance(value, dict):
        result = {k: compact(v) for k, v in value.items() if k not in ("daily_equity", "execution_audit", "stop_events")}
        if "stop_events" in value:
            result["distinct_hours_with_stop"] = len({r["timestamp_ms"] for r in value["stop_events"]})
        return result
    if isinstance(value, list):
        return [compact(v) for v in value]
    return value


if __name__ == "__main__":
    source = ROOT / "results/trailing_research.json"
    report = json.loads(source.read_text(encoding="utf-8"))
    curves = {name: periods["combined"]["stress"]["daily_equity"] for name, periods in report["results"].items()}
    summary = compact(report)
    summary["full_report_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    summary["statistical_diagnostic"] = family_bootstrap(curves, "portfolio_pct_4pct")
    summary["selection_status"] = "4% portfolio stop highlighted AFTER comparing this retrospective grid; not prospective selection."
    summary["statistical_diagnostic"]["limits"].append("Nine trailing variants only; does not adjust the entire prior research history.")
    target = ROOT / "docs/trailing_research_2026-09-26.json"
    target.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    frozen = ROOT / "docs/trailing_candidate_freeze_2026-09-26.json"
    if not frozen.exists():
        candidate = {"created_utc": datetime.now(timezone.utc).isoformat(),
                     "status": "Exploratory risk-control candidate fixed after this retrospective comparison; not approved for trading.",
                     "base_rule": report["rule"], "scope": "portfolio_pct", "distance": .04,
                     "observation": "Hourly opens; all legs exit together; next later weekly signal permits a fresh cycle.",
                     "base_freeze_sha256": report["freeze_sha256"],
                     "source_code_sha256": report["source_code_sha256"],
                     "full_report_sha256": summary["full_report_sha256"],
                     "latest_evaluated_end_utc": "2026-09-26T00:00:00Z", "deployable": False,
                     "limits": ["Selected after evaluating nine trailing variants on previously inspected history.",
                                "Improved aggregate drawdown, but worsened the independent August-September window.",
                                "Further execution-delay sensitivity and chronologically new evidence remain necessary."]}
        frozen.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(target)
