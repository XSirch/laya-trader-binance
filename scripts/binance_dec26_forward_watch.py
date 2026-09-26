"""Read-only, fixed-schedule public-book observation for December delivery basis."""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from binance_dec26_forward_quote import BASES, ROOT, TARGETS, collect


SAMPLES = 12
INTERVAL_SECONDS = 60
MIN_PASSING_SAMPLES = 10
PROTOCOL = "docs/binance_dec26_forward_watch_protocol.md"


def main() -> None:
    started = datetime.now(timezone.utc)
    run_id = started.strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = ROOT / "outputs" / "binance_dec26_forward_watch" / run_id
    run_dir.mkdir(parents=True)
    raw_path = run_dir / "samples.jsonl"
    schedule_start = time.monotonic()
    summaries = []
    with raw_path.open("x", encoding="utf-8", newline="\n") as raw:
        for index in range(SAMPLES):
            remaining = schedule_start + index * INTERVAL_SECONDS - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            print(f"sample {index + 1}/{SAMPLES} started", flush=True)
            report = collect()
            report["observation_index"] = index + 1
            report["scheduled_offset_seconds"] = index * INTERVAL_SECONDS
            raw.write(json.dumps(report, separators=(",", ":")) + "\n")
            raw.flush()
            os.fsync(raw.fileno())
            row = {
                "index": index + 1,
                "started_utc": report["started_utc"],
                "finished_utc": report["finished_utc"],
                "full_gate": report["both_coins_both_sizes_qualify"],
                "legs": {},
            }
            for base in BASES:
                result = report["results"][base]
                for size in TARGETS:
                    leg = next((item for item in result.get("sizes", [])
                                if item["intended_spot_notional"] == size), None)
                    row["legs"][f"{base}_{size}"] = {
                        "status": leg["status"] if leg else result["status"],
                        "timely": result.get("timely_under_protocol", False),
                        "annualized_conditional_return": (
                            leg.get("annualized_conditional_return_on_reserved_capital")
                            if leg else None),
                        "qualifies": (leg["qualifies_for_longer_forward_observation"]
                                      if leg else False),
                    }
            summaries.append(row)
            print(f"sample {index + 1}/{SAMPLES} full_gate={row['full_gate']}", flush=True)

    digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    passing = sum(row["full_gate"] for row in summaries)
    summary = {
        "protocol": PROTOCOL,
        "run_id": run_id,
        "scheduled_samples": SAMPLES,
        "interval_seconds": INTERVAL_SECONDS,
        "minimum_passing_samples": MIN_PASSING_SAMPLES,
        "passing_full_gate_samples": passing,
        "stability_gate": passing >= MIN_PASSING_SAMPLES,
        "raw_sha256": digest,
        "samples": summaries,
        "limits": "Adjacent quotes are correlated and conditional; no orders or realized returns",
    }
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print("passing full gate", passing, "/", SAMPLES, flush=True)
    print("saved", summary_path, "raw SHA256", digest, flush=True)


if __name__ == "__main__":
    main()
