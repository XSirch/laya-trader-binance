"""Post-result five-minute aggregate-volume stress for the six-month basis rule."""

from __future__ import annotations

import hashlib
import json

import pandas as pd

from quarterly_basis_final_2026 import load_daily
from quarterly_basis_minute_probe import first_minutes
from six_month_basis_replay import (
    INITIAL_CAPITAL, PERIODS, ROOT, SPOT_ALLOCATION, SPOT_SIDE_COST,
    FUTURE_SIDE_COST, SYMBOLS, download_sources, replay, sources,
)


ACCOUNT_USDT = 1000.0
REPORT = ROOT / "outputs/six_month_volume_window_report.json"


def completion(frame: pd.DataFrame, quantity: float) -> pd.Timestamp | None:
    reached = frame.volume.cumsum().ge(quantity)
    return frame.index[reached][0] if reached.any() else None


def volume_leg(period, symbol: str, minute_bars: dict) -> tuple[dict | None, dict]:
    entry = pd.Timestamp(period.entry, tz="UTC")
    exit_time = period.exit
    contract = f"{symbol}_{period.contract_suffix}"
    entry_day = entry.strftime("%Y-%m-%d")
    exit_day = exit_time.strftime("%Y-%m-%d")
    entry_spot = minute_bars[("spot", symbol, entry_day)]
    entry_future = minute_bars[("future", contract, entry_day)]
    preliminary_q = SPOT_ALLOCATION / float(entry_spot.iloc[0].high)
    preliminary_example_q = preliminary_q * ACCOUNT_USDT / INITIAL_CAPITAL
    entry_spot_done = completion(entry_spot, preliminary_example_q)
    entry_future_done = completion(entry_future, preliminary_example_q)
    fields = {"period": period.name, "symbol": symbol, "contract": contract,
              "preliminary_entry_quantity_at_1000_usdt": preliminary_example_q,
              "entry_spot_five_minute_volume": float(entry_spot.volume.sum()),
              "entry_future_five_minute_volume": float(entry_future.volume.sum())}
    if entry_spot_done is None or entry_future_done is None:
        fields["availability"] = "entry volume shortfall"
        return None, fields
    entry_done = max(entry_spot_done, entry_future_done)
    s0 = float(entry_spot.loc[:entry_done].high.max())
    f0 = float(entry_future.loc[:entry_done].low.min())
    q = SPOT_ALLOCATION / s0
    q_example = q * ACCOUNT_USDT / INITIAL_CAPITAL

    exit_spot = minute_bars[("spot", symbol, exit_day)]
    exit_future = minute_bars[("future", contract, exit_day)]
    exit_spot_done = completion(exit_spot, q_example)
    exit_future_done = completion(exit_future, q_example)
    fields.update({"quantity_at_1000_usdt": q_example,
                   "exit_spot_five_minute_volume": float(exit_spot.volume.sum()),
                   "exit_future_five_minute_volume": float(exit_future.volume.sum())})
    if exit_spot_done is None or exit_future_done is None:
        fields["availability"] = "exit volume shortfall"
        return None, fields
    exit_done = max(exit_spot_done, exit_future_done)
    s1 = float(exit_spot.loc[:exit_done].low.min())
    f1 = float(exit_future.loc[:exit_done].high.max())
    profit = q * (s1 - s0 + f0 - f1
                  - SPOT_SIDE_COST * (s0 + s1)
                  - FUTURE_SIDE_COST * (f0 + f1))
    entry_volume = min(float(entry_spot.loc[:entry_done].volume.sum()),
                       float(entry_future.loc[:entry_done].volume.sum()))
    exit_volume = min(float(exit_spot.loc[:exit_done].volume.sum()),
                      float(exit_future.loc[:exit_done].volume.sum()))
    fields["availability"] = "aggregate volume reached"
    fields["entry_completion_minute"] = entry_done.isoformat()
    fields["exit_completion_minute"] = exit_done.isoformat()
    leg = {
        **fields,
        "entry_minute": entry_done.isoformat(),
        "exit_minute": exit_done.isoformat(),
        "entry_delay_minutes": int((entry_done - entry).total_seconds() / 60),
        "exit_delay_minutes": int((exit_done - exit_time).total_seconds() / 60),
        "spot_entry_high": s0, "future_entry_low": f0,
        "spot_exit_low": s1, "future_exit_high": f1,
        "quantity": q, "stressed_cash_profit": profit,
        "illustrative_1000_usdt_quantity": q_example,
        "minimum_aggregate_entry_volume_through_completion": entry_volume,
        "minimum_aggregate_exit_volume_through_completion": exit_volume,
        "minute_volume_covers_illustrative_quantity": True,
    }
    return leg, fields


def main() -> None:
    daily_tasks, minute_tasks = sources()
    manifest = download_sources(daily_tasks, minute_tasks)
    minute_bars = {task: first_minutes(*task).sort_index()
                   for task in minute_tasks}
    legs = []
    availability = []
    for period in PERIODS:
        for symbol in SYMBOLS:
            leg, status = volume_leg(period, symbol, minute_bars)
            availability.append(status)
            if leg is not None:
                legs.append(leg)
                print(period.name, symbol, "entry delay",
                      leg["entry_delay_minutes"], "exit delay",
                      leg["exit_delay_minutes"], flush=True)
            else:
                print(period.name, symbol, status["availability"], flush=True)
    manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    report = {
        "protocol": "docs/six_month_volume_window_protocol.md, frozen at commit cd094c3",
        "source": "Binance public spot and USD-M delivery 1d/1m archives; SHA256 and ZIP CRC verified",
        "archive_count": len(manifest),
        "source_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "illustrative_total_account_usdt": ACCOUNT_USDT,
        "complete_volume_legs": len(legs),
        "required_legs": len(PERIODS) * len(SYMBOLS),
        "availability": availability,
        "limits": "Cumulative traded volume and adverse minute ranges are not bid/ask depth, queue position or fill guarantees; waiting can leave one side temporarily unhedged",
    }
    if len(legs) == len(PERIODS) * len(SYMBOLS):
        daily = load_daily(daily_tasks)
        _, path, summary = replay(legs, daily)
        report["result"] = summary
        report["maximum_completion_delay_minutes"] = max(
            max(leg["entry_delay_minutes"], leg["exit_delay_minutes"])
            for leg in legs)
        pd.DataFrame(legs).to_parquet(
            ROOT / "outputs/six_month_volume_window_legs.parquet", index=False)
        pd.DataFrame(path).to_parquet(
            ROOT / "outputs/six_month_volume_window_daily.parquet", index=False)
    else:
        report["result"] = None
        report["maximum_completion_delay_minutes"] = None
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (ROOT / "outputs/six_month_volume_window_sources.json").write_bytes(manifest_bytes)
    print(json.dumps({key: value for key, value in report.items()
                      if key != "availability"}, indent=2), flush=True)
    print("saved", REPORT, flush=True)


if __name__ == "__main__":
    main()
