"""Download and validate Binance's first-party monthly spot kline archives."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://data.binance.vision/data/spot/monthly/klines"
HOUR_MS = 3_600_000


@dataclass(frozen=True)
class Bar:
    open_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def months(first: str, last: str) -> list[str]:
    """Inclusive YYYY-MM month sequence."""
    start = datetime.strptime(first, "%Y-%m")
    stop = datetime.strptime(last, "%Y-%m")
    if start > stop:
        raise ValueError("first month must be at or before last month")
    result = []
    year, month = start.year, start.month
    while (year, month) <= (stop.year, stop.month):
        result.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return result


def archive_url(symbol: str, month: str) -> str:
    if not symbol.isalnum() or symbol.upper() != symbol:
        raise ValueError("symbol must be uppercase alphanumeric")
    datetime.strptime(month, "%Y-%m")
    return f"{BASE_URL}/{symbol}/1h/{symbol}-1h-{month}.zip"


def _read_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "jev-binance-research/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Binance archive unavailable: {url} ({exc.code})") from exc


def _expected_hash(checksum_bytes: bytes) -> str:
    first = checksum_bytes.decode("ascii").strip().split()[0].lower()
    if len(first) != 64 or any(ch not in "0123456789abcdef" for ch in first):
        raise ValueError("invalid Binance SHA256 checksum")
    return first


def fetch_archive(symbol: str, month: str, root: Path) -> dict:
    """Cache a ZIP only after verifying its first-party SHA256 and ZIP CRC."""
    url = archive_url(symbol, month)
    target = root / symbol / f"{symbol}-1h-{month}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    checksum_path = target.with_suffix(".zip.CHECKSUM")
    if checksum_path.exists():
        checksum_bytes = checksum_path.read_bytes()
    else:
        checksum_bytes = _read_url(url + ".CHECKSUM")
        checksum_path.write_bytes(checksum_bytes)
    expected = _expected_hash(checksum_bytes)
    if target.exists():
        payload = target.read_bytes()
        if hashlib.sha256(payload).hexdigest() != expected:
            raise ValueError(f"cached ZIP checksum mismatch: {target}")
    else:
        payload = _read_url(url)
        actual = hashlib.sha256(payload).hexdigest()
        if actual != expected:
            raise ValueError(f"downloaded ZIP checksum mismatch: {url}")
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if archive.testzip() is not None:
                raise ValueError(f"ZIP CRC mismatch: {url}")
        temporary = target.with_suffix(".zip.part")
        temporary.write_bytes(payload)
        temporary.replace(target)
    return {"symbol": symbol, "month": month, "url": url, "sha256": expected,
            "bytes": len(payload), "path": str(target)}


def _time_ms(raw: str) -> int:
    value = int(raw)
    if value >= 10**15:  # Spot public archives switched to microseconds in 2025.
        value //= 1000
    return value


def spacing_gaps(bars: list[Bar]) -> list[dict]:
    gaps = []
    for previous, current in zip(bars, bars[1:]):
        delta = current.open_ms - previous.open_ms
        if delta <= 0 or delta % HOUR_MS != 0 or delta > 24 * HOUR_MS:
            raise ValueError(f"invalid timestamp spacing near {previous.open_ms}")
        if delta > HOUR_MS:
            gaps.append({"after_open_ms": previous.open_ms,
                         "before_open_ms": current.open_ms,
                         "missing_hours": delta // HOUR_MS - 1})
    return gaps


def parse_archive(path: Path) -> list[Bar]:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"expected one CSV in {path}")
        with archive.open(names[0]) as stream:
            rows = csv.reader(io.TextIOWrapper(stream, encoding="utf-8-sig", newline=""))
            result = []
            for row in rows:
                if not row or row[0].lower() == "open_time":
                    continue
                if len(row) < 6:
                    raise ValueError(f"short kline row in {path}")
                bar = Bar(_time_ms(row[0]), *[float(row[i]) for i in range(1, 6)])
                if not (0 < bar.low <= min(bar.open, bar.close)
                        <= max(bar.open, bar.close) <= bar.high and bar.volume >= 0):
                    raise ValueError(f"invalid OHLCV at {bar.open_ms} in {path}")
                result.append(bar)
    if not result:
        raise ValueError(f"empty archive: {path}")
    spacing_gaps(result)
    return result


def load_range(symbols: list[str], first: str, last: str, root: Path,
               workers: int = 4) -> tuple[dict[str, list[Bar]], list[dict]]:
    tasks = [(symbol, month) for symbol in symbols for month in months(first, last)]
    manifest = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_archive, symbol, month, root): (symbol, month)
                   for symbol, month in tasks}
        for index, future in enumerate(as_completed(futures), start=1):
            record = future.result()
            manifest.append(record)
            print(f"archives {index}/{len(tasks)} {record['symbol']} {record['month']}", flush=True)
    manifest.sort(key=lambda item: (item["symbol"], item["month"]))
    frames = {}
    for symbol in symbols:
        bars = []
        for record in manifest:
            if record["symbol"] == symbol:
                parsed = parse_archive(Path(record["path"]))
                record["rows"] = len(parsed)
                record["gaps"] = spacing_gaps(parsed)
                bars.extend(parsed)
        spacing_gaps(bars)
        frames[symbol] = bars
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return frames, manifest


def load_cached_range(symbols: list[str], first: str, last: str,
                      root: Path) -> tuple[dict[str, list[Bar]], list[dict]]:
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError("download archives before running a cached replay")
    records = json.loads(manifest_path.read_text(encoding="utf-8"))
    lookup = {(row["symbol"], row["month"]): row for row in records}
    selected = []
    frames = {}
    for symbol in symbols:
        bars = []
        for month in months(first, last):
            row = lookup.get((symbol, month))
            if row is None:
                raise ValueError(f"missing cached archive: {symbol} {month}")
            path = Path(row["path"])
            if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
                raise ValueError(f"cached archive changed: {path}")
            bars.extend(parse_archive(path))
            selected.append(row)
        spacing_gaps(bars)
        frames[symbol] = bars
    return frames, selected


def utc_ms(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000)


def bar_dict(bar: Bar) -> dict:
    return asdict(bar)
