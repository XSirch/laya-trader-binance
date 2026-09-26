"""Audit public book-depth archive coverage before using it as a model feature."""

from __future__ import annotations

import argparse
import io
import json
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path

import pandas as pd
import requests

from laya_trader.config import load_config
from laya_trader.dataset.build import load_symbol_klines
from laya_trader.progress import ProgressReporter


ROOT = Path(__file__).resolve().parents[1]
ARCHIVES = ROOT / "outputs/book_depth_qc_archives"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
FIRST_DAY = "2025-01-01"
LAST_DAY = "2025-06-30"
MIN_SNAPSHOTS = 2000
MIN_15M_BARS = 94
MAX_BAD_SHARE = 0.01
BAD_PRICE_DEVIATION = 0.10


def archive_path(symbol: str, day: str) -> Path:
    return ARCHIVES / symbol / f"{symbol}-bookDepth-{day}.zip"


def download_one(symbol: str, day: str) -> tuple[str, str, str]:
    path = archive_path(symbol, day)
    if path.is_file():
        return symbol, day, "cached"
    url = (
        "https://data.binance.vision/data/futures/um/daily/bookDepth/"
        f"{symbol}/{symbol}-bookDepth-{day}.zip"
    )
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 404:
                return symbol, day, "missing"
            response.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                if archive.testzip() is not None:
                    raise ValueError("ZIP CRC failed")
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".zip.tmp")
            temporary.write_bytes(response.content)
            temporary.replace(path)
            return symbol, day, "downloaded"
        except (requests.RequestException, zipfile.BadZipFile, ValueError):
            if attempt == 2:
                return symbol, day, "error"
            time.sleep(1 + 2 * attempt)
    raise AssertionError("unreachable")


def price_opens(symbol: str, first_day: str, last_day: str) -> pd.DataFrame:
    cfg = load_config(ROOT / "configs/dataset.toml")
    frame = load_symbol_klines(cfg, symbol)
    start = pd.Timestamp(first_day, tz="UTC")
    end = pd.Timestamp(last_day, tz="UTC") + timedelta(days=1)
    prices = frame.loc[
        (frame.open_time >= start) & (frame.open_time < end),
        ["open_time", "open"],
    ].rename(columns={"open_time": "timestamp"})
    return prices.sort_values("timestamp")


def audit_one(symbol: str, day: str, prices: pd.DataFrame) -> dict:
    with zipfile.ZipFile(archive_path(symbol, day)) as archive:
        with archive.open(archive.namelist()[0]) as stream:
            frame = pd.read_csv(stream, usecols=["timestamp", "percentage", "depth", "notional"])
    snapshots = int(frame.timestamp.nunique())
    frame = frame.loc[frame.percentage.isin((-5, 5))].copy()
    frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
    frame["depth"] = pd.to_numeric(frame.depth, errors="coerce")
    frame["notional"] = pd.to_numeric(frame.notional, errors="coerce")
    frame = frame.loc[frame.depth.gt(0) & frame.notional.gt(0)]
    frame["level_price"] = frame.notional / frame.depth
    duplicates = int(frame.duplicated(["timestamp", "percentage"]).sum())
    frame = frame.drop_duplicates(["timestamp", "percentage"], keep="last")
    bands = frame.pivot(index="timestamp", columns="percentage", values="level_price")
    bands = bands.dropna(subset=[-5, 5]).sort_index()
    covered_15m_bars = int(bands.index.floor("15min").nunique())
    bands["depth_mid"] = (bands[-5] + bands[5]) / 2
    joined = pd.merge_asof(
        bands[["depth_mid"]].reset_index(), prices,
        on="timestamp", direction="backward", tolerance=timedelta(minutes=15),
    ).dropna()
    deviation = (joined.depth_mid / joined.open - 1).abs()
    start = pd.Timestamp(day, tz="UTC")
    first_seconds = (bands.index.min() - start).total_seconds() if len(bands) else None
    last_seconds = (bands.index.max() - start).total_seconds() if len(bands) else None
    bad_share = float(deviation.gt(BAD_PRICE_DEVIATION).mean()) if len(deviation) else None
    aligned_share = len(joined) / len(bands) if len(bands) else 0.0
    usable = (
        snapshots >= MIN_SNAPSHOTS
        and covered_15m_bars >= MIN_15M_BARS
        and aligned_share >= 0.95
        and bad_share is not None and bad_share <= MAX_BAD_SHARE
        and duplicates == 0
    )
    return {
        "symbol": symbol, "day": day, "status": "usable" if usable else "rejected",
        "snapshots": snapshots, "paired_bands": len(bands), "covered_15m_bars": covered_15m_bars,
        "aligned": len(joined),
        "duplicates": duplicates, "first_seconds": first_seconds,
        "last_seconds": last_seconds, "aligned_share": round(aligned_share, 6),
        "bad_price_share": round(bad_share, 6) if bad_share is not None else None,
        "median_abs_price_deviation": round(float(deviation.median()), 6) if len(deviation) else None,
        "p95_abs_price_deviation": round(float(deviation.quantile(0.95)), 6)
        if len(deviation) else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default=FIRST_DAY)
    parser.add_argument("--end", default=LAST_DAY)
    args = parser.parse_args()
    days = pd.date_range(args.start, args.end, freq="D").strftime("%Y-%m-%d")
    tasks = [(symbol, day) for symbol in SYMBOLS for day in days]
    statuses = {}
    progress = ProgressReporter("book depth download", len(tasks), unit="archives")
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(download_one, *task) for task in tasks]
        for count, future in enumerate(as_completed(futures), 1):
            symbol, day, status = future.result()
            statuses[(symbol, day)] = status
            progress.update(count)
    prices = {symbol: price_opens(symbol, args.start, args.end) for symbol in SYMBOLS}
    rows = []
    progress = ProgressReporter("book depth audit", len(tasks), unit="archives")
    for count, (symbol, day) in enumerate(tasks, 1):
        status = statuses[(symbol, day)]
        if status in ("cached", "downloaded"):
            try:
                rows.append(audit_one(symbol, day, prices[symbol]))
            except (ValueError, KeyError, zipfile.BadZipFile):
                rows.append({"symbol": symbol, "day": day, "status": "parse_error"})
        else:
            rows.append({"symbol": symbol, "day": day, "status": status})
        progress.update(count)
    frame = pd.DataFrame(rows)
    period_tag = f"{args.start}_{args.end}".replace("-", "")
    output = ROOT / f"outputs/book_depth_qc_{period_tag}.csv"
    frame.to_csv(output, index=False)
    summary = {
        "period": [args.start, args.end],
        "symbols": list(SYMBOLS),
        "thresholds": {
            "min_snapshots": MIN_SNAPSHOTS,
            "min_15m_bars": MIN_15M_BARS,
            "max_bad_share": MAX_BAD_SHARE,
            "bad_price_deviation": BAD_PRICE_DEVIATION,
        },
        "status_counts": frame.status.value_counts().to_dict(),
        "by_symbol": {
            symbol: frame.loc[frame.symbol == symbol].status.value_counts().to_dict()
            for symbol in SYMBOLS
        },
        "by_month": frame.groupby([frame.day.str.slice(0, 7), "symbol", "status"])
        .size().rename("days").reset_index().to_dict(orient="records"),
        "rejected_days": frame.loc[frame.status != "usable", ["symbol", "day", "status"]]
        .to_dict(orient="records"),
    }
    report = ROOT / f"outputs/book_depth_qc_{period_tag}.json"
    report.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items()
                      if key != "rejected_days"}, indent=2), flush=True)
    print("saved", output, report, flush=True)


if __name__ == "__main__":
    main()
