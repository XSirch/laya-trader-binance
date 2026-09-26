"""Immutable public REST snapshots for the frozen chronological extension."""

import hashlib
import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from .binance_data import Bar, HOUR_MS, _read_url, utc_ms
from .broad_data import CACHE, load as load_daily
from .broad_execution import evaluate
from .broad_hourly import load as load_hourly
from .broad_research import DAY_MS, features
from .cli import ROOT, RESULTS
from .derivatives_data import Funding

API = "https://fapi.binance.com/fapi/v1/"
SNAPSHOTS = CACHE / "extension_rest"
START, END = utc_ms("2026-08-31"), utc_ms("2026-09-26")


def snapshot(endpoint, symbol):
    if endpoint not in ("klines", "markPriceKlines", "fundingRate"):
        raise ValueError("public research endpoints only")
    params = {"symbol": symbol, "startTime": START, "endTime": END,
              "limit": 1000 if endpoint == "fundingRate" else 1500}
    if endpoint != "fundingRate":
        params["interval"] = "1h"
    url = API + endpoint + "?" + urlencode(params)
    key = hashlib.sha256(url.encode()).hexdigest()
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    payload_path, meta_path = SNAPSHOTS / f"{key}.json", SNAPSHOTS / f"{key}.meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        payload = payload_path.read_bytes()
        if meta["url"] != url or hashlib.sha256(payload).hexdigest() != meta["sha256"]:
            raise ValueError("REST snapshot changed")
    else:
        if payload_path.exists():
            raise ValueError("snapshot without acquisition metadata")
        payload = _read_url(url)
        rows = json.loads(payload)
        if not isinstance(rows, list) or len(rows) >= params["limit"]:
            raise ValueError("unexpected or potentially truncated REST response")
        meta = {"url": url, "endpoint": endpoint, "symbol": symbol,
                "retrieved_utc": datetime.now(timezone.utc).isoformat(),
                "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload), "rows": len(rows),
                "path": str(payload_path), "provenance": "Public HTTPS response; local content hash, not publisher checksum"}
        payload_path.write_bytes(payload)
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return json.loads(payload), meta


def parse_bars(rows, start=START, end=END):
    output = {}
    for row in rows:
        bar = Bar(int(row[0]), *map(float, row[1:6]), float(row[7]), int(row[8]), float(row[9]))
        if (bar.open_ms in output or bar.open_ms % HOUR_MS or
                not all(math.isfinite(v) for v in (bar.open, bar.high, bar.low, bar.close, bar.volume,
                                                   bar.quote_volume, bar.taker_buy_base)) or
                not 0 < bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high or
                bar.volume < 0 or bar.quote_volume < 0 or bar.trades < 0 or
                not 0 <= bar.taker_buy_base <= bar.volume):
            raise ValueError("invalid REST candle")
        output[bar.open_ms] = bar
    if set(output) != set(range(start, end + HOUR_MS, HOUR_MS)):
        raise ValueError("REST hourly calendar incomplete")
    return output


def aggregate_days(bars, start, end):
    result = []
    for day in range(start, end, DAY_MS):
        rows = [bars[day + i * HOUR_MS] for i in range(24)]
        result.append(Bar(day, rows[0].open, max(b.high for b in rows), min(b.low for b in rows),
                          rows[-1].close, sum(b.volume for b in rows), sum(b.quote_volume for b in rows),
                          sum(b.trades for b in rows), sum(b.taker_buy_base for b in rows)))
    return result


def extend(data, hourly):
    active = [s for s, bars in data["klines"].items() if bars[-1].open_ms == START]
    inactive = [s for s in data["klines"] if s not in active]
    if set(inactive) != {"EOSUSDT", "MKRUSDT"}:
        raise ValueError("unexpected archive availability; investigate before extension")
    responses, sources = {}, []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(snapshot, endpoint, s): (endpoint, s)
                   for s in active for endpoint in ("klines", "markPriceKlines", "fundingRate")}
        for future in as_completed(futures):
            key = futures[future]
            rows, meta = future.result()
            responses[key] = rows
            sources.append(meta)
            print(f"verified REST snapshot {len(sources)}/{len(futures)} {key}", flush=True)
    marks = {}
    overlap = {"candles_compared": 0, "funding_compared": 0}
    for s in active:
        for kind in ("klines", "markPriceKlines"):
            bars = parse_bars(responses[kind, s])
            for t, bar in bars.items():
                if t in hourly[kind][s]:
                    prior = hourly[kind][s][t]
                    fields = ("open", "high", "low", "close") if kind != "klines" else (
                        "open", "high", "low", "close", "volume", "quote_volume", "trades", "taker_buy_base")
                    if any(not math.isclose(getattr(prior, f), getattr(bar, f), rel_tol=1e-8, abs_tol=1e-8)
                           for f in fields):
                        raise ValueError(f"archive/REST overlap mismatch: {s} {kind} {t}")
                    overlap["candles_compared"] += 1
                else:
                    hourly[kind][s][t] = bar
            data[kind][s].extend(aggregate_days(bars, START + DAY_MS, END))
        rates = {r.timestamp_ms: r for r in data["fundingRate"][s]}
        previous_hour = max(t // HOUR_MS for t in rates if t < START)
        seen = set()
        for row in responses["fundingRate", s]:
            timestamp = int(row["fundingTime"])
            rate, price = float(row["fundingRate"]), float(row["markPrice"])
            interval = timestamp // HOUR_MS - previous_hour
            if (row["symbol"] != s or timestamp in seen or not START <= timestamp <= END or
                    not 0 <= timestamp % HOUR_MS < 60_000 or not 1 <= interval <= 24 or
                    not math.isfinite(rate) or abs(rate) > .1 or not math.isfinite(price) or price <= 0 or
                    row.get("rateType", "Regular") != "Regular"):
                raise ValueError(f"invalid or unsupported REST funding {s}: {row}")
            seen.add(timestamp)
            previous_hour = timestamp // HOUR_MS
            if timestamp in rates:
                if not math.isclose(rate, rates[timestamp].rate, abs_tol=1e-12) or interval != rates[timestamp].interval_hours:
                    raise ValueError("archive/REST funding mismatch")
                overlap["funding_compared"] += 1
            else:
                rates[timestamp] = Funding(timestamp, interval, rate)
            marks[s, timestamp] = price
        if not seen or END - max(seen) > 24 * HOUR_MS:
            raise ValueError("funding tail incomplete")
        data["fundingRate"][s] = sorted(rates.values(), key=lambda r: r.timestamp_ms)
    sources.sort(key=lambda r: (r["endpoint"], r["symbol"]))
    return sources, overlap, marks


def run():
    path = ROOT / "docs/broad_candidate_freeze_2026-09-26.json"
    frozen = json.loads(path.read_text(encoding="utf-8"))
    for name, expected in frozen["source_code_sha256"].items():
        if hashlib.sha256((ROOT / "src/jev_trader" / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"frozen source changed: {name}")
    data, _, _ = load_daily()
    hourly, _ = load_hourly(data)
    sources, overlap, exact_marks = extend(data, hourly)
    states = features(data)
    results = {}
    for cost in frozen["costs_per_side"]:
        result = evaluate(hourly, data["fundingRate"], states, frozen["rule"],
                          *frozen["chronological_extension_window"], cost, 1)
        results[str(cost)] = result
        print(f"extension cost={cost}: return={result['return_pct']:.4f}% dd={result['max_drawdown_pct']:.4f}%", flush=True)
    exact_diagnostic = evaluate(hourly, data["fundingRate"], states, frozen["rule"],
                                *frozen["chronological_extension_window"], .0015, 1, exact_marks)
    print(f"exact available funding marks: return={exact_diagnostic['return_pct']:.4f}%", flush=True)
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "results": results,
              "period": frozen["chronological_extension_window"], "freeze_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "sources": [{k: v for k, v in r.items() if k != "path"} for r in sources], "overlap": overlap,
              "available_exact_funding_marks": len(exact_marks), "funding_mode": "adverse hourly bounds",
              "exact_available_funding_diagnostic": exact_diagnostic,
              "source_code_sha256": {name: hashlib.sha256((ROOT / "src/jev_trader" / name).read_bytes()).hexdigest()
                                     for name in ("broad_extension.py", "broad_execution.py")},
              "deployable": False, "limits": ["Retrospective extension, not prospective evidence.",
                  "August outcome was already seen before September extension; strategy unchanged.",
                  "September is partial; it ends at September 26 00:00 UTC."]}
    (RESULTS / "broad_extension.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    run()
