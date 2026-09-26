"""Bounded, read-only BTC March 2027 COIN-M forward quote observation."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from binance_coinm_delivery_universe_screen import COIN_API, evaluate
from binance_dec26_forward_quote import ROOT, SPOT_API, read_public, utc_now


PROTOCOL = "docs/binance_coinm_btc_mar_forward_watch_protocol.md"
SAMPLES = 12
INTERVAL_SECONDS = 30 * 60
MAX_START_DELAY_SECONDS = 2 * 60
MIN_PASSING_SAMPLES = 10
CONTRACT = "BTCUSD_270326"
SPOT = "BTCUSDT"


def collect() -> dict:
    started = utc_now()
    sources: dict = {}
    sources["spot_metadata"] = read_public(SPOT_API, "/api/v3/exchangeInfo", {
        "symbol": SPOT,
    })
    sources["future_metadata"] = read_public(COIN_API, "/dapi/v1/exchangeInfo")
    with ThreadPoolExecutor(max_workers=2) as pool:
        spot_task = pool.submit(read_public, SPOT_API, "/api/v3/depth", {
            "symbol": SPOT, "limit": 100,
        })
        future_task = pool.submit(read_public, COIN_API, "/dapi/v1/depth", {
            "symbol": CONTRACT, "limit": 100,
        })
        sources["spot_book"], sources["future_book"] = (
            spot_task.result(), future_task.result())
    sources["future_clock"] = read_public(COIN_API, "/dapi/v1/time")
    try:
        result = evaluate(
            "BTC", "270326", "NEXT_QUARTER",
            sources["spot_metadata"], sources["future_metadata"],
            sources["spot_book"], sources["future_book"],
            sources["future_clock"],
        )
    except (ValueError, TypeError, KeyError, IndexError,
            ArithmeticError) as error:
        result = {
            "symbol": CONTRACT, "status": "evaluation error",
            "reason": str(error), "sizes": [], "both_sizes_qualify": False,
        }
    return {
        "started_utc": started, "finished_utc": utc_now(),
        "sources": sources, "result": result,
    }


def write_atomic(path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    started = datetime.now(timezone.utc)
    run_id = started.strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = ROOT / "outputs" / "binance_coinm_btc_mar_forward_watch" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    raw_path = run_dir / "samples.jsonl"
    progress_path = run_dir / "progress.json"
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    schedule_start = time.monotonic()
    run_info = {
        "protocol": PROTOCOL,
        "protocol_commit": commit,
        "run_id": run_id,
        "process_id": os.getpid(),
        "started_utc": started.isoformat(),
        "expected_last_start_utc": (
            started + timedelta(seconds=(SAMPLES - 1) * INTERVAL_SECONDS)
        ).isoformat(),
        "scheduled_samples": SAMPLES,
        "interval_seconds": INTERVAL_SECONDS,
        "maximum_start_delay_seconds": MAX_START_DELAY_SECONDS,
        "minimum_passing_samples": MIN_PASSING_SAMPLES,
        "completed_samples": 0,
        "passing_samples": 0,
        "status": "running",
    }
    write_atomic(progress_path, run_info)
    print("run", run_id, "pid", os.getpid(), flush=True)
    outcomes = []
    with raw_path.open("x", encoding="utf-8", newline="\n") as raw:
        for index in range(SAMPLES):
            due = schedule_start + index * INTERVAL_SECONDS
            remaining = due - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            delay = max(0.0, time.monotonic() - due)
            if delay > MAX_START_DELAY_SECONDS:
                sample = {
                    "status": "missed scheduled start",
                    "observed_utc": utc_now(),
                    "start_delay_seconds": delay,
                }
                outcome = {"index": index + 1, "status": sample["status"],
                           "both_sizes_qualify": False, "sizes": []}
            else:
                try:
                    sample = collect()
                    result = sample["result"]
                    outcome = {
                        "index": index + 1,
                        "status": result["status"],
                        "started_utc": sample["started_utc"],
                        "finished_utc": sample["finished_utc"],
                        "timely": result.get("timely_under_protocol", False),
                        "both_sizes_qualify": result.get(
                            "both_sizes_qualify", False),
                        "sizes": [{
                            "intended_spot_notional": row["intended_spot_notional"],
                            "status": row["status"],
                            "conditional_net_cash": row.get("conditional_net_cash"),
                            "annualized_conditional_return": row.get(
                                "annualized_conditional_return_on_reserved_capital"),
                        } for row in result.get("sizes", [])],
                    }
                except Exception as error:
                    sample = {
                        "status": "collector error",
                        "observed_utc": utc_now(),
                        "reason": str(error),
                        "traceback": traceback.format_exc(),
                    }
                    outcome = {"index": index + 1, "status": sample["status"],
                               "both_sizes_qualify": False, "sizes": []}
            sample["observation_index"] = index + 1
            sample["scheduled_offset_seconds"] = index * INTERVAL_SECONDS
            sample["start_delay_seconds"] = delay
            raw.write(json.dumps(sample, separators=(",", ":")) + "\n")
            raw.flush()
            os.fsync(raw.fileno())
            outcomes.append(outcome)
            run_info["completed_samples"] = len(outcomes)
            run_info["passing_samples"] = sum(
                bool(item["both_sizes_qualify"]) for item in outcomes)
            run_info["last_sample"] = outcome
            run_info["last_update_utc"] = utc_now()
            write_atomic(progress_path, run_info)
            print("sample", index + 1, "/", SAMPLES,
                  "status", outcome["status"],
                  "gate", outcome["both_sizes_qualify"], flush=True)

    digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    summary = {
        **run_info,
        "status": "complete",
        "finished_utc": utc_now(),
        "raw_sha256": digest,
        "stability_gate": run_info["passing_samples"] >= MIN_PASSING_SAMPLES,
        "samples": outcomes,
        "limits": "Public conditional quotes are not hedged fills or realized profit; no orders",
    }
    write_atomic(run_dir / "summary.json", summary)
    run_info["status"] = "complete"
    run_info["finished_utc"] = summary["finished_utc"]
    run_info["raw_sha256"] = digest
    run_info["stability_gate"] = summary["stability_gate"]
    write_atomic(progress_path, run_info)
    print("complete", run_id, "passing", run_info["passing_samples"],
          "raw_sha256", digest, flush=True)


if __name__ == "__main__":
    main()
