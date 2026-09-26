"""Read-only, fixed full-universe basis-plus-funding entry screen."""

from __future__ import annotations

import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from binance_dec26_forward_quote import FUTURE_API, ROOT, SPOT_API, read_public, utc_now
from binance_recent_carry_entry_quote import (
    INPUT, INPUT_SHA256, TARGETS, evaluate,
)
from laya_trader.config import load_config


SYMBOLS = tuple(load_config(ROOT / "configs/dataset.toml").data.symbols)
REPORT = ROOT / "outputs/binance_full_universe_carry_quote.json"


def main() -> None:
    raw_input = INPUT.read_bytes()
    digest = hashlib.sha256(raw_input).hexdigest()
    if digest != INPUT_SHA256:
        raise ValueError(f"funding input SHA256 mismatch: {digest}")
    funding = json.loads(raw_input)
    if tuple(funding["symbols"]) != SYMBOLS:
        raise ValueError("funding symbols differ from the fixed project universe")
    for symbol in SYMBOLS:
        row = funding["results"][symbol]
        if (row["status"] != "evaluated" or row["settlements_7d"] < 18
                or row["settlements_3d"] < 8):
            raise ValueError(f"{symbol}: incomplete settled-funding input")

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    report = {
        "protocol": "docs/binance_full_universe_carry_quote_protocol.md",
        "protocol_commit": commit,
        "funding_input_sha256": digest,
        "started_utc": utc_now(),
        "symbols": SYMBOLS,
        "targets": TARGETS,
        "economics": "unchanged from binance_recent_carry_entry_quote.evaluate",
        "metadata": {}, "sources": {}, "results": {},
        "limits": "Conditional scenario only; no future funding, exit basis, fills, account fees or margin path verified",
    }
    spot_metadata = read_public(SPOT_API, "/api/v3/exchangeInfo")
    future_metadata = read_public(FUTURE_API, "/fapi/v1/exchangeInfo")
    metadata = {"spot": spot_metadata, "future": future_metadata}
    report["metadata"] = metadata

    for symbol in SYMBOLS:
        input_row = funding["results"][symbol]
        forecast = Decimal(str(min(
            input_row["projected_30d_from_7d"],
            input_row["projected_30d_from_3d"],
        )))
        with ThreadPoolExecutor(max_workers=2) as pool:
            spot_task = pool.submit(read_public, SPOT_API, "/api/v3/depth", {
                "symbol": symbol, "limit": 100,
            })
            future_task = pool.submit(read_public, FUTURE_API, "/fapi/v1/depth", {
                "symbol": symbol, "limit": 100,
            })
            spot_read, future_read = spot_task.result(), future_task.result()
        clock = read_public(FUTURE_API, "/fapi/v1/time")
        report["sources"][symbol] = {
            "spot_book": spot_read, "future_book": future_read,
            "future_clock": clock,
        }
        try:
            result = evaluate(
                symbol, forecast, metadata, spot_read, future_read, clock,
            )
        except (ValueError, KeyError, TypeError, IndexError, ArithmeticError) as error:
            result = {
                "symbol": symbol, "status": "evaluation error",
                "reason": str(error), "sizes": [], "both_sizes_qualify": False,
            }
        report["results"][symbol] = result
        print(symbol, result["status"], flush=True)
        for row in result.get("sizes", []):
            print(" ", row["intended_spot_notional"], row["status"],
                  "net", row.get("conditional_net_cash"),
                  "annualized", row.get(
                      "annualized_conditional_return_on_reserved_capital"),
                  flush=True)

    report["candidate_symbols"] = [
        symbol for symbol in SYMBOLS
        if report["results"][symbol].get("both_sizes_qualify", False)
    ]
    report["finished_utc"] = utc_now()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("candidate symbols", report["candidate_symbols"], flush=True)
    print("saved", REPORT, flush=True)


if __name__ == "__main__":
    main()
