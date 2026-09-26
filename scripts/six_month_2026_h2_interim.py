"""Post-result interim shadow risk observation for the frozen 2026 H2 basis rule."""

from __future__ import annotations

import hashlib
import json

import pandas as pd

from quarterly_basis_final_2026 import load_daily
from six_month_basis_replay import (
    FUTURE_SIDE_COST, FUTURES_CASH, INITIAL_CAPITAL, MAINTENANCE, MARK_SHOCK,
    ROOT, SPOT_ALLOCATION, SPOT_CASH, SPOT_SIDE_COST, SYMBOLS,
    download_sources,
)
from six_month_directional_volume_probe import directional_minutes, reach
from six_month_volume_window_probe import ACCOUNT_USDT


ENTRY = pd.Timestamp("2026-07-01", tz="UTC")
LAST_DAY = pd.Timestamp("2026-09-24", tz="UTC")
CONTRACT_SUFFIX = "261225"
REPORT = ROOT / "outputs/six_month_2026_h2_interim_report.json"


def source_tasks() -> tuple[list[tuple], list[tuple]]:
    daily = set()
    minutes = set()
    for symbol in SYMBOLS:
        contract = f"{symbol}_{CONTRACT_SUFFIX}"
        for market, name in (("spot", symbol), ("future", contract)):
            minutes.add((market, name, "2026-07-01"))
            for month in ("2026-07", "2026-08"):
                daily.add((market, name, month, True))
            for day in pd.date_range(pd.Timestamp("2026-09-01", tz="UTC"),
                                     LAST_DAY, freq="D"):
                daily.add((market, name, day.strftime("%Y-%m-%d"), False))
    return sorted(daily), sorted(minutes)


def entry_leg(symbol: str, bars: dict) -> tuple[dict | None, dict]:
    contract = f"{symbol}_{CONTRACT_SUFFIX}"
    spot = bars[("spot", symbol, "2026-07-01")]
    future = bars[("future", contract, "2026-07-01")]
    preliminary_q = SPOT_ALLOCATION / float(spot.iloc[0].high)
    preliminary_example_q = preliminary_q * ACCOUNT_USDT / INITIAL_CAPITAL
    spot_done = reach(spot, "taker_buy_base_volume", preliminary_example_q)
    future_done = reach(future, "taker_sell_base_volume", preliminary_example_q)
    status = {
        "symbol": symbol, "contract": contract,
        "preliminary_entry_quantity_at_1000_usdt": preliminary_example_q,
        "spot_taker_buy_five_minute_volume": float(spot.taker_buy_base_volume.sum()),
        "future_taker_sell_five_minute_volume": float(future.taker_sell_base_volume.sum()),
        "spot_threshold_minute": spot_done.isoformat() if spot_done is not None else None,
        "future_threshold_minute": future_done.isoformat() if future_done is not None else None,
    }
    if spot_done is None or future_done is None:
        status["availability"] = "entry directional volume shortfall"
        return None, status
    completion = max(spot_done, future_done)
    s0 = float(spot.loc[:completion].high.max())
    f0 = float(future.loc[:completion].low.min())
    q = SPOT_ALLOCATION / s0
    status["availability"] = "entry directional volume reached"
    return {
        **status,
        "entry_completion_minute": completion.isoformat(),
        "entry_delay_minutes": int((completion - ENTRY).total_seconds() / 60),
        "spot_entry_high": s0, "future_entry_low": f0,
        "quantity": q,
        "illustrative_1000_usdt_quantity": q * ACCOUNT_USDT / INITIAL_CAPITAL,
        "adverse_entry_premium_bps": (f0 / s0 - 1) * 10000,
    }, status


def observe(legs: list[dict], daily: dict) -> tuple[list[dict], dict]:
    days = pd.date_range(ENTRY, LAST_DAY, freq="D")
    for leg in legs:
        for market, name in (("spot", leg["symbol"]),
                             ("future", leg["contract"])):
            frame = daily[(market, name)].reindex(days)
            if frame.isna().any().any() or frame.le(0).any().any():
                raise ValueError(f"missing or invalid daily price: {market} {name}")
    spot_cash = SPOT_CASH - sum(
        leg["quantity"] * leg["spot_entry_high"] * (1 + SPOT_SIDE_COST)
        for leg in legs)
    futures_cash = FUTURES_CASH - sum(
        leg["quantity"] * leg["future_entry_low"] * FUTURE_SIDE_COST
        for leg in legs)
    path = []
    for day in days:
        margin_equity = futures_cash
        maintenance = 0.0
        liquidating = spot_cash + futures_cash
        for leg in legs:
            q = leg["quantity"]
            spot_bar = daily[("spot", leg["symbol"])].loc[day]
            future_bar = daily[("future", leg["contract"])].loc[day]
            shock_mark = float(future_bar.high) * (1 + MARK_SHOCK)
            spot_open = float(spot_bar.open)
            future_open = float(future_bar.open)
            margin_equity += q * (leg["future_entry_low"] - shock_mark)
            maintenance += q * shock_mark * MAINTENANCE
            liquidating += q * (spot_open + leg["future_entry_low"] - future_open)
            liquidating -= q * (SPOT_SIDE_COST * spot_open
                                + FUTURE_SIDE_COST * future_open)
        path.append({
            "day": day.isoformat(),
            "hypothetical_liquidating_equity_at_open": liquidating,
            "modeled_margin_shock_cushion": margin_equity - maintenance,
        })
    frame = pd.DataFrame(path)
    peak = frame.hypothetical_liquidating_equity_at_open.cummax().clip(
        lower=INITIAL_CAPITAL)
    latest = path[-1]
    breach = next((row["day"] for row in path
                   if row["modeled_margin_shock_cushion"] < 0), None)
    summary = {
        "initial_capital": INITIAL_CAPITAL,
        "spot_cash_after_hypothetical_entry": spot_cash,
        "futures_cash_after_hypothetical_entry": futures_cash,
        "observed_days": len(path),
        "last_observed_day": latest["day"],
        "latest_hypothetical_liquidating_equity_at_daily_open": (
            latest["hypothetical_liquidating_equity_at_open"]),
        "latest_hypothetical_liquidating_return_on_initial_capital": (
            latest["hypothetical_liquidating_equity_at_open"] / INITIAL_CAPITAL - 1),
        "minimum_modeled_margin_shock_cushion": min(
            row["modeled_margin_shock_cushion"] for row in path),
        "first_modeled_margin_breach_day": breach,
        "maximum_daily_hypothetical_liquidating_drawdown": float(
            (frame.hypothetical_liquidating_equity_at_open / peak - 1).min()),
    }
    return path, summary


def main() -> None:
    daily_tasks, minute_tasks = source_tasks()
    manifest = download_sources(daily_tasks, minute_tasks)
    bars = {task: directional_minutes(*task) for task in minute_tasks}
    observations = [entry_leg(symbol, bars) for symbol in SYMBOLS]
    legs = [leg for leg, _ in observations if leg is not None]
    availability = [status for _, status in observations]
    manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    report = {
        "protocol": "docs/six_month_2026_h2_interim_protocol.md, frozen at commit 4dd1362",
        "source": "Binance public spot and USD-M delivery 1d/1m archives; SHA256 and ZIP CRC verified",
        "archive_count": len(manifest),
        "source_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "entry_availability": availability,
        "entry_legs": legs,
        "limits": "Post-result daily traded-price observation, not a completed return, bid/ask fill, exact liquidation engine or live position",
    }
    if len(legs) != len(SYMBOLS):
        report["status"] = "entry directional volume shortfall"
        report["interim_risk"] = None
        REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        (ROOT / "outputs/six_month_2026_h2_interim_sources.json").write_bytes(
            manifest_bytes)
        print(json.dumps(report, indent=2), flush=True)
        print("saved", REPORT, flush=True)
        return
    daily = load_daily(daily_tasks)
    path, summary = observe(legs, daily)
    report["status"] = "complete interim risk observation"
    report["interim_risk"] = summary
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (ROOT / "outputs/six_month_2026_h2_interim_sources.json").write_bytes(
        manifest_bytes)
    pd.DataFrame(path).to_parquet(
        ROOT / "outputs/six_month_2026_h2_interim_daily.parquet", index=False)
    print(json.dumps(report, indent=2), flush=True)
    print("saved", REPORT, flush=True)


if __name__ == "__main__":
    main()
