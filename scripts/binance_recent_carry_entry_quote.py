"""Read-only spot/perpetual entry quote for fixed recent-funding candidates."""

from __future__ import annotations

import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal, ROUND_DOWN

from binance_dec26_forward_quote import (
    FUTURE_API, ROOT, SPOT_API, marketable_vwap, one_filter,
    read_public, step_for_both, utc_now,
)


INPUT = ROOT / "outputs/binance_recent_funding_20.json"
INPUT_SHA256 = "c438b79c20391ae1cd42c45cac98ef9cf6d917431d3a3fb81d1e63364300fe5e"
SYMBOLS = ("ADAUSDT", "NEARUSDT", "APTUSDT")
TARGETS = (500, 1000)
REPORT = ROOT / "outputs/binance_recent_carry_entry_quote.json"
HOLD_DAYS = Decimal(30)
SPOT_TAKER = Decimal("0.001")
FUTURE_TAKER = Decimal("0.0005")
SLIPPAGE_PER_SIDE = Decimal("0.0002")
EXTRA_PAIR_COST = Decimal("0.0008")
EXTRA_UNCERTAINTY = Decimal("0.0025")
ANNUAL_CAPITAL_CHARGE = Decimal("0.01")
CAPITAL_MULTIPLE = Decimal("2.025")
MIN_ANNUALIZED = Decimal("0.04")


def quantity_rules(symbol: dict) -> tuple[Decimal, Decimal, Decimal]:
    lot = one_filter(symbol, "LOT_SIZE")
    market = next((item for item in symbol["filters"]
                   if item.get("filterType") == "MARKET_LOT_SIZE"), None)
    lot_step = Decimal(lot["stepSize"])
    if lot_step <= 0:
        raise ValueError("invalid lot step")
    market_step = Decimal(market["stepSize"]) if market is not None else Decimal(0)
    step = step_for_both(lot_step, market_step) if market_step > 0 else lot_step
    minimum = Decimal(lot["minQty"])
    maximum = Decimal(lot["maxQty"])
    if market is not None:
        minimum = max(minimum, Decimal(market["minQty"]))
        maximum = min(maximum, Decimal(market["maxQty"]))
    return step, minimum, maximum


def evaluate(symbol: str, forecast: Decimal, metadata: dict,
             spot_read: dict, future_read: dict, clock: dict) -> dict:
    result = {"symbol": symbol, "sizes": [], "both_sizes_qualify": False}
    if any(item["status"] != "ok" for item in (
            metadata["spot"], metadata["future"], spot_read, future_read, clock)):
        result["status"] = "required public API read failed"
        return result
    spots = [row for row in metadata["spot"]["payload"].get("symbols", [])
             if row.get("symbol") == symbol]
    futures = [row for row in metadata["future"]["payload"].get("symbols", [])
               if row.get("symbol") == symbol]
    if len(spots) != 1 or len(futures) != 1:
        result["status"] = "symbol missing from metadata"
        return result
    spot, future = spots[0], futures[0]
    if (spot.get("status") != "TRADING"
            or future.get("status") != "TRADING"
            or future.get("contractType") != "PERPETUAL"
            or future.get("marginAsset") != "USDT"):
        result["status"] = "spot or perpetual not trading"
        return result
    spot_asks = spot_read["payload"].get("asks", [])
    future_bids = future_read["payload"].get("bids", [])
    if not spot_asks or not future_bids:
        result["status"] = "required book side is empty"
        return result
    spot_step, spot_min, spot_max = quantity_rules(spot)
    future_step, future_min, future_max = quantity_rules(future)
    step = step_for_both(spot_step, future_step)
    minimum = max(spot_min, future_min)
    maximum = min(spot_max, future_max)
    spot_receive = datetime.fromisoformat(spot_read["received_utc"])
    future_receive = datetime.fromisoformat(future_read["received_utc"])
    offset = abs((spot_receive - future_receive).total_seconds())
    age = (int(clock["payload"]["serverTime"])
           - int(future_read["payload"]["T"])) / 1000
    timely = 0 <= age <= 10 and offset <= 5
    best_spot_ask = Decimal(spot_asks[0][0])
    result.update({
        "status": "evaluated",
        "forecast_30d_lower_of_3d_7d": float(forecast),
        "future_book_age_seconds": age,
        "spot_future_receive_offset_seconds": offset,
        "timely_under_protocol": timely,
        "common_lot_step": str(step),
    })
    for target in TARGETS:
        quantity = (Decimal(target) / best_spot_ask / step).to_integral_value(
            rounding=ROUND_DOWN) * step
        row = {"intended_spot_notional": target, "rounded_quantity": str(quantity)}
        if quantity < minimum or quantity > maximum:
            row["status"] = "quantity outside lot limits"
        else:
            spot_vwap, visible_spot = marketable_vwap(spot_asks, quantity)
            future_vwap, visible_future = marketable_vwap(future_bids, quantity)
            row["visible_spot_ask_quantity"] = str(visible_spot)
            row["visible_future_bid_quantity"] = str(visible_future)
            if spot_vwap is None or future_vwap is None:
                row["status"] = "insufficient displayed entry depth"
            else:
                spot_value = quantity * spot_vwap
                future_value = quantity * future_vwap
                minimums = [Decimal(str(item["minNotional"]))
                            for item in spot["filters"]
                            if item.get("filterType") in ("NOTIONAL", "MIN_NOTIONAL")]
                if minimums and spot_value < max(minimums):
                    row["status"] = "spot cost below minimum notional"
                else:
                    basis = future_value - spot_value
                    funding = forecast * spot_value
                    spot_fees = SPOT_TAKER * spot_value * 2
                    future_fees = FUTURE_TAKER * (future_value + spot_value)
                    extra_slippage = SLIPPAGE_PER_SIDE * spot_value * 4
                    pair_stress = EXTRA_PAIR_COST * spot_value
                    uncertainty = EXTRA_UNCERTAINTY * spot_value
                    capital = CAPITAL_MULTIPLE * spot_value
                    capital_charge = (
                        ANNUAL_CAPITAL_CHARGE * capital * HOLD_DAYS / 365)
                    net = (basis + funding - spot_fees - future_fees
                           - extra_slippage - pair_stress - uncertainty
                           - capital_charge)
                    annualized = net / capital * 365 / HOLD_DAYS
                    row.update({
                        "status": "conditional 30-day scenario only",
                        "spot_ask_vwap": float(spot_vwap),
                        "future_bid_vwap": float(future_vwap),
                        "spot_entry_value": float(spot_value),
                        "future_entry_value": float(future_value),
                        "entry_basis_cash": float(basis),
                        "forecast_funding_cash": float(funding),
                        "spot_entry_exit_fees": float(spot_fees),
                        "future_entry_exit_fees": float(future_fees),
                        "extra_slippage": float(extra_slippage),
                        "pair_stress": float(pair_stress),
                        "extra_uncertainty": float(uncertainty),
                        "capital_charge": float(capital_charge),
                        "reserved_capital": float(capital),
                        "conditional_net_cash": float(net),
                        "annualized_conditional_return_on_reserved_capital": (
                            float(annualized)),
                    })
        row["qualifies_for_forward_observation"] = (
            timely and row.get("status") == "conditional 30-day scenario only"
            and row["conditional_net_cash"] > 0
            and row["annualized_conditional_return_on_reserved_capital"]
            >= float(MIN_ANNUALIZED))
        result["sizes"].append(row)
    result["both_sizes_qualify"] = all(
        row["qualifies_for_forward_observation"] for row in result["sizes"])
    return result


def main() -> None:
    raw_input = INPUT.read_bytes()
    digest = hashlib.sha256(raw_input).hexdigest()
    if digest != INPUT_SHA256:
        raise ValueError(f"funding input SHA256 mismatch: {digest}")
    funding = json.loads(raw_input)
    if tuple(funding["candidate_symbols"]) != SYMBOLS:
        raise ValueError("funding candidate symbols differ from frozen protocol")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    report = {
        "protocol": "docs/binance_recent_carry_entry_quote_protocol.md",
        "protocol_commit": commit,
        "funding_input_sha256": digest,
        "started_utc": utc_now(),
        "symbols": SYMBOLS, "targets": TARGETS,
        "hold_days": str(HOLD_DAYS),
        "cost_assumptions": {
            "spot_taker_per_side": str(SPOT_TAKER),
            "future_taker_per_side": str(FUTURE_TAKER),
            "extra_slippage_per_side": str(SLIPPAGE_PER_SIDE),
            "additional_pair_stress": str(EXTRA_PAIR_COST),
            "extra_uncertainty": str(EXTRA_UNCERTAINTY),
            "annual_capital_charge": str(ANNUAL_CAPITAL_CHARGE),
            "reserved_capital_multiple": str(CAPITAL_MULTIPLE),
            "minimum_annualized_return": str(MIN_ANNUALIZED),
        },
        "metadata": {}, "sources": {}, "results": {},
        "limits": "Funding persistence and exit basis assumed, no orders, fills, actual account fees or margin path",
    }
    spot_metadata = read_public(SPOT_API, "/api/v3/exchangeInfo")
    future_metadata = read_public(FUTURE_API, "/fapi/v1/exchangeInfo")
    metadata = {"spot": spot_metadata, "future": future_metadata}
    report["metadata"] = metadata
    for symbol in SYMBOLS:
        input_row = funding["results"][symbol]
        forecast = Decimal(str(min(input_row["projected_30d_from_7d"],
                                   input_row["projected_30d_from_3d"])))
        with ThreadPoolExecutor(max_workers=2) as pool:
            spot_task = pool.submit(read_public, SPOT_API, "/api/v3/depth", {
                "symbol": symbol, "limit": 100})
            future_task = pool.submit(read_public, FUTURE_API, "/fapi/v1/depth", {
                "symbol": symbol, "limit": 100})
            spot_read, future_read = spot_task.result(), future_task.result()
        clock = read_public(FUTURE_API, "/fapi/v1/time")
        report["sources"][symbol] = {
            "spot_book": spot_read, "future_book": future_read,
            "future_clock": clock,
        }
        try:
            result = evaluate(symbol, forecast, metadata,
                              spot_read, future_read, clock)
        except (ValueError, KeyError, TypeError, IndexError,
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
