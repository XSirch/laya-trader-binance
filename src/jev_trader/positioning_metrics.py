"""Validate revised daily positioning archives, assuming naive CSV times are UTC.

These summaries describe the downloaded archive. They do not establish when its
values were first published or available to a historical trading decision.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import math
import re
import zipfile


METRIC_FIELDS = (
    "sum_open_interest",
    "sum_open_interest_value",
    "count_toptrader_long_short_ratio",
    "sum_toptrader_long_short_ratio",
    "count_long_short_ratio",
    "sum_taker_long_short_vol_ratio",
)
CSV_FIELDS = ("create_time", "symbol", *METRIC_FIELDS)
DAY_MS = 86_400_000
SLOT_MS = 300_000
EXPECTED_SLOTS = DAY_MS // SLOT_MS
MIN_VALID_SLOTS = 284
MAX_CSV_BYTES = 2 * 1024 * 1024
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}\Z")


def _day_start(day: str) -> int:
    if not isinstance(day, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day):
        raise ValueError("day must have the exact YYYY-MM-DD format")
    try:
        return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    except (ValueError, OverflowError, OSError) as exc:
        raise ValueError("invalid archive day") from exc


def _number(raw: str, field: str, line_number: int) -> float | None:
    token = raw.strip()
    if token.lower() in ("", "nan", "null"):
        return None
    if not _NUMBER.fullmatch(token):
        raise ValueError(f"invalid numeric token for {field} at CSV line {line_number}")
    value = float(token)
    if not math.isfinite(value):
        raise ValueError(f"nonfinite value for {field} at CSV line {line_number}")
    if value < 0:
        raise ValueError(f"invalid negative value for {field} at CSV line {line_number}")
    return value


def _quality(observations: list[dict], start: int, duplicate_rows: int) -> dict:
    present = {row["timestamp_ms"] for row in observations}
    missing = [timestamp for timestamp in range(start, start + DAY_MS, SLOT_MS) if timestamp not in present]
    valid = {field: sum(row[field] is not None for row in observations) for field in METRIC_FIELDS}
    positive = {field: sum(row[field] is not None and row[field] > 0 for row in observations)
                for field in METRIC_FIELDS}
    return {
        "expected_slots": EXPECTED_SLOTS,
        "unique_rows": len(observations),
        "duplicate_rows": duplicate_rows,
        "raw_rows": len(observations) + duplicate_rows,
        "missing_slots": len(missing),
        "missing_timestamp_ms": missing,
        "first_observed_timestamp_ms": observations[0]["timestamp_ms"] if observations else None,
        "last_observed_timestamp_ms": observations[-1]["timestamp_ms"] if observations else None,
        "field_valid_counts": valid,
        "field_positive_counts": positive,
        "field_missing_counts": {field: len(observations) - valid[field] for field in METRIC_FIELDS},
        "field_zero_counts": {field: valid[field] - positive[field] for field in METRIC_FIELDS},
        "zero_oi_counts": {field: valid[field] - positive[field] for field in METRIC_FIELDS[:2]},
        "timezone_assumption": "UTC",
        "original_publication_time_known": False,
        "counting_basis": "unique observations; identical raw field duplicates excluded",
    }


def parse_metrics(payload: bytes, symbol: str, day: str) -> dict:
    """Parse one exact daily ZIP member, retaining missing observations explicitly.

    Only duplicate rows with identical CSV field strings are deduplicated. A
    numerically equivalent but textually different version at the same timestamp
    is a conflict, not permission to choose a preferred archive observation.
    """
    start = _day_start(day)
    if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z0-9]{2,30}", symbol):
        raise ValueError("invalid archive symbol")
    if not isinstance(payload, bytes):
        raise ValueError("archive payload must be bytes")
    expected_member = f"{symbol}-metrics-{day}.csv"
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = archive.infolist()
            if len(members) != 1 or members[0].filename != expected_member or members[0].is_dir():
                raise ValueError("expected exactly the named daily CSV ZIP member")
            if members[0].flag_bits & 1:
                raise ValueError("encrypted metrics archives are unsupported")
            if members[0].file_size > MAX_CSV_BYTES:
                raise ValueError("metrics CSV exceeds the 2 MiB uncompressed size limit")
            if archive.testzip() is not None:
                raise ValueError("metrics archive CRC mismatch")
            with archive.open(members[0]) as member:
                raw_data = member.read(MAX_CSV_BYTES + 1)
            if len(raw_data) > MAX_CSV_BYTES:
                raise ValueError("metrics CSV exceeds the 2 MiB uncompressed size limit")
            data = raw_data.decode("utf-8-sig", errors="strict")
    except (zipfile.BadZipFile, UnicodeDecodeError, RuntimeError, NotImplementedError) as exc:
        raise ValueError("invalid metrics ZIP or UTF-8 CSV") from exc
    observations = {}
    raw_by_timestamp = {}
    duplicate_rows = 0
    try:
        reader = csv.reader(io.StringIO(data, newline=""), strict=True)
        header = next(reader, None)
        if header != list(CSV_FIELDS):
            raise ValueError("unexpected metrics CSV columns or column order")
        for raw in reader:
            line_number = reader.line_num
            if len(raw) != len(CSV_FIELDS):
                raise ValueError(f"wrong field count at CSV line {line_number}")
            if raw[1] != symbol:
                raise ValueError(f"wrong symbol at CSV line {line_number}")
            if not _TIME.fullmatch(raw[0]):
                raise ValueError(f"invalid timestamp format at CSV line {line_number}")
            try:
                timestamp = int(datetime.strptime(raw[0], "%Y-%m-%d %H:%M:%S")
                                .replace(tzinfo=timezone.utc).timestamp() * 1000)
            except (ValueError, OverflowError, OSError) as exc:
                raise ValueError(f"invalid timestamp at CSV line {line_number}") from exc
            if not start <= timestamp < start + DAY_MS or timestamp % SLOT_MS:
                raise ValueError(f"timestamp outside day or five-minute grid at CSV line {line_number}")
            fingerprint = tuple(raw)
            if timestamp in raw_by_timestamp:
                if raw_by_timestamp[timestamp] != fingerprint:
                    raise ValueError(f"conflicting duplicate timestamp at CSV line {line_number}")
                duplicate_rows += 1
                continue
            values = {field: _number(token, field, line_number)
                      for field, token in zip(METRIC_FIELDS, raw[2:])}
            raw_by_timestamp[timestamp] = fingerprint
            observations[timestamp] = {"timestamp_ms": timestamp, **values}
    except csv.Error as exc:
        raise ValueError("malformed metrics CSV") from exc
    ordered = [observations[timestamp] for timestamp in sorted(observations)]
    return {"symbol": symbol, "day": day, "observations": ordered,
            "quality": _quality(ordered, start, duplicate_rows)}


def snapshot(parsed: dict) -> dict:
    """Return daily medians or explicit unavailability, with no temporal filling.

    Coverage counts are based on distinct five-minute slots. Valid observed OI
    zeros remain in the median, but do not satisfy strictly positive coverage.
    This function establishes no historical publication or availability cutoff.
    """
    start = _day_start(parsed["day"])
    observations = parsed["observations"]
    quality = _quality(observations, start, parsed["quality"]["duplicate_rows"])
    reasons = []
    if quality["unique_rows"] < MIN_VALID_SLOTS:
        reasons.append(f"unique_slots_below_{MIN_VALID_SLOTS}")
    if quality["last_observed_timestamp_ms"] != start + DAY_MS - SLOT_MS:
        reasons.append("final_23_55_observation_missing")
    for field in METRIC_FIELDS:
        if quality["field_positive_counts"][field] < MIN_VALID_SLOTS:
            reasons.append(f"positive_coverage_below_{MIN_VALID_SLOTS}:{field}")
    available = not reasons
    values = {} if available else None
    if available:
        for field in METRIC_FIELDS:
            ordered = sorted(row[field] for row in observations if row[field] is not None)
            middle = len(ordered) // 2
            # All values are nonnegative; the difference avoids overflow in a+b.
            values[field] = (ordered[middle] if len(ordered) % 2 else
                             ordered[middle - 1] + (ordered[middle] - ordered[middle - 1]) / 2)
    return {"symbol": parsed["symbol"], "day": parsed["day"], "available": available,
            "reasons": reasons, "values": values,
            "last_observed_timestamp_ms": quality["last_observed_timestamp_ms"],
            "timezone_assumption": "UTC", "original_publication_time_known": False,
            "quality": quality}
