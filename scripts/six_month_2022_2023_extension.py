"""Fixed earlier-regime extension of the six-month delivery-basis replay."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

import six_month_basis_replay as basis
from laya_trader.progress import ProgressReporter
from quarterly_basis_final_2026 import load_daily
from six_month_directional_volume_probe import directional_leg, directional_minutes


EXTENSION_PERIODS = (
    basis.Period("2022H1", "2022-01-01", "2022-06-24"),
    basis.Period("2022H2", "2022-07-01", "2022-12-30"),
    basis.Period("2023H1", "2023-01-01", "2023-06-30"),
    basis.Period("2023H2", "2023-07-01", "2023-12-29"),
)
REPORT = basis.ROOT / "outputs/six_month_2022_2023_extension_report.json"


def verified_manifest(daily_tasks: list[tuple], minute_tasks: list[tuple]) -> list[dict]:
    tasks = [(basis.fetch_daily, task) for task in daily_tasks]
    tasks.extend((basis.fetch_minute_verified, task) for task in minute_tasks)
    manifest = []
    progress = ProgressReporter("earlier-regime archives", len(tasks), unit="archives")
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(function, task) for function, task in tasks]
        for count, future in enumerate(as_completed(futures), 1):
            manifest.append(future.result())
            progress.update(count)
    return sorted(manifest, key=lambda row: str(row["task"]))


def write_report(report: dict, manifest: list[dict] | None = None) -> None:
    if manifest is not None:
        manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
        report["archive_count"] = len(manifest)
        report["source_manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
        (basis.ROOT / "outputs/six_month_2022_2023_extension_sources.json").write_bytes(
            manifest_bytes)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items()
                      if key != "availability"}, indent=2), flush=True)
    print("saved", REPORT, flush=True)


def main() -> None:
    basis.PERIODS = EXTENSION_PERIODS
    report = {
        "protocol": "docs/six_month_2022_2023_extension_protocol.md, frozen at commit 4ad12aa",
        "source": "Binance public spot and USD-M delivery 1d/1m archives; SHA256 and ZIP CRC required",
        "periods": [period.name for period in EXTENSION_PERIODS],
        "required_legs": len(EXTENSION_PERIODS) * len(basis.SYMBOLS),
        "limits": "Earlier historical periods are not prospective; traded-volume direction does not establish bid/ask depth or fill capacity; account fees, eligibility and financing remain unknown",
    }
    daily_tasks, minute_tasks = basis.sources()
    manifest = verified_manifest(daily_tasks, minute_tasks)
    failures = [row for row in manifest if row["status"] != "verified"]
    if failures:
        report["status"] = "verified archive set incomplete"
        report["missing_or_invalid_archives"] = failures
        write_report(report, manifest)
        return
    bars = {task: directional_minutes(*task) for task in minute_tasks}
    aggregate_bars = {task: frame[["volume"]] for task, frame in bars.items()}
    legs = []
    availability = []
    for period in EXTENSION_PERIODS:
        for symbol in basis.SYMBOLS:
            leg, status = directional_leg(period, symbol, bars, aggregate_bars)
            availability.append(status)
            if leg is None:
                print(period.name, symbol, status["availability"], flush=True)
            else:
                legs.append(leg)
                print(period.name, symbol, "entry delay", leg["entry_delay_minutes"],
                      "exit delay", leg["exit_delay_minutes"], flush=True)
    report["availability"] = availability
    report["complete_directional_volume_legs"] = len(legs)
    if len(legs) != report["required_legs"]:
        report["status"] = "directional volume shortfall"
        report["result"] = None
        write_report(report, manifest)
        return
    daily = load_daily(daily_tasks)
    periods, path, summary = basis.replay(legs, daily)
    for row in periods:
        holding_days = (pd.Timestamp(row["exit"]) - pd.Timestamp(row["entry"])).days
        row["holding_days"] = holding_days
        row["simple_annualized_break_even_capital_charge"] = (
            row["return_on_initial_capital"] * 365 / holding_days)
    report["status"] = "complete historical extension"
    report["result"] = {
        "initial_capital": summary["initial_capital"],
        "periods": periods,
        "total_stressed_cash_profit": summary["total_stressed_cash_profit"],
        "total_return_on_initial_capital": summary["total_return_on_initial_capital"],
        "minimum_margin_shock_cushion": summary["minimum_margin_shock_cushion"],
        "minimum_spot_cash": summary["minimum_spot_cash"],
        "maximum_daily_liquidation_drawdown": summary["maximum_daily_liquidation_drawdown"],
        "all_four_half_years_profitable": all(row["stressed_cash_profit"] > 0
                                          for row in periods),
        "wallet_and_margin_remain_positive": (
            summary["minimum_spot_cash"] >= 0
            and summary["minimum_margin_shock_cushion"] >= 0),
    }
    pd.DataFrame(legs).to_parquet(
        basis.ROOT / "outputs/six_month_2022_2023_extension_legs.parquet", index=False)
    pd.DataFrame(path).to_parquet(
        basis.ROOT / "outputs/six_month_2022_2023_extension_daily.parquet", index=False)
    write_report(report, manifest)


if __name__ == "__main__":
    main()
