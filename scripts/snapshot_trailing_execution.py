"""Save compact evidence with matched no-stop comparisons."""

import hashlib
import json

from snapshot_trailing import ROOT, compact


if __name__ == "__main__":
    source = ROOT / "results/trailing_execution.json"
    report = json.loads(source.read_text(encoding="utf-8"))
    summary = compact(report)
    summary["full_report_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    comparisons = {}
    for name, periods in report["results"].items():
        if not name.startswith("delay"):
            continue
        _, entry, cost, _ = name.split("_")
        reference = f"none_{entry}_{cost}"
        comparisons[name] = {
            "reference": reference,
            "periods": {
                period: {
                    metric + "_difference_pp": row[metric] - report["results"][reference][period][metric]
                    for metric in ("return_pct", "max_drawdown_pct")
                }
                for period, row in periods.items()
            },
        }
    summary["matched_comparisons"] = comparisons
    target = ROOT / "docs/trailing_execution_2026-09-26.json"
    target.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(target)
