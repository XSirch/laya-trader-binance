"""Read-only Binance December 2026 delivery-basis forward quote gate."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "outputs/binance_dec26_forward_quote.json"
PROTOCOL_COMMIT = "25f219d"
BASES = ("BTC", "ETH")
TARGETS = (500, 1000)
SPOT_API = "https://data-api.binance.vision"
FUTURE_API = "https://fapi.binance.com"
SPOT_ENTRY_FEE = Decimal("0.001")
FUTURE_ENTRY_FEE = Decimal("0.0005")
FUTURE_SETTLEMENT_STRESS = Decimal("0.0005")
SPOT_EXIT_FEE = Decimal("0.001")
SPOT_EXIT_SLIPPAGE = Decimal("0.001")
INDEX_SPOT_MISMATCH = Decimal("0.001")
EXTRA_UNCERTAINTY = Decimal("0.0025")
ANNUAL_CAPITAL_CHARGE = Decimal("0.01")
CAPITAL_MULTIPLE = Decimal("2.025")
MIN_ANNUALIZED_RETURN = Decimal("0.04")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_public(base_url: str, path: str, params: dict | None = None) -> dict:
    record = {"requested_utc": utc_now(), "path": path, "params": params or {}}
    try:
        response = requests.get(base_url + path, params=params, timeout=(5, 15))
        record["url"] = response.url
        record["http_status"] = response.status_code
        response.raise_for_status()
        record["payload"] = response.json()
        record["status"] = "ok"
    except (requests.RequestException, ValueError) as error:
        record["status"] = "error"
        record["reason"] = str(error)
    record["received_utc"] = utc_now()
    return record


def one_filter(symbol: dict, kind: str) -> dict:
    matches = [item for item in symbol["filters"]
               if item.get("filterType") == kind]
    if len(matches) != 1:
        raise ValueError(f"expected one {kind} filter for {symbol['symbol']}")
    return matches[0]


def step_for_both(spot_step: Decimal, future_step: Decimal) -> Decimal:
    candidate = max(spot_step, future_step)
    if candidate % spot_step or candidate % future_step:
        raise ValueError("spot/future lot steps do not divide exactly")
    return candidate


def marketable_vwap(levels: list, quantity: Decimal) -> tuple[Decimal | None, Decimal]:
    remaining = quantity
    cash = Decimal(0)
    for price_text, size_text in levels:
        price, size = Decimal(price_text), Decimal(size_text)
        if not price.is_finite() or not size.is_finite() or price <= 0 or size <= 0:
            raise ValueError("invalid public book level")
        matched = min(size, remaining)
        cash += matched * price
        remaining -= matched
        if remaining <= 0:
            return cash / quantity, quantity
    return None, quantity - remaining


def evaluate(base: str, sources: dict) -> dict:
    result = {"base": base, "sizes": [], "both_sizes_qualify": False}
    metadata = sources["metadata"]
    spot_read = sources["spot_book"]
    future_read = sources["future_book"]
    future_clock = sources["future_clock"]
    if any(row["status"] != "ok" for row in (
            metadata["spot"], metadata["future"], spot_read, future_read,
            future_clock)):
        result["status"] = "required public API read failed"
        return result
    spot_symbol = f"{base}USDT"
    future_symbol = f"{base}USDT_261225"
    spots = [row for row in metadata["spot"]["payload"].get("symbols", [])
             if row.get("symbol") == spot_symbol]
    futures = [row for row in metadata["future"]["payload"].get("symbols", [])
               if row.get("symbol") == future_symbol]
    if len(spots) != 1 or len(futures) != 1:
        result["status"] = "required symbol absent from exchange metadata"
        return result
    spot, future = spots[0], futures[0]
    if (spot.get("status") != "TRADING" or future.get("status") != "TRADING"
            or future.get("quoteAsset") != "USDT"
            or future.get("marginAsset") != "USDT"):
        result["status"] = "instrument not trading or wrong settlement asset"
        return result
    spot_book = spot_read["payload"]
    future_book = future_read["payload"]
    if not spot_book.get("asks") or not future_book.get("bids"):
        result["status"] = "one entry book side is empty"
        return result
    spot_lot = one_filter(spot, "LOT_SIZE")
    future_lot = one_filter(future, "LOT_SIZE")
    step = step_for_both(Decimal(spot_lot["stepSize"]),
                         Decimal(future_lot["stepSize"]))
    minimum = max(Decimal(spot_lot["minQty"]), Decimal(future_lot["minQty"]))
    maximum = min(Decimal(spot_lot["maxQty"]), Decimal(future_lot["maxQty"]))
    best_spot_ask = Decimal(spot_book["asks"][0][0])
    delivery_ms = int(future["deliveryDate"])
    server_ms = int(future_clock["payload"]["serverTime"])
    age_seconds = (server_ms - int(future_book["T"])) / 1000
    spot_received = datetime.fromisoformat(spot_read["received_utc"])
    future_received = datetime.fromisoformat(future_read["received_utc"])
    book_offset_seconds = abs((spot_received - future_received).total_seconds())
    days_to_delivery = (delivery_ms - server_ms) / (1000 * 60 * 60 * 24)
    timely = (0 <= age_seconds <= 10 and book_offset_seconds <= 5)
    result.update({
        "status": "evaluated", "spot_symbol": spot_symbol,
        "future_symbol": future_symbol,
        "best_spot_ask": float(best_spot_ask),
        "best_future_bid": float(Decimal(future_book["bids"][0][0])),
        "future_book_age_seconds_at_clock_read": age_seconds,
        "spot_future_receive_offset_seconds": book_offset_seconds,
        "timely_under_protocol": timely,
        "days_to_delivery": days_to_delivery,
        "common_lot_step": str(step),
    })
    if days_to_delivery <= 0 or step <= 0 or best_spot_ask <= 0:
        result["status"] = "expired contract or invalid lot/reference price"
        return result
    for intended in TARGETS:
        quantity = (Decimal(intended) / best_spot_ask / step).to_integral_value(
            rounding=ROUND_DOWN) * step
        row = {"intended_spot_notional": intended, "rounded_quantity": str(quantity)}
        if quantity < minimum or quantity > maximum:
            row["status"] = "quantity outside spot/future lot limits"
        else:
            spot_vwap, spot_visible = marketable_vwap(spot_book["asks"], quantity)
            future_vwap, future_visible = marketable_vwap(
                future_book["bids"], quantity)
            row["visible_spot_ask_quantity"] = str(spot_visible)
            row["visible_future_bid_quantity"] = str(future_visible)
            if spot_vwap is None or future_vwap is None:
                row["status"] = "insufficient displayed entry depth"
            else:
                spot_value = quantity * spot_vwap
                future_value = quantity * future_vwap
                entry_premium = future_value - spot_value
                entry_spot_fee = SPOT_ENTRY_FEE * spot_value
                entry_future_fee = FUTURE_ENTRY_FEE * future_value
                future_settlement = FUTURE_SETTLEMENT_STRESS * spot_value
                exit_spot_fee = SPOT_EXIT_FEE * spot_value
                exit_slippage = SPOT_EXIT_SLIPPAGE * spot_value
                mismatch = INDEX_SPOT_MISMATCH * spot_value
                extra = EXTRA_UNCERTAINTY * spot_value
                capital = CAPITAL_MULTIPLE * spot_value
                capital_charge = (ANNUAL_CAPITAL_CHARGE * capital
                                  * Decimal(str(days_to_delivery)) / Decimal(365))
                net = (entry_premium - entry_spot_fee - entry_future_fee
                       - future_settlement - exit_spot_fee - exit_slippage
                       - mismatch - extra - capital_charge)
                annualized = net / capital * Decimal(365) / Decimal(
                    str(days_to_delivery))
                row.update({
                    "status": "conditional entry quote only",
                    "spot_ask_vwap": float(spot_vwap),
                    "future_bid_vwap": float(future_vwap),
                    "actual_spot_notional": float(spot_value),
                    "entry_premium": float(entry_premium),
                    "entry_spot_fee": float(entry_spot_fee),
                    "entry_future_fee": float(entry_future_fee),
                    "future_settlement_stress": float(future_settlement),
                    "spot_exit_fee_stress": float(exit_spot_fee),
                    "spot_exit_slippage_stress": float(exit_slippage),
                    "index_spot_mismatch_stress": float(mismatch),
                    "extra_uncertainty_stress": float(extra),
                    "reserved_capital": float(capital),
                    "capital_charge": float(capital_charge),
                    "conditional_net_cash": float(net),
                    "conditional_return_on_reserved_capital": float(net / capital),
                    "annualized_conditional_return_on_reserved_capital": (
                        float(annualized)),
                })
        row["qualifies_for_longer_forward_observation"] = (
            timely and row.get("status") == "conditional entry quote only"
            and row["conditional_net_cash"] > 0
            and row["annualized_conditional_return_on_reserved_capital"]
            >= float(MIN_ANNUALIZED_RETURN))
        result["sizes"].append(row)
    result["both_sizes_qualify"] = all(
        row["qualifies_for_longer_forward_observation"] for row in result["sizes"])
    return result


def main() -> None:
    report = {
        "protocol": "docs/binance_dec26_forward_quote_protocol.md",
        "protocol_commit": PROTOCOL_COMMIT,
        "started_utc": utc_now(),
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
        "sources": {}, "results": {},
        "limits": "Public book depth is not a fill; legs are not atomic; exit convergence, account fees, collateral and margin path unverified; no orders submitted",
    }
    spot_metadata = read_public(SPOT_API, "/api/v3/exchangeInfo")
    future_metadata = read_public(FUTURE_API, "/fapi/v1/exchangeInfo")
    report["metadata"] = {"spot": spot_metadata, "future": future_metadata}
    for base in BASES:
        with ThreadPoolExecutor(max_workers=2) as pool:
            spot_future = pool.submit(read_public, SPOT_API, "/api/v3/depth", {
                "symbol": f"{base}USDT", "limit": 100})
            future_future = pool.submit(read_public, FUTURE_API, "/fapi/v1/depth", {
                "symbol": f"{base}USDT_261225", "limit": 100})
            spot_book, future_book = spot_future.result(), future_future.result()
        clock = read_public(FUTURE_API, "/fapi/v1/time")
        sources = {"metadata": {"spot": spot_metadata, "future": future_metadata},
                   "spot_book": spot_book, "future_book": future_book,
                   "future_clock": clock}
        report["sources"][base] = {
            "spot_book": spot_book, "future_book": future_book,
            "future_clock": clock}
        try:
            report["results"][base] = evaluate(base, sources)
        except (ValueError, TypeError, KeyError, IndexError, ArithmeticError) as error:
            report["results"][base] = {
                "status": "evaluation error", "reason": str(error),
                "both_sizes_qualify": False}
        print(base, report["results"][base]["status"], flush=True)
        for row in report["results"][base].get("sizes", []):
            print(" ", row["intended_spot_notional"], row["status"],
                  "net", row.get("conditional_net_cash"),
                  "annualized", row.get(
                      "annualized_conditional_return_on_reserved_capital"),
                  flush=True)
    report["both_coins_both_sizes_qualify"] = all(
        report["results"][base].get("both_sizes_qualify", False)
        for base in BASES)
    report["finished_utc"] = utc_now()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("saved", REPORT, flush=True)


if __name__ == "__main__":
    main()
