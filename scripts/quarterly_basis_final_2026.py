"""Run the frozen 2026 quarterly-basis evaluation exactly once per data revision."""

from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import requests

from laya_trader.dataset.build import _read_zip
from laya_trader.features.core import normalize_klines
from laya_trader.progress import ProgressReporter
from quarterly_basis_minute_probe import (
    EXAMPLE_ACCOUNT_USDT, EXTRA_SIDE_COST, FURTHER_FUTURES_SIDE_COST,
    FURTHER_SPOT_SIDE_COST, archive_path as minute_path, archive_url as minute_url,
    fetch_one as fetch_minute, first_minutes, leg_result,
)
from quarterly_basis_probe import (
    EXTRA_MARK_SHOCK, FUTURES_MARGIN, MAINTENANCE_ASSUMPTION, SPOT_CASH,
    SYMBOLS, contract_dates, contract_name,
)
from spot_perp_carry_probe import PERP_SIDE_COST, ROOT, SPOT_SIDE_COST


ARCHIVES = ROOT / "outputs/quarterly_basis_final_2026_archives"
OUTPUT = ROOT / "outputs/quarterly_basis_final_2026_report.json"
INITIAL_CAPITAL = SPOT_CASH + FUTURES_MARGIN
SPOT_COST = SPOT_SIDE_COST + EXTRA_SIDE_COST + FURTHER_SPOT_SIDE_COST
FUTURE_COST = PERP_SIDE_COST + EXTRA_SIDE_COST + FURTHER_FUTURES_SIDE_COST
QUARTERS = pd.period_range("2026Q1", "2026Q3", freq="Q")


def daily_archive_task(market: str, name: str, key: str, monthly: bool) -> tuple:
    return market, name, key, monthly


def archive_path(task: tuple) -> Path:
    market, name, key, monthly = task
    frequency = "monthly" if monthly else "daily"
    return ARCHIVES / market / frequency / name / f"{name}-1d-{key}.zip"


def archive_url(task: tuple) -> str:
    market, name, key, monthly = task
    root = "spot" if market == "spot" else "futures/um"
    frequency = "monthly" if monthly else "daily"
    return (f"https://data.binance.vision/data/{root}/{frequency}/klines/"
            f"{name}/1d/{name}-1d-{key}.zip")


def fetch_daily(task: tuple) -> dict:
    path = archive_path(task)
    url = archive_url(task)
    for attempt in range(3):
        try:
            if path.is_file():
                payload = path.read_bytes()
            else:
                response = requests.get(url, timeout=30)
                if response.status_code == 404:
                    return {"task": task, "status": "missing"}
                response.raise_for_status()
                payload = response.content
            checksum = requests.get(url + ".CHECKSUM", timeout=20)
            checksum.raise_for_status()
            expected = checksum.text.split()[0].lower()
            digest = hashlib.sha256(payload).hexdigest()
            if digest != expected:
                raise ValueError(f"SHA256 mismatch: {url}")
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                if archive.testzip() is not None:
                    raise ValueError(f"ZIP CRC failure: {url}")
            if not path.is_file():
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".zip.tmp")
                temporary.write_bytes(payload)
                temporary.replace(path)
            return {"task": task, "status": "verified", "sha256": digest}
        except (requests.RequestException, zipfile.BadZipFile, ValueError, IndexError) as exc:
            if attempt == 2:
                return {"task": task, "status": "error", "reason": str(exc)}
            time.sleep(1 + 2 * attempt)
    raise AssertionError("unreachable")


def fetch_minute_verified(task: tuple) -> dict:
    market, name, day = task
    result = fetch_minute(market, name, day)
    if result[3] in ("error", "missing"):
        return {"task": [*task, "1m"], "status": result[3]}
    path = minute_path(market, name, day)
    url = minute_url(market, name, day)
    for attempt in range(3):
        try:
            payload = path.read_bytes()
            response = requests.get(url + ".CHECKSUM", timeout=20)
            response.raise_for_status()
            digest = hashlib.sha256(payload).hexdigest()
            if digest != response.text.split()[0].lower():
                raise ValueError(f"SHA256 mismatch: {url}")
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                if archive.testzip() is not None:
                    raise ValueError(f"ZIP CRC failure: {url}")
            return {"task": [*task, "1m"], "status": "verified", "sha256": digest}
        except (requests.RequestException, zipfile.BadZipFile, ValueError, IndexError) as exc:
            if attempt == 2:
                return {"task": [*task, "1m"], "status": "error", "reason": str(exc)}
            time.sleep(1 + 2 * attempt)
    raise AssertionError("unreachable")


def source_tasks() -> tuple[list[tuple], list[tuple], list[SimpleNamespace]]:
    daily = set()
    minutes = set()
    legs = []
    for quarter in QUARTERS:
        entry, exit_time, expiry = contract_dates(quarter)
        for symbol in SYMBOLS:
            contract = contract_name(symbol, expiry)
            legs.append(SimpleNamespace(quarter=str(quarter), symbol=symbol,
                                        contract=contract, entry=entry, exit=exit_time))
            for day in (entry, exit_time):
                key = day.strftime("%Y-%m-%d")
                minutes.add(("spot", symbol, key))
                minutes.add(("future", contract, key))
            for month in pd.period_range(entry.tz_localize(None),
                                         exit_time.tz_localize(None), freq="M"):
                if str(month) == "2026-09":
                    for day in pd.date_range("2026-09-01", "2026-09-22", freq="D"):
                        daily.add(daily_archive_task("spot", symbol,
                                                     day.strftime("%Y-%m-%d"), False))
                        daily.add(daily_archive_task("future", contract,
                                                     day.strftime("%Y-%m-%d"), False))
                else:
                    daily.add(daily_archive_task("spot", symbol, str(month), True))
                    daily.add(daily_archive_task("future", contract, str(month), True))
    return sorted(daily), sorted(minutes), legs


def download_sources(daily_tasks: list[tuple], minute_tasks: list[tuple]) -> list[dict]:
    total = len(daily_tasks) + len(minute_tasks)
    progress = ProgressReporter("2026 frozen source archives", total, unit="archives")
    manifest = []
    failures = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = ([pool.submit(fetch_daily, task) for task in daily_tasks]
                   + [pool.submit(fetch_minute_verified, task) for task in minute_tasks])
        for count, future in enumerate(as_completed(futures), 1):
            result = future.result()
            if result["status"] in ("error", "missing"):
                failures.append(result)
            manifest.append(result)
            progress.update(count)
    if failures:
        raise RuntimeError(f"Required 2026 archives unavailable: {failures}")
    return manifest


def load_daily(tasks: list[tuple]) -> dict[tuple[str, str], pd.DataFrame]:
    by_market = {}
    for task in tasks:
        market, name, _, _ = task
        frame = normalize_klines(_read_zip(archive_path(task)))
        by_market.setdefault((market, name), []).append(frame)
    result = {}
    for key, frames in by_market.items():
        frame = pd.concat(frames, ignore_index=True)
        frame = frame.drop_duplicates("open_time").sort_values("open_time")
        if frame.open_time.duplicated().any():
            raise ValueError(f"Duplicate daily timestamps: {key}")
        result[key] = frame.set_index("open_time")[["open", "high"]].astype(float)
    return result


def model(legs: list[SimpleNamespace], minute_tasks: list[tuple],
          daily: dict[tuple[str, str], pd.DataFrame]) -> tuple[list[dict], list[dict], dict]:
    minute_bars = {task: first_minutes(*task) for task in minute_tasks}
    executions = [leg_result(leg, minute_bars) for leg in legs]
    by_quarter = {quarter: [row for row in executions if row["quarter"] == quarter]
                  for quarter in (str(item) for item in QUARTERS)}
    spot_cash, futures_cash = SPOT_CASH, FUTURES_MARGIN
    quarter_rows = []
    daily_rows = []
    min_margin = float("inf")
    min_spot_cash = float("inf")
    for quarter in QUARTERS:
        rows = by_quarter[str(quarter)]
        if len(rows) != len(SYMBOLS) or {row["symbol"] for row in rows} != set(SYMBOLS):
            raise ValueError(f"Incomplete legs: {quarter}")
        entry, exit_time, _ = contract_dates(quarter)
        days = pd.date_range(entry, exit_time, freq="D", inclusive="left")
        for row in rows:
            for market, name in (("spot", row["symbol"]), ("future", row["contract"])):
                if daily[(market, name)].reindex(days).isna().any().any():
                    raise ValueError(f"Incomplete daily series: {quarter} {market} {name}")
        before = spot_cash + futures_cash
        for row in rows:
            q = 0.5 / row["spot_entry_adverse"]
            row["quantity"] = q
            spot_cash -= q * row["spot_entry_adverse"] * (1 + SPOT_COST)
            futures_cash -= q * row["future_entry_adverse"] * FUTURE_COST
        min_spot_cash = min(min_spot_cash, spot_cash)
        for day in days:
            margin_equity = futures_cash
            maintenance = 0.0
            liquidating = spot_cash + futures_cash
            for row in rows:
                q = row["quantity"]
                future = daily[("future", row["contract"])].loc[day]
                spot = daily[("spot", row["symbol"])].loc[day]
                shock_mark = float(future["high"]) * (1 + EXTRA_MARK_SHOCK)
                f_open, s_open = float(future["open"]), float(spot["open"])
                margin_equity += q * (row["future_entry_adverse"] - shock_mark)
                maintenance += q * shock_mark * MAINTENANCE_ASSUMPTION
                liquidating += q * (s_open + row["future_entry_adverse"] - f_open)
                liquidating -= q * (SPOT_COST * s_open + FUTURE_COST * f_open)
            cushion = margin_equity - maintenance
            min_margin = min(min_margin, cushion)
            daily_rows.append({"day": day, "quarter": str(quarter),
                               "estimated_liquidating_equity": liquidating,
                               "margin_shock_cushion": cushion})
        for row in rows:
            q = row["quantity"]
            spot_cash += q * row["spot_exit_adverse"] * (1 - SPOT_COST)
            futures_cash += q * (row["future_entry_adverse"]
                                  - row["future_exit_adverse"])
            futures_cash -= q * row["future_exit_adverse"] * FUTURE_COST
        after = spot_cash + futures_cash
        daily_rows.append({"day": exit_time, "quarter": str(quarter),
                           "estimated_liquidating_equity": after,
                           "margin_shock_cushion": None})
        transfer = FUTURES_MARGIN - futures_cash
        spot_cash -= transfer
        futures_cash += transfer
        min_spot_cash = min(min_spot_cash, spot_cash)
        expected_profit = sum(row["further_stress_cash"] for row in rows)
        if abs((after - before) - expected_profit) > 1e-8:
            raise ValueError(f"Account/leg profit mismatch: {quarter}")
        quarter_rows.append({"quarter": str(quarter), "entry": entry.isoformat(),
                             "exit": exit_time.isoformat(), "further_stress_cash": after - before,
                             "return_on_initial_capital": (after - before) / INITIAL_CAPITAL,
                             "account_equity_after_exit": after,
                             "spot_cash_after_transfer": spot_cash,
                             "futures_cash_after_transfer": futures_cash,
                             "transfer_to_futures": transfer,
                             "minimum_margin_shock_cushion": min(
                                 row["margin_shock_cushion"] for row in daily_rows
                                 if row["quarter"] == str(quarter)
                                 and row["margin_shock_cushion"] is not None)})
    path = pd.DataFrame(daily_rows).sort_values("day")
    peak = path.estimated_liquidating_equity.cummax().clip(lower=INITIAL_CAPITAL)
    maximum_drawdown = float((path.estimated_liquidating_equity / peak - 1).min())
    for row in executions:
        q_example = row["quantity"] * EXAMPLE_ACCOUNT_USDT / INITIAL_CAPITAL
        row["minute_volume_covers_1000_usdt"] = bool(min(
            row["entry_spot_volume"], row["entry_future_volume"],
            row["exit_spot_volume"], row["exit_future_volume"]) >= q_example)
    profit = spot_cash + futures_cash - INITIAL_CAPITAL
    conditions = {
        "three_positive_quarters": all(row["further_stress_cash"] > 0 for row in quarter_rows),
        "aggregate_return_at_least_1_5_percent": profit / INITIAL_CAPITAL >= 0.015,
        "minimum_margin_cushion_at_least_0_50": min_margin >= 0.50,
        "no_spot_wallet_shortfall": min_spot_cash >= 0,
        "maximum_daily_drawdown_less_than_5_percent": maximum_drawdown > -0.05,
        "all_common_minutes_within_5_minutes": all(
            row["entry_delay_min"] < 5 and row["exit_delay_min"] < 5
            for row in executions),
    }
    summary = {
        "initial_capital": INITIAL_CAPITAL,
        "spot_cost_per_side": SPOT_COST,
        "futures_cost_per_side": FUTURE_COST,
        "quarters": quarter_rows,
        "total_further_stress_cash": profit,
        "total_return_on_initial_capital": profit / INITIAL_CAPITAL,
        "minimum_margin_shock_cushion": min_margin,
        "minimum_spot_cash": min_spot_cash,
        "maximum_daily_liquidation_drawdown": maximum_drawdown,
        "minute_volume_covers_1000_usdt_legs": sum(
            row["minute_volume_covers_1000_usdt"] for row in executions),
        "legs": len(executions),
        "conditions": conditions,
        "quantitative_gate_passed": all(conditions.values()),
    }
    return executions, daily_rows, summary


def main() -> None:
    daily_tasks, minute_tasks, legs = source_tasks()
    manifest = download_sources(daily_tasks, minute_tasks)
    daily = load_daily(daily_tasks)
    executions, daily_rows, summary = model(legs, minute_tasks, daily)
    report = {
        "protocol": "docs/quarterly_basis_2026_protocol.md, frozen at commit 5ad9f22",
        "source": "Binance public 1d and 1m spot/quarterly future archives; SHA256 and ZIP CRC verified",
        "archive_count": len(manifest),
        "result": summary,
        "limitations": [
            "One-minute high/low and volume do not prove order fills or available depth.",
            "Assumed maintenance and daily-high shock do not reproduce the exchange liquidation engine.",
            "Account eligibility, contract lot sizes, actual fees, transfer timing and financing cost remain unverified.",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    pd.DataFrame(executions).to_parquet(ROOT / "outputs/quarterly_basis_final_2026_legs.parquet",
                                       index=False)
    pd.DataFrame(daily_rows).to_parquet(ROOT / "outputs/quarterly_basis_final_2026_daily.parquet",
                                       index=False)
    (ROOT / "outputs/quarterly_basis_final_2026_sources.json").write_text(
        json.dumps(sorted(manifest, key=lambda item: str(item["task"])), indent=2) + "\n",
        encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    print("saved", OUTPUT, flush=True)


if __name__ == "__main__":
    main()
