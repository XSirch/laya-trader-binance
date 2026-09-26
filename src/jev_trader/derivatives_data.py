"""Checksum-verified USD-M futures candles, mark prices and funding history."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .binance_data import (_expected_hash, _read_url, months, parse_archive,
                           spacing_gaps, HOUR_MS)
from .cli import ROOT, SYMBOLS

DATA_ROOT = ROOT / "data" / "binance" / "futures" / "um"
BASE = "https://data.binance.vision/data/futures/um/monthly"


@dataclass(frozen=True)
class Funding:
    timestamp_ms: int
    interval_hours: int
    rate: float


def fetch(kind, symbol, month, frequency="monthly"):
    suffix = f"{symbol}-fundingRate-{month}.zip" if kind == "fundingRate" else f"{symbol}-1h-{month}.zip"
    subpath = f"{kind}/{symbol}/{suffix}" if kind == "fundingRate" else f"{kind}/{symbol}/1h/{suffix}"
    url = f"{BASE.replace('/monthly', '/' + frequency)}/{subpath}"
    path = DATA_ROOT / subpath if frequency == "monthly" else DATA_ROOT / frequency / subpath
    checksum = path.with_suffix(".zip.CHECKSUM")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw_checksum = checksum.read_bytes() if checksum.exists() else _read_url(url + ".CHECKSUM")
    expected = _expected_hash(raw_checksum)
    payload = path.read_bytes() if path.exists() else _read_url(url)
    if hashlib.sha256(payload).hexdigest() != expected:
        raise ValueError(f"checksum mismatch {url}")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        if archive.testzip() is not None:
            raise ValueError(f"CRC mismatch {url}")
    if not path.exists():
        temporary = path.with_suffix(".zip.part")
        temporary.write_bytes(payload)
        temporary.replace(path)
    if not checksum.exists():
        checksum.write_bytes(raw_checksum)
    return {"kind": kind, "symbol": symbol, "month": month, "url": url,
            "path": str(path), "sha256": expected, "bytes": len(payload), "frequency": frequency}


def download(first="2023-01", last="2026-08"):
    jobs = [(kind, symbol, month) for kind in ("klines", "markPriceKlines", "fundingRate")
            for symbol in SYMBOLS for month in months(first, last)]
    records = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch, *job) for job in jobs]
        for i, future in enumerate(as_completed(futures), 1):
            records.append(future.result())
            if i % 25 == 0 or i == len(jobs):
                print(f"verified futures archives {i}/{len(jobs)}", flush=True)
    records.sort(key=lambda row: (row["kind"], row["symbol"], row["month"]))
    (DATA_ROOT / "manifest.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    return records


def parse_funding(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != 1:
            raise ValueError("expected one funding CSV")
        data = archive.read(names[0]).decode("utf-8-sig")
        rows = [Funding(int(r["calc_time"]), int(r["funding_interval_hours"]), float(r["last_funding_rate"]))
                for r in csv.DictReader(io.StringIO(data))]
    for row in rows:
        if (row.interval_hours <= 0 or row.interval_hours > 24 or not math.isfinite(row.rate)
                or abs(row.rate) > .1 or not 0 <= row.timestamp_ms % HOUR_MS < 60_000):
            raise ValueError(f"invalid funding observation: {row}")
    return rows


def load(first="2023-01", last="2026-08"):
    manifest = json.loads((DATA_ROOT / "manifest.json").read_text(encoding="utf-8"))
    wanted = set(months(first, last))
    selected = [r for r in manifest if r["month"] in wanted and r["symbol"] in SYMBOLS]
    if len(selected) != len(wanted) * len(SYMBOLS) * 3:
        raise ValueError("incomplete derivatives manifest")
    result = {kind: {symbol: [] for symbol in SYMBOLS} for kind in ("klines", "markPriceKlines", "fundingRate")}
    for record in selected:
        path = Path(record["path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError(f"cached derivatives changed: {path}")
        rows = parse_funding(path) if record["kind"] == "fundingRate" else parse_archive(path, max_gap_hours=48)
        result[record["kind"]][record["symbol"]].extend(rows)
    supplements = []
    for kind, symbols in result.items():
        for symbol, rows in symbols.items():
            if kind == "fundingRate":
                if any(a.timestamp_ms >= b.timestamp_ms for a, b in zip(rows, rows[1:])):
                    raise ValueError(f"duplicate/reversed funding {symbol}")
            else:
                gaps = spacing_gaps(rows, max_gap_hours=48)
                if gaps:
                    missing = {timestamp for gap in gaps for timestamp in
                               range(gap["after_open_ms"] + HOUR_MS, gap["before_open_ms"], HOUR_MS)}
                    days = sorted({datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%Y-%m-%d") for t in missing})
                    lookup = {bar.open_ms: bar for bar in rows}
                    for day in days:
                        supplemental = fetch(kind, symbol, day, "daily")
                        supplements.append(supplemental)
                        for bar in parse_archive(Path(supplemental["path"])):
                            if bar.open_ms in missing:
                                lookup[bar.open_ms] = bar
                    restored = sorted(lookup.values(), key=lambda bar: bar.open_ms)
                    if spacing_gaps(restored):
                        raise ValueError(f"unresolved derivative gaps: {kind} {symbol}")
                    result[kind][symbol] = restored
    if supplements:
        (DATA_ROOT / "supplemental_manifest.json").write_text(
            json.dumps(supplements, indent=2) + "\n", encoding="utf-8")
        selected = selected + supplements
    return result, selected


if __name__ == "__main__":
    download()
