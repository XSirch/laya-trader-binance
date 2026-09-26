"""Anchor the current read-only observation chain in versioned evidence."""

import hashlib
import json

from jev_trader.cli import ROOT, RESULTS
from jev_trader.forward_observer import read_chain


if __name__ == "__main__":
    path = RESULTS / "forward_observer/observations.jsonl"
    records = read_chain(path)
    if not records:
        raise ValueError("no observed captures")
    summary = {"observations": records, "ledger_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
               "status": "acquisition_verified_only", "deployable": False,
               "paper_returns_available": False, "continuous_service_running": False}
    target = ROOT / "docs/forward_observer_2026-09-26.json"
    target.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"anchored {len(records)} observations")
