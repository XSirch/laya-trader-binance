"""Read-only longer-maturity Deribit inverse quote screen."""

from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor

from binance_dec26_forward_quote import ROOT, read_public, utc_now
from deribit_inverse_delivery_universe_screen import (
    API,
    BASES,
    TARGETS,
    evaluate,
    result,
)


PROTOCOL = "docs/deribit_inverse_long_delivery_protocol.md"
REPORT = ROOT / "outputs/deribit_inverse_long_delivery.json"
EXPIRIES = ("25JUN27", "24SEP27")


def main() -> None:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout.strip()
    report = {"protocol": PROTOCOL, "protocol_commit": commit,
              "started_utc": utc_now(), "bases": BASES, "expiries": EXPIRIES,
              "targets": TARGETS,
              "evaluator": "deribit_inverse_delivery_universe_screen.evaluate",
              "cost_protocol": "docs/deribit_inverse_delivery_universe_protocol.md",
              "post_selection": True, "metadata": {}, "sources": {},
              "results": {}, "limits": "Conditional public-book quotes only; post-selection, no fills, account fees, margin or final exit; no orders"}
    spot_meta = read_public(API, "/api/v2/public/get_instruments",
                            {"currency": "USDC", "kind": "spot", "expired": "false"})
    futures_meta = {base: read_public(API, "/api/v2/public/get_instruments",
                                      {"currency": base, "kind": "future",
                                       "expired": "false"}) for base in BASES}
    report["metadata"] = {"spot": spot_meta, "futures": futures_meta}
    try:
        spots = result(spot_meta)
    except (ValueError, TypeError, KeyError) as error:
        spots = []
        report["spot_metadata_error"] = str(error)
    for base in BASES:
        try:
            futures = result(futures_meta[base])
        except (ValueError, TypeError, KeyError) as error:
            futures = []
            report[f"{base}_metadata_error"] = str(error)
        spot_symbol = f"{base}_USDC"
        spot = next((item for item in spots if item.get("instrument_name") == spot_symbol), {})
        for expiry in EXPIRIES:
            symbol = f"{base}-{expiry}"
            future = next((item for item in futures if item.get("instrument_name") == symbol), {})
            with ThreadPoolExecutor(max_workers=2) as pool:
                a = pool.submit(read_public, API, "/api/v2/public/get_order_book",
                                {"instrument_name": spot_symbol, "depth": 100})
                b = pool.submit(read_public, API, "/api/v2/public/get_order_book",
                                {"instrument_name": symbol, "depth": 100})
                spot_read, future_read = a.result(), b.result()
            time_read = read_public(API, "/api/v2/public/get_time")
            report["sources"][symbol] = {"spot_book": spot_read,
                                          "future_book": future_read,
                                          "server_clock": time_read}
            try:
                rowset = evaluate(base, expiry, spot, future,
                                  spot_read, future_read, time_read)
            except (ValueError, TypeError, KeyError, IndexError, ArithmeticError) as error:
                rowset = {"future_symbol": symbol, "status": "evaluation error",
                          "reason": str(error), "both_sizes_qualify": False}
            report["results"][symbol] = rowset
            print(symbol, rowset["status"], [
                row.get("annualized_conditional_return") for row in rowset.get("sizes", [])
            ], flush=True)
    report["candidate_contracts"] = [symbol for symbol, rowset in report["results"].items()
                                     if rowset.get("both_sizes_qualify")]
    report["finished_utc"] = utc_now()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("candidate contracts", report["candidate_contracts"], flush=True)
    print("saved", REPORT, flush=True)


if __name__ == "__main__":
    main()
