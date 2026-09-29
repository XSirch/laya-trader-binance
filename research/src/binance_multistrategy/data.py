"""Public Binance archives only. No API keys, trading endpoints or paid providers."""
from __future__ import annotations
import hashlib
import io
import json
import re
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
import numpy as np
import pandas as pd

COLUMNS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
           "quote_volume", "num_trades", "taker_buy_base", "taker_buy_quote", "ignore"]
BASE = "https://data.binance.vision/data"


def utc_timestamp(value: str | pd.Timestamp) -> pd.Timestamp:
    value = pd.Timestamp(value)
    return value.tz_localize("UTC") if value.tzinfo is None else value.tz_convert("UTC")


def parse_times(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().all():
        # Per row: supports the Binance Spot 2025 millisecond -> microsecond transition.
        absolute = numeric.abs()
        divisor = np.select([absolute >= 1e17, absolute >= 1e14, absolute >= 1e11],
                            [1e6, 1e3, 1], default=.001)
        return pd.Series(pd.to_datetime(np.rint(numeric.to_numpy() / divisor).astype("int64"), unit="ms", utc=True), index=values.index, name=values.name)
    return pd.to_datetime(values, utc=True, errors="raise")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def get_bytes(url: str, attempts: int = 3) -> bytes:
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "multistrategy-research/0.1"})
            with urllib.request.urlopen(request, timeout=45) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
                raise RuntimeError(f"Archive unavailable: {url} (HTTP {exc.code}); no invented data") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == attempts - 1:
                raise RuntimeError(f"Download failed: {url}: {exc}") from exc
        time.sleep(2 ** attempt)
    raise RuntimeError(f"Download failed: {url}")


def verified_archive(url: str, cache: Path) -> tuple[bytes, dict]:
    cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(url.encode()).hexdigest()[:16] + "_" + url.rsplit("/", 1)[-1]
    path, checksum_path = cache / key, cache / (key + ".CHECKSUM")
    checksum = checksum_path.read_bytes() if checksum_path.exists() else get_bytes(url + ".CHECKSUM")
    match = re.match(rb"\s*([a-fA-F0-9]{64})(?:\s|$)", checksum)
    if match is None:
        raise ValueError(f"Malformed Binance checksum: {url}")
    expected = match.group(1).decode().lower()
    payload = path.read_bytes() if path.exists() else get_bytes(url)
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise ValueError(f"SHA256 mismatch: {url}; delete corrupted cache before retrying")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        if archive.testzip() is not None or len(archive.namelist()) != 1:
            raise ValueError(f"Invalid archive: {url}")
        csv_data = archive.read(archive.namelist()[0])
    if not path.exists():
        temp = path.with_suffix(".part")
        temp.write_bytes(payload)
        temp.replace(path)
    checksum_path.write_bytes(checksum)
    return csv_data, {"url": url, "sha256": actual, "bytes": len(payload), "cache_file": key}


def parse_klines(raw: bytes) -> pd.DataFrame:
    first = raw.decode("utf-8-sig").splitlines()[0].split(",")[0]
    has_header = not first.isdigit()
    df = pd.read_csv(io.BytesIO(raw), header=0 if has_header else None)
    if len(df.columns) != 12:
        raise ValueError("Expected 12 columns in Binance kline archive")
    df.columns = COLUMNS
    df["open_time"] = parse_times(df.open_time)
    for column in COLUMNS[1:]:
        df[column] = pd.to_numeric(df[column], errors="raise")
    return df.drop(columns=["close_time", "ignore"])


def validate_candles(df: pd.DataFrame, market: str) -> pd.DataFrame:
    required = {"symbol", "open_time", "open", "high", "low", "close", "volume"}
    if not required.issubset(df):
        raise ValueError(f"Missing candle columns: {sorted(required - set(df))}")
    df = df.copy()
    df["open_time"] = parse_times(df.open_time)
    if "market" in df and not (df.market == market).all():
        raise ValueError("A model/dataset must use one market; do not mix Spot and Futures prices")
    df["market"] = market
    if df.empty or df.symbol.isna().any():
        raise ValueError("Empty dataset or missing symbol")
    for column in ["open", "high", "low", "close", "volume"]:
        df[column] = pd.to_numeric(df[column], errors="raise")
    price = df[["open", "high", "low", "close"]]
    if not np.isfinite(price).all().all() or (price <= 0).any().any():
        raise ValueError("Non-finite or non-positive OHLC")
    if ((df.high < price.max(axis=1)) | (df.low > price.min(axis=1))).any():
        raise ValueError("Inconsistent OHLC bounds")
    if not np.isfinite(df.volume).all() or (df.volume < 0).any():
        raise ValueError("Invalid volume")
    if df.duplicated(["symbol", "open_time"]).any():
        raise ValueError("Duplicate candles are not silently removed")
    df = df.sort_values(["symbol", "open_time"]).reset_index(drop=True)
    if ((df.open_time.astype("int64") // 10**9) % 60 != 0).any():
        raise ValueError("Expected minute-aligned open timestamps")
    for symbol, group in df.groupby("symbol", sort=False):
        differences = group.open_time.diff().dropna()
        if not (differences == pd.Timedelta(minutes=1)).all():
            bad = differences[differences != pd.Timedelta(minutes=1)].iloc[0]
            raise ValueError(f"{symbol}: missing/non-1m candles ({bad}). Repair from verified archives or use a contiguous period; no gap-filling")
    # The user must not accidentally supply the currently forming minute.
    if (df.open_time + pd.Timedelta(minutes=1) > pd.Timestamp.now(tz="UTC")).any():
        raise ValueError("Dataset contains future or currently unclosed candles")
    if market == "usd_m":
        extra = {"mark_open", "mark_high", "mark_low", "mark_close", "funding_rate", "funding_event"}
        if not extra.issubset(df):
            raise ValueError(f"Futures require observed mark prices and settlement events: {sorted(extra - set(df))}")
        marks = df[["mark_open", "mark_high", "mark_low", "mark_close"]]
        if not np.isfinite(marks).all().all() or (marks <= 0).any().any():
            raise ValueError("Missing/invalid mark prices")
        if ((df.mark_high < marks.max(axis=1)) | (df.mark_low > marks.min(axis=1))).any():
            raise ValueError("Invalid mark-price OHLC")
        if not np.isfinite(df.funding_rate).all() or (df.funding_rate.abs() > .1).any():
            raise ValueError("Invalid funding observations")
        if not df.funding_event.isin([0, 1]).all():
            raise ValueError("funding_event must be 0 or 1")
        if ((df.funding_event == 0) & (df.funding_rate != 0)).any():
            raise ValueError("A funding rate is payable only on its settlement event")
    else:
        for column in ["open", "high", "low", "close"]:
            df[f"mark_{column}"] = df[column]
        df["funding_rate"] = 0.0
        df["funding_event"] = 0
    return df


def recover_missing_mark_prices(symbol: str, candles: pd.DataFrame, marks: pd.DataFrame,
                                cache: Path, receipts: list[dict]) -> pd.DataFrame:
    """Recover absent monthly mark rows only from checksum-verified daily archives."""
    if marks.open_time.duplicated().any():
        raise ValueError(f"{symbol}: duplicate monthly mark timestamps")
    missing = pd.DatetimeIndex(candles.open_time.drop_duplicates()).difference(marks.open_time)
    if missing.empty:
        return marks
    patches = []
    mark_root = f"{BASE}/futures/um/daily/markPriceKlines/{symbol}/1m"
    for day in missing.normalize().unique():
        date = day.strftime("%Y-%m-%d")
        url = f"{mark_root}/{symbol}-1m-{date}.zip"
        raw, receipt = verified_archive(url, cache)
        daily = parse_klines(raw)[["open_time", "open", "high", "low", "close"]]
        if daily.open_time.duplicated().any():
            raise ValueError(f"{symbol}: duplicate timestamps in daily mark archive {date}")
        daily = daily.rename(columns={c: f"mark_{c}" for c in ["open", "high", "low", "close"]})
        recovered = daily.loc[daily.open_time.isin(missing)]
        patches.append(recovered)
        receipt["archive_kind"] = "daily_mark_recovery"
        receipt["recovered_rows"] = len(recovered)
        receipts.append(receipt)
    recovered = pd.concat(patches, ignore_index=True) if patches else marks.iloc[0:0]
    combined = pd.concat([marks, recovered], ignore_index=True)
    unresolved = pd.DatetimeIndex(candles.open_time.drop_duplicates()).difference(combined.open_time)
    if len(unresolved):
        preview = ", ".join(str(value) for value in unresolved[:5])
        raise ValueError(f"{symbol}: daily archives did not recover {len(unresolved)} missing mark rows ({preview}); no gap-filling")
    return combined


def download_dataset(output: Path, market: str, symbols: list[str], first: str, last: str,
                     start_time: str | pd.Timestamp | None = None,
                     end_time: str | pd.Timestamp | None = None) -> Path:
    if market not in {"spot", "usd_m"}:
        raise ValueError("market must be spot or usd_m")
    if not symbols or any(not re.fullmatch(r"[A-Z0-9]{4,25}", symbol) for symbol in symbols):
        raise ValueError("Provide uppercase Binance symbols, e.g. BTCUSDT")
    periods = pd.period_range(first, last, freq="M")
    if len(periods) == 0:
        raise ValueError("Empty month range")
    start = utc_timestamp(start_time) if start_time is not None else None
    end = utc_timestamp(end_time) if end_time is not None else None
    if (start is None) != (end is None) or (start is not None and start >= end):
        raise ValueError("Provide both start_time and exclusive end_time, with start_time < end_time")
    current_month = pd.Timestamp.now(tz="UTC").strftime("%Y-%m")
    if str(periods[-1]) >= current_month:
        raise ValueError("Only completed months; use a separate forward-data collector for the current month")
    output.mkdir(parents=True, exist_ok=True)
    receipts, all_symbols = [], []
    root = "spot" if market == "spot" else "futures/um"
    for symbol in dict.fromkeys(symbols):
        chunks, marks, funding_chunks = [], [], []
        for period in periods:
            month = str(period)
            url = f"{BASE}/{root}/monthly/klines/{symbol}/1m/{symbol}-1m-{month}.zip"
            raw, receipt = verified_archive(url, output / "cache")
            receipts.append(receipt)
            chunks.append(parse_klines(raw))
            if market == "usd_m":
                url = f"{BASE}/{root}/monthly/markPriceKlines/{symbol}/1m/{symbol}-1m-{month}.zip"
                raw, receipt = verified_archive(url, output / "cache")
                receipts.append(receipt)
                mark = parse_klines(raw)[["open_time", "open", "high", "low", "close"]]
                marks.append(mark.rename(columns={c: f"mark_{c}" for c in ["open", "high", "low", "close"]}))
                url = f"{BASE}/{root}/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip"
                raw, receipt = verified_archive(url, output / "cache")
                receipts.append(receipt)
                funding = pd.read_csv(io.BytesIO(raw))
                if not {"calc_time", "last_funding_rate"}.issubset(funding):
                    raise ValueError(f"Unexpected funding schema: {url}")
                funding["open_time"] = parse_times(funding.calc_time).dt.floor("min")
                funding["funding_rate"] = pd.to_numeric(funding.last_funding_rate, errors="raise")
                funding["funding_event"] = 1
                funding_chunks.append(funding[["open_time", "funding_rate", "funding_event"]])
            print(f"Verified {market} {symbol} {month}", flush=True)
        data = pd.concat(chunks, ignore_index=True)
        data["symbol"], data["market"] = symbol, market
        if start is not None:
            data = data.loc[(data.open_time >= start) & (data.open_time < end)].copy()
            if data.empty:
                raise ValueError(f"{symbol}: no candles inside requested UTC interval")
        if market == "usd_m":
            mark_data = pd.concat(marks, ignore_index=True)
            if start is not None:
                mark_data = recover_missing_mark_prices(symbol, data, mark_data, output / "cache", receipts)
            data = data.merge(mark_data, on="open_time", how="left", validate="one_to_one")
            settlements = pd.concat(funding_chunks, ignore_index=True)
            if start is not None:
                settlements = settlements.loc[(settlements.open_time >= start) & (settlements.open_time < end)]
            if settlements.open_time.duplicated().any():
                raise ValueError("Duplicate funding settlement minute")
            if not settlements.open_time.isin(data.open_time).all():
                raise ValueError("Funding event outside/missing from candle history")
            data = data.merge(settlements, on="open_time", how="left", validate="one_to_one")
            # Zero only means no event in COMPLETE checksum-verified monthly funding archives.
            data[["funding_rate", "funding_event"]] = data[["funding_rate", "funding_event"]].fillna(0)
        all_symbols.append(data)
    data = validate_candles(pd.concat(all_symbols, ignore_index=True), market)
    filename = output / "candles.csv.gz"
    temporary = output / "candles.tmp.csv.gz"
    data.to_csv(temporary, index=False, compression="gzip")
    temporary.replace(filename)
    manifest = {
        "market": market, "interval": "1m", "symbols": sorted(data.symbol.unique()),
        "first_month": first, "last_month": last, "rows": len(data),
        "start_time_inclusive": str(start) if start is not None else None,
        "end_time_exclusive": str(end) if end is not None else None,
        "data_sha256": sha256(filename), "funding_archives_verified": market == "usd_m",
        "source": "Binance public archives with SHA256 verification", "receipts": receipts,
    }
    (output / "dataset.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return filename


def load_dataset(path: Path, market: str) -> tuple[pd.DataFrame, dict]:
    filename = path / "candles.csv.gz" if path.is_dir() else path
    if not filename.is_file():
        raise FileNotFoundError(filename)
    meta_path = filename.parent / "dataset.json"
    manifest = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    digest = sha256(filename)
    if manifest.get("data_sha256") and manifest["data_sha256"] != digest:
        raise ValueError("Normalized dataset SHA256 differs from its manifest")
    if market == "usd_m" and not manifest.get("funding_archives_verified"):
        raise ValueError("Futures require a manifest confirming complete verified funding archives; do not invent a manifest for incomplete data")
    result = validate_candles(pd.read_csv(filename), market)
    return result, {**manifest, "data_sha256": digest, "path": str(filename),
                    "verified": bool(manifest.get("receipts"))}
