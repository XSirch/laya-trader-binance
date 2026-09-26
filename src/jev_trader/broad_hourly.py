"""Acquire hourly execution evidence for the frozen broad-cohort candidate."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from .binance_data import HOUR_MS, months, parse_archive
from .broad_data import CACHE, listing
from .derivatives_data import fetch


def download(first="2024-01", last="2026-08", manifest_name="hourly_manifest.json"):
    cohort = json.loads((CACHE / "cohort.json").read_text(encoding="utf-8"))
    jobs = []
    for symbol in cohort["selected"]:
        for kind in ("klines", "markPriceKlines"):
            prefix = f"data/futures/um/monthly/{kind}/{symbol}/1h/"
            keys = set(listing(prefix))
            for month in months(first, last):
                filename = f"{symbol}-1h-{month}.zip"
                if prefix + filename in keys:
                    jobs.append((kind, symbol, month))
    records = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(fetch, *job) for job in jobs]
        for i, future in enumerate(as_completed(futures), 1):
            records.append(future.result())
            if i % 100 == 0 or i == len(jobs):
                print(f"verified hourly execution archives {i}/{len(jobs)}", flush=True)
    records.sort(key=lambda row: (row["kind"], row["symbol"], row["month"]))
    (CACHE / manifest_name).write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    return records


def load(daily, manifest_name="hourly_manifest.json"):
    records = json.loads((CACHE / manifest_name).read_text(encoding="utf-8"))
    output = {kind: {s: {} for s in daily["klines"]} for kind in ("klines", "markPriceKlines")}
    for record in records:
        path = Path(record["path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError(f"changed hourly source: {path}")
        lookup = output[record["kind"]][record["symbol"]]
        for bar in parse_archive(path, max_gap_hours=24 * 40):
            if bar.open_ms in lookup:
                raise ValueError("duplicate hourly observation")
            lookup[bar.open_ms] = bar
    jobs = set()
    for symbol, lookup in output["klines"].items():
        # Exclude dead-contract placeholder tails, not genuine internal zero-trade hours.
        live = [t for t, b in lookup.items() if b.volume > 0 and b.trades > 0]
        first, last = min(live), max(live)
        output["klines"][symbol] = {t: b for t, b in lookup.items() if first <= t <= last}
        for kind in output:
            missing = set(range(first, last + HOUR_MS, HOUR_MS)) - set(output[kind][symbol])
            for timestamp in missing:
                day = datetime.fromtimestamp(timestamp / 1000, timezone.utc).strftime("%Y-%m-%d")
                jobs.add((kind, symbol, day))
    supplements = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch, kind, symbol, day, "daily") for kind, symbol, day in sorted(jobs)]
        for future in as_completed(futures):
            record = future.result()
            supplements.append(record)
            lookup = output[record["kind"]][record["symbol"]]
            for bar in parse_archive(Path(record["path"])):
                lookup.setdefault(bar.open_ms, bar)
    for symbol, lookup in output["klines"].items():
        live = [t for t, b in lookup.items() if b.volume > 0 and b.trades > 0]
        first, last = min(live), max(live)
        output["klines"][symbol] = {t: b for t, b in lookup.items() if first <= t <= last}
        expected = set(range(first, last + HOUR_MS, HOUR_MS))
        for kind in output:
            if expected - set(output[kind][symbol]):
                raise ValueError(f"unresolved hourly calendar: {kind} {symbol}")
    supplements.sort(key=lambda r: (r["kind"], r["symbol"], r["month"]))
    supplements_name = manifest_name.replace("manifest", "supplements")
    (CACHE / supplements_name).write_text(json.dumps(supplements, indent=2) + "\n", encoding="utf-8")
    return output, records + supplements


if __name__ == "__main__":
    download()
