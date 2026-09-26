"""Exploratory daily carry rule with separate spot cash and futures margin."""

from __future__ import annotations

import json
from dataclasses import dataclass
from dataclasses import replace

import numpy as np
import pandas as pd

from funding_probe import SYMBOLS
from laya_trader.config import load_config
from laya_trader.dataset.build import load_symbol_klines
from laya_trader.progress import ProgressReporter
from spot_perp_carry_probe import (
    EXTRA_PAIR_COST, PERP_SIDE_COST, ROOT, SPOT_SIDE_COST,
    download_spot, perp_and_funding, spot_opens,
)


START = pd.Timestamp("2023-02-01", tz="UTC")
END = pd.Timestamp("2026-01-01", tz="UTC")
LOOKBACK_DAYS = 7
MIN_FUNDING_EVENTS = 18
ENTRY_30D_FUNDING = 0.008  # More than twice the approximate pair round-trip cost.
EXIT_30D_FUNDING = 0.004
SPOT_CASH_INITIAL = 1.05
FUTURES_CASH_INITIAL = 2.50
SPOT_ALLOCATION = 0.20
MAINTENANCE_ASSUMPTION = 0.05
EXTRA_MARK_SHOCK = 0.10
EXTRA_SIDE_COST = EXTRA_PAIR_COST / 4


@dataclass
class Position:
    quantity: float
    futures_entry: float


@dataclass
class Market:
    spot: pd.Series
    futures: pd.Series
    daily_high: pd.Series
    funding_times_ns: np.ndarray
    funding_rate_prefix: np.ndarray
    funding_notional_prefix: np.ndarray


def load_markets() -> dict[str, Market]:
    download_spot("2026-01")
    cfg = load_config(ROOT / "configs/dataset.toml")
    cfg = replace(cfg, data=replace(cfg.data, start="2023-01-01", end="2026-01-01"))
    expected = pd.date_range(START, END, freq="D")
    result = {}
    progress = ProgressReporter("daily carry markets", len(SYMBOLS), unit="symbols")
    for count, symbol in enumerate(SYMBOLS, 1):
        spot = spot_opens(symbol, "2026-01")
        futures, funding = perp_and_funding(symbol, "2026-01-01")
        raw = load_symbol_klines(cfg, symbol)
        daily_high = raw.groupby(raw.open_time.dt.floor("1d")).high.max()
        for name, prices in (("spot", spot), ("futures", futures), ("daily high", daily_high)):
            if prices.reindex(expected).isna().any():
                raise ValueError(f"missing {name} daily price for {symbol}")
        funding = funding.sort_values("calc_time")
        times = funding.calc_time.astype("int64").to_numpy()
        rate = funding.last_funding_rate.to_numpy(float)
        notional = rate * funding.perp_mark.to_numpy(float)
        if not np.isfinite(rate).all() or not np.isfinite(notional).all():
            raise ValueError(f"invalid funding records for {symbol}")
        result[symbol] = Market(
            spot=spot, futures=futures, daily_high=daily_high,
            funding_times_ns=times,
            funding_rate_prefix=np.r_[0.0, rate.cumsum()],
            funding_notional_prefix=np.r_[0.0, notional.cumsum()],
        )
        progress.update(count)
    return result


def signal(market: Market, day: pd.Timestamp) -> tuple[float, int]:
    times = market.funding_times_ns
    first = np.searchsorted(times, (day - pd.Timedelta(days=LOOKBACK_DAYS)).value, side="left")
    last = np.searchsorted(times, day.value, side="left")
    count = int(last - first)
    trailing = float(market.funding_rate_prefix[last] - market.funding_rate_prefix[first])
    return trailing * 30 / LOOKBACK_DAYS, count


def funding_notional(market: Market, day: pd.Timestamp, next_day: pd.Timestamp) -> float:
    times = market.funding_times_ns
    first = np.searchsorted(times, day.value, side="right")
    last = np.searchsorted(times, next_day.value, side="right")
    return float(market.funding_notional_prefix[last] - market.funding_notional_prefix[first])


def liquidating_equity(
    day: pd.Timestamp, markets: dict[str, Market], positions: dict[str, Position],
    spot_cash: float, futures_cash: float, extra_fees: float,
) -> tuple[float, float]:
    equity = spot_cash + futures_cash
    hypothetical_exit = 0.0
    hypothetical_extra = 0.0
    for symbol, position in positions.items():
        market = markets[symbol]
        spot = float(market.spot[day])
        futures = float(market.futures[day])
        q = position.quantity
        equity += q * (spot + position.futures_entry - futures)
        hypothetical_exit += q * (SPOT_SIDE_COST * spot + PERP_SIDE_COST * futures)
        hypothetical_extra += q * EXTRA_SIDE_COST * (spot + futures)
    return equity - hypothetical_exit, equity - hypothetical_exit - extra_fees - hypothetical_extra


def simulate(markets: dict[str, Market]) -> pd.DataFrame:
    positions: dict[str, Position] = {}
    spot_cash = SPOT_CASH_INITIAL
    futures_cash = FUTURES_CASH_INITIAL
    extra_fees = 0.0
    previous_liquidation = SPOT_CASH_INITIAL + FUTURES_CASH_INITIAL
    previous_stress_liquidation = previous_liquidation
    rows = []
    days = pd.date_range(START, END - pd.Timedelta(days=1), freq="D")
    progress = ProgressReporter("daily carry replay", len(days), unit="days")
    for index, day in enumerate(days, 1):
        next_day = day + pd.Timedelta(days=1)
        forecasts = {symbol: signal(markets[symbol], day) for symbol in SYMBOLS}
        entries, exits, skipped_entries = 0, 0, 0
        for symbol in SYMBOLS:
            forecast, events = forecasts[symbol]
            if symbol not in positions or (events >= MIN_FUNDING_EVENTS
                                            and forecast >= EXIT_30D_FUNDING):
                continue
            position = positions.pop(symbol)
            market = markets[symbol]
            s0, f0 = float(market.spot[day]), float(market.futures[day])
            q = position.quantity
            spot_cash += q * s0 * (1 - SPOT_SIDE_COST)
            futures_cash += q * (position.futures_entry - f0) - q * f0 * PERP_SIDE_COST
            extra_fees += q * EXTRA_SIDE_COST * (s0 + f0)
            exits += 1
        for symbol in SYMBOLS:
            forecast, events = forecasts[symbol]
            if symbol in positions or events < MIN_FUNDING_EVENTS or forecast <= ENTRY_30D_FUNDING:
                continue
            market = markets[symbol]
            s0, f0 = float(market.spot[day]), float(market.futures[day])
            q = SPOT_ALLOCATION / s0
            required_spot = q * s0 * (1 + SPOT_SIDE_COST)
            if spot_cash < required_spot:
                skipped_entries += 1
                continue
            spot_cash -= required_spot
            futures_cash -= q * f0 * PERP_SIDE_COST
            extra_fees += q * EXTRA_SIDE_COST * (s0 + f0)
            positions[symbol] = Position(quantity=q, futures_entry=f0)
            entries += 1
        margin_at_open = futures_cash
        margin_under_shock = futures_cash
        maintenance = 0.0
        for symbol, position in positions.items():
            market = markets[symbol]
            f0 = float(market.futures[day])
            stressed_mark = float(market.daily_high[day]) * (1 + EXTRA_MARK_SHOCK)
            q = position.quantity
            margin_at_open += q * (position.futures_entry - f0)
            margin_under_shock += q * (position.futures_entry - stressed_mark)
            maintenance += q * stressed_mark * MAINTENANCE_ASSUMPTION
        daily_funding = 0.0
        for symbol, position in positions.items():
            amount = position.quantity * funding_notional(markets[symbol], day, next_day)
            futures_cash += amount
            daily_funding += amount
        liquidation, stressed_liquidation = liquidating_equity(
            next_day, markets, positions, spot_cash, futures_cash, extra_fees,
        )
        rows.append({
            "day": day, "month": day.strftime("%Y-%m"),
            "active_legs": len(positions), "entries": entries, "exits": exits,
            "skipped_entries": skipped_entries,
            "spot_cash": spot_cash, "futures_cash": futures_cash,
            "futures_margin_at_open": margin_at_open,
            "margin_shock_cushion": margin_under_shock - maintenance,
            "funding_cash": daily_funding,
            "liquidation_equity": liquidation,
            "stress_liquidation_equity": stressed_liquidation,
            "net_profit": liquidation - previous_liquidation,
            "stress_profit": stressed_liquidation - previous_stress_liquidation,
        })
        previous_liquidation = liquidation
        previous_stress_liquidation = stressed_liquidation
        progress.update(index)
    return pd.DataFrame(rows)


def period_summary(frame: pd.DataFrame, first: str, last: str) -> dict:
    section = frame.loc[frame.month.between(first, last)]
    months = section.groupby("month", sort=True).agg(
        net=("net_profit", "sum"), stress=("stress_profit", "sum"),
        active_days=("active_legs", lambda values: int(values.gt(0).sum())),
        entries=("entries", "sum"), exits=("exits", "sum"),
        skipped_entries=("skipped_entries", "sum"),
    )
    starting_equity = float(section.liquidation_equity.iloc[0] - section.net_profit.iloc[0])
    path = section.liquidation_equity
    peak = path.cummax().clip(lower=starting_equity)
    drawdown = path / peak - 1
    return {
        "months": len(months),
        "active_months": int(months.active_days.gt(0).sum()),
        "positive_active_months": int(months.loc[months.active_days.gt(0), "net"].gt(0).sum()),
        "entries": int(months.entries.sum()), "exits": int(months.exits.sum()),
        "skipped_entries": int(months.skipped_entries.sum()),
        "net_on_initial_capital": round(float(months.net.sum() / (SPOT_CASH_INITIAL + FUTURES_CASH_INITIAL)), 6),
        "stress_on_initial_capital": round(float(months.stress.sum() / (SPOT_CASH_INITIAL + FUTURES_CASH_INITIAL)), 6),
        "max_daily_drawdown": round(float(drawdown.min()), 6),
        "monthly": months.round(6).reset_index().to_dict(orient="records"),
    }


def main() -> None:
    markets = load_markets()
    daily = simulate(markets)
    periods = {
        "development_2023_h1": ("2023-02", "2023-06"),
        "selection_2023_h2": ("2023-07", "2023-12"),
        "validation_2024_h1": ("2024-01", "2024-06"),
        "validation_2024_h2": ("2024-07", "2024-12"),
        "validation_2025_h1": ("2025-01", "2025-06"),
        "diagnostic_2025_h2": ("2025-07", "2025-12"),
    }
    sections = {name: period_summary(daily, *bounds) for name, bounds in periods.items()}
    stressed_profit = daily.stress_profit.sum()
    total_capital = SPOT_CASH_INITIAL + FUTURES_CASH_INITIAL
    report = {
        "hypothesis": "daily spot-perpetual carry with seven-day settled funding signal",
        "provenance": "exploratory rule designed after monthly carry results through 2025",
        "symbols": list(SYMBOLS),
        "parameters": {
            "lookback_days": LOOKBACK_DAYS,
            "minimum_funding_events": MIN_FUNDING_EVENTS,
            "entry_projected_30d": ENTRY_30D_FUNDING,
            "exit_projected_30d": EXIT_30D_FUNDING,
            "spot_cash_initial": SPOT_CASH_INITIAL,
            "futures_cash_initial": FUTURES_CASH_INITIAL,
            "spot_allocation_per_symbol": SPOT_ALLOCATION,
            "spot_side_cost": SPOT_SIDE_COST,
            "futures_side_cost": PERP_SIDE_COST,
            "extra_side_cost": EXTRA_SIDE_COST,
            "maintenance_assumption": MAINTENANCE_ASSUMPTION,
            "extra_mark_shock": EXTRA_MARK_SHOCK,
        },
        "periods": sections,
        "minimum_spot_cash": round(float(daily.spot_cash.min()), 6),
        "minimum_margin_shock_cushion": round(float(daily.margin_shock_cushion.min()), 6),
        "worst_margin_day": daily.loc[daily.margin_shock_cushion.idxmin(), "day"].isoformat(),
        "overall_stress_return": round(float(stressed_profit / total_capital), 6),
    }
    report["research_gate"] = (
        report["minimum_spot_cash"] >= 0 and report["minimum_margin_shock_cushion"] > 0
        and all(sections[name]["stress_on_initial_capital"] > 0 for name in periods
                if name != "development_2023_h1")
        and all(sections[name]["active_months"] >= 3 for name in periods
                if name != "development_2023_h1")
        and sections["validation_2025_h1"]["stress_on_initial_capital"]
        + sections["diagnostic_2025_h2"]["stress_on_initial_capital"] >= 0.02
        and min(value["max_daily_drawdown"] for value in sections.values()) > -0.10
    )
    daily.to_parquet(ROOT / "outputs/spot_perp_daily_carry_ledger.parquet", index=False)
    output = ROOT / "outputs/spot_perp_daily_carry_report.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"periods": {name: {key: value for key, value in summary.items()
                                    if key != "monthly"} for name, summary in sections.items()},
                      "minimum_spot_cash": report["minimum_spot_cash"],
                      "minimum_margin_shock_cushion": report["minimum_margin_shock_cushion"],
                      "overall_stress_return": report["overall_stress_return"],
                      "research_gate": report["research_gate"]}, indent=2), flush=True)
    print("saved", output, flush=True)


if __name__ == "__main__":
    main()
