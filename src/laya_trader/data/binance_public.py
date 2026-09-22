from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
from pathlib import Path
import re
import sys
import zipfile

import requests

from laya_trader.config import load_config

BASE_URL = "https://data.binance.vision/data/futures"


def month_keys(start: str, end: str) -> list[str]:
    import pandas as pd

    periods = pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq="M")
    return [p.strftime("%Y-%m") for p in periods]


def kline_url(market: str, symbol: str, interval: str, month: str) -> str:
    filename = f"{symbol}-{interval}-{month}.zip"
    return f"{BASE_URL}/{market}/monthly/klines/{symbol}/{interval}/{filename}"


def verify_checksum(file_path: Path, checksum_text: str) -> None:
    match = re.search(r"\b([0-9a-fA-F]{64})\b", checksum_text)
    if not match:
        raise ValueError(f"could not parse checksum for {file_path.name}")
    expected = match.group(1).lower()
    digest = hashlib.sha256()
    with file_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected:
        file_path.unlink(missing_ok=True)
        raise ValueError(f"checksum mismatch for {file_path.name}: {actual} != {expected}")


def download_one(
    market: str,
    symbol: str,
    interval: str,
    month: str,
    raw_dir: Path,
    timeout: int = 45,
) -> tuple[str, str, str]:
    out_dir = raw_dir / "binance" / "futures" / market / "monthly" / "klines" / symbol / interval
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{symbol}-{interval}-{month}.zip"
    target = out_dir / filename
    url = kline_url(market, symbol, interval, month)
    checksum_url = url + ".CHECKSUM"

    with requests.Session() as session:
        if target.exists() and target.stat().st_size > 0:
            try:
                validate_archive(session, target, checksum_url, timeout)
            except (OSError, ValueError):
                target.unlink(missing_ok=True)
            else:
                return symbol, month, "cached"

        response = session.get(url, timeout=timeout)
        if response.status_code == 404:
            return symbol, month, "not-listed"
        response.raise_for_status()
        tmp = target.with_suffix(".zip.part")
        tmp.write_bytes(response.content)
        try:
            validate_archive(session, tmp, checksum_url, timeout)
            tmp.replace(target)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
    return symbol, month, "downloaded"


def download_dataset(config_path: str | Path) -> dict[str, int]:
    cfg = load_config(config_path)
    if cfg.data.market not in {"um", "cm"}:
        raise ValueError("data.market must be 'um' (USD-M) or 'cm' (COIN-M)")
    if not cfg.data.symbols:
        raise ValueError("configure at least one symbol")

    jobs = [
        (cfg.data.market, symbol, cfg.data.interval, month, cfg.data.raw_dir)
        for symbol in cfg.data.symbols
        for month in month_keys(cfg.data.start, cfg.data.end)
    ]
    counts: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=max(1, cfg.data.workers)) as pool:
        futures = [pool.submit(download_one, *job) for job in jobs]
        for fut in as_completed(futures):
            symbol, month, status = fut.result()
            counts[status] = counts.get(status, 0) + 1
            print(f"{symbol} {month}: {status}")
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download monthly Binance Futures kline archives")
    parser.add_argument("--config", default="configs/dataset.toml")
    args = parser.parse_args(argv)
    try:
        counts = download_dataset(args.config)
    except Exception as exc:
        print(f"download failed: {exc}", file=sys.stderr)
        return 1
    print("summary:", counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
