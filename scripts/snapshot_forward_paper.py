"""Anchor the explicitly named, current paper series without inventing results."""

import hashlib
import json

from jev_trader.cli import ROOT, RESULTS
from jev_trader.forward_observer import read_chain


if __name__ == "__main__":
    root = RESULTS / "forward_paper_v2"
    path = root / "ledger.jsonl"
    rows = read_chain(path)
    latest = rows[-1]
    market_rows = read_chain(RESULTS / "forward_observer/observations.jsonl")
    signal_path = root / latest["signal_file"]
    if hashlib.sha256(signal_path.read_bytes()).hexdigest() != latest["signal_file_sha256"]:
        raise ValueError("signal attachment hash changed")
    summary = {"series": root.name, "captures": len(rows), "first_record": rows[0], "latest_record": latest,
               "latest_signal": json.loads(signal_path.read_text(encoding="utf-8")),
               "ledger_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
               "deployable": False, "continuous_service_running": False,
               "paper_fills": {name: sum(e["type"] == "paper_fill" for e in account["events"])
                               for name, account in latest["accounts"].items()},
               "rejected_market_captures_since_initialization": [r for r in market_rows
                   if r["server_time_ms"] >= rows[0]["server_time_ms"] and r["rejected_quotes"]],
               "superseded_series": {"path": "results/forward_paper", "reason": "Initial flat-only engineering check before funding and trailing-peak review fixes; preserved without deletion."}}
    target = ROOT / "docs/forward_paper_2026-09-26.json"
    target.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"captures": len(rows), "status": latest["status"], "paper_fills": summary["paper_fills"]}))
