"""Read-only March 2027 Binance delivery-basis public-book quote screen."""

from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor

from binance_dec26_forward_quote import (
    ANNUAL_CAPITAL_CHARGE,
    BASES,
    CAPITAL_MULTIPLE,
    EXTRA_UNCERTAINTY,
    FUTURE_API,
    FUTURE_ENTRY_FEE,
    FUTURE_SETTLEMENT_STRESS,
    INDEX_SPOT_MISMATCH,
    MIN_ANNUALIZED_RETURN,
    ROOT,
    SPOT_API,
    SPOT_ENTRY_FEE,
    SPOT_EXIT_FEE,
    SPOT_EXIT_SLIPPAGE,
    TARGETS,
    evaluate,
    read_public,
    utc_now,
)


CONTRACT_SUFFIX = "270326"
EXPECTED_TYPE = "NEXT_QUARTER"
REPORT = ROOT / "outputs/binance_mar27_forward_quote.json"


def main() -> None:
    protocol_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    report = {
        "protocol": "docs/binance_mar27_forward_quote_protocol.md",
        "protocol_commit": protocol_commit,
        "started_utc": utc_now(),
        "contract_suffix": CONTRACT_SUFFIX,
        "expected_contract_type": EXPECTED_TYPE,
        "target_spot_notionals": TARGETS,
        "minimum_annualized_conditional_return": str(MIN_ANNUALIZED_RETURN),
        "cost_assumptions": {
            "spot_entry_taker": str(SPOT_ENTRY_FEE),
            "future_entry_taker": str(FUTURE_ENTRY_FEE),
            "future_settlement_stress": str(FUTURE_SETTLEMENT_STRESS),
            "spot_exit_fee": str(SPOT_EXIT_FEE),
            "spot_exit_slippage": str(SPOT_EXIT_SLIPPAGE),
            "index_spot_mismatch": str(INDEX_SPOT_MISMATCH),
            "extra_uncertainty": str(EXTRA_UNCERTAINTY),
            "annual_capital_charge": str(ANNUAL_CAPITAL_CHARGE),
            "reserved_capital_multiple": str(CAPITAL_MULTIPLE),
        },
        "metadata": {}, "sources": {}, "results": {},
        "limits": "Public depth is not a fill; legs are not atomic; actual fees, margin path and final exit unknown; no orders",
    }
    spot_metadata = read_public(SPOT_API, "/api/v3/exchangeInfo")
    future_metadata = read_public(FUTURE_API, "/fapi/v1/exchangeInfo")
    report["metadata"] = {"spot": spot_metadata, "future": future_metadata}
    for base in BASES:
        with ThreadPoolExecutor(max_workers=2) as pool:
            spot_task = pool.submit(read_public, SPOT_API, "/api/v3/depth", {
                "symbol": f"{base}USDT", "limit": 100})
            future_task = pool.submit(read_public, FUTURE_API, "/fapi/v1/depth", {
                "symbol": f"{base}USDT_{CONTRACT_SUFFIX}", "limit": 100})
            spot_book, future_book = spot_task.result(), future_task.result()
        clock = read_public(FUTURE_API, "/fapi/v1/time")
        sources = {
            "metadata": {"spot": spot_metadata, "future": future_metadata},
            "spot_book": spot_book, "future_book": future_book,
            "future_clock": clock,
        }
        report["sources"][base] = {
            "spot_book": spot_book, "future_book": future_book,
            "future_clock": clock,
        }
        try:
            result = evaluate(base, sources, CONTRACT_SUFFIX, EXPECTED_TYPE)
        except (ValueError, TypeError, KeyError, IndexError, ArithmeticError) as error:
            result = {"status": "evaluation error", "reason": str(error),
                      "both_sizes_qualify": False}
        report["results"][base] = result
        print(base, result["status"], flush=True)
        for row in result.get("sizes", []):
            print(" ", row["intended_spot_notional"], row["status"],
                  "net", row.get("conditional_net_cash"),
                  "annualized", row.get(
                      "annualized_conditional_return_on_reserved_capital"), flush=True)
    report["candidate_coins"] = [
        base for base in BASES if report["results"][base].get("both_sizes_qualify", False)
    ]
    report["finished_utc"] = utc_now()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("candidate coins", report["candidate_coins"], flush=True)
    print("saved", REPORT, flush=True)


if __name__ == "__main__":
    main()
