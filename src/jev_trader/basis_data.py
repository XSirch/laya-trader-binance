"""Read the frozen spot/perpetual basis inventory without network or writes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import zipfile

from .binance_data import HOUR_MS, months, parse_archive, spacing_gaps
from .cli import ROOT
from .derivatives_data import parse_funding

SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
FIRST, LAST = "2023-01", "2026-08"
SUPPLEMENT_DAYS = ("2023-02-24", "2026-06-29")
PINS = {
    "data/binance/spot/1h/manifest.json":
        "786bfeeb9ccfa3486033ca36cf98aad5a6b3a6ac59ec3c7ec4e1713634a0efe6",
    "data/binance/futures/um/manifest.json":
        "c2e6ec8281437f6771a236bb0311264e17ebf0e4d2dc19ee11bcd68cee2215bd",
    "data/binance/futures/um/supplemental_manifest.json":
        "1f1c645c313563f20201a8a5665f068f4c464af045ea8c76de1d2612509a3f75",
}
_SPOT, _DERIVATIVES, _SUPPLEMENTS = tuple(PINS)
_KINDS = {"klines": "futures", "markPriceKlines": "mark", "fundingRate": "funding"}
_REVERSE_KINDS = {value: key for key, value in _KINDS.items()}
_MAX_MONTH_HOURS = 31 * 24 + 1


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _utc(timestamp):
    return datetime.fromtimestamp(timestamp / 1000, timezone.utc).isoformat()


def _period_bounds(period, frequency):
    date = datetime.strptime(period, "%Y-%m-%d" if frequency == "daily" else "%Y-%m").replace(tzinfo=timezone.utc)
    if frequency == "daily":
        end = date + timedelta(days=1)
    else:
        end = date.replace(year=date.year + 1, month=1) if date.month == 12 else date.replace(month=date.month + 1)
    return int(date.timestamp() * 1000), int(end.timestamp() * 1000)


def _expected_inventory():
    calendar = months(FIRST, LAST)
    return {
        _SPOT: {("spot", symbol, "monthly", month) for symbol in SYMBOLS for month in calendar},
        _DERIVATIVES: {(market, symbol, "monthly", month)
                       for market in ("futures", "mark", "funding") for symbol in SYMBOLS for month in calendar},
        _SUPPLEMENTS: {("mark", symbol, "daily", day) for symbol in SYMBOLS for day in SUPPLEMENT_DAYS},
    }


def _identity(record, manifest):
    if not isinstance(record, dict):
        raise ValueError("source record must be an object")
    symbol, period = record.get("symbol"), record.get("month")
    if symbol not in SYMBOLS or not isinstance(period, str):
        raise ValueError("invalid source symbol or period")
    if manifest == _SPOT:
        market, frequency = "spot", "monthly"
        if record.get("kind", "klines") != "klines":
            raise ValueError("invalid spot source kind")
    elif manifest == _DERIVATIVES:
        market, frequency = _KINDS.get(record.get("kind")), "monthly"
        if market is None:
            raise ValueError("invalid derivative source kind")
    elif manifest == _SUPPLEMENTS:
        market, frequency = "mark", "daily"
        if record.get("kind") != "markPriceKlines":
            raise ValueError("invalid supplemental source kind")
    else:
        raise ValueError("unrecognized manifest path")
    if record.get("frequency", frequency) != frequency:
        raise ValueError("source frequency mismatch")
    interval = None if market == "funding" else "1h"
    if record.get("interval", interval) != interval:
        raise ValueError("source interval mismatch")
    _period_bounds(period, frequency)
    return market, symbol, frequency, period


def _source_location(identity):
    market, symbol, frequency, period = identity
    basename = f"{symbol}-fundingRate-{period}.zip" if market == "funding" else f"{symbol}-1h-{period}.zip"
    if market == "spot":
        relative = f"data/binance/spot/1h/{symbol}/{basename}"
        remote = f"spot/monthly/klines/{symbol}/1h/{basename}"
    else:
        kind = _REVERSE_KINDS[market]
        suffix = f"{kind}/{symbol}/{basename}" if market == "funding" else f"{kind}/{symbol}/1h/{basename}"
        relative = "data/binance/futures/um/" + ("daily/" if frequency == "daily" else "") + suffix
        remote = f"futures/um/{frequency}/{suffix}"
    return relative, f"https://data.binance.vision/data/{remote}"


def _confined(root, value):
    path = Path(value)
    if ".." in path.parts:
        raise ValueError("source path contains parent traversal")
    resolved = (path if path.is_absolute() else root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("source path escapes repository root")
    return resolved


def _read_manifest(root, name, pin, expected):
    path = _confined(root, name)
    payload = path.read_bytes()
    if _sha(payload) != pin:
        raise ValueError(f"manifest checksum mismatch: {name}")
    records = json.loads(payload.decode("utf-8"))
    if not isinstance(records, list):
        raise ValueError("manifest must be an array")
    found, validated = set(), []
    for record in records:
        identity = _identity(record, name)
        if identity in found:
            raise ValueError(f"duplicate source identity: {identity}")
        if identity not in expected:
            raise ValueError(f"unexpected source identity: {identity}")
        found.add(identity)
        relative, url = _source_location(identity)
        if not isinstance(record.get("path"), str):
            raise ValueError("source path must be text")
        actual_path = _confined(root, record["path"])
        canonical_path = _confined(root, relative)
        if actual_path != canonical_path or record.get("url") != url:
            raise ValueError(f"source identity/path/URL mismatch: {identity}")
        digest, size = record.get("sha256"), record.get("bytes")
        if (not isinstance(digest, str) or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
                or type(size) is not int or size <= 0):
            raise ValueError("invalid source checksum or size")
        validated.append((identity, canonical_path, relative, record))
    if found != expected:
        raise ValueError(f"incomplete manifest inventory: {name}")
    return sorted(validated), {"path": name, "sha256": pin, "bytes": len(payload), "sources": len(records)}


def _parse_source(identity, path, payload):
    market, _, frequency, period = identity
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        if archive.namelist() != [path.with_suffix(".csv").name]:
            raise ValueError(f"ZIP member identity mismatch: {path.name}")
        if archive.testzip() is not None:
            raise ValueError(f"ZIP CRC mismatch: {path.name}")
    stream = io.BytesIO(payload)
    rows = parse_funding(stream) if market == "funding" else parse_archive(stream, max_gap_hours=_MAX_MONTH_HOURS)
    start, end = _period_bounds(period, frequency)
    previous = None
    if not rows:
        raise ValueError(f"empty source archive: {path.name}")
    for row in rows:
        stamp = row.timestamp_ms if market == "funding" else row.open_ms
        if not start <= stamp < end:
            raise ValueError(f"row outside source period: {path.name}")
        if previous is not None and stamp <= previous:
            raise ValueError(f"duplicate/reversed source timestamps: {path.name}")
        previous = stamp
        if market != "funding":
            if stamp % HOUR_MS:
                raise ValueError(f"non-hourly candle timestamp: {path.name}")
            numbers = (row.open, row.high, row.low, row.close, row.volume,
                       row.quote_volume, row.trades, row.taker_buy_base)
            if any(value is not None and not math.isfinite(value) for value in numbers):
                raise ValueError(f"non-finite candle value: {path.name}")
    return rows


def _merge(target, rows, funding=False):
    duplicates = 0
    for row in rows:
        stamp = row.timestamp_ms if funding else row.open_ms
        if stamp in target:
            if target[stamp] != row:
                raise ValueError(f"conflicting duplicate observation: {stamp}")
            duplicates += 1
        else:
            target[stamp] = row
    return duplicates


def _coverage(rows, funding=False):
    stamps = [row.timestamp_ms if funding else row.open_ms for row in rows]
    result = {"rows": len(rows), "first_ms": stamps[0] if stamps else None,
              "last_ms": stamps[-1] if stamps else None,
              "first_utc": _utc(stamps[0]) if stamps else None,
              "last_utc": _utc(stamps[-1]) if stamps else None}
    if funding:
        intervals = [b - a for a, b in zip(stamps, stamps[1:])]
        result.update(
            interval_hours_values=sorted({row.interval_hours for row in rows}),
            minimum_spacing_ms=min(intervals) if intervals else None,
            maximum_spacing_ms=max(intervals) if intervals else None,
            maximum_event_offset_ms=max((stamp % HOUR_MS for stamp in stamps), default=None),
            interval_mismatches=[{"after_ms": a.timestamp_ms, "before_ms": b.timestamp_ms,
                                  "previous_interval_hours": a.interval_hours}
                                 for a, b in zip(rows, rows[1:])
                                 if b.timestamp_ms // HOUR_MS - a.timestamp_ms // HOUR_MS != a.interval_hours],
        )
    else:
        result.update(gaps=spacing_gaps(rows, max_gap_hours=24 * 366 * 5),
                      zero_volume_count=sum(row.volume == 0 for row in rows),
                      zero_trades_count=sum(row.trades == 0 for row in rows),
                      missing_trades_count=sum(row.trades is None for row in rows))
    return result


def _load_inventory(root, pins, expected):
    """Private fixture seam; public load always supplies the frozen inventory."""
    root = Path(root).resolve()
    if set(pins) != set(expected):
        raise ValueError("manifest pins and expected inventory differ")
    records, manifests = [], []
    for name, pin in pins.items():
        entries, manifest = _read_manifest(root, name, pin, expected[name])
        records.extend(entries)
        manifests.append(manifest)
    market = {kind: {symbol: {} for symbol in SYMBOLS} for kind in ("spot", "futures", "mark", "funding")}
    sources = []
    for identity, path, relative, record in records:
        payload = path.read_bytes()
        if len(payload) != record["bytes"] or _sha(payload) != record["sha256"]:
            raise ValueError(f"source checksum/size mismatch: {relative}")
        rows = _parse_source(identity, path, payload)
        kind, symbol, frequency, period = identity
        duplicate_count = _merge(market[kind][symbol], rows, funding=kind == "funding")
        sources.append({"path": relative, "url": record["url"], "sha256": record["sha256"],
                        "bytes": len(payload), "market": kind, "symbol": symbol,
                        "frequency": frequency, "period": period, "rows": len(rows),
                        "identical_duplicate_rows": duplicate_count})
    coverage = {kind: {} for kind in market}
    zero_trades = []
    for kind, by_symbol in market.items():
        for symbol, observations in by_symbol.items():
            ordered = dict(sorted(observations.items()))
            rows = list(ordered.values())
            by_symbol[symbol] = rows if kind == "funding" else ordered
            coverage[kind][symbol] = _coverage(rows, funding=kind == "funding")
            if kind in ("spot", "futures"):
                zero_trades.extend({"market": kind, "symbol": symbol, "open_ms": row.open_ms,
                                    "volume": row.volume} for row in rows if row.trades == 0)
    audit = {"schema": "basis-data-v1", "historical_point_in_time_verified": False,
             "network_requests": 0, "cache_writes": 0, "symbols": list(SYMBOLS),
             "first_month": FIRST, "last_month": LAST, "manifests": manifests,
             "sources": sources, "source_count": len(sources),
             "source_bytes": sum(source["bytes"] for source in sources),
             "identical_duplicate_rows": sum(source["identical_duplicate_rows"] for source in sources),
             "coverage": coverage, "zero_trades": zero_trades,
             "mark_trade_counts_are_not_execution_liquidity": True}
    audit["source_inventory_sha256"] = _sha(json.dumps(sources, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return market, audit


def load(root=ROOT):
    """Verify all 712 pinned ZIPs, preserving original timestamps and gaps.

    Candles map open_ms to Bar under spot/futures/mark; funding contains
    chronologically sorted Funding lists. Supplements may add missing candles
    or repeat exactly identical candles, never replace a conflicting value.
    No execution window, signal, forward return or liquidity filter is applied.
    """
    return _load_inventory(root, PINS, _expected_inventory())
