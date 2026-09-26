"""Read-only ten-sample watch of Bybit native BTC/ETH carry-spread books."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import requests

from spot_perp_carry_probe import ROOT


SYMBOLS = (
    "BTCUSDT-25DEC26_BTC/USDT",
    "ETHUSDT-25DEC26_ETH/USDT",
)
SAMPLES = 10
INTERVAL_SECONDS = 30
REPORT = ROOT / "outputs/bybit_native_spread_watch.json"
ENDPOINT = "https://api.bybit.com/v5/spread/orderbook"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def top_level(levels: list) -> tuple[float | None, float | None]:
    if not levels:
        return None, None
    return float(levels[0][0]), float(levels[0][1])


def observe(symbol: str) -> dict:
    requested = utc_now()
    try:
        response = requests.get(ENDPOINT, params={"symbol": symbol, "limit": 25},
                                timeout=15)
        response.raise_for_status()
        payload = response.json()
        if payload.get("retCode") != 0:
            raise ValueError(f"Bybit retCode={payload.get('retCode')}")
        book = payload["result"]
        if book["s"] != symbol:
            raise ValueError("wrong spread symbol returned")
        bid, bid_qty = top_level(book.get("b", []))
        ask, ask_qty = top_level(book.get("a", []))
        ts_ms = int(book["ts"])
        cts_ms = int(book["cts"])
        age_seconds = (ts_ms - cts_ms) / 1000
        fresh_two_sided = (
            bid is not None and ask is not None
            and bid > 0 and ask > 0 and bid_qty > 0 and ask_qty > 0
            and 0 <= age_seconds <= 10)
        return {
            "symbol": symbol, "requested_utc": requested,
            "received_utc": utc_now(), "status": "ok",
            "response_ts_ms": ts_ms, "matching_engine_cts_ms": cts_ms,
            "quote_age_seconds_at_response": age_seconds,
            "update_id": book.get("u"), "sequence": book.get("seq"),
            "best_bid_spread": bid, "best_bid_quantity": bid_qty,
            "best_ask_spread": ask, "best_ask_quantity": ask_qty,
            "fresh_two_sided_under_protocol": fresh_two_sided,
        }
    except (requests.RequestException, ValueError, KeyError, TypeError,
            IndexError, json.JSONDecodeError) as error:
        return {"symbol": symbol, "requested_utc": requested,
                "received_utc": utc_now(), "status": "error",
                "reason": str(error), "fresh_two_sided_under_protocol": False}


def write_report(samples: list[dict]) -> None:
    summary = {}
    for symbol in SYMBOLS:
        rows = [row for item in samples for row in item["books"]
                if row["symbol"] == symbol]
        valid = [row for row in rows if row["status"] == "ok"]
        summary[symbol] = {
            "observed_samples": len(rows),
            "successful_samples": len(valid),
            "fresh_two_sided_samples": sum(
                row["fresh_two_sided_under_protocol"] for row in rows),
            "qualifies_for_further_account_evaluation": (
                len(rows) == SAMPLES and sum(
                    row["fresh_two_sided_under_protocol"] for row in rows) >= 8),
            "oldest_quote_age_seconds": max(
                (row["quote_age_seconds_at_response"] for row in valid),
                default=None),
            "distinct_matching_engine_update_ids": len({
                row["update_id"] for row in valid}),
            "distinct_best_bids": len({
                row["best_bid_spread"] for row in valid}),
            "distinct_best_asks": len({
                row["best_ask_spread"] for row in valid}),
        }
    report = {
        "protocol": "docs/bybit_native_spread_watch_protocol.md, frozen at commit a0952df",
        "source": "Bybit public native spread 25-level order-book API",
        "planned_samples": SAMPLES,
        "interval_seconds": INTERVAL_SECONDS,
        "samples": samples,
        "summary": summary,
        "limits": "Snapshot freshness and displayed sizes are not fill, account fee, collateral, exit liquidity or profit evidence; no orders submitted",
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    samples = []
    for index in range(SAMPLES):
        if index:
            time.sleep(INTERVAL_SECONDS)
        books = [observe(symbol) for symbol in SYMBOLS]
        samples.append({"sample": index + 1, "books": books})
        write_report(samples)
        for row in books:
            print(index + 1, row["symbol"], row["status"],
                  "age", row.get("quote_age_seconds_at_response"),
                  "fresh", row["fresh_two_sided_under_protocol"], flush=True)
    print("saved", REPORT, flush=True)


if __name__ == "__main__":
    main()
