"""Inspect historical quarterly-future bid/ask quotes at simulated entry and exit."""

from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

from laya_trader.progress import ProgressReporter
from quarterly_basis_probe import FUTURES_MARGIN, SPOT_CASH
from spot_perp_carry_probe import ROOT


ARCHIVES = ROOT / "outputs/quarterly_bookticker_archives"
BASE_URL = "https://data.binance.vision/data/futures/um/daily/bookTicker"
EXAMPLE_ACCOUNT_USDT = 1000.0
ASSUMED_FUTURES_SLIPPAGE_PER_SIDE = 0.0002


def archive_path(contract: str, day: str) -> Path:
    return ARCHIVES / contract / f"{contract}-bookTicker-{day}.zip"


def fetch_one(contract: str, day: str) -> tuple[str, str, str]:
    path = archive_path(contract, day)
    if path.is_file():
        return contract, day, "cached"
    url = f"{BASE_URL}/{contract}/{path.name}"
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=90)
            if response.status_code == 404:
                return contract, day, "missing"
            response.raise_for_status()
            checksum = requests.get(url + ".CHECKSUM", timeout=20)
            checksum.raise_for_status()
            expected = checksum.text.split()[0].lower()
            actual = hashlib.sha256(response.content).hexdigest()
            if expected != actual:
                raise ValueError(f"SHA256 mismatch for {contract} {day}")
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                if not archive.namelist():
                    raise ValueError(f"empty archive for {contract} {day}")
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".zip.tmp")
            temporary.write_bytes(response.content)
            temporary.replace(path)
            return contract, day, "downloaded"
        except (requests.RequestException, zipfile.BadZipFile, ValueError, IndexError):
            if attempt == 2:
                return contract, day, "error"
            time.sleep(1 + 2 * attempt)
    raise AssertionError("unreachable")


def first_quotes(contract: str, day: str) -> dict:
    path = archive_path(contract, day)
    start_ms = int(pd.Timestamp(day, tz="UTC").timestamp() * 1000)
    end_ms = start_ms + 60_000
    rows = []
    with zipfile.ZipFile(path) as archive:
        with archive.open(archive.namelist()[0]) as stream:
            chunks = pd.read_csv(
                stream, usecols=["best_bid_price", "best_bid_qty", "best_ask_price",
                                 "best_ask_qty", "event_time"], chunksize=10_000,
            )
            for chunk in chunks:
                times = pd.to_numeric(chunk.event_time, errors="coerce")
                subset = chunk.loc[times.between(start_ms, end_ms, inclusive="left")].copy()
                if not subset.empty:
                    rows.append(subset)
                if times.max() >= end_ms:
                    break
    if not rows:
        raise ValueError(f"no quote in first minute: {contract} {day}")
    frame = pd.concat(rows, ignore_index=True)
    for name in ("best_bid_price", "best_bid_qty", "best_ask_price", "best_ask_qty"):
        frame[name] = pd.to_numeric(frame[name], errors="coerce")
    frame = frame.loc[(frame.best_bid_price > 0) & (frame.best_ask_price > frame.best_bid_price)
                      & (frame.best_bid_qty > 0) & (frame.best_ask_qty > 0)]
    if frame.empty:
        raise ValueError(f"no valid quote in first minute: {contract} {day}")
    mid = (frame.best_bid_price + frame.best_ask_price) / 2
    spread = (frame.best_ask_price - frame.best_bid_price) / mid * 10_000
    first = frame.iloc[0]
    return {
        "first_event_delay_ms": int(first.event_time - start_ms),
        "first_bid": float(first.best_bid_price),
        "first_ask": float(first.best_ask_price),
        "first_bid_qty": float(first.best_bid_qty),
        "first_ask_qty": float(first.best_ask_qty),
        "first_spread_bps": round(float(spread.iloc[0]), 4),
        "median_first_minute_spread_bps": round(float(spread.median()), 4),
        "p95_first_minute_spread_bps": round(float(spread.quantile(0.95)), 4),
        "first_minute_updates": len(frame),
    }


def main() -> None:
    legs_path = ROOT / "outputs/quarterly_basis_diagnostic_legs.parquet"
    if not legs_path.is_file():
        raise FileNotFoundError("run quarterly_basis_probe.py --diagnostic-all first")
    legs = pd.read_parquet(legs_path)
    tasks = sorted({(str(row.contract), pd.Timestamp(value).strftime("%Y-%m-%d"))
                    for row in legs.itertuples() for value in (row.entry, row.exit)})
    progress = ProgressReporter("quarterly bookTicker archives", len(tasks), unit="archives")
    missing = []
    errors = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(fetch_one, *task) for task in tasks]
        for count, future in enumerate(as_completed(futures), 1):
            contract, day, status = future.result()
            if status == "missing":
                missing.append((contract, day))
            elif status == "error":
                errors.append((contract, day))
            progress.update(count)
    if errors:
        raise RuntimeError(f"bookTicker download or checksum errors: {errors}")
    missing.sort()
    quotes = {}
    available = [task for task in tasks if task not in missing]
    progress = ProgressReporter("quarterly entry and exit quotes", len(available), unit="archives")
    for count, (contract, day) in enumerate(available, 1):
        quotes[(contract, day)] = first_quotes(contract, day)
        progress.update(count)
    rows = []
    for leg in legs.itertuples():
        entry_day = pd.Timestamp(leg.entry).strftime("%Y-%m-%d")
        exit_day = pd.Timestamp(leg.exit).strftime("%Y-%m-%d")
        entry = quotes.get((leg.contract, entry_day))
        exit_quote = quotes.get((leg.contract, exit_day))
        complete = entry is not None and exit_quote is not None
        size_at_1000 = EXAMPLE_ACCOUNT_USDT / (SPOT_CASH + FUTURES_MARGIN) * leg.quantity
        if complete:
            quote_adjustment = leg.quantity * (
                entry["first_bid"] - leg.future_entry
                - exit_quote["first_ask"] + leg.future_exit
                + ASSUMED_FUTURES_SLIPPAGE_PER_SIDE * (leg.future_entry + leg.future_exit)
            )
            stress_cash_at_quote = leg.stress_net_cash + quote_adjustment
            top_book_covers = (entry["first_bid_qty"] >= size_at_1000
                               and exit_quote["first_ask_qty"] >= size_at_1000)
        else:
            quote_adjustment = None
            stress_cash_at_quote = None
            top_book_covers = None
        rows.append({
            "quarter": leg.quarter, "symbol": leg.symbol, "contract": leg.contract,
            "entry_quote_available": entry is not None,
            "exit_quote_available": exit_quote is not None,
            "entry_delay_ms": entry["first_event_delay_ms"] if entry else None,
            "exit_delay_ms": exit_quote["first_event_delay_ms"] if exit_quote else None,
            "entry_spread_bps": entry["first_spread_bps"] if entry else None,
            "exit_spread_bps": exit_quote["first_spread_bps"] if exit_quote else None,
            "entry_bid_qty": entry["first_bid_qty"] if entry else None,
            "exit_ask_qty": exit_quote["first_ask_qty"] if exit_quote else None,
            "hypothetical_quantity_at_1000_usdt": size_at_1000,
            "top_book_covers_1000_usdt": top_book_covers,
            "original_stress_cash": leg.stress_net_cash,
            "quote_adjusted_stress_cash": stress_cash_at_quote,
            "quote_adjustment_cash": quote_adjustment,
        })
    frame = pd.DataFrame(rows)
    complete = frame.loc[frame.quote_adjusted_stress_cash.notna()].copy()
    complete["top_book_account_capacity_usdt"] = (
        complete[["entry_bid_qty", "exit_ask_qty"]].min(axis=1)
        / complete.hypothetical_quantity_at_1000_usdt * EXAMPLE_ACCOUNT_USDT
    )
    annual = frame.groupby(frame.quarter.str[:4]).agg(
        legs=("symbol", "size"),
        covered_legs=("quote_adjusted_stress_cash", "count"),
        covered_1000_usdt=("top_book_covers_1000_usdt", "sum"),
        original_stress_cash=("original_stress_cash", "sum"),
        quote_adjusted_stress_cash=("quote_adjusted_stress_cash", "sum"),
    )
    capital = SPOT_CASH + FUTURES_MARGIN
    annual["original_on_capital"] = annual.original_stress_cash / capital
    annual["quote_adjusted_on_capital"] = (
        annual.quote_adjusted_stress_cash / capital
    ).where(annual.covered_legs.eq(annual.legs))
    annual["quote_adjusted_stress_cash"] = annual.quote_adjusted_stress_cash.where(
        annual.covered_legs.eq(annual.legs))
    spreads = pd.concat([frame.entry_spread_bps, frame.exit_spread_bps]).dropna()
    delays = pd.concat([frame.entry_delay_ms, frame.exit_delay_ms]).dropna()
    report = {
        "source": "Binance USD-M daily bookTicker ZIPs, SHA256 checked against archive CHECKSUM",
        "method": "first valid quote in first UTC minute; future bid on short entry, ask on cover; replace 2bps assumed futures slippage",
        "example_account_usdt": EXAMPLE_ACCOUNT_USDT,
        "daily_archives": len(tasks),
        "available_archives": len(available),
        "missing_archives": [f"{contract}:{day}" for contract, day in missing],
        "legs": len(frame),
        "legs_with_both_quotes": int(frame.quote_adjusted_stress_cash.count()),
        "minimum_top_book_account_capacity_usdt_on_covered_legs": round(
            float(complete.top_book_account_capacity_usdt.min()), 2,
        ) if len(complete) else None,
        "covered_leg_original_stress_cash": round(
            float(complete.original_stress_cash.sum()), 6,
        ) if len(complete) else None,
        "covered_leg_quote_adjusted_stress_cash": round(
            float(complete.quote_adjusted_stress_cash.sum()), 6,
        ) if len(complete) else None,
        "max_first_event_delay_ms": int(delays.max()) if len(delays) else None,
        "median_first_spread_bps": round(float(spreads.median()), 4) if len(spreads) else None,
        "p95_first_spread_bps": round(float(spreads.quantile(0.95)), 4) if len(spreads) else None,
        "top_book_coverage_1000_usdt_legs": int(frame.top_book_covers_1000_usdt.eq(True).sum()),
        "annual": annual.round(6).reset_index().astype(object).where(
            pd.notna(annual.round(6).reset_index()), None,
        ).to_dict(orient="records"),
    }
    frame.to_parquet(ROOT / "outputs/quarterly_basis_execution_legs.parquet", index=False)
    output = ROOT / "outputs/quarterly_basis_execution_report.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    print("saved", output, flush=True)


if __name__ == "__main__":
    main()
