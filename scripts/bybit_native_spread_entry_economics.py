"""Read-only fixed-size Bybit native carry-spread quote economics screen."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "outputs/bybit_native_spread_entry_economics.json"
API = "https://api.bybit.com"
PAIRS = (
    ("BTC", "BTCUSDT-25DEC26_BTC/USDT"),
    ("ETH", "ETHUSDT-25DEC26_ETH/USDT"),
)
TARGET_NOTIONALS = (500, 1000)
PROTOCOL_COMMIT = "a29357a"
SPOT_TAKER = 0.001
FUTURE_TAKER = 0.00055
COMBO_DISCOUNT = 0.5
FUTURE_SETTLEMENT_FEE = 0.0005
SPOT_EXIT_FEE = 0.001
SPOT_EXIT_SLIPPAGE = 0.001
INDEX_SPOT_MISMATCH = 0.001
ANNUAL_CAPITAL_CHARGE = 0.01
RESERVED_CAPITAL_MULTIPLE = 2.025


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_public(path: str, params: dict) -> dict:
    requested = now_utc()
    record = {"requested_utc": requested, "path": path, "params": params}
    try:
        response = requests.get(API + path, params=params, timeout=(5, 15))
        record["url"] = response.url
        response.raise_for_status()
        payload = response.json()
        record["received_utc"] = now_utc()
        record["payload"] = payload
        if payload.get("retCode") != 0:
            raise ValueError(f"Bybit retCode={payload.get('retCode')}")
        record["status"] = "ok"
    except (requests.RequestException, ValueError, KeyError, TypeError) as error:
        record["received_utc"] = now_utc()
        record["status"] = "error"
        record["reason"] = str(error)
    return record


def positive_top(book: dict) -> bool:
    try:
        return (all(book.get(side) for side in ("a", "b"))
                and all(float(book[side][0][index]) > 0
                        for side in ("a", "b") for index in (0, 1)))
    except (TypeError, ValueError, IndexError, KeyError):
        return False


def sell_bid_vwap(levels: list, quantity: float) -> tuple[float | None, float]:
    remaining = quantity
    revenue = 0.0
    for price_string, size_string in levels:
        price = float(price_string)
        size = float(size_string)
        if not math.isfinite(price) or not math.isfinite(size) or price <= 0 or size <= 0:
            raise ValueError("invalid spread bid price or size")
        taken = min(remaining, size)
        revenue += taken * price
        remaining -= taken
        if remaining <= 1e-10:
            return revenue / quantity, quantity
    return None, quantity - remaining


def evaluate(base: str, calls: dict, name: str | None = None) -> dict:
    name = name or f"{base}USDT-25DEC26_{base}/USDT"
    relevant = [calls[key] for key in ("instrument", "spread_book", "spot_book")]
    result = {"base": base, "spread_symbol": name}
    if any(row["status"] != "ok" for row in relevant):
        result["status"] = "required API read failed"
        return result
    instrument_list = calls["instrument"]["payload"]["result"].get("list", [])
    matches = [row for row in instrument_list if row.get("symbol") == name]
    if len(matches) != 1:
        result["status"] = "missing or ambiguous instrument metadata"
        return result
    metadata = matches[0]
    spread = calls["spread_book"]["payload"]["result"]
    spot = calls["spot_book"]["payload"]["result"]
    if (metadata.get("status") != "Trading" or metadata.get("contractType") != "CarryTrade"
            or spread.get("s") != name or spot.get("s") != f"{base}USDT"
            or not positive_top(spread) or not positive_top(spot)):
        result["status"] = "instrument or two-sided book invalid"
        return result
    spot_ask = float(spot["a"][0][0])
    lot = float(metadata["lotSize"])
    minimum = float(metadata["minSize"])
    maximum = float(metadata["maxSize"])
    delivery_ms = int(metadata["deliveryTime"])
    read_ms = int(calls["spread_book"]["payload"]["time"])
    days_to_delivery = (delivery_ms - read_ms) / (1000 * 60 * 60 * 24)
    if not all(math.isfinite(x) and x > 0 for x in (spot_ask, lot, minimum, maximum)) or days_to_delivery <= 0:
        result["status"] = "invalid size, reference price or delivery"
        return result
    spread_age = (int(spread["ts"]) - int(spread["cts"])) / 1000
    spot_age = (int(spot["ts"]) - int(spot["cts"])) / 1000
    book_offset = abs(int(spread["ts"]) - int(spot["ts"])) / 1000
    current = (0 <= spread_age <= 10 and 0 <= spot_age <= 10 and book_offset <= 5)
    result.update({
        "status": "evaluated", "spot_best_ask": spot_ask,
        "spread_best_bid": float(spread["b"][0][0]),
        "spread_best_bid_size": float(spread["b"][0][1]),
        "spread_best_ask": float(spread["a"][0][0]),
        "spread_quote_age_seconds": spread_age,
        "spot_quote_age_seconds": spot_age,
        "book_timestamp_offset_seconds": book_offset,
        "current_under_fixed_protocol": current,
        "days_to_delivery": days_to_delivery,
        "sizes": [],
    })
    for intended in TARGET_NOTIONALS:
        quantity = math.floor(intended / spot_ask / lot) * lot
        row = {"intended_spot_notional": intended, "rounded_quantity": quantity}
        if quantity < minimum or quantity > maximum:
            row["status"] = "quantity outside instrument limits"
        else:
            bid_vwap, visible = sell_bid_vwap(spread["b"], quantity)
            row["visible_bid_quantity_within_25_levels"] = visible
            if bid_vwap is None:
                row["status"] = "insufficient displayed bid depth"
            else:
                spot_value = quantity * spot_ask
                future_entry_reference = spot_ask + bid_vwap
                premium = quantity * bid_vwap
                entry_fees = quantity * COMBO_DISCOUNT * (
                    SPOT_TAKER * spot_ask + FUTURE_TAKER * future_entry_reference)
                settlement_fee = FUTURE_SETTLEMENT_FEE * spot_value
                spot_exit_fee = SPOT_EXIT_FEE * spot_value
                spot_exit_slippage = SPOT_EXIT_SLIPPAGE * spot_value
                index_spot_mismatch = INDEX_SPOT_MISMATCH * spot_value
                reserved_capital = RESERVED_CAPITAL_MULTIPLE * spot_value
                capital_charge = (ANNUAL_CAPITAL_CHARGE * reserved_capital
                                  * days_to_delivery / 365)
                net = (premium - entry_fees - settlement_fee - spot_exit_fee
                       - spot_exit_slippage - index_spot_mismatch - capital_charge)
                row.update({
                    "status": "conditional estimate only",
                    "actual_spot_notional": spot_value,
                    "sell_combo_bid_vwap": bid_vwap,
                    "entry_premium": premium,
                    "entry_combo_fees": entry_fees,
                    "future_settlement_fee_stress": settlement_fee,
                    "spot_exit_fee_stress": spot_exit_fee,
                    "spot_exit_slippage_stress": spot_exit_slippage,
                    "index_spot_mismatch_stress": index_spot_mismatch,
                    "reserved_capital": reserved_capital,
                    "capital_charge": capital_charge,
                    "conditional_net_cash": net,
                    "conditional_return_on_reserved_capital": net / reserved_capital,
                })
        row["qualifies_for_longer_observation"] = (
            current and row.get("status") == "conditional estimate only"
            and row["conditional_net_cash"] > 0)
        result["sizes"].append(row)
    result["both_sizes_qualify"] = all(
        row["qualifies_for_longer_observation"] for row in result["sizes"])
    return result


def main() -> None:
    report = {
        "protocol": "docs/bybit_native_spread_entry_economics_protocol.md",
        "protocol_commit": PROTOCOL_COMMIT,
        "started_utc": now_utc(), "source": "public Bybit API",
        "fee_and_exit_stresses": {
            "spot_taker": SPOT_TAKER, "future_taker": FUTURE_TAKER,
            "combo_discount": COMBO_DISCOUNT,
            "future_settlement_fee": FUTURE_SETTLEMENT_FEE,
            "spot_exit_fee": SPOT_EXIT_FEE,
            "spot_exit_slippage": SPOT_EXIT_SLIPPAGE,
            "index_spot_mismatch": INDEX_SPOT_MISMATCH,
            "annual_capital_charge": ANNUAL_CAPITAL_CHARGE,
            "reserved_capital_multiple": RESERVED_CAPITAL_MULTIPLE,
        },
        "observations": {}, "results": {},
        "limits": "Public displayed depth is not a fill; future price path, settlement spot-index basis, fees, account collateral, borrowing and liquidation unverified; no orders submitted",
    }
    for base, name in PAIRS:
        calls = {
            "instrument": read_public("/v5/spread/instrument", {"symbol": name}),
            "spread_book": read_public("/v5/spread/orderbook", {"symbol": name, "limit": 25}),
            "spot_book": read_public("/v5/market/orderbook", {
                "category": "spot", "symbol": f"{base}USDT", "limit": 25}),
        }
        report["observations"][base] = calls
        try:
            report["results"][base] = evaluate(base, calls)
        except (ValueError, TypeError, KeyError, IndexError, ZeroDivisionError) as error:
            report["results"][base] = {
                "status": "evaluation error", "reason": str(error)}
        print(base, report["results"][base]["status"], flush=True)
    report["finished_utc"] = now_utc()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("saved", REPORT, flush=True)


if __name__ == "__main__":
    main()
