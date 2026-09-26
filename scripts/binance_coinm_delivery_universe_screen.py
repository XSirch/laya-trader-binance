"""Read-only COIN-M delivery-basis screen with inverse-contract accounting."""

from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal, ROUND_DOWN, ROUND_UP

from binance_dec26_forward_quote import (
    ROOT,
    SPOT_API,
    marketable_vwap,
    one_filter,
    read_public,
    step_for_both,
    utc_now,
)


COIN_API = "https://dapi.binance.com"
BASES = ("BNB", "BTC", "ETH", "SOL", "XRP")
CONTRACTS = (("261225", "CURRENT_QUARTER"),
             ("270326", "NEXT_QUARTER"))
TARGETS = (500, 1000)
REPORT = ROOT / "outputs/binance_coinm_delivery_universe.json"
SPOT_ENTRY_FEE = Decimal("0.001")
FUTURE_ENTRY_FEE = Decimal("0.0005")
FUTURE_FEE_EXIT_PRICE_MULTIPLE = Decimal("2")
FUTURE_SETTLEMENT_FEE = Decimal("0.0005")
SPOT_EXIT_FEE = Decimal("0.001")
SPOT_EXIT_SLIPPAGE = Decimal("0.001")
INDEX_SPOT_MISMATCH = Decimal("0.001")
EXTRA_UNCERTAINTY = Decimal("0.0025")
ANNUAL_CAPITAL_CHARGE = Decimal("0.01")
CAPITAL_MULTIPLE = Decimal("1.025")
MIN_ANNUALIZED_RETURN = Decimal("0.04")


def spot_step_and_limits(symbol: dict) -> tuple[Decimal, Decimal, Decimal]:
    lot = one_filter(symbol, "LOT_SIZE")
    market = one_filter(symbol, "MARKET_LOT_SIZE")
    lot_step = Decimal(lot["stepSize"])
    market_step = Decimal(market["stepSize"])
    if lot_step <= 0:
        raise ValueError("invalid spot lot step")
    step = step_for_both(lot_step, market_step) if market_step > 0 else lot_step
    minimum = max(Decimal(lot["minQty"]), Decimal(market["minQty"]))
    maximum = min(Decimal(lot["maxQty"]), Decimal(market["maxQty"]))
    return step, minimum, maximum


def future_contracts_at_bids(levels: list, contracts: Decimal,
                             contract_size: Decimal) -> tuple[Decimal | None, Decimal]:
    remaining = contracts
    hedge_coin = Decimal(0)
    for price_text, count_text in levels:
        price, count = Decimal(price_text), Decimal(count_text)
        if (not price.is_finite() or not count.is_finite()
                or price <= 0 or count <= 0):
            raise ValueError("invalid COIN-M bid level")
        matched = min(count, remaining)
        hedge_coin += matched * contract_size / price
        remaining -= matched
        if remaining <= 0:
            return hedge_coin, contracts
    return None, contracts - remaining


def evaluate(base: str, suffix: str, expected_type: str,
             spot_metadata: dict, future_metadata: dict,
             spot_book_read: dict, future_book_read: dict,
             clock_read: dict) -> dict:
    symbol = f"{base}USD_{suffix}"
    result = {"symbol": symbol, "sizes": [], "both_sizes_qualify": False}
    if any(record["status"] != "ok" for record in (
            spot_metadata, future_metadata, spot_book_read,
            future_book_read, clock_read)):
        result["status"] = "required public API read failed"
        return result
    spot_symbol = f"{base}USDT"
    spots = [row for row in spot_metadata["payload"].get("symbols", [])
             if row.get("symbol") == spot_symbol]
    futures = [row for row in future_metadata["payload"].get("symbols", [])
               if row.get("symbol") == symbol]
    if len(spots) != 1 or len(futures) != 1:
        result["status"] = "required symbol absent from metadata"
        return result
    spot, future = spots[0], futures[0]
    if (spot.get("status") != "TRADING"
            or future.get("contractStatus") != "TRADING"
            or future.get("contractType") != expected_type
            or future.get("baseAsset") != base
            or future.get("marginAsset") != base
            or future.get("quoteAsset") != "USD"):
        result["status"] = "instrument status, type or settlement asset invalid"
        return result
    spot_asks = spot_book_read["payload"].get("asks", [])
    future_bids = future_book_read["payload"].get("bids", [])
    if not spot_asks or not future_bids:
        result["status"] = "one required book side is empty"
        return result
    step, spot_min, spot_max = spot_step_and_limits(spot)
    future_lot = one_filter(future, "LOT_SIZE")
    future_market = one_filter(future, "MARKET_LOT_SIZE")
    contract_size = Decimal(str(future["contractSize"]))
    future_min = max(Decimal(future_lot["minQty"]),
                     Decimal(future_market["minQty"]))
    future_max = min(Decimal(future_lot["maxQty"]),
                     Decimal(future_market["maxQty"]))
    future_step = step_for_both(Decimal(future_lot["stepSize"]),
                                Decimal(future_market["stepSize"]))
    delivery_ms = int(future["deliveryDate"])
    server_ms = int(clock_read["payload"]["serverTime"])
    days_to_delivery = Decimal(delivery_ms - server_ms) / Decimal(86_400_000)
    book_age = Decimal(server_ms - int(future_book_read["payload"]["T"])) / 1000
    receive_offset = abs((datetime.fromisoformat(spot_book_read["received_utc"])
                          - datetime.fromisoformat(
                              future_book_read["received_utc"])).total_seconds())
    timely = 0 <= book_age <= 10 and receive_offset <= 5
    result.update({
        "status": "evaluated", "spot_symbol": spot_symbol,
        "contract_type": expected_type, "contract_size_usd": str(contract_size),
        "days_to_delivery": float(days_to_delivery),
        "future_book_age_seconds_at_clock_read": float(book_age),
        "spot_future_receive_offset_seconds": receive_offset,
        "timely_under_protocol": timely,
        "spot_lot_step": str(step), "future_contract_step": str(future_step),
    })
    if contract_size <= 0 or future_step <= 0 or days_to_delivery <= 0:
        result["status"] = "invalid contract size, step or delivery date"
        return result
    for target in TARGETS:
        contracts = (Decimal(target) / contract_size / future_step).to_integral_value(
            rounding=ROUND_DOWN) * future_step
        row = {"intended_spot_notional": target,
               "contracts": str(contracts),
               "usd_face": float(contracts * contract_size)}
        if contracts < future_min or contracts > future_max:
            row["status"] = "contract count outside lot limits"
        else:
            hedge_coin, visible_contracts = future_contracts_at_bids(
                future_bids, contracts, contract_size)
            row["visible_future_contracts"] = str(visible_contracts)
            if hedge_coin is None:
                row["status"] = "insufficient displayed future bid depth"
            else:
                spot_quantity = (hedge_coin / step).to_integral_value(
                    rounding=ROUND_UP) * step
                row["exact_hedge_coin"] = str(hedge_coin)
                row["rounded_spot_coin"] = str(spot_quantity)
                row["excess_spot_coin_written_off"] = str(
                    spot_quantity - hedge_coin)
                if spot_quantity < spot_min or spot_quantity > spot_max:
                    row["status"] = "spot quantity outside lot limits"
                else:
                    spot_vwap, visible_spot = marketable_vwap(
                        spot_asks, spot_quantity)
                    row["visible_spot_ask_coin"] = str(visible_spot)
                    if spot_vwap is None:
                        row["status"] = "insufficient displayed spot ask depth"
                    else:
                        spot_cost = spot_quantity * spot_vwap
                        minimums = [Decimal(str(item["minNotional"]))
                                    for item in spot["filters"]
                                    if item.get("filterType") in
                                    ("NOTIONAL", "MIN_NOTIONAL")]
                        if minimums and spot_cost < max(minimums):
                            row["status"] = "spot cost below minimum notional"
                        else:
                            face = contracts * contract_size
                            spot_entry_fee = SPOT_ENTRY_FEE * spot_cost
                            future_entry_fee_coin = FUTURE_ENTRY_FEE * hedge_coin
                            future_entry_fee_stress = (
                                future_entry_fee_coin * spot_vwap
                                * FUTURE_FEE_EXIT_PRICE_MULTIPLE)
                            settlement_fee = FUTURE_SETTLEMENT_FEE * face
                            spot_exit_fee = SPOT_EXIT_FEE * face
                            exit_slippage = SPOT_EXIT_SLIPPAGE * face
                            mismatch = INDEX_SPOT_MISMATCH * face
                            extra = EXTRA_UNCERTAINTY * face
                            capital = CAPITAL_MULTIPLE * spot_cost
                            capital_charge = (ANNUAL_CAPITAL_CHARGE * capital
                                              * days_to_delivery / 365)
                            net = (face - spot_cost - spot_entry_fee
                                   - future_entry_fee_stress - settlement_fee
                                   - spot_exit_fee - exit_slippage - mismatch
                                   - extra - capital_charge)
                            annualized = net / capital * 365 / days_to_delivery
                            row.update({
                                "status": "conditional entry quote only",
                                "spot_ask_vwap": float(spot_vwap),
                                "actual_spot_cost": float(spot_cost),
                                "entry_basis_cash_before_costs": float(face - spot_cost),
                                "entry_spot_fee": float(spot_entry_fee),
                                "future_entry_fee_coin": float(future_entry_fee_coin),
                                "future_entry_fee_doubled_exit_price_stress": (
                                    float(future_entry_fee_stress)),
                                "future_settlement_fee": float(settlement_fee),
                                "spot_exit_fee": float(spot_exit_fee),
                                "spot_exit_slippage": float(exit_slippage),
                                "index_spot_mismatch": float(mismatch),
                                "extra_uncertainty": float(extra),
                                "capital_charge": float(capital_charge),
                                "reserved_capital": float(capital),
                                "conditional_net_cash": float(net),
                                "annualized_conditional_return_on_reserved_capital": (
                                    float(annualized)),
                            })
        row["qualifies_for_forward_observation"] = (
            timely and row.get("status") == "conditional entry quote only"
            and row["conditional_net_cash"] > 0
            and row["annualized_conditional_return_on_reserved_capital"]
            >= float(MIN_ANNUALIZED_RETURN))
        result["sizes"].append(row)
    result["both_sizes_qualify"] = all(
        row["qualifies_for_forward_observation"] for row in result["sizes"])
    return result


def main() -> None:
    protocol_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    report = {
        "protocol": "docs/binance_coinm_delivery_universe_protocol.md",
        "protocol_commit": protocol_commit,
        "started_utc": utc_now(),
        "bases": BASES, "contracts": CONTRACTS, "targets": TARGETS,
        "cost_assumptions": {
            "spot_entry_fee": str(SPOT_ENTRY_FEE),
            "future_entry_fee_coin": str(FUTURE_ENTRY_FEE),
            "future_fee_exit_price_multiple": str(FUTURE_FEE_EXIT_PRICE_MULTIPLE),
            "future_settlement_fee": str(FUTURE_SETTLEMENT_FEE),
            "spot_exit_fee": str(SPOT_EXIT_FEE),
            "spot_exit_slippage": str(SPOT_EXIT_SLIPPAGE),
            "index_spot_mismatch": str(INDEX_SPOT_MISMATCH),
            "extra_uncertainty": str(EXTRA_UNCERTAINTY),
            "annual_capital_charge": str(ANNUAL_CAPITAL_CHARGE),
            "reserved_capital_multiple": str(CAPITAL_MULTIPLE),
            "minimum_annualized_return": str(MIN_ANNUALIZED_RETURN),
        },
        "metadata": {}, "sources": {}, "results": {},
        "limits": "Conditional quotes, no fills; coin margin, liquidation, transfer eligibility, actual fees, spot exit and taxes unverified; no orders",
    }
    spot_metadata = read_public(SPOT_API, "/api/v3/exchangeInfo")
    future_metadata = read_public(COIN_API, "/dapi/v1/exchangeInfo")
    report["metadata"] = {"spot": spot_metadata, "future": future_metadata}
    for base in BASES:
        for suffix, expected_type in CONTRACTS:
            symbol = f"{base}USD_{suffix}"
            with ThreadPoolExecutor(max_workers=2) as pool:
                spot_task = pool.submit(read_public, SPOT_API, "/api/v3/depth", {
                    "symbol": f"{base}USDT", "limit": 100})
                future_task = pool.submit(read_public, COIN_API, "/dapi/v1/depth", {
                    "symbol": symbol, "limit": 100})
                spot_book, future_book = spot_task.result(), future_task.result()
            clock = read_public(COIN_API, "/dapi/v1/time")
            report["sources"][symbol] = {
                "spot_book": spot_book, "future_book": future_book,
                "future_clock": clock,
            }
            try:
                result = evaluate(base, suffix, expected_type,
                                  spot_metadata, future_metadata,
                                  spot_book, future_book, clock)
            except (ValueError, TypeError, KeyError, IndexError,
                    ArithmeticError) as error:
                result = {"symbol": symbol, "status": "evaluation error",
                          "reason": str(error), "sizes": [],
                          "both_sizes_qualify": False}
            report["results"][symbol] = result
            print(symbol, result["status"], flush=True)
            for row in result.get("sizes", []):
                print(" ", row["intended_spot_notional"], row["status"],
                      "net", row.get("conditional_net_cash"),
                      "annualized", row.get(
                          "annualized_conditional_return_on_reserved_capital"),
                      flush=True)
    report["candidate_contracts"] = [
        symbol for symbol, result in report["results"].items()
        if result.get("both_sizes_qualify", False)
    ]
    report["finished_utc"] = utc_now()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("candidate contracts", report["candidate_contracts"], flush=True)
    print("saved", REPORT, flush=True)


if __name__ == "__main__":
    main()
