"""Read-only current settled-funding input screen for the fixed project universe."""

from __future__ import annotations

import json
import math
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from binance_dec26_forward_quote import FUTURE_API, ROOT, SPOT_API, read_public, utc_now
from laya_trader.config import load_config


SYMBOLS = tuple(load_config(ROOT / "configs/dataset.toml").data.symbols)
LOOKBACK_DAYS = 7
RECENT_DAYS = 3
MAX_GAP_MS = int(8.5 * 60 * 60 * 1000)
MIN_EVENTS_7D = 18
MIN_EVENTS_3D = 8
ENTRY_PROJECTED_30D = 0.008
REPORT = ROOT / "outputs/binance_recent_funding_20.json"


def evaluate(symbol: str, read: dict, start_ms: int, end_ms: int,
             spot_metadata: dict, future_metadata: dict) -> dict:
    row = {"symbol": symbol, "status": "not evaluated", "passes_input_gate": False}
    if any(source["status"] != "ok" for source in (
            read, spot_metadata, future_metadata)):
        row["status"] = "required public API read failed"
        return row
    spots = [item for item in spot_metadata["payload"].get("symbols", [])
             if item.get("symbol") == symbol]
    futures = [item for item in future_metadata["payload"].get("symbols", [])
               if item.get("symbol") == symbol]
    if (len(spots) != 1 or len(futures) != 1
            or spots[0].get("status") != "TRADING"
            or futures[0].get("status") != "TRADING"
            or futures[0].get("contractType") != "PERPETUAL"
            or futures[0].get("quoteAsset") != "USDT"):
        row["status"] = "spot/perpetual pair not active"
        return row
    records = read["payload"]
    if not isinstance(records, list):
        row["status"] = "funding response is not a list"
        return row
    times = [int(item["fundingTime"]) for item in records]
    rates = [float(item["fundingRate"]) for item in records]
    if (not times or any(item.get("symbol") != symbol for item in records)
            or any(not math.isfinite(value) for value in rates)
            or any(not start_ms <= value <= end_ms for value in times)
            or any(a >= b for a, b in zip(times, times[1:]))):
        row["status"] = "invalid funding timestamps or symbols"
        return row
    if (times[0] - start_ms > MAX_GAP_MS
            or end_ms - times[-1] > MAX_GAP_MS
            or any(b - a > MAX_GAP_MS for a, b in zip(times, times[1:]))):
        row["status"] = "incomplete seven-day settlement coverage"
        return row
    recent_start = end_ms - RECENT_DAYS * 86_400_000
    recent = [(time, rate) for time, rate in zip(times, rates)
              if time >= recent_start]
    if (len(recent) < MIN_EVENTS_3D
            or recent[0][0] - recent_start > MAX_GAP_MS):
        row["status"] = "incomplete recent three-day settlement coverage"
        return row
    if len(times) < MIN_EVENTS_7D:
        row["status"] = "too few seven-day settlements"
        return row
    projected_7d = sum(rates) * 30 / LOOKBACK_DAYS
    projected_3d = sum(rate for _, rate in recent) * 30 / RECENT_DAYS
    row.update({
        "status": "evaluated",
        "settlements_7d": len(times),
        "settlements_3d": len(recent),
        "first_settlement_utc": datetime.fromtimestamp(
            times[0] / 1000, timezone.utc).isoformat(),
        "last_settlement_utc": datetime.fromtimestamp(
            times[-1] / 1000, timezone.utc).isoformat(),
        "observed_funding_7d": sum(rates),
        "observed_funding_3d": sum(rate for _, rate in recent),
        "projected_30d_from_7d": projected_7d,
        "projected_30d_from_3d": projected_3d,
        "passes_input_gate": (projected_7d > ENTRY_PROJECTED_30D
                              and projected_3d > ENTRY_PROJECTED_30D),
    })
    return row


def main() -> None:
    protocol_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    report = {
        "protocol": "docs/binance_recent_funding_20_protocol.md",
        "protocol_commit": protocol_commit,
        "started_utc": utc_now(),
        "symbols": SYMBOLS,
        "window_days": LOOKBACK_DAYS,
        "recent_days": RECENT_DAYS,
        "max_gap_ms": MAX_GAP_MS,
        "minimum_events_7d": MIN_EVENTS_7D,
        "minimum_events_3d": MIN_EVENTS_3D,
        "entry_projected_30d": ENTRY_PROJECTED_30D,
        "sources": {}, "results": {},
        "limits": "Historical settled rates do not guarantee future receipts; no basis, books, fees, margin or orders",
    }
    clock = read_public(FUTURE_API, "/fapi/v1/time")
    spot_metadata = read_public(SPOT_API, "/api/v3/exchangeInfo")
    future_metadata = read_public(FUTURE_API, "/fapi/v1/exchangeInfo")
    report["sources"]["clock"] = clock
    report["sources"]["spot_metadata"] = spot_metadata
    report["sources"]["future_metadata"] = future_metadata
    if clock["status"] != "ok":
        report["status"] = "server clock read failed"
    else:
        end_ms = int(clock["payload"]["serverTime"])
        start_ms = end_ms - LOOKBACK_DAYS * 86_400_000
        report["start_ms"] = start_ms
        report["end_ms"] = end_ms
        with ThreadPoolExecutor(max_workers=5) as pool:
            tasks = {
                pool.submit(read_public, FUTURE_API, "/fapi/v1/fundingRate", {
                    "symbol": symbol,
                    "startTime": start_ms,
                    "endTime": end_ms,
                    "limit": 1000,
                }): symbol for symbol in SYMBOLS
            }
            for task in as_completed(tasks):
                symbol = tasks[task]
                source = task.result()
                report["sources"][symbol] = source
                try:
                    result = evaluate(symbol, source, start_ms, end_ms,
                                      spot_metadata, future_metadata)
                except (ValueError, KeyError, TypeError, OverflowError) as error:
                    result = {"symbol": symbol, "status": "evaluation error",
                              "reason": str(error), "passes_input_gate": False}
                report["results"][symbol] = result
                print(symbol, result["status"],
                      "projected_7d", result.get("projected_30d_from_7d"),
                      "projected_3d", result.get("projected_30d_from_3d"),
                      flush=True)
        report["candidate_symbols"] = [
            symbol for symbol in SYMBOLS
            if report["results"][symbol]["passes_input_gate"]
        ]
        report["status"] = "complete"
    report["finished_utc"] = utc_now()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("candidate symbols", report.get("candidate_symbols"), flush=True)
    print("saved", REPORT, flush=True)


if __name__ == "__main__":
    main()
