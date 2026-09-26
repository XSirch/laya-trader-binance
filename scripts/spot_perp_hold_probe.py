"""Exploratory spot-perpetual carry with positions retained across monthly decisions."""

from __future__ import annotations

import json
import math

import pandas as pd

from funding_probe import SYMBOLS
from laya_trader.progress import ProgressReporter
from spot_perp_carry_probe import (
    EXTRA_PAIR_COST, FIRST_MONTH, FUNDING_CACHE, MIN_PAST_SETTLEMENTS,
    MIN_TRAILING_FUNDING, PERP_SIDE_COST, ROOT, SPOT_SIDE_COST, TRAILING_DAYS,
    VALIDATION_STAGES, download_spot, perp_and_funding, spot_opens,
)


SPOT_ALLOCATION = 0.2
ACCOUNT_CAPITAL = 2.0  # One unit for spot and one unit for perpetual margin.


def signal_at(funding: pd.DataFrame, start: pd.Timestamp) -> tuple[bool, float, int]:
    past = funding.loc[(funding.calc_time >= start - pd.Timedelta(days=TRAILING_DAYS))
                       & (funding.calc_time < start)]
    value = float(past.last_funding_rate.sum())
    return len(past) >= MIN_PAST_SETTLEMENTS and value > MIN_TRAILING_FUNDING, value, len(past)


def simulate_symbol(symbol: str, last_month: str) -> list[dict]:
    next_month = pd.Period(last_month, freq="M") + 1
    spot = spot_opens(symbol, str(next_month))
    perp, funding = perp_and_funding(symbol, next_month.start_time.date().isoformat())
    funding = funding.loc[funding.calc_time < next_month.start_time.tz_localize("UTC")]
    months = pd.period_range(FIRST_MONTH, last_month, freq="M")
    quantity = 0.0
    rows = []
    for month in months:
        start = month.start_time.tz_localize("UTC")
        end = (month + 1).start_time.tz_localize("UTC")
        active, signal, count = signal_at(funding, start)
        next_active, _, _ = signal_at(funding, end)
        record = {"symbol": symbol, "month": str(month), "active": active,
                  "signal_30d": signal, "past_settlements": count,
                  "next_active": next_active, "quantity": quantity,
                  "price_cash": 0.0, "funding_cash": 0.0,
                  "entry_cost_cash": 0.0, "exit_cost_cash": 0.0,
                  "stress_cost_cash": 0.0, "net_on_capital": 0.0,
                  "stress_net_on_capital": 0.0}
        if not active:
            if quantity != 0.0:
                raise ValueError(f"position transition mismatch: {symbol} {month}")
            rows.append(record)
            continue
        if start not in spot.index or end not in spot.index:
            raise ValueError(f"missing spot entry or exit: {symbol} {month}")
        if start not in perp.index or end not in perp.index:
            raise ValueError(f"missing perpetual entry or exit: {symbol} {month}")
        s0, s1 = float(spot[start]), float(spot[end])
        f0, f1 = float(perp[start]), float(perp[end])
        opening = quantity == 0.0
        if opening:
            quantity = SPOT_ALLOCATION / s0
        record["quantity"] = quantity
        settled = funding.loc[(funding.calc_time > start) & (funding.calc_time < end)]
        if len(settled) < (end - start).days * 2.5:
            raise ValueError(f"sparse funding settlements: {symbol} {month}")
        price_cash = quantity * (s1 - s0 - f1 + f0)
        funding_cash = quantity * float((settled.last_funding_rate * settled.perp_mark).sum())
        entry_cost = quantity * (SPOT_SIDE_COST * s0 + PERP_SIDE_COST * f0) if opening else 0.0
        closing = not next_active
        exit_cost = quantity * (SPOT_SIDE_COST * s1 + PERP_SIDE_COST * f1) if closing else 0.0
        extra_side = EXTRA_PAIR_COST / 4
        stress_cost = quantity * extra_side * (
            (s0 + f0 if opening else 0.0) + (s1 + f1 if closing else 0.0)
        )
        net = (price_cash + funding_cash - entry_cost - exit_cost) / ACCOUNT_CAPITAL
        record.update({
            "price_cash": price_cash, "funding_cash": funding_cash,
            "entry_cost_cash": entry_cost, "exit_cost_cash": exit_cost,
            "stress_cost_cash": stress_cost,
            "net_on_capital": net,
            "stress_net_on_capital": net - stress_cost / ACCOUNT_CAPITAL,
        })
        rows.append(record)
        if closing:
            quantity = 0.0
    return rows


def build(last_month: str) -> pd.DataFrame:
    download_spot(str(pd.Period(last_month, freq="M") + 1))
    progress = ProgressReporter(f"retained carry through {last_month}", len(SYMBOLS), unit="symbols")
    rows = []
    for count, symbol in enumerate(SYMBOLS, 1):
        rows.extend(simulate_symbol(symbol, last_month))
        progress.update(count)
    return pd.DataFrame(rows)


def summarize(frame: pd.DataFrame, first_month: str, last_month: str) -> dict:
    months = pd.period_range(first_month, last_month, freq="M").astype(str)
    segment = frame.loc[frame.month.isin(months)]
    monthly = segment.groupby("month", sort=True).agg(
        net=("net_on_capital", "sum"), stress=("stress_net_on_capital", "sum"),
        active_legs=("active", "sum"),
        funding_cash=("funding_cash", "sum"),
        price_cash=("price_cash", "sum"),
        entry_cost_cash=("entry_cost_cash", "sum"),
        exit_cost_cash=("exit_cost_cash", "sum"),
    )
    active = monthly.active_legs.gt(0)
    equity = 1 + monthly.net.cumsum()
    drawdown = equity / equity.cummax().clip(lower=1) - 1
    return {
        "months": len(monthly), "active_months": int(active.sum()),
        "active_legs": int(monthly.active_legs.sum()),
        "positive_active_months": int(monthly.loc[active, "net"].gt(0).sum()),
        "mean_monthly_net_on_capital": round(float(monthly.net.mean()), 6),
        "mean_monthly_stress_on_capital": round(float(monthly.stress.mean()), 6),
        "total_return_on_capital": round(float(monthly.net.sum()), 6),
        "max_month_end_drawdown": round(float(drawdown.min()), 6),
        "monthly": monthly.round(6).reset_index().to_dict(orient="records"),
    }


def passes(result: dict) -> bool:
    return (result["months"] == 6 and result["active_months"] >= 4
            and result["active_legs"] >= 10
            and result["positive_active_months"]
            >= math.ceil(0.75 * result["active_months"])
            and result["mean_monthly_net_on_capital"] > 0
            and result["mean_monthly_stress_on_capital"] > 0
            and result["max_month_end_drawdown"] > -0.15)


def main() -> None:
    frame = build("2023-12")
    report = {
        "hypothesis": "retain long spot and short perpetual while trailing 30d funding exceeds 0.5%",
        "provenance": "exploratory revision after inspecting monthly-turnover results through 2025 H1",
        "account_capital": ACCOUNT_CAPITAL,
        "spot_allocation_per_symbol": SPOT_ALLOCATION,
        "train": summarize(frame, "2023-02", "2023-06"),
        "calibration": summarize(frame, "2023-07", "2023-12"),
    }
    passed = passes(report["calibration"])
    report["calibration_gate"] = passed
    for stage_name, first_month, last_month in VALIDATION_STAGES:
        report[stage_name] = None
        diagnostic = stage_name.startswith("diagnostic_")
        if not passed and not (diagnostic and report.get("validation_2025_h1") is not None):
            continue
        frame = build(last_month)
        result = summarize(frame, first_month, last_month)
        report[stage_name] = result
        if not diagnostic:
            passed = passes(result)
            report[f"{stage_name}_gate"] = passed
        print(stage_name, "gate", "diagnostic only" if diagnostic else passed,
              "mean on capital", result["mean_monthly_net_on_capital"], flush=True)
    output = ROOT / "outputs/spot_perp_hold_probe_report.json"
    frame.to_parquet(ROOT / "outputs/spot_perp_hold_probe_legs.parquet", index=False)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: {k: v for k, v in value.items() if k != "monthly"}
                      if isinstance(value, dict) else value
                      for key, value in report.items() if key.endswith("_gate")
                      or key in ("train", "calibration")
                      or key.startswith(("validation_", "diagnostic_"))},
                     indent=2), flush=True)
    print("saved", output, flush=True)


if __name__ == "__main__":
    main()
