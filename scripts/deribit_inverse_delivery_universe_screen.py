"""Read-only Deribit inverse delivery books under a frozen cost protocol."""

from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal, ROUND_DOWN, ROUND_UP

from binance_coinm_delivery_universe_screen import future_contracts_at_bids
from binance_dec26_forward_quote import ROOT, read_public, utc_now
from deribit_usdc_delivery_universe_screen import API, result
from okx_usdm_delivery_universe_screen import book_cash, round_step


PROTOCOL = "docs/deribit_inverse_delivery_universe_protocol.md"
REPORT = ROOT / "outputs/deribit_inverse_delivery_universe.json"
BASES = ("BTC", "ETH")
EXPIRIES = ("30OCT26", "27NOV26", "25DEC26", "26MAR27")
TARGETS = (500, 1000)
SPOT_ENTRY_FEE = Decimal("0.0015")
FUTURE_ENTRY_FEE = Decimal("0.0005")
FUTURE_FEE_EXIT_PRICE_MULTIPLE = Decimal("2")
EXPIRY_FEE_STRESS = Decimal("0.0005")
SPOT_EXIT_FEE = Decimal("0.0015")
SPOT_EXIT_SLIPPAGE = Decimal("0.001")
INDEX_SPOT_MISMATCH = Decimal("0.001")
USD_USDC_INDEX_VALUATION = Decimal("0.0025")
EXTRA_UNCERTAINTY = Decimal("0.0025")
ANNUAL_CAPITAL_CHARGE = Decimal("0.01")
CAPITAL_MULTIPLE = Decimal("1.025")
MIN_ANNUALIZED_RETURN = Decimal("0.04")


def evaluate(base: str, expiry: str, spot: dict, future: dict,
             spot_read: dict, future_read: dict, time_read: dict) -> dict:
    symbol, spot_symbol = f"{base}-{expiry}", f"{base}_USDC"
    rowset = {"future_symbol": symbol, "spot_symbol": spot_symbol,
              "sizes": [], "both_sizes_qualify": False}
    if any(read.get("status") != "ok" for read in (spot_read, future_read, time_read)):
        rowset["status"] = "required public API request failed"
        return rowset
    if (spot.get("instrument_name") != spot_symbol or not spot.get("is_active")
            or spot.get("kind") != "spot" or spot.get("quote_currency") != "USDC"
            or future.get("instrument_name") != symbol or not future.get("is_active")
            or future.get("kind") != "future"
            or future.get("instrument_type") != "reversed"
            or future.get("base_currency") != base
            or future.get("quote_currency") != "USD"
            or future.get("settlement_currency") != base):
        rowset["status"] = "instrument metadata invalid"
        return rowset
    spot_book, future_book, server_ms = result(spot_read), result(future_read), result(time_read)
    if (spot_book.get("state") != "open" or future_book.get("state") != "open"
            or not spot_book.get("asks") or not future_book.get("bids")):
        rowset["status"] = "instrument closed or required book side empty"
        return rowset
    spot_age = (server_ms - int(spot_book["timestamp"])) / 1000
    future_age = (server_ms - int(future_book["timestamp"])) / 1000
    offset = abs((datetime.fromisoformat(spot_read["received_utc"])
                  - datetime.fromisoformat(future_read["received_utc"])).total_seconds())
    timely = 0 <= spot_age <= 10 and 0 <= future_age <= 10 and offset <= 5
    days = Decimal(int(future["expiration_timestamp"]) - server_ms) / Decimal(86_400_000)
    future_step = Decimal(str(future["contract_size"]))
    spot_step = Decimal(str(spot["contract_size"]))
    future_min = Decimal(str(future["min_trade_amount"]))
    spot_min = Decimal(str(spot["min_trade_amount"]))
    best_ask = Decimal(str(spot_book["asks"][0][0]))
    rowset.update({"status": "evaluated", "spot_book_age_seconds": spot_age,
                   "future_book_age_seconds": future_age,
                   "receive_offset_seconds": offset,
                   "timely_under_protocol": timely, "days_to_expiry": float(days)})
    if min(future_step, spot_step, best_ask, days) <= 0:
        rowset["status"] = "invalid lot, price or expiry"
        return rowset
    for target in TARGETS:
        face = round_step(Decimal(target), future_step, ROUND_DOWN)
        row = {"intended_spot_notional": target, "usd_face": str(face)}
        if face < future_min:
            row["status"] = "below future minimum"
        else:
            hedge_coin, visible_face = future_contracts_at_bids(
                future_book["bids"], face, Decimal(1))
            row["visible_future_usd_face"] = str(visible_face)
            if hedge_coin is None:
                row["status"] = "insufficient displayed future bid depth"
            else:
                spot_coin = round_step(hedge_coin, spot_step, ROUND_UP)
                row["exact_hedge_coin"] = str(hedge_coin)
                row["spot_coin"] = str(spot_coin)
                row["excess_spot_coin_written_off"] = str(spot_coin - hedge_coin)
                if spot_coin < spot_min:
                    row["status"] = "below spot minimum"
                else:
                    spot_cash, visible_spot = book_cash(
                        spot_book["asks"], spot_coin, Decimal(1))
                    row["visible_spot_coin"] = str(visible_spot)
                    if spot_cash is None:
                        row["status"] = "insufficient displayed spot ask depth"
                    else:
                        fees = {
                            "spot_entry_fee": SPOT_ENTRY_FEE * spot_cash,
                            "future_entry_fee_doubled_exit_price_stress": (
                                FUTURE_ENTRY_FEE * hedge_coin * spot_cash / spot_coin
                                * FUTURE_FEE_EXIT_PRICE_MULTIPLE),
                            "expiry_fee_stress": EXPIRY_FEE_STRESS * face,
                            "spot_exit_fee": SPOT_EXIT_FEE * face,
                            "spot_exit_slippage": SPOT_EXIT_SLIPPAGE * face,
                            "index_spot_mismatch": INDEX_SPOT_MISMATCH * face,
                            "usd_usdc_index_valuation": USD_USDC_INDEX_VALUATION * face,
                            "extra_uncertainty": EXTRA_UNCERTAINTY * face,
                        }
                        capital = CAPITAL_MULTIPLE * spot_cash
                        fees["capital_charge"] = ANNUAL_CAPITAL_CHARGE * capital * days / 365
                        net = face - spot_cash - sum(fees.values())
                        annualized = net / capital * 365 / days
                        row.update({"status": "conditional entry quote only",
                                    "spot_ask_cash": float(spot_cash),
                                    "entry_basis_before_costs": float(face - spot_cash),
                                    "fees_and_stresses": {k: float(v) for k, v in fees.items()},
                                    "reserved_capital": float(capital),
                                    "conditional_net_cash": float(net),
                                    "annualized_conditional_return": float(annualized)})
        row["qualifies"] = (timely and row.get("status") == "conditional entry quote only"
                            and row["conditional_net_cash"] > 0
                            and row["annualized_conditional_return"]
                            >= float(MIN_ANNUALIZED_RETURN))
        rowset["sizes"].append(row)
    rowset["both_sizes_qualify"] = all(row["qualifies"] for row in rowset["sizes"])
    return rowset


def main() -> None:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout.strip()
    report = {"protocol": PROTOCOL, "protocol_commit": commit,
              "started_utc": utc_now(), "bases": BASES, "expiries": EXPIRIES,
              "targets": TARGETS, "cost_assumptions": {
                  "spot_entry_fee": str(SPOT_ENTRY_FEE),
                  "future_entry_fee": str(FUTURE_ENTRY_FEE),
                  "future_fee_exit_price_multiple": str(FUTURE_FEE_EXIT_PRICE_MULTIPLE),
                  "expiry_fee_stress": str(EXPIRY_FEE_STRESS),
                  "spot_exit_fee": str(SPOT_EXIT_FEE),
                  "spot_exit_slippage": str(SPOT_EXIT_SLIPPAGE),
                  "index_spot_mismatch": str(INDEX_SPOT_MISMATCH),
                  "usd_usdc_index_valuation": str(USD_USDC_INDEX_VALUATION),
                  "extra_uncertainty": str(EXTRA_UNCERTAINTY),
                  "annual_capital_charge": str(ANNUAL_CAPITAL_CHARGE),
                  "capital_multiple": str(CAPITAL_MULTIPLE),
                  "minimum_annualized_return": str(MIN_ANNUALIZED_RETURN),
              }, "metadata": {}, "sources": {}, "results": {},
              "limits": "Public books and conditional inverse settlement only; actual access, routing, fees, fills, coin margin and final exit unknown; no orders"}
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
