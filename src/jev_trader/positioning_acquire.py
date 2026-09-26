"""Fixed, resumable weekly data acquisition; contains no financial replay."""

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

from .metrics_catalog import load_catalog, weekly_candidates, calendar
from .metrics_fetch import fetch


ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data/binance/positioning"
PROTOCOL = ROOT / "docs/positioning_acquisition_protocol_2026-09-26.md"
CONFIG = {"schema_version": 1, "first_friday": "2021-12-03", "last_friday": "2026-09-18",
          "maximum_workers": 4, "minimum_daily_slots": 284, "minimum_positive_values_per_field": 284,
          "require_final_slot": "23:55:00", "week_lags": [0, 1, 4], "additional_features": 8,
          "historical_point_in_time_verified": False, "orders_enabled": False, "jev_enabled": False}
CODE = ("metrics_catalog.py", "metrics_fetch.py", "positioning_metrics.py",
        "positioning_features.py", "positioning_acquire.py")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+"\n").encode("utf-8")


def _write(path, value):
    temporary = path.with_name(path.name+".part")
    temporary.write_bytes(encoded(value))
    temporary.replace(path)


def anchors():
    blocks = re.findall(r"```json\s*\n(.*?)\n```", PROTOCOL.read_text(encoding="utf-8"), re.DOTALL)
    if len(blocks) != 1 or json.loads(blocks[0]) != CONFIG:
        raise ValueError("positioning acquisition protocol differs from fixed configuration")
    return {"protocol_sha256": sha(PROTOCOL),
            "code_sha256": {name: sha(ROOT/"src/jev_trader"/name) for name in CODE},
            "cohort_sha256": sha(ROOT/"data/binance/broad/cohort.json"),
            "lifecycle_sha256": sha(ROOT/"docs/contract_lifecycle_sources_2026-09-26.json"),
            "source_inventory_sha256": sha(ROOT/"docs/derivatives_metrics_inventory_2026-09-26.md")}


def prepare():
    frozen = anchors()
    path = CACHE/"acquisition_plan.json"
    existing = None
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing["anchors"] != frozen or existing["config"] != CONFIG:
            raise ValueError("existing acquisition plan is frozen; explicit new revision required")
        for symbol, expected in existing["catalog_sha256"].items():
            if sha(ROOT/"data/binance/metrics_catalog"/symbol/"catalog.json") != expected:
                raise ValueError("catalog changed after plan freeze")
    cohort = json.loads((ROOT/"data/binance/broad/cohort.json").read_text(encoding="utf-8"))["selected"]
    reference = json.loads((ROOT/"docs/broad_candidate_freeze_2026-09-26.json").read_text(encoding="utf-8"))["cohort"]
    if cohort != reference:
        raise ValueError("historical cohort changed")
    events = json.loads((ROOT/"docs/contract_lifecycle_sources_2026-09-26.json").read_text(encoding="utf-8"))["events"]
    settlements = {event["symbol"]: event["automatic_settlement_utc"][:10] for event in events}
    jobs, absent, excluded, catalogs = [], [], [], {}
    days = calendar(CONFIG["first_friday"], CONFIG["last_friday"], 4)
    for symbol in cohort:
        catalog_path = ROOT/"data/binance/metrics_catalog"/symbol/"catalog.json"
        if not catalog_path.exists():
            raise ValueError("complete metadata inventory required before acquisition")
        def offline(url):
            raise ValueError("plan requires preserved catalog pages; network is disabled")
        catalog = load_catalog(symbol, fetcher=offline)
        catalogs[symbol] = sha(catalog_path)
        candidates = {row["date"]: row for row in weekly_candidates(catalog, days[0], days[-1])}
        for day in days:
            if symbol in settlements and day > settlements[symbol]:
                excluded.append({"symbol": symbol, "day": day, "reason": "after_automatic_settlement",
                                 "pair_exists": day in candidates})
            elif day not in candidates:
                absent.append({"symbol": symbol, "day": day, "reason": "catalog_pair_missing"})
            else:
                row = candidates[day]
                jobs.append({"symbol": symbol, "day": day, "zip": row["zip"], "checksum": row["checksum"]})
    jobs.sort(key=lambda row: (row["day"], row["symbol"]))
    plan = {"created_utc": existing["created_utc"] if existing else datetime.now(timezone.utc).isoformat(),
            "anchors": frozen, "config": CONFIG,
            "cohort": cohort, "catalog_sha256": catalogs, "expected_fridays_per_symbol": len(days),
            "jobs": jobs, "missing_pairs": absent, "post_settlement_exclusions": excluded,
            "historical_point_in_time_verified": False}
    CACHE.mkdir(parents=True, exist_ok=True)
    if existing is not None:
        if existing != plan:
            raise ValueError("acquisition plan differs from preserved catalog and fixed calendar")
        return existing
    with path.open("xb") as handle:
        handle.write(encoded(plan))
    return plan


def record_path(job):
    return CACHE/job["symbol"]/(Path(job["zip"]["key"]).name+".record.json")


def run(download=False, limit=None, workers=4):
    if isinstance(workers, bool) or workers not in range(1, 5):
        raise ValueError("workers must be from one to four")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
        raise ValueError("limit must be a positive integer")
    CACHE.mkdir(parents=True, exist_ok=True)
    lock = CACHE/"acquisition.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(descriptor, str(os.getpid()).encode())
    os.close(descriptor)
    try:
        started = time.perf_counter()
        plan = prepare()
        print("Plan:", len(plan["jobs"]), "paired jobs; missing", len(plan["missing_pairs"]),
              "post-settlement excluded", len(plan["post_settlement_exclusions"]), flush=True)
        if not download:
            return plan
        cached = [job for job in plan["jobs"] if record_path(job).exists()]
        pending = [job for job in plan["jobs"] if not record_path(job).exists()]
        chosen = cached + (pending if limit is None else pending[:limit])
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")+"-"+uuid.uuid4().hex[:8]
        folder = CACHE/"runs"/run_id
        folder.mkdir(parents=True)
        status = {"run_id": run_id, "pid": os.getpid(), "phase": "acquiring",
                  "plan_sha256": sha(CACHE/"acquisition_plan.json"), "planned": len(plan["jobs"]),
                  "selected": len(chosen), "not_selected": len(plan["jobs"])-len(chosen),
                  "complete_records": 0, "usable_snapshots": 0, "cache_hits": 0, "failures": [],
                  "jev_calls": 0, "orders_sent": 0, "historical_point_in_time_verified": False}
        last_update = 0.0
        futures, pending_jobs, stop_submissions = {}, iter(chosen), False
        submitted = 0
        with (folder/"records.jsonl").open("x", encoding="utf-8", newline="\n") as journal:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                def replenish():
                    nonlocal submitted
                    while not stop_submissions and len(futures) < workers:
                        job = next(pending_jobs, None)
                        if job is None:
                            break
                        futures[pool.submit(fetch, job, CACHE)] = job
                        submitted += 1
                replenish()
                while futures:
                    done, _ = wait(futures, return_when=FIRST_COMPLETED)
                    for future in done:
                        job = futures.pop(future)
                        try:
                            result = future.result()
                        except Exception as exc:
                            failure = {"symbol": job["symbol"], "day": job["day"],
                                       "error_type": type(exc).__name__, "error": str(exc)}
                            status["failures"].append(failure)
                            stop_submissions = True
                            journal.write(json.dumps({"status": "failed", **failure}, sort_keys=True)+"\n")
                            print("FAILED; stopping new submissions", failure, flush=True)
                        else:
                            status["complete_records"] += 1
                            status["usable_snapshots"] += int(result["snapshot"]["available"])
                            status["cache_hits"] += int(result["cache_hit"])
                            journal.write(json.dumps({"status": "verified", "symbol": job["symbol"], "day": job["day"],
                                "record_path": result["record_path"], "record_sha256": sha(Path(result["record_path"])),
                                "zip_sha256": result["zip"]["sha256"], "available": result["snapshot"]["available"],
                                "cache_hit": result["cache_hit"]}, sort_keys=True)+"\n")
                        completed = status["complete_records"]+len(status["failures"])
                        if completed % 50 == 0 or time.monotonic()-last_update >= 15 or not futures:
                            journal.flush()
                            status.update(updated_utc=datetime.now(timezone.utc).isoformat(),
                                          elapsed_seconds=time.perf_counter()-started)
                            _write(CACHE/"acquisition_status.json", status)
                            print("Acquisition", completed, "/", len(chosen), "verified", status["complete_records"],
                                  "usable", status["usable_snapshots"], "failures", len(status["failures"]), flush=True)
                            last_update = time.monotonic()
                    replenish()
        if anchors() != plan["anchors"]:
            raise ValueError("acquisition code or protocol changed during run")
        status.update(phase="stopped_after_failure" if stop_submissions else "finished",
                      submitted=submitted, unattempted=len(plan["jobs"])-submitted,
                      elapsed_seconds=time.perf_counter()-started,
                      updated_utc=datetime.now(timezone.utc).isoformat(),
                      all_planned_records_verified=status["complete_records"] == len(plan["jobs"]),
                      records_journal_sha256=sha(folder/"records.jsonl"))
        _write(folder/"summary.json", status)
        _write(CACHE/"acquisition_status.json", status)
        return status
    finally:
        lock.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    run(args.download, args.limit, args.workers)
