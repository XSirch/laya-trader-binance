"""Save compact, UTF-8 research evidence without bulky intermediate equity paths."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def compact(value):
    if isinstance(value, dict):
        return {key: compact(item) for key, item in value.items() if key != "daily_equity"}
    if isinstance(value, list):
        return [compact(item) for item in value]
    return value


for family in ("carry", "directional", "adaptive"):
    source = ROOT / "results" / f"{family}_research.json"
    target = ROOT / "docs" / f"{family}_research_2026-09-26.json"
    report = compact(json.loads(source.read_text(encoding="utf-8")))
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(target)

source = ROOT / "data" / "binance" / "futures" / "um"
records = []
for filename in ("manifest.json", "supplemental_manifest.json"):
    for row in json.loads((source / filename).read_text(encoding="utf-8")):
        records.append({key: value for key, value in row.items() if key != "path"})
target = ROOT / "docs" / "derivatives_sources_2026-09-26.json"
target.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"{len(records)} verified derivative sources")
