"""Screen funding-only economics for the fixed 20-symbol daily carry rule."""

from __future__ import annotations

import json
from datetime import timedelta

import numpy as np
import pandas as pd

from cross_basis_daily_probe import FUNDING_CACHE, ROOT, SYMBOLS, market_history
from spot_perp_carry_probe import EXTRA_PAIR_COST, PERP_SIDE_COST, SPOT_SIDE_COST


START = pd.Timestamp("2025-01-01", tz="UTC")
END = pd.Timestamp("2025-07-01", tz="UTC")
LOOKBACK_DAYS = 7
MIN_EVENTS = 18
ENTRY_PROJECTED_30D = 0.008
EXIT_PROJECTED_30D = 0.004
SPOT_ALLOCATION = 0.05
SPOT_CASH = 1.05
FUTURES_CASH = 2.50
PAIR_ROUND_TRIP_COST = 2 * (SPOT_SIDE_COST + PERP_SIDE_COST) + EXTRA_PAIR_COST
OUTPUT = ROOT / "outputs/expanded_carry_funding_screen.json"


def symbol_days(symbol: str, funding: pd.DataFrame) -> list[dict]:
    group = funding.loc[funding.symbol == symbol].sort_values("calc_time")
    times = group.calc_time.astype("int64").to_numpy()
    rates = group.last_funding_rate.to_numpy(float)
    if not np.isfinite(rates).all():
        raise ValueError(f"Nonfinite funding rates: {symbol}")
    prefix = np.r_[0.0, rates.cumsum()]
    active = False
    rows = []
    for day in pd.date_range(START, END - timedelta(days=1), freq="D"):
        first = np.searchsorted(times, (day - timedelta(days=LOOKBACK_DAYS)).value,
                                side="left")
        last = np.searchsorted(times, day.value, side="left")
        count = int(last - first)
        forecast = float((prefix[last] - prefix[first]) * 30 / LOOKBACK_DAYS)
        entry = not active and count >= MIN_EVENTS and forecast > ENTRY_PROJECTED_30D
        exit_ = active and (count < MIN_EVENTS or forecast < EXIT_PROJECTED_30D)
        if exit_:
            active = False
        if entry:
            active = True
        # Bracket the UTC-boundary settlement when trade/settlement order is unknown.
        receipt_start_strict = np.searchsorted(times, day.value, side="right")
        receipt_end = np.searchsorted(times, (day + timedelta(days=1)).value,
                                          side="left")
        optimistic_rate = float(prefix[receipt_end] - prefix[last]) if active else 0.0
        strict_rate = float(prefix[receipt_end] - prefix[receipt_start_strict]) if active else 0.0
        rows.append({"symbol": symbol, "day": day, "month": day.strftime("%Y-%m"),
                     "active": active, "entry": entry, "exit": exit_,
                     "projected_30d": forecast, "past_events": count,
                     "optimistic_received_rate": optimistic_rate,
                     "strict_received_rate": strict_rate})
    return rows


def main() -> None:
    if not FUNDING_CACHE.is_file():
        market_history()
    funding = pd.read_parquet(FUNDING_CACHE)
    funding["calc_time"] = pd.to_datetime(funding.calc_time, utc=True)
    if set(funding.symbol) != set(SYMBOLS):
        raise ValueError("Funding cache does not cover the fixed 20-symbol universe")
    period = funding.loc[(funding.calc_time >= START) & (funding.calc_time < END)].copy()
    period["day"] = period.calc_time.dt.floor("D")
    expected_days = pd.date_range(START, END - timedelta(days=1), freq="D")
    expected_index = pd.MultiIndex.from_product(
        [SYMBOLS, expected_days], names=["symbol", "day"]
    )
    daily_events = period.groupby(["symbol", "day"]).size().reindex(expected_index)
    if daily_events.isna().any() or not daily_events.eq(3).all():
        raise ValueError("Expected exactly three funding settlements per symbol-day")
    rows = [row for symbol in SYMBOLS for row in symbol_days(symbol, funding)]
    days = pd.DataFrame(rows)
    cost_per_completed_pair = SPOT_ALLOCATION * PAIR_ROUND_TRIP_COST
    days["optimistic_funding_cash"] = days.optimistic_received_rate * SPOT_ALLOCATION
    days["strict_funding_cash"] = days.strict_received_rate * SPOT_ALLOCATION
    days["reserved_pair_cost"] = days.entry.astype(float) * cost_per_completed_pair
    monthly = days.groupby("month", sort=True).agg(
        active_symbol_days=("active", "sum"), entries=("entry", "sum"),
        exits=("exit", "sum"),
        optimistic_funding_cash=("optimistic_funding_cash", "sum"),
        strict_funding_cash=("strict_funding_cash", "sum"),
        reserved_pair_cost=("reserved_pair_cost", "sum"),
    )
    monthly["optimistic_funding_less_cost"] = (monthly.optimistic_funding_cash
                                               - monthly.reserved_pair_cost)
    monthly["strict_funding_less_cost"] = (monthly.strict_funding_cash
                                           - monthly.reserved_pair_cost)
    still_open = int(days.sort_values("day").groupby("symbol").active.last().sum())
    report = {
        "universe": list(SYMBOLS), "period": "2025-01-01 through 2025-06-30 UTC",
        "funding_coverage": {"symbols": len(SYMBOLS), "days": len(expected_days),
                             "settlements_per_symbol_day": 3},
        "method": "2025 H1 new-entry cohort starts empty on January 1; fixed daily 7-day settled-funding signal and 0.05 spot notional per pair; optimistic cash counts a settlement at the entry UTC boundary",
        "limits": "excludes pairs opened before January 1 and does not model spot/perpetual basis, price change in funding notional, execution depth, margin or liquidation",
        "assumptions": {
            "initial_total_capital": SPOT_CASH + FUTURES_CASH,
            "spot_allocation_per_pair": SPOT_ALLOCATION,
            "entry_projected_30d": ENTRY_PROJECTED_30D,
            "exit_projected_30d": EXIT_PROJECTED_30D,
            "minimum_past_events": MIN_EVENTS,
            "round_trip_cost_including_8bps_stress": PAIR_ROUND_TRIP_COST,
        },
        "entry_opportunity_symbol_days": int(
            ((days.projected_30d > ENTRY_PROJECTED_30D)
             & (days.past_events >= MIN_EVENTS)).sum()),
        "symbol_days_above_2pct_projected_30d": int(
            ((days.projected_30d > 0.02) & (days.past_events >= MIN_EVENTS)).sum()),
        "entries": int(days.entry.sum()), "exits": int(days.exit.sum()),
        "open_pairs_at_period_end": still_open,
        "optimistic_funding_on_initial_capital": float(
            days.optimistic_funding_cash.sum() / (SPOT_CASH + FUTURES_CASH)),
        "strict_funding_on_initial_capital": float(
            days.strict_funding_cash.sum() / (SPOT_CASH + FUTURES_CASH)),
        "reserved_pair_cost_on_initial_capital": float(
            days.reserved_pair_cost.sum() / (SPOT_CASH + FUTURES_CASH)),
        "optimistic_funding_less_cost_on_initial_capital": float(
            (days.optimistic_funding_cash.sum() - days.reserved_pair_cost.sum())
            / (SPOT_CASH + FUTURES_CASH)),
        "strict_funding_less_cost_on_initial_capital": float(
            (days.strict_funding_cash.sum() - days.reserved_pair_cost.sum())
            / (SPOT_CASH + FUTURES_CASH)),
        "positive_months_optimistic_funding_less_cost": int(
            monthly.optimistic_funding_less_cost.gt(0).sum()),
        "monthly": monthly.round(8).reset_index().to_dict(orient="records"),
    }
    report["funding_only_gate"] = (
        report["open_pairs_at_period_end"] == 0
        and report["optimistic_funding_less_cost_on_initial_capital"] > 0
        and report["positive_months_optimistic_funding_less_cost"] >= 4
    )
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    days.to_parquet(ROOT / "outputs/expanded_carry_funding_days.parquet", index=False)
    print(json.dumps(report, indent=2), flush=True)
    print("saved", OUTPUT, flush=True)


if __name__ == "__main__":
    main()
