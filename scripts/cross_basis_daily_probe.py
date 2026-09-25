"""Research-only daily cross-sectional premium portfolio with realized funding."""

from __future__ import annotations

import io
import json
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from laya_trader.config import load_config
from laya_trader.data.binance_public import month_keys
from laya_trader.dataset.build import load_symbol_klines
from laya_trader.features.core import _aggregate_ohlcv
from laya_trader.progress import ProgressReporter


ROOT = Path(__file__).resolve().parents[1]
ARCHIVES = ROOT / "outputs/cross_basis_archives"
PREMIUM_CACHE = ROOT / "outputs/cross_basis_premium.parquet"
FUNDING_CACHE = ROOT / "outputs/cross_basis_funding.parquet"
SYMBOLS = load_config(ROOT / "configs/dataset.toml").data.symbols
RANK_SIZE = 5
ROUND_TRIP_COST = 0.0014
MAX_PREMIUM_AGE = timedelta(hours=3)


def archive_path(kind: str, symbol: str, month: str) -> Path:
    return ARCHIVES / kind / symbol / f"{symbol}-{month}.zip"


def archive_url(kind: str, symbol: str, month: str) -> str:
    base = "https://data.binance.vision/data/futures/um/monthly"
    if kind == "premium":
        return f"{base}/premiumIndexKlines/{symbol}/1h/{symbol}-1h-{month}.zip"
    return f"{base}/fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip"


def download_one(kind: str, symbol: str, month: str) -> tuple[str, str, str, bool]:
    path = archive_path(kind, symbol, month)
    if path.is_file():
        return kind, symbol, month, True
    url = archive_url(kind, symbol, month)
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 404:
                return kind, symbol, month, False
            response.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                if archive.testzip() is not None:
                    raise ValueError(f"bad ZIP member: {url}")
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".zip.tmp")
            temporary.write_bytes(response.content)
            temporary.replace(path)
            return kind, symbol, month, True
        except (requests.RequestException, zipfile.BadZipFile, ValueError):
            if attempt == 2:
                raise
            time.sleep(1 + 2 * attempt)
    raise AssertionError("unreachable")


def read_archive(kind: str, symbol: str, month: str) -> pd.DataFrame:
    path = archive_path(kind, symbol, month)
    with zipfile.ZipFile(path) as archive:
        with archive.open(archive.namelist()[0]) as stream:
            columns = ["close_time", "close"] if kind == "premium" else [
                "calc_time", "last_funding_rate"
            ]
            frame = pd.read_csv(stream, usecols=columns)
    frame["symbol"] = symbol
    return frame


def market_history() -> tuple[pd.DataFrame, pd.DataFrame]:
    if PREMIUM_CACHE.is_file() and FUNDING_CACHE.is_file():
        return pd.read_parquet(PREMIUM_CACHE), pd.read_parquet(FUNDING_CACHE)
    months = month_keys("2023-01", "2025-12")
    tasks = [(kind, symbol, month) for kind in ("premium", "funding")
             for symbol in SYMBOLS for month in months]
    found = []
    missing = []
    progress = ProgressReporter("basis archives", len(tasks), unit="archives")
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(download_one, *task) for task in tasks]
        for count, future in enumerate(as_completed(futures), 1):
            kind, symbol, month, present = future.result()
            (found if present else missing).append((kind, symbol, month))
            progress.update(count)
    print("archive coverage", len(found), "found", len(missing), "missing", flush=True)
    frames = {"premium": [], "funding": []}
    for kind, symbol, month in found:
        frames[kind].append(read_archive(kind, symbol, month))
    premium = pd.concat(frames["premium"], ignore_index=True)
    premium["close_time"] = pd.to_datetime(premium.close_time, unit="ms", utc=True)
    premium["close"] = pd.to_numeric(premium.close, errors="coerce")
    premium = premium.drop_duplicates(["symbol", "close_time"]).sort_values(["symbol", "close_time"])
    premium["premium_8h_mean"] = premium.groupby("symbol").close.transform(
        lambda values: values.rolling(8, min_periods=8).mean()
    )
    funding = pd.concat(frames["funding"], ignore_index=True)
    funding["calc_time"] = pd.to_datetime(funding.calc_time, unit="ms", utc=True)
    funding["last_funding_rate"] = pd.to_numeric(funding.last_funding_rate, errors="coerce")
    funding = funding.drop_duplicates(["symbol", "calc_time"]).sort_values(["symbol", "calc_time"])
    premium.to_parquet(PREMIUM_CACHE, index=False)
    funding.to_parquet(FUNDING_CACHE, index=False)
    print("history rows", len(premium), len(funding), flush=True)
    return premium, funding


def load_daily_prices() -> dict[str, pd.DataFrame]:
    cfg = load_config(ROOT / "configs/dataset.toml")
    prices = {}
    for symbol in SYMBOLS:
        start = time.monotonic()
        raw = load_symbol_klines(cfg, symbol)
        raw = raw.loc[
            (raw.timestamp >= pd.Timestamp("2023-01-01", tz="UTC"))
            & (raw.timestamp < pd.Timestamp("2026-01-01", tz="UTC"))
        ].copy()
        complete = raw.groupby(raw.timestamp.dt.floor("1d"), sort=True).size().eq(96)
        daily = _aggregate_ohlcv(raw, "1d")
        daily = daily.loc[daily.timestamp.dt.floor("1d").map(complete)].copy()
        daily = daily.sort_values("timestamp").reset_index(drop=True)
        daily["bar_start"] = daily.timestamp.dt.floor("1d")
        daily["segment"] = daily.bar_start.diff().dt.total_seconds().ne(86400).cumsum()
        prices[symbol] = daily.set_index("bar_start")
        print("price", symbol, len(daily), "seconds", round(time.monotonic() - start, 1), flush=True)
    return prices


def signal_at(history: pd.DataFrame, start: pd.Timestamp) -> float | None:
    cutoff = start - timedelta(hours=1)
    pos = history.close_time.searchsorted(cutoff, side="right") - 1
    if pos < 0 or cutoff - history.iloc[pos].close_time > MAX_PREMIUM_AGE:
        return None
    value = float(history.iloc[pos].premium_8h_mean)
    return value if np.isfinite(value) else None


def leg_return(
    symbol: str, direction: str, start: pd.Timestamp, end: pd.Timestamp,
    prices: dict[str, pd.DataFrame], funding: dict[str, pd.DataFrame],
) -> dict | None:
    bars = prices[symbol]
    if start not in bars.index or end not in bars.index:
        return None
    first, last = bars.index.get_indexer([start, end])
    if last - first != 1 or bars.iloc[first].segment != bars.iloc[last].segment:
        return None
    entry, exit_ = float(bars.iloc[first].open), float(bars.iloc[last].open)
    if entry <= 0 or exit_ <= 0:
        return None
    events = funding[symbol]
    settled = events.loc[(events.calc_time > start) & (events.calc_time < end)]
    if settled.empty:
        return None
    price_return = (exit_ / entry - 1) * (1 if direction == "long" else -1)
    funding_return = float(settled.last_funding_rate.sum()) * (-1 if direction == "long" else 1)
    return {
        "price_return": price_return, "funding_return": funding_return,
        "net_return": price_return + funding_return - ROUND_TRIP_COST,
    }


def build_portfolios(first_start: str, last_start: str) -> pd.DataFrame:
    premium, funding = market_history()
    prices = load_daily_prices()
    premium_by_symbol = {
        symbol: premium.loc[premium.symbol == symbol].sort_values("close_time")
        for symbol in SYMBOLS
    }
    funding_by_symbol = {
        symbol: funding.loc[funding.symbol == symbol].sort_values("calc_time")
        for symbol in SYMBOLS
    }
    days = []
    starts = pd.date_range(first_start, last_start, freq="D", tz="UTC")
    for start in starts:
        end = start + timedelta(days=1)
        available = {
            symbol: value
            for symbol in SYMBOLS
            if start in prices[symbol].index
            if (value := signal_at(premium_by_symbol[symbol], start)) is not None
        }
        if len(available) < 2 * RANK_SIZE:
            continue
        ranked = sorted(available, key=lambda symbol: (available[symbol], symbol))
        longs, shorts = ranked[:RANK_SIZE], ranked[-RANK_SIZE:]
        legs = [leg_return(symbol, "long", start, end, prices, funding_by_symbol)
                for symbol in longs]
        legs += [leg_return(symbol, "short", start, end, prices, funding_by_symbol)
                 for symbol in shorts]
        if any(leg is None for leg in legs):
            continue
        days.append({
            "start": start, "end": end, "eligible_symbols": len(available),
            "long_symbols": ",".join(longs), "short_symbols": ",".join(shorts),
            "premium_spread": float(np.mean([available[s] for s in shorts])
                                    - np.mean([available[s] for s in longs])),
            "price_return": float(np.mean([leg["price_return"] for leg in legs])),
            "funding_return": float(np.mean([leg["funding_return"] for leg in legs])),
            "net_return": float(np.mean([leg["net_return"] for leg in legs])),
        })
    result = pd.DataFrame(days)
    print("complete daily portfolios", len(result), flush=True)
    return result


def metrics(frame: pd.DataFrame) -> dict:
    monthly = frame.groupby(frame.start.dt.strftime("%Y-%m")).net_return.sum()
    net = frame.net_return.to_numpy()
    equity = np.cumprod(1 + net)
    drawdown = equity / np.maximum.accumulate(np.r_[1.0, equity])[1:] - 1
    return {
        "days": len(frame),
        "mean_daily_return": round(float(net.mean()), 7),
        "total_compounded_return": round(float(equity[-1] - 1), 5),
        "mean_price_return": round(float(frame.price_return.mean()), 7),
        "mean_funding_return": round(float(frame.funding_return.mean()), 7),
        "mean_with_extra_4bps": round(float((net - 0.0004).mean()), 7),
        "positive_months": int((monthly > 0).sum()), "months": len(monthly),
        "max_drawdown": round(float(drawdown.min()), 5),
        "monthly_return": monthly.round(5).to_dict(),
    }


def main() -> None:
    daily = build_portfolios("2023-01-02", "2025-06-30")
    cutoffs = {
        "train": ("2023-01-01", "2024-12-31"),
        "calibration": ("2025-01-01", "2025-06-30"),
    }
    splits = {}
    for name, (begin, last_day) in cutoffs.items():
        begin_ts = pd.Timestamp(begin, tz="UTC")
        end_ts = pd.Timestamp(last_day, tz="UTC") + timedelta(days=1)
        splits[name] = daily.loc[(daily.start >= begin_ts) & (daily.end <= end_ts)].copy()
    report = {
        "hypothesis": "daily long five lowest and short five highest lagged premiums, equal gross weights, realized funding, 14 bps round trip per leg",
        "train": metrics(splits["train"]),
        "calibration": metrics(splits["calibration"]),
    }
    cal = report["calibration"]
    qualified = (
        cal["days"] >= 150 and cal["mean_daily_return"] > 0
        and cal["mean_with_extra_4bps"] > 0
        and cal["positive_months"] >= 4
    )
    report["calibration_gate"] = qualified
    if qualified:
        validation = build_portfolios("2025-07-01", "2025-12-30")
        report["validation"] = metrics(validation)
        daily = pd.concat([daily, validation], ignore_index=True)
    else:
        report["validation"] = None
    daily.to_parquet(ROOT / "outputs/cross_basis_daily_portfolios.parquet", index=False)
    output = ROOT / "outputs/cross_basis_daily_report.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    print("saved", output, flush=True)


if __name__ == "__main__":
    main()
