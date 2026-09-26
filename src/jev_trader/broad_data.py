"""Point-in-time cohort discovery from the public Binance archive catalog."""

from __future__ import annotations

import json
import hashlib
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from .binance_data import _read_url, months, parse_archive
from .cli import ROOT
from .derivatives_data import fetch, parse_funding

S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
CACHE = ROOT / "data" / "binance" / "broad"


def listing(prefix, delimiter=None):
    key = prefix.replace("/", "_") + ("_prefixes" if delimiter else "_keys")
    path = CACHE / "catalog" / (key + ".json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    params = {"prefix": prefix}
    if delimiter:
        params["delimiter"] = delimiter
    values = []
    while True:
        raw = _read_url(S3 + "?" + urllib.parse.urlencode(params))
        root = ET.fromstring(raw)
        values.extend(x.text for x in root.findall("s:CommonPrefixes/s:Prefix" if delimiter else "s:Contents/s:Key", NS))
        if root.findtext("s:IsTruncated", namespaces=NS) != "true":
            break
        marker = root.findtext("s:NextMarker", namespaces=NS)
        if not marker:
            marker = values[-1]
        if marker == params.get("marker"):
            raise ValueError("catalog pagination stalled")
        params["marker"] = marker
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
    return values


def symbol_catalog(symbol):
    prefix = f"data/futures/um/monthly/klines/{symbol}/1d/"
    return symbol, listing(prefix)


def discover():
    prefixes = listing("data/futures/um/monthly/klines/", "/")
    symbols = sorted(p.rstrip("/").split("/")[-1] for p in prefixes
                     if p.rstrip("/").endswith("USDT") and "_" not in p.rstrip("/").split("/")[-1])
    eligible = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(symbol_catalog, symbol) for symbol in symbols]
        for i, future in enumerate(as_completed(futures), 1):
            symbol, keys = future.result()
            wanted = f"data/futures/um/monthly/klines/{symbol}/1d/{symbol}-1d-2021-01.zip"
            if wanted in keys:
                eligible.append(symbol)
            if i % 100 == 0 or i == len(symbols):
                print(f"catalog {i}/{len(symbols)}; January 2021 contracts={len(eligible)}", flush=True)
    ranked = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch, "klines", symbol, "2021-01", interval="1d"): symbol for symbol in eligible}
        for future in as_completed(futures):
            record = future.result()
            bars = parse_archive(Path(record["path"]), max_gap_hours=72)
            ranked.append({"symbol": record["symbol"], "quote_volume": sum(b.quote_volume for b in bars),
                           "days": len(bars), "source": record})
    ranked.sort(key=lambda row: (-row["quote_volume"], row["symbol"]))
    report = {"formation_month": "2021-01", "criterion": "top 20 monthly quote volumes; no current-survival filter",
              "catalog_symbols": len(symbols), "ranked": ranked, "selected": [r["symbol"] for r in ranked[:20]]}
    (CACHE / "cohort.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"selected": report["selected"], "eligible": len(ranked)}, indent=2), flush=True)
    return report


def download():
    path = CACHE / "cohort.json"
    cohort = json.loads(path.read_text(encoding="utf-8")) if path.exists() else discover()
    records, availability, absent = [], {}, []
    allowed = set(months("2021-01", "2026-08"))
    jobs = []
    for symbol in cohort["selected"]:
        keys = listing(f"data/futures/um/monthly/klines/{symbol}/1d/")
        available = sorted(key[-11:-4] for key in keys if key.endswith(".zip") and key[-11:-4] in allowed)
        availability[symbol] = available
        for kind in ("klines", "markPriceKlines", "fundingRate"):
            prefix = f"data/futures/um/monthly/{kind}/{symbol}/" + ("1d/" if kind != "fundingRate" else "")
            kind_keys = set(listing(prefix))
            for month in available:
                suffix = f"{symbol}-fundingRate-{month}.zip" if kind == "fundingRate" else f"{symbol}-1d-{month}.zip"
                if prefix + suffix not in kind_keys:
                    absent.append({"kind": kind, "symbol": symbol, "month": month})
                    continue
                jobs.append((kind, symbol, month))
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch, *job, interval="1d") for job in jobs]
        for i, future in enumerate(as_completed(futures), 1):
            records.append(future.result())
            if i % 100 == 0 or i == len(jobs):
                print(f"verified broad archives {i}/{len(jobs)}", flush=True)
    records.sort(key=lambda row: (row["kind"], row["symbol"], row["month"]))
    (CACHE / "manifest.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    (CACHE / "availability.json").write_text(json.dumps(availability, indent=2) + "\n", encoding="utf-8")
    (CACHE / "absent_archives.json").write_text(json.dumps(absent, indent=2) + "\n", encoding="utf-8")
    return records


def load():
    cohort = json.loads((CACHE / "cohort.json").read_text(encoding="utf-8"))
    records = json.loads((CACHE / "manifest.json").read_text(encoding="utf-8"))
    result = {kind: {s: [] for s in cohort["selected"]} for kind in ("klines", "markPriceKlines", "fundingRate")}
    for record in records:
        path = Path(record["path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError(f"source hash changed: {path}")
        rows = parse_funding(path) if record["kind"] == "fundingRate" else parse_archive(path, max_gap_hours=24 * 40)
        result[record["kind"]][record["symbol"]].extend(rows)
    supplements, quality, mark_lookup, missing_jobs = [], {}, {}, []
    original_counts = {s: len(result["klines"][s]) for s in cohort["selected"]}
    zero_counts = {s: sum(b.volume <= 0 or b.trades <= 0 for b in result["klines"][s]) for s in cohort["selected"]}
    trade_lookup = {}
    trading_jobs = []
    for s in cohort["selected"]:
        traded = [b for b in result["klines"][s] if b.volume > 0 and b.trades > 0]
        trade_lookup[s] = {b.open_ms: b for b in traded}
        for previous, current in zip(traded, traded[1:]):
            for timestamp in range(previous.open_ms + 86_400_000, current.open_ms, 86_400_000):
                day = datetime.fromtimestamp(timestamp / 1000, timezone.utc).strftime("%Y-%m-%d")
                trading_jobs.append((s, day))
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch, "klines", s, day, "daily", "1d") for s, day in trading_jobs]
        for future in as_completed(futures):
            record = future.result()
            supplements.append(record)
            for bar in parse_archive(Path(record["path"])):
                if bar.volume > 0 and bar.trades > 0:
                    trade_lookup[record["symbol"]][bar.open_ms] = bar
    for s in cohort["selected"]:
        result["klines"][s] = sorted(trade_lookup[s].values(), key=lambda b: b.open_ms)
        if any(b.open_ms - a.open_ms != 86_400_000 for a, b in zip(result["klines"][s], result["klines"][s][1:])):
            raise ValueError(f"unresolved internal trading calendar gap: {s}")
    for s in cohort["selected"]:
        # The archive continues emitting flat, zero-volume candles for some
        # delisted contracts. They are not tradable prices or live observations.
        traded = result["klines"][s]
        quality[s] = {"archive_candle_count": original_counts[s], "tradable_candle_count": len(traded),
                      "zero_volume_or_trade_count_removed": zero_counts[s],
                      "verified_daily_candles_added": len(traded) - original_counts[s] + zero_counts[s],
                      "first_tradable_open_ms": traded[0].open_ms,
                      "last_tradable_open_ms": traded[-1].open_ms}
        traded_months = {datetime.fromtimestamp(b.open_ms / 1000, timezone.utc).strftime("%Y-%m")
                         for b in result["klines"][s]}
        funding_months = {r["month"] for r in records if r["symbol"] == s and r["kind"] == "fundingRate"}
        if traded_months - funding_months:
            raise ValueError(f"funding missing for traded months: {s} {sorted(traded_months - funding_months)}")
        expected = {b.open_ms for b in result["klines"][s]}
        marks = {b.open_ms: b for b in result["markPriceKlines"][s]}
        mark_lookup[s] = marks
        for timestamp in sorted(expected - set(marks)):
            day = datetime.fromtimestamp(timestamp / 1000, timezone.utc).strftime("%Y-%m-%d")
            missing_jobs.append((s, day))
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch, "markPriceKlines", s, day, "daily", "1d") for s, day in missing_jobs]
        for future in as_completed(futures):
            record = future.result()
            supplements.append(record)
            for bar in parse_archive(Path(record["path"])):
                mark_lookup[record["symbol"]][bar.open_ms] = bar
    for s in cohort["selected"]:
        if any(b.open_ms not in mark_lookup[s] for b in result["klines"][s]):
            raise ValueError(f"mark price gaps not repaired: {s}")
        result["markPriceKlines"][s] = sorted(mark_lookup[s].values(), key=lambda b: b.open_ms)
        for kind in result:
            times = [r.timestamp_ms if kind == "fundingRate" else r.open_ms for r in result[kind][s]]
            if times != sorted(set(times)):
                raise ValueError(f"duplicate or reversed {kind} {s}")
    supplements.sort(key=lambda r: (r["kind"], r["symbol"], r["month"]))
    if supplements:
        (CACHE / "supplements.json").write_text(json.dumps(supplements, indent=2) + "\n", encoding="utf-8")
    (CACHE / "data_quality.json").write_text(json.dumps(quality, indent=2) + "\n", encoding="utf-8")
    return result, records + supplements, cohort


if __name__ == "__main__":
    download()
