"""Read-only post-observation quote screen of all listed Bybit native carry combos."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from bybit_native_spread_entry_economics import (
    API, ROOT, evaluate, now_utc, read_public,
)


BASES = ("BTC", "ETH", "SOL")
OUTPUT = ROOT / "outputs/bybit_native_carry_universe_screen.json"
PROTOCOL_COMMIT = "6b0c2ae"
EXTRA_ADVERSE_FRICTION = 0.0025
MIN_DAYS_TO_DELIVERY = 30
MIN_ANNUALIZED_STRESSED_RETURN = 0.04


def instrument_pages(base: str) -> tuple[list[dict], list[dict], bool]:
    pages = []
    metadata = []
    cursor = None
    seen_cursors = set()
    for _ in range(100):
        params = {"baseCoin": base, "limit": 500}
        if cursor:
            params["cursor"] = cursor
        page = read_public("/v5/spread/instrument", params)
        pages.append(page)
        if page["status"] != "ok":
            return pages, metadata, False
        body = page["payload"]["result"]
        metadata.extend(body.get("list", []))
        cursor = body.get("nextPageCursor") or None
        if not cursor:
            return pages, metadata, True
        if cursor in seen_cursors:
            return pages, metadata, False
        seen_cursors.add(cursor)
    return pages, metadata, False


def calculate(base: str, meta: dict, spread_read: dict, spot_read: dict) -> dict:
    synthetic_instrument = {
        "status": "ok", "payload": {"result": {"list": [meta]}}}
    calls = {
        "instrument": synthetic_instrument,
        "spread_book": spread_read,
        "spot_book": spot_read,
    }
    try:
        result = evaluate(base, calls, meta["symbol"])
    except (ValueError, TypeError, KeyError, IndexError, ZeroDivisionError) as error:
        return {"symbol": meta.get("symbol"), "status": "evaluation error",
                "reason": str(error), "preliminary_candidate": False}
    result["preliminary_candidate"] = False
    if result["status"] != "evaluated":
        return result
    for row in result["sizes"]:
        if row.get("status") == "conditional estimate only":
            extra_cost = EXTRA_ADVERSE_FRICTION * row["actual_spot_notional"]
            stressed_net = row["conditional_net_cash"] - extra_cost
            stressed_return = stressed_net / row["reserved_capital"]
            row["extra_adverse_friction"] = extra_cost
            row["stressed_net_cash"] = stressed_net
            row["stressed_return_on_reserved_capital"] = stressed_return
            row["annualized_stressed_return_on_reserved_capital"] = (
                stressed_return * 365 / result["days_to_delivery"])
    result["preliminary_candidate"] = (
        result["current_under_fixed_protocol"]
        and result["days_to_delivery"] >= MIN_DAYS_TO_DELIVERY
        and len(result["sizes"]) == 2
        and all(row.get("status") == "conditional estimate only"
                and row["annualized_stressed_return_on_reserved_capital"]
                >= MIN_ANNUALIZED_STRESSED_RETURN
                for row in result["sizes"]))
    return result


def main() -> None:
    report = {
        "protocol": "docs/bybit_native_carry_universe_protocol.md",
        "protocol_commit": PROTOCOL_COMMIT,
        "started_utc": now_utc(), "source": API,
        "extra_adverse_friction_spot_notional": EXTRA_ADVERSE_FRICTION,
        "minimum_days_to_delivery_for_candidate": MIN_DAYS_TO_DELIVERY,
        "minimum_annualized_stressed_capital_return_for_candidate": (
            MIN_ANNUALIZED_STRESSED_RETURN),
        "metadata_pages": {}, "spot_books": {}, "spread_books": {},
        "results": {}, "universe_complete": True,
        "limits": "Quote-only screen; no fills, actual account fees, collateral, future path or realized profit; no orders submitted",
    }
    for base in BASES:
        pages, metadata, complete = instrument_pages(base)
        report["metadata_pages"][base] = pages
        report["universe_complete"] = report["universe_complete"] and complete
        eligible = sorted((item for item in metadata
                           if item.get("contractType") == "CarryTrade"
                           and item.get("status") == "Trading"
                           and int(item.get("deliveryTime", 0)) > time.time() * 1000),
                          key=lambda item: item["symbol"])
        print(base, "metadata", len(metadata), "eligible", len(eligible),
              "complete", complete, flush=True)
        with ThreadPoolExecutor(max_workers=12) as pool:
            spot_future = pool.submit(read_public, "/v5/market/orderbook", {
                "category": "spot", "symbol": f"{base}USDT", "limit": 25})
            futures = {pool.submit(read_public, "/v5/spread/orderbook", {
                "symbol": item["symbol"], "limit": 25}): item
                       for item in eligible}
            spread_reads = {}
            for future in as_completed(futures):
                item = futures[future]
                spread_reads[item["symbol"]] = future.result()
                print(base, item["symbol"],
                      spread_reads[item["symbol"]]["status"], flush=True)
            spot_read = spot_future.result()
        report["spot_books"][base] = spot_read
        for item in eligible:
            name = item["symbol"]
            report["spread_books"][name] = spread_reads[name]
            report["results"][name] = calculate(base, item, spread_reads[name],
                                                 spot_read)
    report["finished_utc"] = now_utc()
    report["summary"] = {
        "eligible_combos": len(report["results"]),
        "evaluated": sum(row["status"] == "evaluated"
                         for row in report["results"].values()),
        "current_under_fixed_protocol": sum(
            row.get("current_under_fixed_protocol", False)
            for row in report["results"].values()),
        "preliminary_candidates": [name for name, row in report["results"].items()
                                   if row["preliminary_candidate"]],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2), flush=True)
    print("saved", OUTPUT, flush=True)


if __name__ == "__main__":
    main()
