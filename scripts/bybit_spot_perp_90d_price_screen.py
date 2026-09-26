"""Fixed Bybit spot-perpetual 90-day adverse-price and funding screen."""

from __future__ import annotations

import hashlib
import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed

from bybit_native_funding_only_screen import BASES, WINDOWS, utc_ms
from bybit_native_spread_entry_economics import ROOT, now_utc, read_public


SOURCE = ROOT / "outputs/bybit_native_funding_only_screen.json"
SOURCE_SHA256 = "0556180273221016b17a736bb07ae40d2e880cb0b16e993c7c4428f12dfbca7c"
REPORT = ROOT / "outputs/bybit_spot_perp_90d_price_screen.json"
PROTOCOL_COMMIT = "199c758"
SPOT_TAKER = 0.001
PERP_TAKER = 0.00055
ADVERSE_EXECUTION = 0.0025
CAPITAL_MULTIPLE = 2.025
ANNUAL_CAPITAL_CHARGE = 0.01
MIN_ANNUALIZED_RETURN = 0.04
MINUTE_MS = 60_000
STARTS = sorted({day for window in WINDOWS for day in window})


def load_funding() -> dict:
    raw = SOURCE.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != SOURCE_SHA256:
        raise ValueError(f"funding report SHA256 changed: {actual}")
    data = json.loads(raw)
    for base in BASES:
        symbol = data["results"][base]
        if not symbol["assessable"] or len(symbol["windows"]) != len(WINDOWS):
            raise ValueError(f"funding source incomplete: {base}")
        for expected, row in zip(WINDOWS, symbol["windows"]):
            if (not row["complete"] or (row["start_utc"], row["end_utc"]) != expected):
                raise ValueError(f"funding window incomplete or reordered: {base} {expected}")
    return data


def read_window(task: tuple[str, str, str]) -> tuple[tuple[str, str, str], dict]:
    base, category, day = task
    start = utc_ms(day)
    response = read_public("/v5/market/kline", {
        "category": category, "symbol": f"{base}USDT", "interval": "1",
        "start": start, "end": start + 5 * MINUTE_MS - 1, "limit": 5})
    return task, response


def price_extremes(task: tuple[str, str, str], response: dict) -> dict:
    base, category, day = task
    result = {"base": base, "category": category, "day": day}
    if response["status"] != "ok":
        result["status"] = "API failure"
        return result
    body = response["payload"].get("result", {})
    if body.get("category") != category or body.get("symbol") != f"{base}USDT":
        result["status"] = "wrong market or symbol"
        return result
    rows = body.get("list", [])
    expected = {utc_ms(day) + index * MINUTE_MS for index in range(5)}
    try:
        starts = [int(row[0]) for row in rows]
        if len(rows) != 5 or set(starts) != expected:
            result.update({"status": "missing or duplicate minute",
                           "received_start_times": starts})
            return result
        prices = []
        for row in rows:
            high, low, volume = float(row[2]), float(row[3]), float(row[5])
            if (not all(math.isfinite(value) for value in (high, low, volume))
                    or high < low or low <= 0 or volume <= 0):
                result["status"] = "invalid price or no traded volume"
                return result
            prices.append((high, low))
    except (TypeError, ValueError, IndexError) as error:
        result.update({"status": "malformed kline", "reason": str(error)})
        return result
    result.update({"status": "complete", "highest_trade_price": max(
        high for high, _ in prices), "lowest_trade_price": min(
        low for _, low in prices), "minute_count": len(rows)})
    return result


def calculate_period(base: str, index: int, prices: dict, funding: dict) -> dict:
    entry, exit_day = WINDOWS[index]
    result = {"symbol": f"{base}USDT", "entry_utc": entry,
              "exit_utc": exit_day}
    keys = ((base, "spot", entry), (base, "linear", entry),
            (base, "spot", exit_day), (base, "linear", exit_day))
    if any(prices[key]["status"] != "complete" for key in keys):
        result["status"] = "required price window unavailable"
        result["input_statuses"] = {"/".join(key): prices[key]["status"]
                                    for key in keys}
        return result
    spot_entry = prices[keys[0]]["highest_trade_price"]
    perp_entry = prices[keys[1]]["lowest_trade_price"]
    spot_exit = prices[keys[2]]["lowest_trade_price"]
    perp_exit = prices[keys[3]]["highest_trade_price"]
    quantity = 1 / spot_entry
    funding_rate_sum = funding["results"][base]["windows"][index][
        "funding_sum_on_fixed_reference_notional"]
    spot_pnl = quantity * (spot_exit - spot_entry)
    perp_pnl = quantity * (perp_entry - perp_exit)
    funding_cash = quantity * perp_entry * funding_rate_sum
    fees = quantity * (SPOT_TAKER * (spot_entry + spot_exit)
                       + PERP_TAKER * (perp_entry + perp_exit))
    days = (utc_ms(exit_day) - utc_ms(entry)) / (1000 * 60 * 60 * 24)
    capital_charge = ANNUAL_CAPITAL_CHARGE * CAPITAL_MULTIPLE * days / 365
    net = (spot_pnl + perp_pnl + funding_cash - fees
           - ADVERSE_EXECUTION - capital_charge)
    result.update({
        "status": "complete price-only proxy",
        "spot_entry_high": spot_entry, "perp_entry_low": perp_entry,
        "spot_exit_low": spot_exit, "perp_exit_high": perp_exit,
        "quantity_per_initial_spot_notional": quantity,
        "funding_rate_sum": funding_rate_sum,
        "spot_pnl": spot_pnl, "perp_pnl": perp_pnl,
        "funding_cash_fixed_entry_perp_notional": funding_cash,
        "ordinary_leg_taker_fees": fees,
        "adverse_execution_stress": ADVERSE_EXECUTION,
        "capital_charge": capital_charge,
        "net_cash_per_initial_spot_notional": net,
        "return_on_reserved_capital": net / CAPITAL_MULTIPLE,
    })
    return result


def main() -> None:
    funding = load_funding()
    tasks = [(base, category, day) for base in BASES
             for category in ("spot", "linear") for day in STARTS]
    report = {
        "protocol": "docs/bybit_spot_perp_90d_price_protocol.md",
        "protocol_commit": PROTOCOL_COMMIT,
        "funding_source_sha256": SOURCE_SHA256,
        "started_utc": now_utc(),
        "costs": {
            "spot_taker_each_side": SPOT_TAKER,
            "perp_taker_each_side": PERP_TAKER,
            "adverse_execution_initial_spot_notional": ADVERSE_EXECUTION,
            "annual_capital_charge": ANNUAL_CAPITAL_CHARGE,
            "reserved_capital_multiple": CAPITAL_MULTIPLE,
        },
        "raw_kline_responses": {}, "price_windows": {}, "results": {},
        "limits": "Separately adverse trade-bar extremes are not synchronized bid/ask fills; funding fixed to entry perp notional; no native combo book, account fees, collateral or margin path; no orders submitted",
    }
    responses = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(read_window, task) for task in tasks]
        for count, future in enumerate(as_completed(futures), 1):
            task, response = future.result()
            responses[task] = response
            print("kline", count, "/", len(tasks), task,
                  response["status"], flush=True)
    prices = {task: price_extremes(task, responses[task]) for task in tasks}
    report["raw_kline_responses"] = {"/".join(task): responses[task]
                                     for task in tasks}
    report["price_windows"] = {"/".join(task): prices[task] for task in tasks}
    for base in BASES:
        periods = [calculate_period(base, index, prices, funding)
                   for index in range(len(WINDOWS))]
        complete = all(row["status"] == "complete price-only proxy"
                       for row in periods)
        result = {"periods": periods, "assessable": complete,
                  "research_gate_pass": False}
        if complete:
            returns = [row["return_on_reserved_capital"] for row in periods]
            annualized = sum(returns) / len(returns) * 365 / 30
            result["mean_monthly_annualized_reserved_capital_return"] = annualized
            result["research_gate_pass"] = (all(value > 0 for value in returns)
                                            and annualized >= MIN_ANNUALIZED_RETURN)
        report["results"][base] = result
        print(base, "assessable", complete, "gate", result["research_gate_pass"],
              [row.get("return_on_reserved_capital") for row in periods],
              flush=True)
    report["finished_utc"] = now_utc()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("saved", REPORT, flush=True)


if __name__ == "__main__":
    main()
