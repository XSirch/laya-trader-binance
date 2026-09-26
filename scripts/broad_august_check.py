"""Run the frozen candidate on previously unevaluated August archive hours."""

import hashlib
import json
from datetime import datetime, timezone

from jev_trader.broad_data import load as load_daily
from jev_trader.broad_hourly import load as load_hourly
from jev_trader.broad_execution import evaluate
from jev_trader.broad_research import features
from jev_trader.cli import ROOT, RESULTS


if __name__ == "__main__":
    path = ROOT / "docs/broad_candidate_freeze_2026-09-26.json"
    frozen = json.loads(path.read_text(encoding="utf-8"))
    for name, expected in frozen["source_code_sha256"].items():
        if hashlib.sha256((ROOT / "src/jev_trader" / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"frozen source changed: {name}")
    data, _, _ = load_daily()
    hourly, sources = load_hourly(data)
    states = features(data)
    # August archives end at 23:00 UTC Aug 31. Exit at that observed open;
    # do not invent the September 1 opening price.
    period = ["2026-08-01", "2026-08-31T23:00:00"]
    results = {}
    for cost in frozen["costs_per_side"]:
        result = evaluate(hourly, data["fundingRate"], states, frozen["rule"], *period, cost, 1)
        results[str(cost)] = result
        print(f"August cost={cost}: return={result['return_pct']:.4f}% "
              f"drawdown={result['max_drawdown_pct']:.4f}%", flush=True)
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "period": period,
              "freeze_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "results": results, "deployable": False,
              "design": "Frozen 1h execution delay; August evaluated after candidate freeze, no retuning.",
              "limits": ["One retrospective month cannot establish consistency or prospective performance.",
                         "Final hour omitted because September opening price is not in August archives."]}
    (RESULTS / "broad_august.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
