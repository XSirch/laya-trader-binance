"""Read-only screen of archived USD-M delivery-future entry basis."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import pandas as pd

from laya_trader.progress import ProgressReporter

from quarterly_basis_final_2026 import (
    FUTURE_COST, INITIAL_CAPITAL, SPOT_COST, fetch_minute_verified,
)
from quarterly_basis_minute_probe import first_minutes
from spot_perp_carry_probe import ROOT


SYMBOLS = ("BTCUSDT", "ETHUSDT")
SPOT_ALLOCATION_PER_LEG = 0.5
EXIT_PRICE_MULTIPLIERS = (0.5, 1.0, 2.0)


def screen(day: str, expiry: str) -> dict:
    if date.fromisoformat(day).isoformat() != day:
        raise ValueError("Day must use YYYY-MM-DD")
    if date.fromisoformat(expiry).isoformat() != expiry:
        raise ValueError("Expiry must use YYYY-MM-DD")
    observed_day = pd.Timestamp(day, tz="UTC")
    expiry_day = pd.Timestamp(expiry, tz="UTC")
    if expiry_day <= observed_day:
        raise ValueError("Expiry must follow the archived observation day")
    suffix = expiry_day.strftime("%y%m%d")
    tasks = [(market, symbol if market == "spot" else f"{symbol}_{suffix}", day)
             for symbol in SYMBOLS for market in ("spot", "future")]
    source_results = []
    progress = ProgressReporter("delivery basis archives", len(tasks), unit="archives")
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fetch_minute_verified, task) for task in tasks]
        for count, future in enumerate(as_completed(futures), 1):
            result = future.result()
            source_results.append(result)
            progress.update(count)
    bad = [row for row in source_results if row["status"] != "verified"]
    if bad:
        raise RuntimeError(f"Required archived prices unavailable: {bad}")

    legs = []
    for symbol in SYMBOLS:
        contract = f"{symbol}_{suffix}"
        spot = first_minutes("spot", symbol, day)
        future = first_minutes("future", contract, day)
        common = spot.index.intersection(future.index).sort_values()
        if common.empty:
            raise ValueError(f"No common traded minute for {symbol} on {day}")
        instant = common[0]
        s0 = float(spot.loc[instant].high)
        f0 = float(future.loc[instant].low)
        if s0 <= 0 or f0 <= 0:
            raise ValueError(f"Nonpositive entry price for {symbol}")
        q = SPOT_ALLOCATION_PER_LEG / s0
        exit_scenarios = {}
        for multiple in EXIT_PRICE_MULTIPLIERS:
            exit_price = s0 * multiple
            gross = q * (f0 - s0)
            fees = q * (SPOT_COST * (s0 + exit_price)
                        + FUTURE_COST * (f0 + exit_price))
            exit_scenarios[str(multiple)] = {
                "cash_profit_normalized": gross - fees,
                "return_on_initial_account": (gross - fees) / INITIAL_CAPITAL,
            }
        leg = {
            "symbol": symbol, "contract": contract,
            "first_common_minute_utc": instant.isoformat(),
            "spot_entry_high": s0, "future_entry_low": f0,
            "adverse_entry_premium_bps": (f0 / s0 - 1) * 10000,
            "spot_first_minute_base_volume": float(spot.loc[instant].volume),
            "future_first_minute_base_volume": float(future.loc[instant].volume),
            "hypothetical_base_quantity_at_1000_usdt_total": q * 1000 / INITIAL_CAPITAL,
            "exit_at_basis_convergence": exit_scenarios,
        }
        legs.append(leg)
        print(symbol, instant, "adverse premium bps",
              round(leg["adverse_entry_premium_bps"], 2), flush=True)

    account_scenarios = {
        str(multiple): sum(
            leg["exit_at_basis_convergence"][str(multiple)]["return_on_initial_account"]
            for leg in legs
        ) for multiple in EXIT_PRICE_MULTIPLIERS
    }
    return {
        "archived_observation_day": day,
        "delivery_expiry_day": expiry,
        "method": "first common positive-volume minute within five minutes of 00:00 UTC; buy spot at minute high and sell future at minute low",
        "limits": "delayed historical screen, not live executable quotes; exit basis convergence and exit price scenarios are assumptions; order-book depth, margin, liquidation, financing and taxes are absent",
        "source_manifest": sorted(source_results, key=lambda item: item["task"]),
        "assumptions": {
            "initial_normalized_capital": INITIAL_CAPITAL,
            "spot_allocation_per_leg": SPOT_ALLOCATION_PER_LEG,
            "spot_fee_and_slippage_per_side": SPOT_COST,
            "future_fee_and_slippage_per_side": FUTURE_COST,
            "idle_usdt_yield": 0,
        },
        "legs": legs,
        "account_return_under_convergence_scenarios": account_scenarios,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day", required=True, help="Archived UTC date, YYYY-MM-DD")
    parser.add_argument("--expiry", required=True,
                        help="Delivery date encoded in symbol, YYYY-MM-DD")
    args = parser.parse_args()
    result = screen(args.day, args.expiry)
    output = ROOT / f"outputs/delivery_basis_archived_screen_{args.day}.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    print("saved", output, flush=True)


if __name__ == "__main__":
    main()
