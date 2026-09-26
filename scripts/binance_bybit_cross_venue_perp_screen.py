"""Read-only, fixed Binance-Bybit perpetual funding/entry quote screen."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal, ROUND_DOWN

from binance_dec26_forward_quote import (
    FUTURE_API, ROOT, marketable_vwap, one_filter, read_public as binance_read,
    step_for_both, utc_now,
)
from binance_recent_carry_entry_quote import INPUT, INPUT_SHA256
from bybit_native_spread_entry_economics import read_public as bybit_read
from laya_trader.config import load_config


SYMBOLS = tuple(load_config(ROOT / "configs/dataset.toml").data.symbols)
TARGETS = (500, 1000)
DIRECTIONS = ("long_binance_short_bybit", "long_bybit_short_binance")
REPORT = ROOT / "outputs/binance_bybit_cross_venue_perp_screen.json"
HOLD_DAYS = Decimal(30)
BINANCE_TAKER = Decimal("0.0005")
BYBIT_TAKER = Decimal("0.00055")
SLIPPAGE_PER_SIDE = Decimal("0.0002")
PAIR_STRESS = Decimal("0.0008")
UNCERTAINTY = Decimal("0.0025")
CAPITAL_MULTIPLE = Decimal("2.05")
ANNUAL_CAPITAL_CHARGE = Decimal("0.01")
MIN_ANNUALIZED = Decimal("0.04")
MAX_BOOK_AGE_SECONDS = 10
MAX_RECEIVE_OFFSET_SECONDS = 5
MAX_FUNDING_PAGES = 100


def bybit_funding_pages(symbol: str, start_ms: int, end_ms: int,
                        interval_ms: int) -> tuple[list[dict], list[dict], bool]:
    pages: list[dict] = []
    rows: list[dict] = []
    cursor_end = end_ms
    for _ in range(MAX_FUNDING_PAGES):
        page = bybit_read("/v5/market/funding/history", {
            "category": "linear", "symbol": symbol,
            "startTime": start_ms, "endTime": cursor_end, "limit": 200,
        })
        pages.append(page)
        if page["status"] != "ok":
            return pages, rows, False
        batch = page["payload"].get("result", {}).get("list", [])
        if not isinstance(batch, list) or not batch:
            return pages, rows, False
        rows.extend(batch)
        oldest = min(int(item["fundingRateTimestamp"]) for item in batch)
        if oldest <= start_ms + interval_ms * 1.25:
            return pages, rows, True
        if len(batch) < 200 or oldest >= cursor_end:
            return pages, rows, False
        cursor_end = oldest - 1
    return pages, rows, False


def bybit_projection(symbol: str, rows: list[dict], start_ms: int, end_ms: int,
                     interval_ms: int, pagination_complete: bool) -> dict:
    result = {"status": "incomplete funding", "pagination_complete": pagination_complete}
    if not pagination_complete:
        return result
    ordered = sorted(rows, key=lambda row: int(row["fundingRateTimestamp"]))
    times = [int(row["fundingRateTimestamp"]) for row in ordered]
    rates = [float(row["fundingRate"]) for row in ordered]
    bound = interval_ms * 1.25
    recent_start = end_ms - 3 * 86_400_000
    recent = [(time, rate) for time, rate in zip(times, rates)
              if time >= recent_start]
    if (not times or any(row.get("symbol") != symbol for row in ordered)
            or len(times) != len(set(times))
            or any(not start_ms <= time <= end_ms for time in times)
            or any(not math.isfinite(rate) for rate in rates)
            or times[0] - start_ms > bound or end_ms - times[-1] > bound
            or any(right - left > bound for left, right in zip(times, times[1:]))
            or not recent or recent[0][0] - recent_start > bound
            or end_ms - recent[-1][0] > bound
            or any(right[0] - left[0] > bound
                   for left, right in zip(recent, recent[1:]))):
        return result
    result.update({
        "status": "evaluated",
        "settlements_7d": len(times), "settlements_3d": len(recent),
        "first_settlement_ms": times[0], "last_settlement_ms": times[-1],
        "sum_rates_7d": sum(rates),
        "sum_rates_3d": sum(rate for _, rate in recent),
        "projected_30d_from_7d": sum(rates) * 30 / 7,
        "projected_30d_from_3d": sum(rate for _, rate in recent) * 30 / 3,
    })
    return result


def binance_lot(symbol: dict) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    lot = one_filter(symbol, "LOT_SIZE")
    market = next((item for item in symbol["filters"]
                   if item.get("filterType") == "MARKET_LOT_SIZE"), None)
    step = Decimal(lot["stepSize"])
    minimum = Decimal(lot["minQty"])
    maximum = Decimal(lot["maxQty"])
    if market is not None and Decimal(market["stepSize"]) > 0:
        step = step_for_both(step, Decimal(market["stepSize"]))
        minimum = max(minimum, Decimal(market["minQty"]))
        maximum = min(maximum, Decimal(market["maxQty"]))
    minimum_notional = max((Decimal(item.get("notional", "0"))
                            for item in symbol["filters"]
                            if item.get("filterType") == "MIN_NOTIONAL"),
                           default=Decimal(0))
    return step, minimum, maximum, minimum_notional


def bybit_lot(symbol: dict) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    lot = symbol["lotSizeFilter"]
    return (Decimal(lot["qtyStep"]), Decimal(lot["minOrderQty"]),
            min(Decimal(lot["maxOrderQty"]),
                Decimal(lot.get("maxMktOrderQty", lot["maxOrderQty"]))),
            Decimal(lot.get("minNotionalValue", "0")))


def evaluate_books(symbol: str, binance_meta: dict, bybit_meta: dict,
                   binance_book: dict, bybit_book: dict,
                   binance_clock: dict, bybit_clock: dict,
                   forecasts: dict[str, Decimal]) -> dict:
    result = {"symbol": symbol, "status": "unassessable", "directions": {}}
    if any(source["status"] != "ok" for source in (
            binance_meta, bybit_meta, binance_book, bybit_book,
            binance_clock, bybit_clock)):
        result["status"] = "required public API read failed"
        return result
    bm = [item for item in binance_meta["payload"].get("symbols", [])
          if item.get("symbol") == symbol]
    ym = [item for item in bybit_meta["payload"].get("result", {}).get("list", [])
          if item.get("symbol") == symbol]
    if len(bm) != 1 or len(ym) != 1:
        result["status"] = "missing metadata"
        return result
    bmeta, ymeta = bm[0], ym[0]
    if (bmeta.get("status") != "TRADING"
            or bmeta.get("contractType") != "PERPETUAL"
            or bmeta.get("marginAsset") != "USDT"
            or ymeta.get("status") != "Trading"
            or ymeta.get("contractType") != "LinearPerpetual"
            or ymeta.get("settleCoin") != "USDT"):
        result["status"] = "instrument not active USDT perpetual"
        return result
    bbook = binance_book["payload"]
    ybook = bybit_book["payload"].get("result", {})
    if (ybook.get("s") != symbol or not bbook.get("bids")
            or not bbook.get("asks") or not ybook.get("b")
            or not ybook.get("a")):
        result["status"] = "missing book side or wrong symbol"
        return result
    bstep, bmin, bmax, bnotional = binance_lot(bmeta)
    ystep, ymin, ymax, ynotional = bybit_lot(ymeta)
    step = step_for_both(bstep, ystep)
    minimum, maximum = max(bmin, ymin), min(bmax, ymax)
    b_age = (int(binance_clock["payload"]["serverTime"])
             - int(bbook["T"])) / 1000
    y_time = int(bybit_clock["payload"]["time"])
    y_age = (y_time - int(ybook["cts"])) / 1000
    b_received = datetime.fromisoformat(binance_book["received_utc"])
    y_received = datetime.fromisoformat(bybit_book["received_utc"])
    offset = abs((b_received - y_received).total_seconds())
    timely = (0 <= b_age <= MAX_BOOK_AGE_SECONDS
              and 0 <= y_age <= MAX_BOOK_AGE_SECONDS
              and offset <= MAX_RECEIVE_OFFSET_SECONDS)
    result.update({
        "status": "evaluated", "common_lot_step": str(step),
        "binance_book_age_seconds": b_age,
        "bybit_book_age_seconds": y_age,
        "receive_offset_seconds": offset, "timely": timely,
    })
    for direction in DIRECTIONS:
        long_binance = direction == "long_binance_short_bybit"
        long_asks = bbook["asks"] if long_binance else ybook["a"]
        short_bids = ybook["b"] if long_binance else bbook["bids"]
        forecast = forecasts[direction]
        rows = []
        best_ask = Decimal(long_asks[0][0])
        for target in TARGETS:
            quantity = (Decimal(target) / best_ask / step).to_integral_value(
                rounding=ROUND_DOWN) * step
            row = {"intended_long_notional": target,
                   "rounded_quantity": str(quantity)}
            if quantity < minimum or quantity > maximum:
                row["status"] = "quantity outside lot limits"
            else:
                ask, ask_visible = marketable_vwap(long_asks, quantity)
                bid, bid_visible = marketable_vwap(short_bids, quantity)
                row["visible_long_ask_quantity"] = str(ask_visible)
                row["visible_short_bid_quantity"] = str(bid_visible)
                if ask is None or bid is None:
                    row["status"] = "insufficient displayed entry depth"
                else:
                    long_value, short_value = quantity * ask, quantity * bid
                    b_entry = long_value if long_binance else short_value
                    y_entry = short_value if long_binance else long_value
                    if (b_entry < bnotional or y_entry < ynotional):
                        row["status"] = "below venue minimum notional"
                    else:
                        common_exit = long_value
                        basis = short_value - long_value
                        funding = forecast * long_value
                        b_fee = BINANCE_TAKER * (b_entry + common_exit)
                        y_fee = BYBIT_TAKER * (y_entry + common_exit)
                        slippage = SLIPPAGE_PER_SIDE * long_value * 4
                        pair_stress = PAIR_STRESS * long_value
                        uncertainty = UNCERTAINTY * long_value
                        capital = CAPITAL_MULTIPLE * long_value
                        capital_charge = (ANNUAL_CAPITAL_CHARGE * capital
                                          * HOLD_DAYS / 365)
                        net = (basis + funding - b_fee - y_fee - slippage
                               - pair_stress - uncertainty - capital_charge)
                        annualized = net / capital * 365 / HOLD_DAYS
                        row.update({
                            "status": "conditional 30-day scenario only",
                            "long_ask_vwap": float(ask),
                            "short_bid_vwap": float(bid),
                            "entry_long_value": float(long_value),
                            "entry_short_value": float(short_value),
                            "entry_basis_cash": float(basis),
                            "forecast_net_funding_30d": float(forecast),
                            "forecast_funding_cash": float(funding),
                            "binance_fees": float(b_fee),
                            "bybit_fees": float(y_fee),
                            "extra_slippage": float(slippage),
                            "pair_stress": float(pair_stress),
                            "uncertainty": float(uncertainty),
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
            rows.append(row)
        result["directions"][direction] = {
            "sizes": rows,
            "both_sizes_qualify": all(
                row["qualifies_for_forward_observation"] for row in rows),
        }
    return result


def main() -> None:
    raw_input = INPUT.read_bytes()
    digest = hashlib.sha256(raw_input).hexdigest()
    if digest != INPUT_SHA256:
        raise ValueError(f"Binance funding input SHA256 mismatch: {digest}")
    funding = json.loads(raw_input)
    if tuple(funding["symbols"]) != SYMBOLS or funding.get("status") != "complete":
        raise ValueError("Binance funding input incomplete or wrong universe")
    start_ms, end_ms = int(funding["start_ms"]), int(funding["end_ms"])
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    report = {
        "protocol": "docs/binance_bybit_cross_venue_perp_protocol.md",
        "protocol_commit": commit,
        "binance_funding_input_sha256": digest,
        "started_utc": utc_now(), "symbols": SYMBOLS,
        "directions": DIRECTIONS, "targets": TARGETS,
        "funding_window_start_ms": start_ms,
        "funding_window_end_ms": end_ms,
        "hold_days": str(HOLD_DAYS),
        "cost_assumptions": {
            "binance_taker_per_side": str(BINANCE_TAKER),
            "bybit_taker_per_side": str(BYBIT_TAKER),
            "extra_slippage_per_side": str(SLIPPAGE_PER_SIDE),
            "pair_stress": str(PAIR_STRESS),
            "uncertainty": str(UNCERTAINTY),
            "reserved_capital_multiple": str(CAPITAL_MULTIPLE),
            "annual_capital_charge": str(ANNUAL_CAPITAL_CHARGE),
            "minimum_annualized_return": str(MIN_ANNUALIZED),
        },
        "sources": {}, "results": {},
        "limits": "Future funding, exit basis, account fees, fills, collateral and margin path unverified; no orders",
    }
    binance_meta = binance_read(FUTURE_API, "/fapi/v1/exchangeInfo")
    report["sources"]["binance_metadata"] = binance_meta
    for symbol in SYMBOLS:
        sources = {}
        report["sources"][symbol] = sources
        bybit_meta = bybit_read("/v5/market/instruments-info", {
            "category": "linear", "symbol": symbol,
        })
        sources["bybit_metadata"] = bybit_meta
        matches = []
        if bybit_meta["status"] == "ok":
            matches = [item for item in bybit_meta["payload"].get("result", {}).get("list", [])
                       if item.get("symbol") == symbol]
        if len(matches) != 1:
            report["results"][symbol] = {
                "symbol": symbol, "status": "missing Bybit metadata"}
            print(symbol, "missing Bybit metadata", flush=True)
            continue
        interval_ms = int(matches[0]["fundingInterval"]) * 60_000
        if interval_ms <= 0:
            report["results"][symbol] = {
                "symbol": symbol, "status": "invalid Bybit funding interval"}
            print(symbol, "invalid Bybit funding interval", flush=True)
            continue
        pages, rows, complete = bybit_funding_pages(
            symbol, start_ms, end_ms, interval_ms)
        sources["bybit_funding_pages"] = pages
        try:
            projection = bybit_projection(
                symbol, rows, start_ms, end_ms, interval_ms, complete)
        except (ValueError, KeyError, TypeError, IndexError) as error:
            projection = {"status": "evaluation error", "reason": str(error)}
        binance_row = funding["results"][symbol]
        if projection["status"] != "evaluated" or binance_row["status"] != "evaluated":
            report["results"][symbol] = {
                "symbol": symbol, "status": "funding unavailable",
                "bybit_projection": projection,
                "binance_funding_status": binance_row["status"],
            }
            print(symbol, "funding unavailable", flush=True)
            continue
        b7 = Decimal(str(binance_row["projected_30d_from_7d"]))
        b3 = Decimal(str(binance_row["projected_30d_from_3d"]))
        y7 = Decimal(str(projection["projected_30d_from_7d"]))
        y3 = Decimal(str(projection["projected_30d_from_3d"]))
        forecasts = {
            DIRECTIONS[0]: min(y7 - b7, y3 - b3),
            DIRECTIONS[1]: min(b7 - y7, b3 - y3),
        }
        with ThreadPoolExecutor(max_workers=2) as pool:
            btask = pool.submit(binance_read, FUTURE_API, "/fapi/v1/depth", {
                "symbol": symbol, "limit": 100,
            })
            ytask = pool.submit(bybit_read, "/v5/market/orderbook", {
                "category": "linear", "symbol": symbol, "limit": 100,
            })
            bbook, ybook = btask.result(), ytask.result()
        with ThreadPoolExecutor(max_workers=2) as pool:
            btask = pool.submit(binance_read, FUTURE_API, "/fapi/v1/time")
            ytask = pool.submit(bybit_read, "/v5/market/time", {})
            bclock, yclock = btask.result(), ytask.result()
        sources.update({
            "binance_book": bbook, "bybit_book": ybook,
            "binance_clock": bclock, "bybit_clock": yclock,
        })
        try:
            result = evaluate_books(symbol, binance_meta, bybit_meta,
                                    bbook, ybook, bclock, yclock, forecasts)
        except (ValueError, KeyError, TypeError, IndexError,
                ArithmeticError) as error:
            result = {"symbol": symbol, "status": "evaluation error",
                      "reason": str(error), "directions": {}}
        result["bybit_projection"] = projection
        result["funding_forecast_30d_by_direction"] = {
            direction: float(value) for direction, value in forecasts.items()}
        report["results"][symbol] = result
        print(symbol, result["status"], flush=True)
        for direction, data in result.get("directions", {}).items():
            for row in data["sizes"]:
                print(" ", direction, row["intended_long_notional"],
                      row["status"], "net", row.get("conditional_net_cash"),
                      "annualized", row.get(
                          "annualized_conditional_return_on_reserved_capital"),
                      flush=True)
    report["candidate_symbol_directions"] = [
        {"symbol": symbol, "direction": direction}
        for symbol in SYMBOLS
        for direction in DIRECTIONS
        if report["results"][symbol].get("directions", {}).get(
            direction, {}).get("both_sizes_qualify", False)
    ]
    report["finished_utc"] = utc_now()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("candidate symbol/directions", report["candidate_symbol_directions"],
          flush=True)
    print("saved", REPORT, flush=True)


if __name__ == "__main__":
    main()
