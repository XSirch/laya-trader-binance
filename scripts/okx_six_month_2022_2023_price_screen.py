"""Independent OKX trade-price screen for the frozen six-month basis dates."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from laya_trader.progress import ProgressReporter
from six_month_basis_replay import (
    FUTURE_SIDE_COST, INITIAL_CAPITAL, ROOT, SPOT_ALLOCATION,
    SPOT_SIDE_COST,
)


PERIODS = (
    ("2022H1", "2022-01-01", "2022-06-24"),
    ("2022H2", "2022-07-01", "2022-12-30"),
    ("2023H1", "2023-01-01", "2023-06-30"),
    ("2023H2", "2023-07-01", "2023-12-29"),
)
SYMBOLS = ("BTC", "ETH")
ARCHIVES = ROOT / "outputs/okx_six_month_trade_archives"
REPORT = ROOT / "outputs/okx_six_month_2022_2023_price_screen.json"


def archive_name(market: str, symbol: str, day: str) -> str:
    family = f"{symbol}-USDT"
    stem = family if market == "spot" else f"{family}-futureschain"
    return f"{stem}-trades-{day}.zip"


def archive_url(market: str, symbol: str, day: str) -> str:
    key = day.replace("-", "")
    return (f"https://static.okx.com/cdn/okex/traderecords/trades/daily/{key}/"
            f"{archive_name(market, symbol, day)}?v=999")


def archive_path(market: str, symbol: str, day: str) -> Path:
    return ARCHIVES / market / symbol / archive_name(market, symbol, day)


def fetch(task: tuple[str, str, str]) -> dict:
    market, symbol, day = task
    url = archive_url(*task)
    path = archive_path(*task)
    try:
        if path.is_file():
            payload = path.read_bytes()
        else:
            response = requests.get(url, timeout=60)
            if response.status_code == 404:
                return {"task": task, "url": url, "status": "missing"}
            response.raise_for_status()
            payload = response.content
        digest = hashlib.sha256(payload).hexdigest()
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            bad = archive.testzip()
            if bad is not None:
                raise ValueError(f"ZIP CRC failed at {bad}")
            if len(archive.namelist()) != 1:
                raise ValueError("expected one CSV in ZIP")
            csv_name = archive.namelist()[0]
            if csv_name != archive_name(market, symbol, day).removesuffix(".zip") + ".csv":
                raise ValueError(f"unexpected CSV name: {csv_name}")
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".zip.tmp")
            temporary.write_bytes(payload)
            temporary.replace(path)
        return {"task": task, "url": url, "status": "verified_local_sha256_and_zip_crc",
                "sha256": digest, "bytes": len(payload)}
    except (requests.RequestException, zipfile.BadZipFile, ValueError, OSError) as error:
        return {"task": task, "url": url, "status": "error", "reason": str(error)}


def required_tasks() -> list[tuple[str, str, str]]:
    tasks = set()
    for _, entry_day, expiry_day in PERIODS:
        exit_day = (pd.Timestamp(expiry_day) - timedelta(days=2)).strftime("%Y-%m-%d")
        for day in (entry_day, exit_day):
            for symbol in SYMBOLS:
                for market in ("spot", "future"):
                    tasks.add((market, symbol, day))
    return sorted(tasks)


def trade_window(market: str, symbol: str, day: str, expiry_day: str) -> dict:
    path = archive_path(market, symbol, day)
    with zipfile.ZipFile(path) as archive:
        with archive.open(archive.namelist()[0]) as stream:
            frame = pd.read_csv(stream)
    expected_columns = ["instrument_name", "trade_id", "side", "price", "size", "created_time"]
    if frame.columns.tolist() != expected_columns:
        raise ValueError(f"unexpected CSV schema: {market} {symbol} {day}")
    start = int(pd.Timestamp(day, tz="UTC").timestamp() * 1000)
    end = start + 5 * 60 * 1000
    instrument = f"{symbol}-USDT"
    if market == "future":
        instrument += "-" + pd.Timestamp(expiry_day).strftime("%y%m%d")
    rows = frame.loc[
        frame.instrument_name.eq(instrument)
        & frame.created_time.ge(start) & frame.created_time.lt(end)
    ].copy()
    if rows.empty:
        raise ValueError(f"empty target-instrument UTC window: {market} {symbol} {day}")
    numeric = rows[["price", "size", "created_time"]].to_numpy(dtype=float)
    if not np.isfinite(numeric).all() or (rows.price.le(0) | rows["size"].le(0)).any():
        raise ValueError(f"invalid trade price or size: {market} {symbol} {day}")
    rows["side"] = rows.side.astype(str).str.lower()
    if not rows.side.isin(["buy", "sell"]).all():
        raise ValueError(f"unexpected taker side: {market} {symbol} {day}")
    return {
        "market": market, "symbol": symbol, "instrument": instrument,
        "day": day, "first_timestamp_ms": int(rows.created_time.min()),
        "last_timestamp_ms": int(rows.created_time.max()),
        "trade_count": len(rows), "minimum_trade_price": float(rows.price.min()),
        "maximum_trade_price": float(rows.price.max()),
        "buy_taker_size": float(rows.loc[rows.side.eq("buy"), "size"].sum()),
        "sell_taker_size": float(rows.loc[rows.side.eq("sell"), "size"].sum()),
        "size_unit": "base asset" if market == "spot" else "contracts",
    }


def main() -> None:
    tasks = required_tasks()
    manifest = []
    progress = ProgressReporter("OKX independent price archives", len(tasks), unit="archives")
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fetch, task) for task in tasks]
        for count, future in enumerate(as_completed(futures), 1):
            manifest.append(future.result())
            progress.update(count)
    manifest = sorted(manifest, key=lambda row: str(row["task"]))
    manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    report = {
        "protocol": "docs/okx_six_month_2022_2023_price_screen_protocol.md, frozen at commit 3b79c01",
        "source": "OKX first-party daily trade ZIPs; local SHA256 and ZIP CRC checked; no published checksum",
        "archive_count": len(manifest),
        "source_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "limitations": "Continuous normalized quantity; no contract rounding, executable bid/ask depth, wallet/margin path, account fees or financing; different venue from Binance",
    }
    failures = [row for row in manifest
                if row["status"] != "verified_local_sha256_and_zip_crc"]
    if failures:
        report["status"] = "archive set incomplete"
        report["failures"] = failures
    else:
        windows = {}
        availability = []
        for _, entry_day, expiry_day in PERIODS:
            exit_day = (pd.Timestamp(expiry_day) - timedelta(days=2)).strftime("%Y-%m-%d")
            for day in (entry_day, exit_day):
                for symbol in SYMBOLS:
                    for market in ("spot", "future"):
                        key = (market, symbol, day)
                        try:
                            windows[key] = trade_window(market, symbol, day, expiry_day)
                            print(market, symbol, day, "trades",
                                  windows[key]["trade_count"], flush=True)
                        except ValueError as error:
                            availability.append({"task": key, "reason": str(error)})
        if availability:
            report["status"] = "required UTC trade window unavailable"
            report["failures"] = availability
        else:
            legs = []
            periods = []
            for name, entry_day, expiry_day in PERIODS:
                exit_day = (pd.Timestamp(expiry_day) - timedelta(days=2)).strftime("%Y-%m-%d")
                period_legs = []
                for symbol in SYMBOLS:
                    spot_entry = windows[("spot", symbol, entry_day)]
                    future_entry = windows[("future", symbol, entry_day)]
                    spot_exit = windows[("spot", symbol, exit_day)]
                    future_exit = windows[("future", symbol, exit_day)]
                    s0 = spot_entry["maximum_trade_price"]
                    f0 = future_entry["minimum_trade_price"]
                    s1 = spot_exit["minimum_trade_price"]
                    f1 = future_exit["maximum_trade_price"]
                    q = SPOT_ALLOCATION / s0
                    profit = q * (s1 - s0 + f0 - f1
                                  - SPOT_SIDE_COST * (s0 + s1)
                                  - FUTURE_SIDE_COST * (f0 + f1))
                    leg = {
                        "period": name, "symbol": symbol, "entry_day": entry_day,
                        "exit_day": exit_day, "spot_entry_high": s0,
                        "future_entry_low": f0, "spot_exit_low": s1,
                        "future_exit_high": f1, "quantity_continuous": q,
                        "adverse_entry_premium_bps": (f0 / s0 - 1) * 10000,
                        "cash_profit_normalized": profit,
                        "return_on_initial_capital": profit / INITIAL_CAPITAL,
                    }
                    period_legs.append(leg)
                    legs.append(leg)
                holding_days = (pd.Timestamp(exit_day) - pd.Timestamp(entry_day)).days
                profit = sum(leg["cash_profit_normalized"] for leg in period_legs)
                periods.append({
                    "period": name, "entry_day": entry_day, "exit_day": exit_day,
                    "holding_days": holding_days,
                    "cash_profit_normalized": profit,
                    "return_on_initial_capital": profit / INITIAL_CAPITAL,
                    "simple_annualized_break_even_capital_charge": (
                        profit / INITIAL_CAPITAL * 365 / holding_days),
                })
                print(name, "price-screen account return",
                      round(profit / INITIAL_CAPITAL, 6), flush=True)
            total = sum(row["cash_profit_normalized"] for row in periods)
            report["status"] = "complete price-only screen"
            report["result"] = {
                "legs": legs, "periods": periods,
                "total_cash_profit_normalized": total,
                "total_return_on_initial_capital": total / INITIAL_CAPITAL,
                "all_four_half_years_positive": all(
                    row["cash_profit_normalized"] > 0 for row in periods),
            }
            pd.DataFrame(list(windows.values())).to_parquet(
                ROOT / "outputs/okx_six_month_2022_2023_trade_windows.parquet",
                index=False)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (ROOT / "outputs/okx_six_month_2022_2023_sources.json").write_bytes(
        manifest_bytes)
    print(json.dumps({key: value for key, value in report.items()
                      if key != "result"}, indent=2), flush=True)
    if report.get("result"):
        print(json.dumps({key: value for key, value in report["result"].items()
                          if key != "legs"}, indent=2), flush=True)
    print("saved", REPORT, flush=True)


if __name__ == "__main__":
    main()
