"""Post-result directional trade-volume stress for the six-month basis rule."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

import numpy as np
import pandas as pd

from laya_trader.dataset.build import _read_zip
from laya_trader.features.core import normalize_klines
from quarterly_basis_final_2026 import load_daily
from quarterly_basis_minute_probe import archive_path
from six_month_basis_replay import (
    FUTURE_SIDE_COST, INITIAL_CAPITAL, PERIODS, ROOT, SPOT_ALLOCATION,
    SPOT_SIDE_COST, SYMBOLS, download_sources, replay, sources,
)
from six_month_volume_window_probe import ACCOUNT_USDT, completion


REPORT = ROOT / "outputs/six_month_directional_volume_report.json"


def directional_minutes(market: str, name: str, day: str) -> pd.DataFrame:
    frame = normalize_klines(_read_zip(archive_path(market, name, day)))
    start = pd.Timestamp(day, tz="UTC")
    end = start + timedelta(minutes=5)
    rows = frame.loc[
        (frame.open_time >= start) & (frame.open_time < end),
        ["open_time", "high", "low", "volume", "quote_volume", "taker_buy_base_volume"],
    ].copy()
    numeric = rows[["high", "low", "volume", "quote_volume", "taker_buy_base_volume"]]
    if rows.empty or not np.isfinite(numeric.to_numpy()).all():
        raise ValueError(f"missing or nonfinite directional bars: {market} {name} {day}")
    if (rows.volume.lt(0) | rows.taker_buy_base_volume.lt(0)
            | rows.taker_buy_base_volume.gt(rows.volume + 1e-10)).any():
        raise ValueError(f"invalid taker volume: {market} {name} {day}")
    rows = rows.loc[
        rows.low.gt(0) & rows.high.ge(rows.low)
        & rows.volume.gt(0) & rows.quote_volume.gt(0)
    ].copy()
    if rows.empty:
        raise ValueError(f"no traded minutes: {market} {name} {day}")
    rows["taker_sell_base_volume"] = (
        rows.volume - rows.taker_buy_base_volume).clip(lower=0)
    return rows.set_index("open_time").sort_index()


def reach(frame: pd.DataFrame, column: str, quantity: float) -> pd.Timestamp | None:
    reached = frame[column].cumsum().ge(quantity)
    return frame.index[reached][0] if reached.any() else None


def directional_leg(period, symbol: str, bars: dict, aggregate_bars: dict) -> tuple[dict | None, dict]:
    entry = pd.Timestamp(period.entry, tz="UTC")
    exit_time = period.exit
    contract = f"{symbol}_{period.contract_suffix}"
    entry_day = entry.strftime("%Y-%m-%d")
    exit_day = exit_time.strftime("%Y-%m-%d")
    entry_spot = bars[("spot", symbol, entry_day)]
    entry_future = bars[("future", contract, entry_day)]
    preliminary_q = SPOT_ALLOCATION / float(entry_spot.iloc[0].high)
    preliminary_example_q = preliminary_q * ACCOUNT_USDT / INITIAL_CAPITAL
    entry_spot_done = reach(entry_spot, "taker_buy_base_volume", preliminary_example_q)
    entry_future_done = reach(entry_future, "taker_sell_base_volume", preliminary_example_q)
    status = {
        "period": period.name, "symbol": symbol, "contract": contract,
        "preliminary_entry_quantity_at_1000_usdt": preliminary_example_q,
        "entry_spot_taker_buy_five_minute_volume": float(entry_spot.taker_buy_base_volume.sum()),
        "entry_future_taker_sell_five_minute_volume": float(entry_future.taker_sell_base_volume.sum()),
        "entry_spot_threshold_minute": entry_spot_done.isoformat() if entry_spot_done is not None else None,
        "entry_future_threshold_minute": entry_future_done.isoformat() if entry_future_done is not None else None,
    }
    if entry_spot_done is None or entry_future_done is None:
        status["availability"] = "entry directional volume shortfall"
        return None, status
    entry_done = max(entry_spot_done, entry_future_done)
    s0 = float(entry_spot.loc[:entry_done].high.max())
    f0 = float(entry_future.loc[:entry_done].low.min())
    q = SPOT_ALLOCATION / s0
    q_example = q * ACCOUNT_USDT / INITIAL_CAPITAL

    exit_spot = bars[("spot", symbol, exit_day)]
    exit_future = bars[("future", contract, exit_day)]
    exit_spot_done = reach(exit_spot, "taker_sell_base_volume", q_example)
    exit_future_done = reach(exit_future, "taker_buy_base_volume", q_example)
    status.update({
        "quantity_at_1000_usdt": q_example,
        "exit_spot_taker_sell_five_minute_volume": float(exit_spot.taker_sell_base_volume.sum()),
        "exit_future_taker_buy_five_minute_volume": float(exit_future.taker_buy_base_volume.sum()),
        "exit_spot_threshold_minute": exit_spot_done.isoformat() if exit_spot_done is not None else None,
        "exit_future_threshold_minute": exit_future_done.isoformat() if exit_future_done is not None else None,
    })
    if exit_spot_done is None or exit_future_done is None:
        status["availability"] = "exit directional volume shortfall"
        return None, status
    exit_done = max(exit_spot_done, exit_future_done)
    s1 = float(exit_spot.loc[:exit_done].low.min())
    f1 = float(exit_future.loc[:exit_done].high.max())
    profit = q * (s1 - s0 + f0 - f1
                  - SPOT_SIDE_COST * (s0 + s1)
                  - FUTURE_SIDE_COST * (f0 + f1))
    aggregate_entry_spot = aggregate_bars[("spot", symbol, entry_day)]
    aggregate_entry_future = aggregate_bars[("future", contract, entry_day)]
    aggregate_exit_spot = aggregate_bars[("spot", symbol, exit_day)]
    aggregate_exit_future = aggregate_bars[("future", contract, exit_day)]
    aggregate_entry_done = max(completion(aggregate_entry_spot, preliminary_example_q),
                               completion(aggregate_entry_future, preliminary_example_q))
    aggregate_exit_done = max(completion(aggregate_exit_spot, q_example),
                              completion(aggregate_exit_future, q_example))
    status.update({
        "availability": "directional volume reached",
        "entry_completion_minute": entry_done.isoformat(),
        "exit_completion_minute": exit_done.isoformat(),
        "directional_entry_reached_by_aggregate_deadline": entry_done <= aggregate_entry_done,
        "directional_exit_reached_by_aggregate_deadline": exit_done <= aggregate_exit_done,
    })
    leg = {
        **status,
        "entry_minute": entry_done.isoformat(), "exit_minute": exit_done.isoformat(),
        "entry_delay_minutes": int((entry_done - entry).total_seconds() / 60),
        "exit_delay_minutes": int((exit_done - exit_time).total_seconds() / 60),
        "spot_entry_high": s0, "future_entry_low": f0,
        "spot_exit_low": s1, "future_exit_high": f1,
        "quantity": q, "stressed_cash_profit": profit,
        "illustrative_1000_usdt_quantity": q_example,
        "minute_volume_covers_illustrative_quantity": True,
    }
    return leg, status


def main() -> None:
    daily_tasks, minute_tasks = sources()
    manifest = download_sources(daily_tasks, minute_tasks)
    bars = {task: directional_minutes(*task) for task in minute_tasks}
    aggregate_bars = {task: frame[["volume"]] for task, frame in bars.items()}
    legs = []
    availability = []
    for period in PERIODS:
        for symbol in SYMBOLS:
            leg, status = directional_leg(period, symbol, bars, aggregate_bars)
            availability.append(status)
            if leg is None:
                print(period.name, symbol, status["availability"], flush=True)
            else:
                legs.append(leg)
                print(period.name, symbol, "entry delay", leg["entry_delay_minutes"],
                      "exit delay", leg["exit_delay_minutes"], flush=True)
    manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    report = {
        "protocol": "docs/six_month_directional_volume_protocol.md, frozen at commit 67e24da",
        "source": "Binance public spot and USD-M delivery 1d/1m archives; SHA256 and ZIP CRC verified",
        "archive_count": len(manifest),
        "source_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "illustrative_total_account_usdt": ACCOUNT_USDT,
        "complete_directional_volume_legs": len(legs),
        "required_legs": len(PERIODS) * len(SYMBOLS),
        "availability": availability,
        "limits": "Historical same-direction taker volume is activity, not bid/ask depth, queue position, executable size or a fill guarantee; sequential completion can leave one side temporarily unhedged",
    }
    if len(legs) == len(PERIODS) * len(SYMBOLS):
        daily = load_daily(daily_tasks)
        _, path, summary = replay(legs, daily)
        report["result"] = summary
        report["maximum_completion_delay_minutes"] = max(
            max(leg["entry_delay_minutes"], leg["exit_delay_minutes"])
            for leg in legs)
        report["legs_reached_by_aggregate_completion_deadline"] = sum(
            leg["directional_entry_reached_by_aggregate_deadline"]
            and leg["directional_exit_reached_by_aggregate_deadline"]
            for leg in legs)
        pd.DataFrame(legs).to_parquet(
            ROOT / "outputs/six_month_directional_volume_legs.parquet", index=False)
        pd.DataFrame(path).to_parquet(
            ROOT / "outputs/six_month_directional_volume_daily.parquet", index=False)
    else:
        report["result"] = None
        report["maximum_completion_delay_minutes"] = None
        report["legs_reached_by_aggregate_completion_deadline"] = None
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (ROOT / "outputs/six_month_directional_volume_sources.json").write_bytes(manifest_bytes)
    print(json.dumps({key: value for key, value in report.items()
                      if key != "availability"}, indent=2), flush=True)
    print("saved", REPORT, flush=True)


if __name__ == "__main__":
    main()
