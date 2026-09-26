"""Daily short-leg margin screen for the exploratory retained-carry positions."""

from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pandas as pd

from funding_probe import SYMBOLS
from laya_trader.config import load_config
from laya_trader.dataset.build import load_symbol_klines
from spot_perp_carry_probe import PERP_SIDE_COST, ROOT, perp_and_funding


INITIAL_MARGIN_CAPITAL = 1.0
MAINTENANCE_ASSUMPTION = 0.05


def runs_for_symbol(legs: pd.DataFrame, symbol: str, perp: pd.Series,
                    funding: pd.DataFrame) -> list[dict]:
    rows = legs.loc[legs.symbol == symbol].sort_values("month")
    opening = rows.active & ~rows.active.shift(fill_value=False)
    closing = rows.active & ~rows.active.shift(-1, fill_value=False)
    runs = []
    for start_month, end_month in zip(rows.loc[opening, "month"],
                                      rows.loc[closing, "month"], strict=True):
        start = pd.Period(start_month, freq="M").start_time.tz_localize("UTC")
        end = (pd.Period(end_month, freq="M") + 1).start_time.tz_localize("UTC")
        quantity = float(rows.loc[rows.month == start_month, "quantity"].iloc[0])
        path = perp.loc[(perp.index >= start) & (perp.index <= end)]
        if len(path) != (end - start).days + 1:
            raise ValueError(f"incomplete daily futures path: {symbol} {start_month}")
        events = funding.loc[(funding.calc_time > start) & (funding.calc_time < end)]
        event_cash = (events.last_funding_rate * events.perp_mark * quantity).to_numpy()
        runs.append({
            "symbol": symbol, "start": start, "end": end,
            "quantity": quantity, "entry": float(perp[start]),
            "exit": float(perp[end]),
            "max_perp_ratio": float(path.max() / perp[start]),
            "max_perp_date": path.idxmax(),
            "funding_times_ns": events.calc_time.astype("int64").to_numpy(),
            "funding_cumulative": np.r_[0.0, event_cash.cumsum()],
        })
    return runs


def contribution(run: dict, day: pd.Timestamp, mark: float) -> tuple[float, float]:
    if day < run["start"]:
        return 0.0, 0.0
    closed = day >= run["end"]
    effective = run["end"] if closed else day
    n_events = int(np.searchsorted(run["funding_times_ns"], effective.value, side="left"))
    funding_cash = float(run["funding_cumulative"][n_events])
    q = run["quantity"]
    exit_mark = run["exit"] if closed else mark
    futures_pnl = q * (run["entry"] - exit_mark)
    fees = q * PERP_SIDE_COST * (run["entry"] + (run["exit"] if closed else 0.0))
    maintenance = 0.0 if closed else q * mark * MAINTENANCE_ASSUMPTION
    return futures_pnl + funding_cash - fees, maintenance


def main() -> None:
    legs_path = ROOT / "outputs/spot_perp_hold_probe_legs.parquet"
    legs = pd.read_parquet(legs_path)
    first_day = pd.Period(legs.month.min(), freq="M").start_time.tz_localize("UTC")
    last_day = (pd.Period(legs.month.max(), freq="M") + 1).start_time.tz_localize("UTC")
    days = pd.date_range(first_day, last_day, freq="D")
    markets = {}
    daily_highs = {}
    runs = []
    cfg = load_config(ROOT / "configs/dataset.toml")
    cfg = replace(cfg, data=replace(cfg.data, start="2023-01-01",
                                    end=last_day.date().isoformat()))
    for symbol in SYMBOLS:
        perp, funding = perp_and_funding(symbol, last_day.date().isoformat())
        markets[symbol] = perp
        raw = load_symbol_klines(cfg, symbol)
        daily_highs[symbol] = raw.groupby(raw.open_time.dt.floor("1d")).high.max()
        runs.extend(runs_for_symbol(legs, symbol, perp, funding))
        print("margin paths", symbol, "runs", sum(r["symbol"] == symbol for r in runs), flush=True)
    daily = []
    for day in days:
        pnl, maintenance = 0.0, 0.0
        high_pnl, high_maintenance = 0.0, 0.0
        shock_pnl, shock_maintenance = 0.0, 0.0
        for run in runs:
            mark = float(markets[run["symbol"]][day]) if day < run["end"] else run["exit"]
            change, required = contribution(run, day, mark)
            pnl += change
            maintenance += required
            high = float(daily_highs[run["symbol"]][day]) if day < run["end"] else run["exit"]
            stressed_change, stressed_required = contribution(run, day, high)
            high_pnl += stressed_change
            high_maintenance += stressed_required
            shocked_change, shocked_required = contribution(
                run, day, high * 1.10 if day < run["end"] else high,
            )
            shock_pnl += shocked_change
            shock_maintenance += shocked_required
        margin_equity = INITIAL_MARGIN_CAPITAL + pnl
        high_equity = INITIAL_MARGIN_CAPITAL + high_pnl
        daily.append({"day": day, "margin_equity": margin_equity,
                      "maintenance_assumption": maintenance,
                      "margin_cushion": margin_equity - maintenance,
                      "simultaneous_daily_high_equity": high_equity,
                      "simultaneous_daily_high_cushion": high_equity - high_maintenance,
                      "daily_high_plus_10pct_cushion":
                      INITIAL_MARGIN_CAPITAL + shock_pnl - shock_maintenance})
    frame = pd.DataFrame(daily)
    peak = frame.margin_equity.cummax().clip(lower=INITIAL_MARGIN_CAPITAL)
    drawdown = frame.margin_equity / peak - 1
    report = {
        "maintenance_assumption": MAINTENANCE_ASSUMPTION,
        "initial_futures_margin": INITIAL_MARGIN_CAPITAL,
        "min_margin_equity": round(float(frame.margin_equity.min()), 6),
        "min_margin_cushion": round(float(frame.margin_cushion.min()), 6),
        "min_simultaneous_daily_high_cushion": round(
            float(frame.simultaneous_daily_high_cushion.min()), 6),
        "min_daily_high_plus_10pct_cushion": round(
            float(frame.daily_high_plus_10pct_cushion.min()), 6),
        "minimum_futures_margin_for_daily_high": round(
            float(INITIAL_MARGIN_CAPITAL - frame.simultaneous_daily_high_cushion.min()), 6),
        "minimum_futures_margin_for_high_plus_10pct": round(
            float(INITIAL_MARGIN_CAPITAL - frame.daily_high_plus_10pct_cushion.min()), 6),
        "max_margin_drawdown": round(float(drawdown.min()), 6),
        "worst_margin_day": frame.loc[frame.margin_cushion.idxmin(), "day"].isoformat(),
        "worst_daily_high_day": frame.loc[
            frame.simultaneous_daily_high_cushion.idxmin(), "day"].isoformat(),
        "runs": [{"symbol": run["symbol"], "start": run["start"].isoformat(),
                  "end": run["end"].isoformat(),
                  "max_perp_ratio": round(run["max_perp_ratio"], 4),
                  "max_perp_date": run["max_perp_date"].isoformat()}
                 for run in runs],
    }
    frame.to_parquet(ROOT / "outputs/spot_perp_margin_daily.parquet", index=False)
    output = ROOT / "outputs/spot_perp_margin_probe_report.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "runs"},
                     indent=2), flush=True)
    print("worst run ratios", sorted(
        [(run["symbol"], run["start"], run["max_perp_ratio"]) for run in runs],
        key=lambda row: row[2], reverse=True,
    )[:5], flush=True)
    print("saved", output, flush=True)


if __name__ == "__main__":
    main()
