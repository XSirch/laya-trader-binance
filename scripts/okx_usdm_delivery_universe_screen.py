"""Read-only OKX USD-margined delivery books under a frozen cost protocol."""

from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal, ROUND_DOWN, ROUND_UP

from binance_dec26_forward_quote import ROOT, read_public, utc_now


API = "https://www.okx.com"
PROTOCOL = "docs/okx_usdm_delivery_universe_protocol.md"
REPORT = ROOT / "outputs/okx_usdm_delivery_universe.json"
BASES = ("BTC", "ETH", "SOL")
EXPIRIES = ("261030", "261127", "261225", "270326")
TARGETS = (500, 1000)
SPOT_ENTRY_FEE = Decimal("0.001")
FUTURE_ENTRY_FEE = Decimal("0.0005")
EXPIRY_FEE_STRESS = Decimal("0.0005")
SPOT_EXIT_FEE = Decimal("0.001")
SPOT_EXIT_SLIPPAGE = Decimal("0.001")
INDEX_SPOT_MISMATCH = Decimal("0.001")
USD_USDC_CONVERSION = Decimal("0.0025")
EXTRA_UNCERTAINTY = Decimal("0.0025")
ANNUAL_CAPITAL_CHARGE = Decimal("0.01")
CAPITAL_MULTIPLE = Decimal("2.025")
MIN_ANNUALIZED_RETURN = Decimal("0.04")


def data(read: dict) -> list:
    if read.get("status") != "ok":
        raise ValueError("public API request failed")
    payload = read["payload"]
    if payload.get("code") != "0" or not isinstance(payload.get("data"), list):
        raise ValueError(f"OKX API error: {payload.get('code')} {payload.get('msg')}")
    return payload["data"]


def round_step(value: Decimal, step: Decimal, mode: str) -> Decimal:
    if step <= 0:
        raise ValueError("nonpositive lot step")
    return (value / step).to_integral_value(rounding=mode) * step


def book_cash(levels: list, quantity: Decimal, base_per_unit: Decimal) -> tuple[Decimal | None, Decimal]:
    remaining = quantity
    cash = Decimal(0)
    for level in levels:
        price, size = Decimal(level[0]), Decimal(level[1])
        if not price.is_finite() or not size.is_finite() or price <= 0 or size <= 0:
            raise ValueError("invalid public book level")
        matched = min(size, remaining)
        cash += matched * base_per_unit * price
        remaining -= matched
        if remaining <= 0:
            return cash, quantity
    return None, quantity - remaining


def evaluate(base: str, expiry: str, spot: dict, future: dict,
             spot_read: dict, future_read: dict, time_read: dict) -> dict:
    result = {"future_symbol": f"{base}-USD_UM-{expiry}", "sizes": [],
              "both_sizes_qualify": False}
    if any(read.get("status") != "ok" for read in (spot_read, future_read, time_read)):
        result["status"] = "required public API request failed"
        return result
    if (spot.get("instId") != f"{base}-USDC" or spot.get("state") != "live"
            or spot.get("ruleType") != "normal"
            or future.get("instId") != result["future_symbol"]
            or future.get("state") != "live"
            or future.get("ruleType") != "normal"
            or future.get("ctType") != "linear"
            or future.get("instFamily") != f"{base}-USD_UM"
            or future.get("settleCcy") != "USD"
            or future.get("ctValCcy") != base):
        result["status"] = "instrument metadata invalid"
        return result
    spot_book, future_book = data(spot_read)[0], data(future_read)[0]
    server_ms = int(data(time_read)[0]["ts"])
    if not spot_book.get("asks") or not future_book.get("bids"):
        result["status"] = "required book side empty"
        return result
    spot_age = (server_ms - int(spot_book["ts"])) / 1000
    future_age = (server_ms - int(future_book["ts"])) / 1000
    offset = abs((datetime.fromisoformat(spot_read["received_utc"])
                  - datetime.fromisoformat(future_read["received_utc"])).total_seconds())
    days = Decimal(int(future["expTime"]) - server_ms) / Decimal(86_400_000)
    timely = (0 <= spot_age <= 10 and 0 <= future_age <= 10 and offset <= 5)
    result.update({"status": "evaluated", "spot_symbol": spot["instId"],
                   "days_to_expiry": float(days), "spot_book_age_seconds": spot_age,
                   "future_book_age_seconds": future_age,
                   "receive_offset_seconds": offset, "timely_under_protocol": timely})
    contract_coin = Decimal(future["ctVal"]) * Decimal(future["ctMult"])
    future_step, future_min = Decimal(future["lotSz"]), Decimal(future["minSz"])
    spot_step, spot_min = Decimal(spot["lotSz"]), Decimal(spot["minSz"])
    best_ask = Decimal(spot_book["asks"][0][0])
    if min(contract_coin, future_step, spot_step, best_ask, days) <= 0:
        result["status"] = "invalid contract, lot, price or expiry"
        return result
    for target in TARGETS:
        contracts = round_step(Decimal(target) / best_ask / contract_coin,
                               future_step, ROUND_DOWN)
        exact_coin = contracts * contract_coin
        spot_coin = round_step(exact_coin, spot_step, ROUND_UP)
        row = {"intended_spot_notional": target, "contracts": str(contracts),
               "exact_hedge_coin": str(exact_coin), "spot_coin": str(spot_coin),
               "excess_spot_coin_written_off": str(spot_coin - exact_coin)}
        if (contracts < future_min or spot_coin < spot_min
                or contracts > Decimal(future["maxMktSz"])
                or spot_coin > Decimal(spot["maxMktSz"])):
            row["status"] = "outside exchange size limits"
        else:
            future_cash, future_visible = book_cash(
                future_book["bids"], contracts, contract_coin)
            spot_cash, spot_visible = book_cash(
                spot_book["asks"], spot_coin, Decimal(1))
            row["visible_future_contracts"] = str(future_visible)
            row["visible_spot_coin"] = str(spot_visible)
            if future_cash is None or spot_cash is None:
                row["status"] = "insufficient displayed entry depth"
            elif spot_cash > Decimal(spot["maxMktAmt"]):
                row["status"] = "spot cash above market amount limit"
            else:
                fees = {
                    "spot_entry_fee": SPOT_ENTRY_FEE * spot_cash,
                    "future_entry_fee": FUTURE_ENTRY_FEE * future_cash,
                    "expiry_fee_stress": EXPIRY_FEE_STRESS * future_cash,
                    "spot_exit_fee": SPOT_EXIT_FEE * future_cash,
                    "spot_exit_slippage": SPOT_EXIT_SLIPPAGE * future_cash,
                    "index_spot_mismatch": INDEX_SPOT_MISMATCH * future_cash,
                    "usd_usdc_conversion": USD_USDC_CONVERSION * future_cash,
                    "extra_uncertainty": EXTRA_UNCERTAINTY * future_cash,
                }
                capital = CAPITAL_MULTIPLE * spot_cash
                fees["capital_charge"] = ANNUAL_CAPITAL_CHARGE * capital * days / 365
                net = future_cash - spot_cash - sum(fees.values())
                annualized = net / capital * 365 / days
                row.update({"status": "conditional entry quote only",
                            "future_bid_cash": float(future_cash),
                            "spot_ask_cash": float(spot_cash),
                            "entry_basis_before_costs": float(future_cash - spot_cash),
                            "fees_and_stresses": {k: float(v) for k, v in fees.items()},
                            "reserved_capital": float(capital),
                            "conditional_net_cash": float(net),
                            "annualized_conditional_return": float(annualized)})
        row["qualifies"] = (timely and row.get("status") == "conditional entry quote only"
                            and row["conditional_net_cash"] > 0
                            and row["annualized_conditional_return"]
                            >= float(MIN_ANNUALIZED_RETURN))
        result["sizes"].append(row)
    result["both_sizes_qualify"] = all(row["qualifies"] for row in result["sizes"])
    return result


def main() -> None:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout.strip()
    report = {"protocol": PROTOCOL, "protocol_commit": commit,
              "started_utc": utc_now(), "bases": BASES, "expiries": EXPIRIES,
              "targets": TARGETS, "cost_assumptions": {
                  "spot_entry_fee": str(SPOT_ENTRY_FEE),
                  "future_entry_fee": str(FUTURE_ENTRY_FEE),
                  "expiry_fee_stress": str(EXPIRY_FEE_STRESS),
                  "spot_exit_fee": str(SPOT_EXIT_FEE),
                  "spot_exit_slippage": str(SPOT_EXIT_SLIPPAGE),
                  "index_spot_mismatch": str(INDEX_SPOT_MISMATCH),
                  "usd_usdc_conversion": str(USD_USDC_CONVERSION),
                  "extra_uncertainty": str(EXTRA_UNCERTAINTY),
                  "annual_capital_charge": str(ANNUAL_CAPITAL_CHARGE),
                  "capital_multiple": str(CAPITAL_MULTIPLE),
                  "minimum_annualized_return": str(MIN_ANNUALIZED_RETURN),
              }, "metadata": {}, "sources": {}, "results": {},
              "limits": "Public books and conditional settlement arithmetic only; account access, fees, fills, USD/USDC conversion, margin and final exit unverified; no orders"}
    spot_meta = read_public(API, "/api/v5/public/instruments", {"instType": "SPOT"})
    future_meta = read_public(API, "/api/v5/public/instruments", {"instType": "FUTURES"})
    report["metadata"] = {"spot": spot_meta, "future": future_meta}
    try:
        spots, futures = data(spot_meta), data(future_meta)
    except (ValueError, TypeError, KeyError) as error:
        spots, futures = [], []
        report["metadata_error"] = str(error)
    for base in BASES:
        for expiry in EXPIRIES:
            symbol = f"{base}-USD_UM-{expiry}"
            spot = next((item for item in spots if item.get("instId") == f"{base}-USDC"), {})
            future = next((item for item in futures if item.get("instId") == symbol), {})
            with ThreadPoolExecutor(max_workers=2) as pool:
                a = pool.submit(read_public, API, "/api/v5/market/books",
                                {"instId": f"{base}-USDC", "sz": 100})
                b = pool.submit(read_public, API, "/api/v5/market/books",
                                {"instId": symbol, "sz": 100})
                spot_read, future_read = a.result(), b.result()
            time_read = read_public(API, "/api/v5/public/time")
            report["sources"][symbol] = {"spot_book": spot_read,
                                          "future_book": future_read,
                                          "server_clock": time_read}
            try:
                result = evaluate(base, expiry, spot, future,
                                  spot_read, future_read, time_read)
            except (ValueError, TypeError, KeyError, IndexError, ArithmeticError) as error:
                result = {"future_symbol": symbol, "status": "evaluation error",
                          "reason": str(error), "both_sizes_qualify": False}
            report["results"][symbol] = result
            print(symbol, result["status"], [
                row.get("annualized_conditional_return") for row in result.get("sizes", [])
            ], flush=True)
    report["candidate_contracts"] = [symbol for symbol, result in report["results"].items()
                                     if result.get("both_sizes_qualify")]
    report["finished_utc"] = utc_now()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("candidate contracts", report["candidate_contracts"], flush=True)
    print("saved", REPORT, flush=True)


if __name__ == "__main__":
    main()
