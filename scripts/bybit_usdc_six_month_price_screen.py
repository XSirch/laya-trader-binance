"""Fixed Bybit USDC spot and delivery-future historical price screen."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path

import pandas as pd
import requests
import numpy as np

from laya_trader.progress import ProgressReporter
from six_month_basis_replay import (
    FUTURE_SIDE_COST, INITIAL_CAPITAL, ROOT, SPOT_ALLOCATION,
    SPOT_SIDE_COST,
)


PERIODS = (
    ("2023H2", "2023-07-01", "2023-12-29"),
    ("2024H1", "2024-01-01", "2024-06-28"),
    ("2024H2", "2024-07-01", "2024-12-27"),
    ("2025H1", "2025-01-01", "2025-06-27"),
    ("2025H2", "2025-07-01", "2025-12-26"),
)
SYMBOLS = ("BTC", "ETH")
CAPITAL_CHARGE_ANNUAL = 0.01
ARCHIVES = ROOT / "outputs/bybit_usdc_six_month_archives"
REPORT = ROOT / "outputs/bybit_usdc_six_month_price_screen.json"


def instrument(market: str, symbol: str, expiry: str) -> str:
    if market == "spot":
        return f"{symbol}USDC"
    suffix = pd.Timestamp(expiry).strftime("%d%b%y").upper()
    return f"{symbol}-{suffix}"


def archive_name(task: tuple[str, str, str, str]) -> str:
    market, symbol, day, expiry = task
    name = instrument(market, symbol, expiry)
    return (f"{name}-{day[:7]}.csv.gz" if market == "spot"
            else f"{name}{day}.csv.gz")


def archive_url(task: tuple[str, str, str, str]) -> str:
    market, symbol, _, expiry = task
    name = instrument(market, symbol, expiry)
    root = "spot" if market == "spot" else "trading"
    return f"https://public.bybit.com/{root}/{name}/{archive_name(task)}"


def archive_path(task: tuple[str, str, str, str]) -> Path:
    market, symbol, _, expiry = task
    return ARCHIVES / market / instrument(market, symbol, expiry) / archive_name(task)


def required_tasks() -> list[tuple[str, str, str, str]]:
    tasks = set()
    for _, entry, expiry in PERIODS:
        exit_day = (pd.Timestamp(expiry) - timedelta(days=2)).strftime("%Y-%m-%d")
        for day in (entry, exit_day):
            for symbol in SYMBOLS:
                for market in ("spot", "future"):
                    tasks.add((market, symbol, day, expiry))
    return sorted(tasks)


def fetch(task: tuple[str, str, str, str]) -> dict:
    url = archive_url(task)
    path = archive_path(task)
    for attempt in range(3):
        try:
            if not path.is_file():
                with requests.get(url, stream=True, timeout=(20, 180)) as response:
                    if response.status_code == 404:
                        return {"task": task, "url": url, "status": "missing"}
                    response.raise_for_status()
                    path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = path.with_suffix(".gz.tmp")
                    with temporary.open("wb") as output:
                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                output.write(chunk)
                    temporary.replace(path)
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                    size += len(chunk)
            return {"task": task, "url": url, "status": "downloaded_or_cached",
                    "sha256": digest.hexdigest(), "bytes": size}
        except (requests.RequestException, OSError) as error:
            if attempt == 2:
                return {"task": task, "url": url, "status": "error",
                        "reason": str(error)}
            time.sleep(2 * (attempt + 1))
    raise AssertionError("unreachable")


def trade_window(task: tuple[str, str, str, str]) -> dict:
    market, symbol, day, expiry = task
    expected_symbol = instrument(market, symbol, expiry)
    start = pd.Timestamp(day, tz="UTC").timestamp()
    end = start + 5 * 60
    count = 0
    lowest = float("inf")
    highest = float("-inf")
    try:
        if market == "spot":
            with gzip.open(archive_path(task), "rt", encoding="utf-8") as stream:
                reader = pd.read_csv(stream, usecols=["timestamp", "price", "volume"],
                                     index_col=False, chunksize=500_000)
                for chunk in reader:
                    selected = chunk.loc[
                        chunk.timestamp.ge(int(start * 1000))
                        & chunk.timestamp.lt(int(end * 1000))]
                    if selected.empty:
                        continue
                    numeric = selected[["price", "volume"]].to_numpy(dtype=float)
                    if not np.isfinite(numeric).all() or (numeric <= 0).any():
                        raise ValueError(f"invalid spot price or volume: {task}")
                    count += len(selected)
                    lowest = min(lowest, float(selected.price.min()))
                    highest = max(highest, float(selected.price.max()))
        else:
            with gzip.open(archive_path(task), "rt", encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream)
                if not {"timestamp", "symbol", "price", "size"}.issubset(reader.fieldnames or []):
                    raise ValueError(f"unexpected trade CSV header: {task}")
                for row in reader:
                    stamp = float(row["timestamp"])
                    if not math.isfinite(stamp):
                        raise ValueError(f"nonfinite timestamp: {task}")
                    if start <= stamp < end:
                        if row["symbol"] != expected_symbol:
                            raise ValueError(f"wrong symbol in target window: {task}")
                        price = float(row["price"])
                        size = float(row["size"])
                        if (not math.isfinite(price) or not math.isfinite(size)
                                or price <= 0 or size <= 0):
                            raise ValueError(f"invalid price or size: {task}")
                        count += 1
                        lowest = min(lowest, price)
                        highest = max(highest, price)
    except (OSError, EOFError, UnicodeError, csv.Error) as error:
        raise ValueError(f"gzip or CSV integrity failure: {task}: {error}") from error
    if count == 0:
        raise ValueError(f"no trades in fixed UTC window: {task}")
    return {"task": task, "instrument": expected_symbol,
            "trades_in_five_minutes": count,
            "minimum_trade_price": lowest, "maximum_trade_price": highest}


def main() -> None:
    tasks = required_tasks()
    manifest = []
    progress = ProgressReporter("Bybit USDC basis archives", len(tasks), unit="archives")
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fetch, task) for task in tasks]
        for count, future in enumerate(as_completed(futures), 1):
            manifest.append(future.result())
            progress.update(count)
    manifest = sorted(manifest, key=lambda row: str(row["task"]))
    manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    report = {
        "protocol": "docs/bybit_usdc_six_month_price_protocol.md, frozen at commit f330a36",
        "source": "Bybit first-party monthly USDC spot and daily USDC future trade gzip files; local compressed SHA256 and full gzip read",
        "archive_count": len(manifest),
        "source_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "capital_charge_annual": CAPITAL_CHARGE_ANNUAL,
        "limits": "Different settlement asset and venue; continuous quantity, no contract rounding, bid/ask fill, wallet/margin path, actual account fees, borrowing rate or tax proof",
    }
    failures = [row for row in manifest if row["status"] != "downloaded_or_cached"]
    if failures:
        report["status"] = "archive set incomplete"
        report["failures"] = failures
    else:
        windows = {}
        failures = []
        for task in tasks:
            try:
                windows[task] = trade_window(task)
                print(task, "trades", windows[task]["trades_in_five_minutes"], flush=True)
            except ValueError as error:
                failures.append({"task": task, "reason": str(error)})
        if failures:
            report["status"] = "required UTC trade window unavailable"
            report["failures"] = failures
        else:
            legs = []
            periods = []
            for name, entry, expiry in PERIODS:
                exit_day = (pd.Timestamp(expiry) - timedelta(days=2)).strftime("%Y-%m-%d")
                period_legs = []
                for symbol in SYMBOLS:
                    spot_entry = windows[("spot", symbol, entry, expiry)]
                    future_entry = windows[("future", symbol, entry, expiry)]
                    spot_exit = windows[("spot", symbol, exit_day, expiry)]
                    future_exit = windows[("future", symbol, exit_day, expiry)]
                    s0 = spot_entry["maximum_trade_price"]
                    f0 = future_entry["minimum_trade_price"]
                    s1 = spot_exit["minimum_trade_price"]
                    f1 = future_exit["maximum_trade_price"]
                    quantity = SPOT_ALLOCATION / s0
                    profit = quantity * (s1 - s0 + f0 - f1
                                         - SPOT_SIDE_COST * (s0 + s1)
                                         - FUTURE_SIDE_COST * (f0 + f1))
                    leg = {
                        "period": name, "symbol": symbol, "entry_day": entry,
                        "exit_day": exit_day, "spot_entry_high": s0,
                        "future_entry_low": f0, "spot_exit_low": s1,
                        "future_exit_high": f1, "quantity_continuous": quantity,
                        "adverse_entry_premium_bps": (f0 / s0 - 1) * 10000,
                        "cash_profit_normalized": profit,
                        "return_on_initial_capital": profit / INITIAL_CAPITAL,
                    }
                    legs.append(leg)
                    period_legs.append(leg)
                days = (pd.Timestamp(exit_day) - pd.Timestamp(entry)).days
                gross = sum(leg["cash_profit_normalized"] for leg in period_legs)
                before_charge = gross / INITIAL_CAPITAL
                capital_charge = CAPITAL_CHARGE_ANNUAL * days / 365
                periods.append({
                    "period": name, "entry_day": entry, "exit_day": exit_day,
                    "holding_days": days,
                    "return_after_execution_costs": before_charge,
                    "illustrative_capital_charge": capital_charge,
                    "return_after_execution_and_capital_charge": (
                        before_charge - capital_charge),
                })
                print(name, "after execution", round(before_charge, 6),
                      "after capital charge", round(before_charge - capital_charge, 6),
                      flush=True)
            report["status"] = "complete price-only screen"
            report["result"] = {
                "legs": legs, "periods": periods,
                "total_return_after_execution_costs": sum(
                    row["return_after_execution_costs"] for row in periods),
                "total_return_after_execution_and_capital_charge": sum(
                    row["return_after_execution_and_capital_charge"]
                    for row in periods),
                "all_five_positive_after_capital_charge": all(
                    row["return_after_execution_and_capital_charge"] > 0
                    for row in periods),
            }
            pd.DataFrame(list(windows.values())).to_parquet(
                ROOT / "outputs/bybit_usdc_six_month_trade_windows.parquet",
                index=False)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (ROOT / "outputs/bybit_usdc_six_month_sources.json").write_bytes(manifest_bytes)
    print(json.dumps({key: value for key, value in report.items()
                      if key != "result"}, indent=2), flush=True)
    if report.get("result"):
        print(json.dumps({key: value for key, value in report["result"].items()
                          if key != "legs"}, indent=2), flush=True)
    print("saved", REPORT, flush=True)


if __name__ == "__main__":
    main()
