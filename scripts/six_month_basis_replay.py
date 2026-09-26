"""Replay the frozen six-month BTC/ETH spot versus delivery-future rule."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import timedelta

import pandas as pd

from laya_trader.progress import ProgressReporter

from quarterly_basis_final_2026 import (
    fetch_daily, fetch_minute_verified, load_daily,
)
from quarterly_basis_minute_probe import first_minutes
from spot_perp_carry_probe import ROOT


@dataclass(frozen=True)
class Period:
    name: str
    entry: str
    expiry: str

    @property
    def contract_suffix(self) -> str:
        return pd.Timestamp(self.expiry).strftime("%y%m%d")

    @property
    def exit(self) -> pd.Timestamp:
        return pd.Timestamp(self.expiry, tz="UTC") - timedelta(days=2)


PERIODS = (
    Period("2024H1", "2024-01-01", "2024-06-28"),
    Period("2024H2", "2024-07-01", "2024-12-27"),
    Period("2025H1", "2025-01-01", "2025-06-27"),
    Period("2025H2", "2025-07-01", "2025-12-26"),
    Period("2026H1", "2026-01-01", "2026-06-26"),
)
SYMBOLS = ("BTCUSDT", "ETHUSDT")
SPOT_CASH = 1.05
FUTURES_CASH = 3.0
INITIAL_CAPITAL = SPOT_CASH + FUTURES_CASH
SPOT_ALLOCATION = 0.5
SPOT_SIDE_COST = 0.0019
FUTURE_SIDE_COST = 0.0019
MARK_SHOCK = 0.10
MAINTENANCE = 0.05
OUTPUT = ROOT / "outputs/six_month_basis_replay_report.json"


def sources() -> tuple[list[tuple], list[tuple]]:
    daily = set()
    minutes = set()
    for period in PERIODS:
        entry = pd.Timestamp(period.entry, tz="UTC")
        exit_time = period.exit
        months = pd.period_range(entry.tz_localize(None),
                                 exit_time.tz_localize(None), freq="M")
        for symbol in SYMBOLS:
            contract = f"{symbol}_{period.contract_suffix}"
            for moment in (entry, exit_time):
                day = moment.strftime("%Y-%m-%d")
                minutes.add(("spot", symbol, day))
                minutes.add(("future", contract, day))
            for month in months:
                daily.add(("spot", symbol, str(month), True))
                daily.add(("future", contract, str(month), True))
    return sorted(daily), sorted(minutes)


def download_sources(daily_tasks: list[tuple], minute_tasks: list[tuple]) -> list[dict]:
    tasks = [(fetch_daily, task) for task in daily_tasks]
    tasks.extend((fetch_minute_verified, task) for task in minute_tasks)
    manifest = []
    progress = ProgressReporter("six-month basis archives", len(tasks), unit="archives")
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(function, task) for function, task in tasks]
        for count, future in enumerate(as_completed(futures), 1):
            result = future.result()
            manifest.append(result)
            progress.update(count)
    failures = [row for row in manifest if row["status"] != "verified"]
    if failures:
        raise RuntimeError(f"Incomplete verified archive set: {failures}")
    return sorted(manifest, key=lambda row: str(row["task"]))


def execute_leg(period: Period, symbol: str, minute_bars: dict) -> dict:
    entry = pd.Timestamp(period.entry, tz="UTC")
    exit_time = period.exit
    contract = f"{symbol}_{period.contract_suffix}"
    seen = {}
    for label, moment in (("entry", entry), ("exit", exit_time)):
        day = moment.strftime("%Y-%m-%d")
        spot = minute_bars[("spot", symbol, day)]
        future = minute_bars[("future", contract, day)]
        common = spot.index.intersection(future.index).sort_values()
        if common.empty:
            raise ValueError(f"No common traded minute: {period.name} {symbol} {label}")
        stamp = common[0]
        seen[label] = (stamp, spot.loc[stamp], future.loc[stamp])
    entry_stamp, entry_spot, entry_future = seen["entry"]
    exit_stamp, exit_spot, exit_future = seen["exit"]
    s0, f0 = float(entry_spot.high), float(entry_future.low)
    s1, f1 = float(exit_spot.low), float(exit_future.high)
    if min(s0, f0, s1, f1) <= 0:
        raise ValueError(f"Nonpositive execution price: {period.name} {symbol}")
    q = SPOT_ALLOCATION / s0
    profit = q * (s1 - s0 + f0 - f1
                  - SPOT_SIDE_COST * (s0 + s1)
                  - FUTURE_SIDE_COST * (f0 + f1))
    volumes = [float(bar.volume) for bar in
               (entry_spot, entry_future, exit_spot, exit_future)]
    q_example = q * 1000 / INITIAL_CAPITAL
    return {
        "period": period.name, "symbol": symbol, "contract": contract,
        "entry_minute": entry_stamp.isoformat(),
        "exit_minute": exit_stamp.isoformat(),
        "entry_delay_minutes": int((entry_stamp - entry).total_seconds() / 60),
        "exit_delay_minutes": int((exit_stamp - exit_time).total_seconds() / 60),
        "spot_entry_high": s0, "future_entry_low": f0,
        "spot_exit_low": s1, "future_exit_high": f1,
        "quantity": q, "stressed_cash_profit": profit,
        "entry_spot_volume": volumes[0], "entry_future_volume": volumes[1],
        "exit_spot_volume": volumes[2], "exit_future_volume": volumes[3],
        "illustrative_1000_usdt_quantity": q_example,
        "minute_volume_covers_illustrative_quantity": min(volumes) >= q_example,
        "account_size_at_minute_volume": min(volumes) / q * INITIAL_CAPITAL,
    }


def replay(executions: list[dict], daily: dict) -> tuple[list[dict], list[dict], dict]:
    by_period = {period.name: [row for row in executions
                              if row["period"] == period.name]
                 for period in PERIODS}
    spot_cash, futures_cash = SPOT_CASH, FUTURES_CASH
    min_spot_cash = spot_cash
    min_margin_cushion = float("inf")
    periods = []
    path = []
    for period in PERIODS:
        legs = by_period[period.name]
        if len(legs) != len(SYMBOLS) or {row["symbol"] for row in legs} != set(SYMBOLS):
            raise ValueError(f"Incomplete legs: {period.name}")
        entry = pd.Timestamp(period.entry, tz="UTC")
        exit_time = period.exit
        days = pd.date_range(entry, exit_time, freq="D", inclusive="left")
        for leg in legs:
            for market, name in (("spot", leg["symbol"]),
                                 ("future", leg["contract"])):
                bars = daily[(market, name)].reindex(days)
                if bars.isna().any().any() or bars.le(0).any().any():
                    raise ValueError(f"Missing or invalid daily prices: {period.name} {name}")
        before = spot_cash + futures_cash
        for leg in legs:
            q = leg["quantity"]
            spot_cash -= q * leg["spot_entry_high"] * (1 + SPOT_SIDE_COST)
            futures_cash -= q * leg["future_entry_low"] * FUTURE_SIDE_COST
        min_spot_cash = min(min_spot_cash, spot_cash)
        period_margin_cushion = float("inf")
        for day in days:
            margin_equity = futures_cash
            maintenance = 0.0
            liquidating = spot_cash + futures_cash
            for leg in legs:
                q = leg["quantity"]
                future = daily[("future", leg["contract"])].loc[day]
                spot = daily[("spot", leg["symbol"])].loc[day]
                shock_mark = float(future.high) * (1 + MARK_SHOCK)
                f_open, s_open = float(future.open), float(spot.open)
                margin_equity += q * (leg["future_entry_low"] - shock_mark)
                maintenance += q * shock_mark * MAINTENANCE
                liquidating += q * (s_open + leg["future_entry_low"] - f_open)
                liquidating -= q * (SPOT_SIDE_COST * s_open
                                    + FUTURE_SIDE_COST * f_open)
            cushion = margin_equity - maintenance
            period_margin_cushion = min(period_margin_cushion, cushion)
            min_margin_cushion = min(min_margin_cushion, cushion)
            path.append({"day": day, "period": period.name,
                         "estimated_liquidating_equity": liquidating,
                         "margin_shock_cushion": cushion})
        for leg in legs:
            q = leg["quantity"]
            spot_cash += q * leg["spot_exit_low"] * (1 - SPOT_SIDE_COST)
            futures_cash += q * (leg["future_entry_low"]
                                  - leg["future_exit_high"])
            futures_cash -= q * leg["future_exit_high"] * FUTURE_SIDE_COST
        after = spot_cash + futures_cash
        expected = sum(leg["stressed_cash_profit"] for leg in legs)
        if abs((after - before) - expected) > 1e-8:
            raise ValueError(f"Account and leg cash mismatch: {period.name}")
        path.append({"day": exit_time, "period": period.name,
                     "estimated_liquidating_equity": after,
                     "margin_shock_cushion": None})
        transfer = FUTURES_CASH - futures_cash
        spot_cash -= transfer
        futures_cash += transfer
        min_spot_cash = min(min_spot_cash, spot_cash)
        periods.append({"period": period.name, "entry": entry.isoformat(),
                        "exit": exit_time.isoformat(),
                        "stressed_cash_profit": after - before,
                        "return_on_initial_capital": (after - before) / INITIAL_CAPITAL,
                        "account_equity_after_exit": after,
                        "spot_cash_after_transfer": spot_cash,
                        "minimum_margin_shock_cushion": period_margin_cushion})
        print(period.name, "account return", round((after - before)
                                                   / INITIAL_CAPITAL, 6),
              "margin cushion", round(period_margin_cushion, 4), flush=True)
    path_frame = pd.DataFrame(path).sort_values("day")
    peak = path_frame.estimated_liquidating_equity.cummax().clip(lower=INITIAL_CAPITAL)
    max_drawdown = float((path_frame.estimated_liquidating_equity / peak - 1).min())
    annual = {str(year): sum(row["stressed_cash_profit"] for row in periods
                             if row["period"].startswith(str(year))) / INITIAL_CAPITAL
              for year in (2024, 2025, 2026)}
    total = spot_cash + futures_cash - INITIAL_CAPITAL
    extra_cost_diagnostic = {}
    for extra_bps in (5, 10, 20, 30):
        extra_side_cost = extra_bps / 10000
        extra_cash = sum(
            leg["quantity"] * extra_side_cost * (
                leg["spot_entry_high"] + leg["spot_exit_low"]
                + leg["future_entry_low"] + leg["future_exit_high"])
            for leg in executions)
        extra_cost_diagnostic[str(extra_bps)] = (total - extra_cash) / INITIAL_CAPITAL
    conditions = {
        "all_five_half_years_profitable": all(row["stressed_cash_profit"] > 0
                                               for row in periods),
        "each_complete_year_at_least_1_percent": all(annual[year] >= 0.01
                                                    for year in ("2024", "2025")),
        "minimum_margin_cushion_at_least_0_50": min_margin_cushion >= 0.50,
        "no_spot_wallet_shortfall": min_spot_cash >= 0,
        "maximum_daily_drawdown_less_than_5_percent": max_drawdown > -0.05,
        "all_common_minutes_within_5_minutes": all(
            leg["entry_delay_minutes"] < 5 and leg["exit_delay_minutes"] < 5
            for leg in executions),
    }
    summary = {
        "initial_capital": INITIAL_CAPITAL,
        "periods": periods, "annual_return_on_initial_capital": annual,
        "total_stressed_cash_profit": total,
        "total_return_on_initial_capital": total / INITIAL_CAPITAL,
        "minimum_margin_shock_cushion": min_margin_cushion,
        "minimum_spot_cash": min_spot_cash,
        "maximum_daily_liquidation_drawdown": max_drawdown,
        "minute_volume_covers_illustrative_quantity_legs": sum(
            leg["minute_volume_covers_illustrative_quantity"] for leg in executions),
        "posthoc_extra_cost_per_side_bps_to_total_return": extra_cost_diagnostic,
        "legs": len(executions), "conditions": conditions,
        "research_gate_passed": all(conditions.values()),
    }
    return periods, path, summary


def main() -> None:
    daily_tasks, minute_tasks = sources()
    manifest = download_sources(daily_tasks, minute_tasks)
    daily = load_daily(daily_tasks)
    minute_bars = {task: first_minutes(*task) for task in minute_tasks}
    executions = [execute_leg(period, symbol, minute_bars)
                  for period in PERIODS for symbol in SYMBOLS]
    _, path, summary = replay(executions, daily)
    manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    source_hash = hashlib.sha256(manifest_bytes).hexdigest()
    report = {
        "protocol": "docs/six_month_basis_protocol.md, frozen at commit 4e6e6ce",
        "source": "Binance public spot and USD-M delivery 1d/1m archives; SHA256 and ZIP CRC verified",
        "archive_count": len(manifest),
        "source_manifest_sha256": source_hash,
        "assumptions": {
            "spot_side_cost": SPOT_SIDE_COST,
            "future_side_cost": FUTURE_SIDE_COST,
            "spot_initial_cash": SPOT_CASH,
            "futures_initial_cash": FUTURES_CASH,
            "spot_allocation_per_leg": SPOT_ALLOCATION,
            "daily_future_high_shock": MARK_SHOCK,
            "maintenance_fraction": MAINTENANCE,
        },
        "result": summary,
        "limitations": [
            "Entry-only premia were inspected before the replay protocol was frozen.",
            "Minute ranges and volume do not establish executable bid/ask depth.",
            "Daily-high shock and assumed maintenance do not reproduce Binance liquidation.",
            "Account fees, eligibility, lot sizes, financing cost and taxes remain unverified.",
        ],
    }
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (ROOT / "outputs/six_month_basis_replay_sources.json").write_bytes(manifest_bytes)
    pd.DataFrame(executions).to_parquet(
        ROOT / "outputs/six_month_basis_replay_legs.parquet", index=False)
    pd.DataFrame(path).to_parquet(
        ROOT / "outputs/six_month_basis_replay_daily.parquet", index=False)
    print(json.dumps(summary, indent=2), flush=True)
    print("saved", OUTPUT, flush=True)


if __name__ == "__main__":
    main()
