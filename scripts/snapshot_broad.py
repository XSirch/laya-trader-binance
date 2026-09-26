"""Preserve daily screening evidence and freeze the next execution experiment."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data/binance/broad"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact(value):
    if isinstance(value, dict):
        return {k: compact(v) for k, v in value.items()
                if k not in ("daily_equity", "execution_audit", "path")}
    if isinstance(value, list):
        return [compact(v) for v in value]
    return value


def save(name, value):
    (ROOT / "docs" / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    for family in ("broad", "broad_combo"):
        report = json.loads((ROOT / "results" / f"{family}_research.json").read_text(encoding="utf-8"))
        save(f"{family}_research_2026-09-26.json", compact(report))
    sources = {}
    for name in ("manifest", "supplements", "hourly_manifest", "cohort", "data_quality", "absent_archives"):
        sources[name] = compact(json.loads((CACHE / f"{name}.json").read_text(encoding="utf-8")))
    save("broad_sources_2026-09-26.json", sources)
    for name in ("broad_execution", "broad_august", "broad_extension"):
        path = ROOT / "results" / f"{name}.json"
        if path.exists():
            save(f"{name}_2026-09-26.json", compact(json.loads(path.read_text(encoding="utf-8"))))
    supplements = CACHE / "hourly_supplements.json"
    if supplements.exists():
        save("broad_hourly_repairs_2026-09-26.json", compact(json.loads(supplements.read_text(encoding="utf-8"))))
    frozen_path = ROOT / "docs/broad_candidate_freeze_2026-09-26.json"
    if not frozen_path.exists():
        combo = json.loads((ROOT / "results/broad_combo_research.json").read_text(encoding="utf-8"))
        save(frozen_path.name, {
            "frozen_utc": datetime.now(timezone.utc).isoformat(),
            "rule": combo["rule"], "members": combo["members"], "weights": combo["weights"],
            "cohort": sources["cohort"]["selected"],
            "design_status": "Post-screen exploratory combination; not an independently preregistered discovery.",
            "rebalance": "Monday 01:00 UTC, signals from completed daily candles through Monday 00:00 UTC",
            "costs_per_side": [0.001, 0.0015, 0.003],
            "delay_sensitivity_hours": [1, 2], "maximum_target_gross": 0.5,
            "historical_execution_window": ["2024-01-01", "2026-08-01"],
            "chronological_extension_window": ["2026-08-01", "2026-09-26"],
            "extension_status": "Not evaluated when frozen; retrospective chronological extension, not prospective proof.",
            "funding": "Hourly adverse mark bounds unless exact settlement marks are verified; no unearned entry funding credits.",
            "missing_held_price": "Fail closed; no assumed settlement or invented fill",
            "deployable": False,
            "source_report_sha256": digest(ROOT / "results/broad_combo_research.json"),
            "source_code_sha256": combo["source_code_sha256"],
            "daily_sources_sha256": digest(CACHE / "manifest.json"),
        })
    print("Daily evidence saved; frozen candidate preserved.")
