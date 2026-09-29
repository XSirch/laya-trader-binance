"""Public USD-M bookTicker capture for the preregistered C20 source audit.

This module has no Binance account credentials and no order methods. It stores
one last-observed BBO sample per UTC second; it does not save raw feed messages.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import time
from typing import Any
from urllib.request import urlopen
import uuid

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI


WS_URL = "wss://fstream.binance.com/public/ws/btcusdt@bookTicker"
TIME_URL = "https://fapi.binance.com/fapi/v1/time"
SYMBOL = "BTCUSDT"
SAMPLE_MS = 1_000
MAX_CAPTURE_DAYS = 112
MAX_QUOTE_AGE_MS = 5_000
MAX_CLOCK_OFFSET_MS = 100.0
CLOCK_PROBE_MAX_AGE_MS = 60_000
UTC_DAY_SECONDS = 86_400
SOURCE_QUALITY_WINDOW_DAYS = 14
SOURCE_QUALITY_MIN_DAYS = 13
SOURCE_QUALITY_MIN_VALID_FRACTION = 0.99
MAX_START_WAIT_SLEEP_S = 30.0
ROTATE_CONNECTION_AFTER_S = 23 * 60 * 60 + 50 * 60
ZERO_HASH = "0" * 64

CSV_FIELDS = [
    "schema_version",
    "second_utc",
    "process_instance_id",
    "connection_generation",
    "connection_state",
    "messages_received",
    "parse_errors",
    "invalid_bookticker_events",
    "duplicate_update_ids",
    "regression_update_ids",
    "nonconsecutive_update_ids",
    "max_update_id_delta",
    "connection_disruptions",
    "event_time_ms",
    "transaction_time_ms",
    "update_id",
    "bid",
    "bid_qty",
    "ask",
    "ask_qty",
    "quote_received_utc_ns",
    "quote_received_monotonic_ns",
    "quote_age_ms",
    "clock_server_time_ms",
    "clock_offset_ms",
    "clock_rtt_ms",
    "clock_uncertainty_ms",
    "clock_qualified",
    "spread_bps",
    "mid",
    "microprice",
    "microprice_deviation_bps",
    "quantity_imbalance",
    "sample_valid",
]


class BookTickerParseError(ValueError):
    """An incoming message doesn't satisfy the frozen BTCUSDT schema."""


def _decimal_field(payload: dict[str, Any], key: str, *, positive: bool) -> Decimal:
    value = payload.get(key)
    if not isinstance(value, str):
        raise BookTickerParseError(f"{key}_not_string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise BookTickerParseError(f"{key}_not_decimal") from exc
    if not result.is_finite() or (positive and result <= 0) or (not positive and result < 0):
        raise BookTickerParseError(f"{key}_out_of_range")
    return result


def _integer_field(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BookTickerParseError(f"{key}_not_nonnegative_integer")
    return value


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


@dataclass(frozen=True)
class BookTicker:
    update_id: int
    event_time_ms: int
    transaction_time_ms: int
    bid: Decimal
    bid_qty: Decimal
    ask: Decimal
    ask_qty: Decimal
    received_utc_ns: int
    received_monotonic_ns: int


def parse_bookticker(
    message: str | bytes,
    *,
    received_utc_ns: int,
    received_monotonic_ns: int,
) -> BookTicker:
    """Parse one raw individual-symbol bookTicker event without coercion."""
    try:
        if isinstance(message, bytes):
            message = message.decode("utf-8", errors="strict")
        payload = json.loads(message)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BookTickerParseError("invalid_json_or_utf8") from exc
    if not isinstance(payload, dict):
        raise BookTickerParseError("payload_not_object")
    if payload.get("e") != "bookTicker":
        raise BookTickerParseError("unexpected_event_type")
    if payload.get("s") != SYMBOL:
        raise BookTickerParseError("unexpected_symbol")
    if payload.get("ps") != SYMBOL:
        raise BookTickerParseError("unexpected_pair")
    symbol_type = payload.get("st")
    if isinstance(symbol_type, bool) or not isinstance(symbol_type, int) or symbol_type != 1:
        raise BookTickerParseError("unexpected_symbol_type")

    update_id = _integer_field(payload, "u")
    event_time_ms = _integer_field(payload, "E")
    transaction_time_ms = _integer_field(payload, "T")
    bid = _decimal_field(payload, "b", positive=True)
    bid_qty = _decimal_field(payload, "B", positive=False)
    ask = _decimal_field(payload, "a", positive=True)
    ask_qty = _decimal_field(payload, "A", positive=False)
    if bid > ask:
        raise BookTickerParseError("crossed_quote")
    if received_utc_ns < 0 or received_monotonic_ns < 0:
        raise BookTickerParseError("invalid_receive_clock")
    return BookTicker(
        update_id=update_id,
        event_time_ms=event_time_ms,
        transaction_time_ms=transaction_time_ms,
        bid=bid,
        bid_qty=bid_qty,
        ask=ask,
        ask_qty=ask_qty,
        received_utc_ns=received_utc_ns,
        received_monotonic_ns=received_monotonic_ns,
    )


@dataclass(frozen=True)
class ClockReading:
    server_time_ms: int
    offset_ms: float
    rtt_ms: float
    uncertainty_ms: float
    measured_utc_ns: int
    qualified: bool
    measured_monotonic_ns: int | None = None


def parse_clock_response(
    body: bytes,
    *,
    request_start_utc_ns: int,
    request_start_monotonic_ns: int,
    request_end_monotonic_ns: int,
) -> ClockReading:
    """Estimate clock offset using the request midpoint and expose its bound."""
    try:
        payload = json.loads(body.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_clock_response") from exc
    server_time = payload.get("serverTime") if isinstance(payload, dict) else None
    if isinstance(server_time, bool) or not isinstance(server_time, int) or server_time < 0:
        raise ValueError("server_time_missing")
    elapsed_ns = request_end_monotonic_ns - request_start_monotonic_ns
    if elapsed_ns < 0:
        raise ValueError("monotonic_clock_reversed")
    midpoint_local_ns = request_start_utc_ns + elapsed_ns // 2
    rtt_ms = elapsed_ns / 1_000_000
    uncertainty_ms = rtt_ms / 2 + 1.0  # includes millisecond server-time quantization
    offset_ms = server_time - midpoint_local_ns / 1_000_000
    qualified = abs(offset_ms) + uncertainty_ms <= MAX_CLOCK_OFFSET_MS
    return ClockReading(
        server_time_ms=server_time,
        offset_ms=offset_ms,
        rtt_ms=rtt_ms,
        uncertainty_ms=uncertainty_ms,
        measured_utc_ns=request_start_utc_ns + elapsed_ns,
        qualified=qualified,
        measured_monotonic_ns=request_end_monotonic_ns,
    )


def build_sample_row(
    *,
    second_epoch: int,
    quote: BookTicker | None,
    counters: dict[str, int],
    connection_state: str,
    connection_generation: int,
    process_instance_id: str,
    now_utc_ns: int,
    clock_reading: ClockReading | None,
    now_monotonic_ns: int | None = None,
) -> dict[str, str | int]:
    """Create a single row; missing or stale observations remain explicit."""
    row: dict[str, str | int] = {
        "schema_version": 1,
        "second_utc": datetime.fromtimestamp(second_epoch, UTC).isoformat().replace("+00:00", "Z"),
        "process_instance_id": process_instance_id,
        "connection_generation": connection_generation,
        "connection_state": connection_state,
    }
    for key in (
        "messages_received",
        "parse_errors",
        "invalid_bookticker_events",
        "duplicate_update_ids",
        "regression_update_ids",
        "nonconsecutive_update_ids",
        "max_update_id_delta",
        "connection_disruptions",
    ):
        row[key] = int(counters.get(key, 0))

    if quote is None:
        age_ms: float | None = None
        receipt_age_monotonic_ms: float | None = None
        quote_fields: dict[str, str | int] = {
            "event_time_ms": "",
            "transaction_time_ms": "",
            "update_id": "",
            "bid": "",
            "bid_qty": "",
            "ask": "",
            "ask_qty": "",
            "quote_received_utc_ns": "",
            "quote_received_monotonic_ns": "",
            "spread_bps": "",
            "mid": "",
            "microprice": "",
            "microprice_deviation_bps": "",
            "quantity_imbalance": "",
        }
    else:
        age_ms = (now_utc_ns - quote.received_utc_ns) / 1_000_000
        if now_monotonic_ns is None:
            # Compatibility for deterministic/offline callers predating the
            # monotonic receive clock argument. Runtime paths pass it directly.
            now_monotonic_ns = quote.received_monotonic_ns + (now_utc_ns - quote.received_utc_ns)
        receipt_age_monotonic_ms = (
            now_monotonic_ns - quote.received_monotonic_ns
        ) / 1_000_000
        mid = (quote.bid + quote.ask) / 2
        spread_bps = (quote.ask - quote.bid) / mid * Decimal(10_000)
        total_qty = quote.bid_qty + quote.ask_qty
        microprice = (
            (quote.ask * quote.bid_qty + quote.bid * quote.ask_qty) / total_qty
            if total_qty > 0
            else mid
        )
        imbalance = (quote.bid_qty - quote.ask_qty) / total_qty if total_qty > 0 else Decimal(0)
        microprice_deviation = (microprice - mid) / mid * Decimal(10_000)
        quote_fields = {
            "event_time_ms": quote.event_time_ms,
            "transaction_time_ms": quote.transaction_time_ms,
            "update_id": quote.update_id,
            "bid": _decimal_text(quote.bid),
            "bid_qty": _decimal_text(quote.bid_qty),
            "ask": _decimal_text(quote.ask),
            "ask_qty": _decimal_text(quote.ask_qty),
            "quote_received_utc_ns": quote.received_utc_ns,
            "quote_received_monotonic_ns": quote.received_monotonic_ns,
            "spread_bps": _decimal_text(spread_bps),
            "mid": _decimal_text(mid),
            "microprice": _decimal_text(microprice),
            "microprice_deviation_bps": _decimal_text(microprice_deviation),
            "quantity_imbalance": _decimal_text(imbalance),
        }
    row.update(quote_fields)
    row["quote_age_ms"] = "" if age_ms is None else f"{age_ms:.3f}"
    receipt_fresh = bool(
        receipt_age_monotonic_ms is not None
        and 0 <= receipt_age_monotonic_ms <= MAX_QUOTE_AGE_MS
    )
    row["receipt_age_monotonic_ms"] = (
        "" if receipt_age_monotonic_ms is None else f"{receipt_age_monotonic_ms:.3f}"
    )
    row["receipt_fresh"] = int(receipt_fresh)
    if clock_reading is not None:
        clock_age_ms = (now_utc_ns - clock_reading.measured_utc_ns) / 1_000_000
    else:
        clock_age_ms = math.inf
    clock_is_fresh = clock_age_ms <= CLOCK_PROBE_MAX_AGE_MS
    clock_probe_fresh = bool(clock_reading and 0 <= clock_age_ms <= CLOCK_PROBE_MAX_AGE_MS)
    clock_wall_monotonic_divergence_ms: float | None = None
    if (clock_reading is not None and now_monotonic_ns is not None
            and clock_reading.measured_monotonic_ns is not None):
        monotonic_age_ms = (now_monotonic_ns - clock_reading.measured_monotonic_ns) / 1_000_000
        clock_wall_monotonic_divergence_ms = clock_age_ms - monotonic_age_ms
        clock_probe_fresh = bool(
            0 <= monotonic_age_ms <= CLOCK_PROBE_MAX_AGE_MS
            and abs(clock_wall_monotonic_divergence_ms) <= MAX_CLOCK_OFFSET_MS
        )
    row["clock_server_time_ms"] = clock_reading.server_time_ms if clock_reading else ""
    row["clock_offset_ms"] = f"{clock_reading.offset_ms:.3f}" if clock_reading else ""
    row["clock_rtt_ms"] = f"{clock_reading.rtt_ms:.3f}" if clock_reading else ""
    row["clock_uncertainty_ms"] = f"{clock_reading.uncertainty_ms:.3f}" if clock_reading else ""
    row["clock_qualified"] = int(bool(clock_reading and clock_is_fresh and clock_reading.qualified))
    quote_fresh = quote is not None and 0 <= age_ms <= MAX_QUOTE_AGE_MS
    temporal_state = "unknown"
    event_age_ms: float | None = None
    transaction_age_ms: float | None = None
    if quote is not None and clock_reading is not None:
        estimated_server_now_ms = now_utc_ns / 1_000_000 + clock_reading.offset_ms
        event_age_ms = estimated_server_now_ms - quote.event_time_ms
        transaction_age_ms = estimated_server_now_ms - quote.transaction_time_ms
        uncertainty_ms = max(0.0, clock_reading.uncertainty_ms)
        if clock_reading.qualified and clock_probe_fresh:
            ages = (event_age_ms, transaction_age_ms)
            if any(age + uncertainty_ms < 0 or age - uncertainty_ms > MAX_QUOTE_AGE_MS for age in ages):
                temporal_state = "stale"
            elif all(age - uncertainty_ms >= 0 and age + uncertainty_ms <= MAX_QUOTE_AGE_MS for age in ages):
                temporal_state = "fresh"
    valid = (
        connection_state == "connected"
        and quote_fresh
        and int(counters.get("parse_errors", 0)) == 0
        and int(counters.get("duplicate_update_ids", 0)) == 0
        and int(counters.get("regression_update_ids", 0)) == 0
        and int(counters.get("connection_disruptions", 0)) == 0
    )
    row["sample_valid"] = int(valid)
    temporal_valid = temporal_state == "fresh"
    row["event_age_ms"] = "" if event_age_ms is None else f"{event_age_ms:.3f}"
    row["transaction_age_ms"] = "" if transaction_age_ms is None else f"{transaction_age_ms:.3f}"
    row["event_freshness"] = temporal_state
    row["clock_probe_fresh"] = int(clock_probe_fresh)
    row["clock_wall_monotonic_divergence_ms"] = (
        "" if clock_wall_monotonic_divergence_ms is None
        else f"{clock_wall_monotonic_divergence_ms:.3f}"
    )
    row["temporal_valid"] = int(temporal_valid)
    row["transport_valid"] = int(connection_state == "connected" and receipt_fresh)
    row["quality_valid"] = int(valid and receipt_fresh and temporal_state != "stale")
    row["execution_eligible"] = int(valid and receipt_fresh and temporal_valid)
    flags = []
    if quote is None:
        flags.append("quote_missing")
    if not receipt_fresh:
        flags.append("receipt_not_fresh")
    if not clock_reading or not clock_probe_fresh or not clock_reading.qualified:
        flags.append("clock_unqualified")
    if temporal_state != "fresh":
        flags.append(f"event_{temporal_state}")
    if counters.get("parse_errors", 0):
        flags.append("stream_parse_errors")
    row["quality_flags"] = json.dumps(flags, separators=(",", ":"))
    return row


def evaluate_first_14_day_quality(
    daily_audits: list[dict[str, Any]],
    *,
    start_epoch: int,
    seconds_per_day: int = UTC_DAY_SECONDS,
    minimum_valid_fraction: float = SOURCE_QUALITY_MIN_VALID_FRACTION,
    window_closed: bool = True,
) -> dict[str, Any]:
    """Evaluate the fixed first 14 days; later days never replace a weak day."""
    if seconds_per_day < 1 or not 0 < minimum_valid_fraction <= 1:
        raise ValueError("invalid_source_quality_threshold")
    expected_days = SOURCE_QUALITY_WINDOW_DAYS
    minimum_valid_rows = math.ceil(seconds_per_day * minimum_valid_fraction)
    first_window = {
        int(row["day_index"]): row
        for row in daily_audits
        if 0 <= int(row["day_index"]) < expected_days
    }
    integrity_errors = sorted({
        str(error)
        for day_index, row in first_window.items()
        for error in row.get("integrity_errors", [])
    })
    qualified_days = []
    failed_days = []
    for day_index in range(expected_days):
        audit = first_window.get(day_index)
        if audit is None:
            continue
        if (audit.get("structural_complete") is True
                and int(audit.get("rows", 0)) == seconds_per_day
                and int(audit.get("valid_rows", 0)) >= minimum_valid_rows):
            qualified_days.append(day_index)
        else:
            failed_days.append(day_index)
    missing_days = [day for day in range(expected_days) if day not in first_window]
    if integrity_errors:
        status = "review_required"
    elif not window_closed:
        status = "pending"
    elif len(qualified_days) >= SOURCE_QUALITY_MIN_DAYS:
        status = "qualified"
    else:
        status = "failed"
    return {
        "status": status,
        "start_epoch": int(start_epoch),
        "days_in_window": expected_days,
        "days_present": len(first_window),
        "qualified_days": len(qualified_days),
        "qualified_day_indices": qualified_days,
        "failed_day_indices": failed_days,
        "missing_day_indices": missing_days,
        "minimum_qualified_days": SOURCE_QUALITY_MIN_DAYS,
        "seconds_per_day": seconds_per_day,
        "minimum_valid_fraction": minimum_valid_fraction,
        "threshold_valid_rows_per_day": minimum_valid_rows,
        "decision_window_end_epoch": int(start_epoch) + expected_days * seconds_per_day,
        "window_closed": bool(window_closed),
        "integrity_errors": integrity_errors,
        "stop_required": status in {"failed", "review_required"},
    }


class SourceQualityGateStop(RuntimeError):
    """The fixed C20 source-quality window failed or requires review."""


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json_file(path: Path, value: dict[str, Any]) -> None:
    raw = (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    temporary = path.with_name(path.name + ".part-" + uuid.uuid4().hex)
    with temporary.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


class DailyStore:
    """Append-only daily samples with a checksum and hash-chained manifest."""

    def __init__(self, data_dir: Path, *, start_epoch: int):
        self.data_dir = data_dir
        self.start_epoch = start_epoch
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = data_dir / "manifest.jsonl"
        self.quality_report_path = data_dir / "source_quality_report.json"
        self.quality_history_path = data_dir / "source_quality_history.jsonl"
        self.previous_record_hash = ZERO_HASH
        self.manifested: dict[str, dict[str, Any]] = {}
        self.quality_history_hash = ZERO_HASH
        self.source_quality_status = "pending"
        self.source_quality_report: dict[str, Any] = {}
        try:
            self._verify_quality_history()
        except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
            report = {
                "status": "review_required",
                "start_epoch": self.start_epoch,
                "days_in_window": SOURCE_QUALITY_WINDOW_DAYS,
                "days_present": 0,
                "qualified_days": 0,
                "minimum_qualified_days": SOURCE_QUALITY_MIN_DAYS,
                "integrity_errors": [f"source_quality_history_integrity:{type(exc).__name__}:{str(exc)[:160]}"],
                "stop_required": True,
            }
            _atomic_json_file(self.quality_report_path, report)
            raise RuntimeError("source_quality_history_requires_review") from exc
        try:
            self._verify_manifest()
        except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
            report = {
                "status": "review_required",
                "start_epoch": self.start_epoch,
                "days_in_window": SOURCE_QUALITY_WINDOW_DAYS,
                "days_present": 0,
                "qualified_days": 0,
                "minimum_qualified_days": SOURCE_QUALITY_MIN_DAYS,
                "integrity_errors": [f"manifest_integrity:{type(exc).__name__}:{str(exc)[:160]}"],
                "stop_required": True,
            }
            self._append_quality_report(report)
            raise RuntimeError(f"manifest_integrity_requires_source_quality_review:{exc}") from exc
        self.active_date: str | None = None
        self.csv_handle: Any = None
        self.csv_writer: Any = None
        self.day_rows = 0
        self.day_valid_rows = 0
        self.day_quality_valid_rows = 0
        self.day_temporal_valid_rows = 0
        self.last_second_epoch = self._last_manifest_second()
        self._restore_unmanifested_day()
        if self.source_quality_status not in {"failed", "review_required", "qualified"}:
            self._refresh_source_quality_report()

    @staticmethod
    def date_for(second_epoch: int) -> str:
        return datetime.fromtimestamp(second_epoch, UTC).date().isoformat()

    def csv_path(self, day: str) -> Path:
        return self.data_dir / f"bookticker_usdm_btcusdt_{day}.csv"

    def events_path(self, day: str) -> Path:
        return self.data_dir / f"events_usdm_btcusdt_{day}.jsonl"

    def temporal_diagnostics_path(self, day: str) -> Path:
        return self.data_dir / f"temporal_diagnostics_usdm_btcusdt_{day}.jsonl"

    def _verify_manifest(self) -> None:
        if not self.manifest_path.exists():
            return
        previous_day: str | None = None
        with self.manifest_path.open("r", encoding="utf-8", errors="strict") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    raise RuntimeError(f"blank_manifest_line:{line_number}")
                record = json.loads(line)
                supplied_hash = record.pop("record_sha256", None)
                if record.get("previous_record_sha256") != self.previous_record_hash:
                    raise RuntimeError(f"manifest_chain_broken:{line_number}")
                expected_hash = hashlib.sha256(_canonical_json(record)).hexdigest()
                if supplied_hash != expected_hash:
                    raise RuntimeError(f"manifest_record_hash_mismatch:{line_number}")
                day = record["date_utc"]
                if previous_day is not None and day <= previous_day:
                    raise RuntimeError(f"manifest_date_order_mismatch:{line_number}")
                if day in self.manifested:
                    raise RuntimeError(f"duplicate_manifest_date:{day}")
                csv_path = self.data_dir / record["csv_file"]
                events_path = self.data_dir / record["events_file"]
                if not csv_path.is_file() or sha256_file(csv_path) != record["csv_sha256"]:
                    raise RuntimeError(f"daily_csv_hash_mismatch:{day}")
                if not events_path.is_file() or sha256_file(events_path) != record["events_sha256"]:
                    raise RuntimeError(f"daily_events_hash_mismatch:{day}")
                if int(record.get("schema_version", 1)) >= 2:
                    temporal_name = record.get("temporal_diagnostics_file")
                    temporal_path = self.data_dir / str(temporal_name or "")
                    if (not temporal_name or not temporal_path.is_file()
                            or sha256_file(temporal_path) != record.get("temporal_diagnostics_sha256")):
                        raise RuntimeError(f"daily_temporal_diagnostics_hash_mismatch:{day}")
                record["record_sha256"] = supplied_hash
                self.manifested[day] = record
                self.previous_record_hash = supplied_hash
                previous_day = day

    def _verify_quality_history(self) -> None:
        if not self.quality_history_path.exists():
            return
        with self.quality_history_path.open("r", encoding="utf-8", errors="strict") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    raise RuntimeError(f"blank_source_quality_history_line:{line_number}")
                record = json.loads(line)
                supplied_hash = record.pop("record_sha256", None)
                if record.get("previous_record_sha256") != self.quality_history_hash:
                    raise RuntimeError(f"source_quality_history_chain_broken:{line_number}")
                expected_hash = hashlib.sha256(_canonical_json(record)).hexdigest()
                if supplied_hash != expected_hash:
                    raise RuntimeError(f"source_quality_history_hash_mismatch:{line_number}")
                report = record.get("report")
                if not isinstance(report, dict) or report.get("start_epoch") != self.start_epoch:
                    raise RuntimeError(f"source_quality_history_anchor_mismatch:{line_number}")
                record["record_sha256"] = supplied_hash
                self.quality_history_hash = supplied_hash
                self.source_quality_report = report
                self.source_quality_status = str(report.get("status", "review_required"))
        if self.source_quality_report and not self.quality_report_path.exists():
            _atomic_json_file(self.quality_report_path, self.source_quality_report)

    def _append_quality_report(self, report: dict[str, Any]) -> None:
        if self.source_quality_report == report:
            return
        body = {
            "schema_version": 1,
            "recorded_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "previous_record_sha256": self.quality_history_hash,
            "report": report,
        }
        record_hash = hashlib.sha256(_canonical_json(body)).hexdigest()
        line = {**body, "record_sha256": record_hash}
        with self.quality_history_path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(json.dumps(line, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        _atomic_json_file(self.quality_report_path, report)
        self.quality_history_hash = record_hash
        self.source_quality_report = report
        self.source_quality_status = str(report["status"])

    def _audit_quality_day(self, day_index: int, day: str, record: dict[str, Any]) -> dict[str, Any]:
        csv_path = self.data_dir / record["csv_file"]
        errors: list[str] = []
        count = valid = quality_valid = temporal_valid = 0
        first_second: int | None = None
        last_second: int | None = None
        expected_start = self.start_epoch + day_index * UTC_DAY_SECONDS
        try:
            if sha256_file(csv_path) != record["csv_sha256"]:
                errors.append("daily_csv_hash_mismatch")
            with csv_path.open("r", newline="", encoding="utf-8", errors="strict") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames != CSV_FIELDS:
                    errors.append("daily_csv_schema_mismatch")
                for row in reader:
                    if None in row or len(row) != len(CSV_FIELDS):
                        errors.append("daily_csv_row_width_mismatch")
                        continue
                    stamp = datetime.fromisoformat(row["second_utc"].replace("Z", "+00:00"))
                    second = int(stamp.timestamp())
                    expected_second = expected_start + count
                    if (self.date_for(second) != day or second != expected_second
                            or second < self.start_epoch
                            or second >= self.start_epoch + SOURCE_QUALITY_WINDOW_DAYS * UTC_DAY_SECONDS):
                        errors.append("daily_csv_order_or_date_mismatch")
                    first_second = second if first_second is None else first_second
                    last_second = second
                    count += 1
                    valid += int(row.get("sample_valid") == "1")
            if count != int(record.get("rows", -1)) or valid != int(record.get("valid_rows", -1)):
                errors.append("daily_csv_manifest_count_mismatch")

            schema_version = int(record.get("schema_version", 1))
            temporal_name = record.get("temporal_diagnostics_file")
            temporal_path = self.data_dir / str(temporal_name or "") if temporal_name else None
            if schema_version >= 2:
                if (temporal_path is None or not temporal_path.is_file()
                        or sha256_file(temporal_path) != record.get("temporal_diagnostics_sha256")):
                    errors.append("daily_temporal_diagnostics_hash_mismatch")
            if temporal_path is not None and temporal_path.is_file():
                if schema_version < 2:
                    errors.append("legacy_schema_temporal_quality_unknown")
                temporal_count = 0
                with temporal_path.open("r", encoding="utf-8", errors="strict") as handle:
                    for line in handle:
                        diagnostic = json.loads(line)
                        second = int(datetime.fromisoformat(
                            diagnostic["second_utc"].replace("Z", "+00:00")).timestamp())
                        if second != expected_start + temporal_count:
                            errors.append("temporal_diagnostics_order_mismatch")
                        quality_valid += int(diagnostic.get("quality_valid") == 1)
                        temporal_valid += int(diagnostic.get("temporal_valid") == 1)
                        temporal_count += 1
                if temporal_count != count:
                    errors.append("temporal_diagnostics_row_count_mismatch")
            else:
                # Old captures did not record monotonic receipt/event-clock diagnostics.
                quality_valid = 0
                if schema_version < 2:
                    errors.append("legacy_schema_temporal_quality_unknown")
            structural = (
                count == UTC_DAY_SECONDS and first_second == expected_start
                and last_second == expected_start + UTC_DAY_SECONDS - 1
                and record.get("complete_utc_day") is True
            )
            if (first_second != record.get("first_second_epoch")
                    or last_second != record.get("last_second_epoch")):
                errors.append("daily_csv_manifest_boundary_mismatch")
            if schema_version >= 2 and quality_valid != int(record.get("quality_valid_rows", -1)):
                errors.append("daily_quality_count_mismatch")
        except (OSError, UnicodeError, csv.Error, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"daily_audit_error:{type(exc).__name__}:{str(exc)[:120]}")
            structural = False
        return {
            "day_index": day_index,
            "date_utc": day,
            "rows": count,
            "valid_rows": quality_valid if int(record.get("schema_version", 1)) >= 2 else valid,
            "legacy_sample_valid_rows": valid,
            "quality_valid_rows": quality_valid,
            "temporal_valid_rows": temporal_valid,
            "structural_complete": structural,
            "integrity_errors": sorted(set(errors)),
            "csv_sha256": record.get("csv_sha256"),
            "temporal_diagnostics_sha256": record.get("temporal_diagnostics_sha256"),
        }

    def _refresh_source_quality_report(self) -> dict[str, Any]:
        if self.source_quality_status in {"failed", "review_required", "qualified"}:
            return self.source_quality_report
        audits = []
        for day_index in range(SOURCE_QUALITY_WINDOW_DAYS):
            day_start = self.start_epoch + day_index * UTC_DAY_SECONDS
            day = self.date_for(day_start)
            record = self.manifested.get(day)
            if record is not None:
                audits.append(self._audit_quality_day(day_index, day, record))
        final_day_start = self.start_epoch + (SOURCE_QUALITY_WINDOW_DAYS - 1) * UTC_DAY_SECONDS
        final_day_record = self.manifested.get(self.date_for(final_day_start))
        window_closed = bool(
            time.time() >= self.start_epoch + SOURCE_QUALITY_WINDOW_DAYS * UTC_DAY_SECONDS
            or (
                final_day_record
                and final_day_record.get("complete_utc_day") is True
                and int(final_day_record.get("last_second_epoch", -1)) >= final_day_start + UTC_DAY_SECONDS - 1
            )
        )
        report = evaluate_first_14_day_quality(
            audits,
            start_epoch=self.start_epoch,
            window_closed=window_closed,
        )
        report["gate_version"] = 1
        if report["status"] in {"qualified", "failed", "review_required"}:
            report["decision_persisted_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        report["daily_audits"] = audits
        report["manifest_sha256"] = sha256_file(self.manifest_path) if self.manifest_path.exists() else None
        self._append_quality_report(report)
        return report

    def _last_manifest_second(self) -> int:
        if not self.manifested:
            return self.start_epoch - 1
        record = next(reversed(self.manifested.values()))
        return int(record["last_second_epoch"])

    def _restore_unmanifested_day(self) -> None:
        unmanifested = []
        for path in self.data_dir.glob("bookticker_usdm_btcusdt_*.csv"):
            day = path.stem.rsplit("_", 1)[-1]
            if day not in self.manifested:
                unmanifested.append((day, path))
        if len(unmanifested) > 1:
            raise RuntimeError("multiple_unmanifested_daily_files")
        if not unmanifested:
            return
        day, path = unmanifested[0]
        if self.manifested and day < max(self.manifested):
            raise RuntimeError("unmanifested_file_precedes_manifest_tail")
        count = 0
        valid = 0
        quality_valid = 0
        temporal_valid = 0
        last_second: int | None = None
        with path.open("r", newline="", encoding="utf-8", errors="strict") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != CSV_FIELDS:
                raise RuntimeError(f"daily_csv_schema_mismatch:{day}")
            for row in reader:
                if None in row or len(row) != len(CSV_FIELDS):
                    raise RuntimeError(f"daily_csv_row_width_mismatch:{day}")
                stamp = datetime.fromisoformat(row["second_utc"].replace("Z", "+00:00"))
                second = int(stamp.timestamp())
                if self.date_for(second) != day or (last_second is not None and second != last_second + 1):
                    raise RuntimeError(f"daily_csv_order_or_date_mismatch:{day}")
                last_second = second
                count += 1
                valid += int(row["sample_valid"] == "1")
        temporal_path = self.temporal_diagnostics_path(day)
        if temporal_path.exists():
            diagnostic_rows = []
            with temporal_path.open("r", encoding="utf-8", errors="strict") as handle:
                for line in handle:
                    diagnostic_rows.append(json.loads(line))
            if len(diagnostic_rows) > count:
                raise RuntimeError(f"temporal_diagnostics_rows_exceed_csv:{day}")
            for diagnostic in diagnostic_rows:
                quality_valid += int(diagnostic.get("quality_valid") == 1)
                temporal_valid += int(diagnostic.get("temporal_valid") == 1)
            if last_second is not None:
                csv_seconds = list(range(last_second - count + 1, last_second + 1))
                diag_seconds = [int(datetime.fromisoformat(
                    row["second_utc"].replace("Z", "+00:00")).timestamp()) for row in diagnostic_rows]
                if diag_seconds != csv_seconds[:len(diag_seconds)]:
                    raise RuntimeError(f"temporal_diagnostics_order_mismatch:{day}")
                if len(diagnostic_rows) < count:
                    with temporal_path.open("a", encoding="utf-8", newline="") as handle:
                        for second in csv_seconds[len(diagnostic_rows):]:
                            handle.write(json.dumps({
                                "schema_version": 1,
                                "second_utc": datetime.fromtimestamp(second, UTC).isoformat().replace("+00:00", "Z"),
                                "receipt_age_monotonic_ms": "",
                                "receipt_fresh": 0,
                                "clock_probe_fresh": 0,
                                "clock_wall_monotonic_divergence_ms": "",
                                "event_age_ms": "",
                                "transaction_age_ms": "",
                                "event_freshness": "unknown",
                                "temporal_valid": 0,
                                "execution_eligible": 0,
                                "quality_valid": 0,
                                "quality_flags": ["legacy_temporal_diagnostics_unavailable"],
                            }, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")
        else:
            # Preserve legacy CSV bytes; an append-only sidecar records that the
            # old rows have no monotonic receipt or event-clock qualification.
            with temporal_path.open("w", encoding="utf-8", newline="") as handle:
                if last_second is not None:
                    first_second = last_second - count + 1
                    for second in range(first_second, last_second + 1):
                        stamp = datetime.fromtimestamp(second, UTC).isoformat().replace("+00:00", "Z")
                        handle.write(json.dumps({
                            "schema_version": 1,
                            "second_utc": stamp,
                            "receipt_age_monotonic_ms": "",
                            "receipt_fresh": 0,
                            "clock_probe_fresh": 0,
                            "clock_wall_monotonic_divergence_ms": "",
                            "event_age_ms": "",
                            "transaction_age_ms": "",
                            "event_freshness": "unknown",
                            "temporal_valid": 0,
                            "execution_eligible": 0,
                            "quality_valid": 0,
                            "quality_flags": ["legacy_temporal_diagnostics_unavailable"],
                        }, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")
        if last_second is not None:
            self.active_date = day
            self.day_rows = count
            self.day_valid_rows = valid
            self.day_quality_valid_rows = quality_valid
            self.day_temporal_valid_rows = temporal_valid
            self.last_second_epoch = last_second
            self.csv_handle = path.open("a", newline="", encoding="utf-8")
            self.csv_writer = csv.DictWriter(
                self.csv_handle,
                fieldnames=CSV_FIELDS,
                extrasaction="raise",
            )

    def log_event(self, event: str, *, timestamp_ns: int | None = None, **fields: Any) -> None:
        timestamp_ns = time.time_ns() if timestamp_ns is None else timestamp_ns
        day = self.date_for(timestamp_ns // 1_000_000_000)
        payload = {
            "timestamp_utc": datetime.fromtimestamp(timestamp_ns / 1_000_000_000, UTC).isoformat().replace("+00:00", "Z"),
            "event": event,
            **fields,
        }
        path = self.events_path(day)
        with path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")
            handle.flush()

    def append_row(self, row: dict[str, str | int], *, second_epoch: int) -> None:
        day = self.date_for(second_epoch)
        if self.source_quality_status in {"failed", "review_required"}:
            raise SourceQualityGateStop(f"source_quality_gate_{self.source_quality_status}")
        if day in self.manifested:
            raise RuntimeError(f"attempt_to_modify_manifested_day:{day}")
        if self.last_second_epoch >= 0 and second_epoch != self.last_second_epoch + 1:
            raise RuntimeError("sample_seconds_not_contiguous")
        if self.active_date is not None and self.active_date != day:
            self._close_csv()
            self.finalize_day(self.active_date)
            if self.source_quality_status in {"failed", "review_required"}:
                raise SourceQualityGateStop(f"source_quality_gate_{self.source_quality_status}")
        if self.active_date != day:
            self.active_date = day
            self.day_rows = 0
            self.day_valid_rows = 0
            self.day_quality_valid_rows = 0
            self.day_temporal_valid_rows = 0
            path = self.csv_path(day)
            exists = path.exists()
            self.csv_handle = path.open("a", newline="", encoding="utf-8")
            self.csv_writer = csv.DictWriter(self.csv_handle, fieldnames=CSV_FIELDS, extrasaction="raise")
            if not exists or path.stat().st_size == 0:
                self.csv_writer.writeheader()
        assert self.csv_writer is not None and self.csv_handle is not None
        self.csv_writer.writerow({field: row[field] for field in CSV_FIELDS})
        self.csv_handle.flush()
        diagnostic = {
            "schema_version": 1,
            "second_utc": row["second_utc"],
            "receipt_age_monotonic_ms": row.get("receipt_age_monotonic_ms", ""),
            "receipt_fresh": int(row.get("receipt_fresh", 0)),
            "clock_probe_fresh": int(row.get("clock_probe_fresh", 0)),
            "clock_wall_monotonic_divergence_ms": row.get("clock_wall_monotonic_divergence_ms", ""),
            "clock_wall_monotonic_divergence_ms": row.get("clock_wall_monotonic_divergence_ms", ""),
            "event_age_ms": row.get("event_age_ms", ""),
            "transaction_age_ms": row.get("transaction_age_ms", ""),
            "event_freshness": row.get("event_freshness", "unknown"),
            "temporal_valid": int(row.get("temporal_valid", 0)),
            "execution_eligible": int(row.get("execution_eligible", 0)),
            "quality_valid": int(row.get("quality_valid", 0)),
            "quality_flags": json.loads(str(row.get("quality_flags", "[]"))),
        }
        temporal_path = self.temporal_diagnostics_path(day)
        with temporal_path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(json.dumps(diagnostic, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")
            handle.flush()
        self.day_rows += 1
        self.day_valid_rows += int(row["sample_valid"])
        self.day_quality_valid_rows += int(diagnostic["quality_valid"])
        self.day_temporal_valid_rows += int(diagnostic["temporal_valid"])
        self.last_second_epoch = second_epoch

    def _close_csv(self) -> None:
        if self.csv_handle is not None:
            self.csv_handle.flush()
            os.fsync(self.csv_handle.fileno())
            self.csv_handle.close()
            self.csv_handle = None
            self.csv_writer = None

    def finalize_day(self, day: str) -> dict[str, Any] | None:
        if day in self.manifested:
            return self.manifested[day]
        path = self.csv_path(day)
        if not path.exists():
            return None
        self._close_csv()
        events_path = self.events_path(day)
        if not events_path.exists():
            events_path.write_bytes(b"")
        temporal_path = self.temporal_diagnostics_path(day)
        if not temporal_path.exists():
            temporal_path.write_bytes(b"")
        day_start = int(datetime.fromisoformat(day).replace(tzinfo=UTC).timestamp())
        first_second = self._first_second_for_active_file(path)
        complete = (
            self.day_rows == UTC_DAY_SECONDS
            and first_second == day_start
            and self.last_second_epoch == day_start + UTC_DAY_SECONDS - 1
        )
        record: dict[str, Any] = {
            "schema_version": 2,
            "date_utc": day,
            "csv_file": path.name,
            "csv_sha256": sha256_file(path),
            "csv_bytes": path.stat().st_size,
            "events_file": events_path.name,
            "events_sha256": sha256_file(events_path),
            "events_bytes": events_path.stat().st_size,
            "temporal_diagnostics_file": temporal_path.name,
            "temporal_diagnostics_sha256": sha256_file(temporal_path),
            "temporal_diagnostics_bytes": temporal_path.stat().st_size,
            "rows": self.day_rows,
            "valid_rows": self.day_valid_rows,
            "quality_valid_rows": self.day_quality_valid_rows,
            "temporal_valid_rows": self.day_temporal_valid_rows,
            "expected_rows": UTC_DAY_SECONDS,
            "valid_fraction_of_utc_day": self.day_quality_valid_rows / UTC_DAY_SECONDS,
            "complete_utc_day": complete,
            "first_second_epoch": first_second,
            "last_second_epoch": self.last_second_epoch,
            "previous_record_sha256": self.previous_record_hash,
        }
        record_hash = hashlib.sha256(_canonical_json(record)).hexdigest()
        line = {**record, "record_sha256": record_hash}
        with self.manifest_path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(json.dumps(line, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        line["record_sha256"] = record_hash
        self.manifested[day] = line
        self.previous_record_hash = record_hash
        self.active_date = None
        self.day_rows = 0
        self.day_valid_rows = 0
        self.day_quality_valid_rows = 0
        self.day_temporal_valid_rows = 0
        self._refresh_source_quality_report()
        return line

    @staticmethod
    def _first_second_for_active_file(path: Path) -> int:
        with path.open("r", newline="", encoding="utf-8", errors="strict") as handle:
            row = next(csv.DictReader(handle), None)
        if row is None:
            return -1
        return int(datetime.fromisoformat(row["second_utc"].replace("Z", "+00:00")).timestamp())

    def close_without_finalizing(self) -> None:
        self._close_csv()


@dataclass
class SecondCounters:
    messages_received: int = 0
    parse_errors: int = 0
    invalid_bookticker_events: int = 0
    duplicate_update_ids: int = 0
    regression_update_ids: int = 0
    nonconsecutive_update_ids: int = 0
    max_update_id_delta: int = 0
    connection_disruptions: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "messages_received": self.messages_received,
            "parse_errors": self.parse_errors,
            "invalid_bookticker_events": self.invalid_bookticker_events,
            "duplicate_update_ids": self.duplicate_update_ids,
            "regression_update_ids": self.regression_update_ids,
            "nonconsecutive_update_ids": self.nonconsecutive_update_ids,
            "max_update_id_delta": self.max_update_id_delta,
            "connection_disruptions": self.connection_disruptions,
        }


class BookTickerCapture:
    def __init__(self, data_dir: Path, *, start_epoch: int, duration_days: int = MAX_CAPTURE_DAYS):
        if duration_days < 1 or duration_days > MAX_CAPTURE_DAYS:
            raise ValueError(f"duration_days_must_be_1_to_{MAX_CAPTURE_DAYS}")
        if start_epoch % 1 != 0:
            raise ValueError("start_epoch_must_be_an_integer_second")
        self.start_epoch = int(start_epoch)
        self.end_epoch = self.start_epoch + duration_days * 86_400
        self.store = DailyStore(data_dir, start_epoch=self.start_epoch)
        self.process_instance_id = str(uuid.uuid4())
        self.connection_generation = 0
        self.websocket_opened = False
        self.connected = False
        self.quote: BookTicker | None = None
        self.clock_reading: ClockReading | None = None
        self.counters = SecondCounters()
        self.previous_update_id: int | None = None
        self.active_second: int | None = None
        self.stop_reason = ""

    def _new_second(self, second: int) -> None:
        self.active_second = second
        self.counters = SecondCounters()

    def _append_gap(self, second: int, state: str) -> None:
        row = build_sample_row(
            second_epoch=second,
            quote=None,
            counters=SecondCounters().as_dict(),
            connection_state=state,
            connection_generation=self.connection_generation,
            process_instance_id=self.process_instance_id,
            now_utc_ns=second * 1_000_000_000 + 999_999_999,
            clock_reading=None,
        )
        self.store.append_row(row, second_epoch=second)

    def _flush_until(self, current_second: int) -> None:
        # The planned end is exclusive. Once the wall clock passes it, clamp
        # final flushing to Tend instead of treating the clamp as clock rollback.
        target_second = min(current_second, self.end_epoch)
        if self.active_second is None:
            self.active_second = max(self.start_epoch, self.store.last_second_epoch + 1)
        if target_second < self.active_second:
            self.store.log_event(
                "wall_clock_regression",
                observed_second=current_second,
                previous_active_second=self.active_second,
                process_instance_id=self.process_instance_id,
            )
            raise RuntimeError("wall_clock_regressed_during_capture")
        while self.active_second < target_second:
            second = self.active_second
            row = build_sample_row(
                second_epoch=second,
                quote=self.quote,
                counters=self.counters.as_dict(),
                connection_state="connected" if self.connected else "disconnected",
                connection_generation=self.connection_generation,
                process_instance_id=self.process_instance_id,
                now_utc_ns=time.time_ns(),
                clock_reading=self.clock_reading,
                now_monotonic_ns=time.monotonic_ns(),
            )
            self.store.append_row(row, second_epoch=second)
            self._new_second(second + 1)
        if self.active_second < target_second:
            raise RuntimeError("sample_clock_advance_failed")

    async def _clock_probe_loop(self) -> None:
        while not self.stop_reason and time.time() < self.end_epoch:
            start_wall = time.time_ns()
            start_mono = time.monotonic_ns()
            try:
                def fetch() -> bytes:
                    with urlopen(TIME_URL, timeout=5) as response:
                        return response.read(4_096)

                body = await asyncio.to_thread(fetch)
                end_mono = time.monotonic_ns()
                if time.time() >= self.end_epoch:
                    self.stop_reason = "capture_window_expired"
                    return
                self.clock_reading = parse_clock_response(
                    body,
                    request_start_utc_ns=start_wall,
                    request_start_monotonic_ns=start_mono,
                    request_end_monotonic_ns=end_mono,
                )
                self.store.log_event(
                    "clock_probe",
                    server_time_ms=self.clock_reading.server_time_ms,
                    offset_ms=round(self.clock_reading.offset_ms, 3),
                    rtt_ms=round(self.clock_reading.rtt_ms, 3),
                    uncertainty_ms=round(self.clock_reading.uncertainty_ms, 3),
                    qualified=self.clock_reading.qualified,
                    process_instance_id=self.process_instance_id,
                )
            except Exception as exc:  # preserve failures as operational evidence
                self.clock_reading = None
                self.store.log_event(
                    "clock_probe_error",
                    error_type=type(exc).__name__,
                    error=str(exc)[:240],
                    process_instance_id=self.process_instance_id,
                )
            if time.time() < self.end_epoch and not self.stop_reason:
                await asyncio.sleep(30)

    def _on_connection_opened(self) -> bool:
        # Account for seconds spent in the handshake as disconnected before
        # marking the new generation active; never carry a quote across sockets.
        if time.time() >= self.end_epoch:
            self.connected = False
            self.stop_reason = "capture_window_expired"
            return False
        self._flush_until(int(time.time()))
        if time.time() >= self.end_epoch:
            self.connected = False
            self.stop_reason = "capture_window_expired"
            return False
        self.quote = None
        self.connected = True
        return True

    def _on_message(self, message: str | bytes) -> bool:
        received_utc_ns = time.time_ns()
        received_mono_ns = time.monotonic_ns()
        received_second = received_utc_ns // 1_000_000_000
        if received_second >= self.end_epoch:
            self.connected = False
            self.stop_reason = "capture_window_expired"
            return False
        self._flush_until(received_second)
        self.counters.messages_received += 1
        try:
            quote = parse_bookticker(
                message,
                received_utc_ns=received_utc_ns,
                received_monotonic_ns=received_mono_ns,
            )
        except BookTickerParseError as exc:
            self.counters.parse_errors += 1
            self.counters.invalid_bookticker_events += 1
            self.store.log_event(
                "bookticker_parse_error",
                error=str(exc),
                process_instance_id=self.process_instance_id,
            )
            return True
        if self.previous_update_id is not None:
            delta = quote.update_id - self.previous_update_id
            if delta == 0:
                self.counters.duplicate_update_ids += 1
            elif delta < 0:
                self.counters.regression_update_ids += 1
            elif delta > 1:
                # Nonconsecutive IDs are recorded, not assumed to prove packet loss.
                self.counters.nonconsecutive_update_ids += 1
                self.counters.max_update_id_delta = max(self.counters.max_update_id_delta, delta)
        self.previous_update_id = quote.update_id
        self.quote = quote
        return True

    async def _wait_until_start(self) -> None:
        while time.time() < self.start_epoch:
            await asyncio.sleep(min(MAX_START_WAIT_SLEEP_S, self.start_epoch - time.time()))

    async def _pause_with_sampling(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and time.time() < self.end_epoch and not self.stop_reason:
            now = time.time()
            self._flush_until(int(now))
            next_boundary = math.floor(now) + 1
            await asyncio.sleep(min(max(0.01, next_boundary - now), deadline - time.monotonic()))

    async def _read_connection(self, websocket: Any) -> str:
        connected_at = time.monotonic()
        while time.time() < self.end_epoch:
            now = time.time()
            self._flush_until(int(now))
            if time.monotonic() - connected_at >= ROTATE_CONNECTION_AFTER_S:
                return "scheduled_24h_rotation"
            timeout = max(0.01, min(math.floor(now) + 1 - now, self.end_epoch - now))
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=timeout)
            except asyncio.TimeoutError:
                continue
            if time.time() >= self.end_epoch:
                return "capture_window_expired"
            self._on_message(message)
        return "capture_window_expired"

    async def run(self) -> dict[str, Any]:
        if self.store.source_quality_status in {"failed", "review_required"}:
            return {
                "reason": f"source_quality_gate_{self.store.source_quality_status}",
                "source_quality": self.store.source_quality_report,
                "data_dir": str(self.store.data_dir),
                "websocket_opened": False,
            }
        if self.store.last_second_epoch >= self.end_epoch - 1:
            if self.store.active_date:
                self.store.finalize_day(self.store.active_date)
            return {
                "reason": "capture_window_already_complete",
                "data_dir": str(self.store.data_dir),
                "manifest_sha256": sha256_file(self.store.manifest_path) if self.store.manifest_path.exists() else None,
                "websocket_opened": False,
            }
        await self._wait_until_start()
        now_second = int(time.time())
        if now_second >= self.end_epoch:
            self.active_second = max(self.start_epoch, self.store.last_second_epoch + 1)
            if self.active_second < self.end_epoch:
                self.store.log_event(
                    "explicit_gap_fill",
                    first_missing_second=self.active_second,
                    last_missing_second=self.end_epoch - 1,
                    reason="capture_window_elapsed_without_observation",
                    process_instance_id=self.process_instance_id,
                )
                for second in range(self.active_second, self.end_epoch):
                    self._append_gap(second, "process_inactive")
                self.active_second = self.end_epoch
            if self.store.active_date:
                self.store.finalize_day(self.store.active_date)
            return {
                "reason": "capture_window_expired_before_resume",
                "data_dir": str(self.store.data_dir),
                "manifest_sha256": sha256_file(self.store.manifest_path) if self.store.manifest_path.exists() else None,
                "source_quality": self.store.source_quality_report,
                "websocket_opened": False,
            }
        if self.store.last_second_epoch >= now_second:
            raise RuntimeError("local_clock_precedes_last_saved_sample")

        self.active_second = max(self.start_epoch, self.store.last_second_epoch + 1)
        gap_end = min(now_second, self.end_epoch)
        if self.active_second < gap_end:
            self.store.log_event(
                "explicit_gap_fill",
                first_missing_second=self.active_second,
                last_missing_second=gap_end - 1,
                reason="process_not_running_or_capture_started_late",
                process_instance_id=self.process_instance_id,
            )
            for second in range(self.active_second, gap_end):
                self._append_gap(second, "process_inactive")
            self.active_second = gap_end
        self._new_second(max(self.active_second, now_second))
        self.store.log_event(
            "capture_process_started",
            preregistered_start_utc=datetime.fromtimestamp(self.start_epoch, UTC).isoformat().replace("+00:00", "Z"),
            capture_window_end_utc=datetime.fromtimestamp(self.end_epoch, UTC).isoformat().replace("+00:00", "Z"),
            ws_url=WS_URL,
            process_instance_id=self.process_instance_id,
        )
        clock_task = asyncio.create_task(self._clock_probe_loop())
        backoff = 1.0
        try:
            while time.time() < self.end_epoch and not self.stop_reason:
                try:
                    self.connection_generation += 1
                    async with connect(
                        WS_URL,
                        open_timeout=20,
                        ping_interval=20,
                        ping_timeout=30,
                        close_timeout=10,
                        max_queue=2_048,
                        compression=None,
                    ) as websocket:
                        if not self._on_connection_opened():
                            break
                        self.websocket_opened = True
                        self.store.log_event(
                            "connection_opened",
                            generation=self.connection_generation,
                            process_instance_id=self.process_instance_id,
                        )
                        backoff = 1.0
                        rotation = await self._read_connection(websocket)
                        if rotation == "capture_window_expired":
                            self.stop_reason = rotation
                        else:
                            self.connected = False
                            self.counters.connection_disruptions += 1
                            self.store.log_event(
                                "connection_closed",
                                generation=self.connection_generation,
                                reason=rotation,
                                process_instance_id=self.process_instance_id,
                            )
                except (ConnectionClosed, InvalidHandshake, InvalidURI, OSError, TimeoutError, asyncio.TimeoutError) as exc:
                    self.connected = False
                    self.counters.connection_disruptions += 1
                    self.store.log_event(
                        "connection_error",
                        generation=self.connection_generation,
                        error_type=type(exc).__name__,
                        error=str(exc)[:240],
                        retry_after_s=round(backoff, 3),
                        process_instance_id=self.process_instance_id,
                    )
                    await self._pause_with_sampling(backoff)
                    backoff = min(backoff * 2, 60.0)
                if self.stop_reason:
                    break
                if not self.connected and time.time() < self.end_epoch:
                    await self._pause_with_sampling(min(backoff, 1.0))
            self._flush_until(self.end_epoch)
            self.connected = False
            self.store.log_event(
                "capture_window_finished",
                reason=self.stop_reason or "capture_window_expired",
                process_instance_id=self.process_instance_id,
            )
            if self.store.active_date:
                self.store.finalize_day(self.store.active_date)
            return {
                "started_utc": datetime.fromtimestamp(self.start_epoch, UTC).isoformat().replace("+00:00", "Z"),
                "ended_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "reason": self.stop_reason or "capture_window_expired",
                "data_dir": str(self.store.data_dir),
                "manifest_sha256": sha256_file(self.store.manifest_path) if self.store.manifest_path.exists() else None,
                "source_quality": self.store.source_quality_report,
                "websocket_opened": self.websocket_opened,
            }
        except SourceQualityGateStop as exc:
            self.stop_reason = str(exc)
            self.connected = False
            self.store.log_event(
                "source_quality_gate_stopped",
                status=self.store.source_quality_status,
                process_instance_id=self.process_instance_id,
            )
            return {
                "reason": self.stop_reason,
                "data_dir": str(self.store.data_dir),
                "manifest_sha256": sha256_file(self.store.manifest_path) if self.store.manifest_path.exists() else None,
                "source_quality": self.store.source_quality_report,
                "websocket_opened": self.websocket_opened,
            }
        except asyncio.CancelledError:
            self.stop_reason = "process_cancelled"
            self.connected = False
            self.store.log_event("capture_process_cancelled", process_instance_id=self.process_instance_id)
            raise
        finally:
            clock_task.cancel()
            try:
                await clock_task
            except asyncio.CancelledError:
                pass
            self.store.close_without_finalizing()


def parse_utc_second(value: str) -> int:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0) or parsed.microsecond:
        raise ValueError("start_utc_must_be_timezone_aware_utc_whole_second")
    return int(parsed.timestamp())


async def _async_main(args: argparse.Namespace) -> int:
    if args.preflight:
        start_wall = time.time_ns()
        start_mono = time.monotonic_ns()
        try:
            def fetch() -> bytes:
                with urlopen(TIME_URL, timeout=5) as response:
                    return response.read(4_096)

            body = await asyncio.to_thread(fetch)
            reading = parse_clock_response(
                body,
                request_start_utc_ns=start_wall,
                request_start_monotonic_ns=start_mono,
                request_end_monotonic_ns=time.monotonic_ns(),
            )
            print(json.dumps({
                "ws_url": WS_URL,
                "time_url": TIME_URL,
                "server_time_ms": reading.server_time_ms,
                "offset_ms": round(reading.offset_ms, 3),
                "rtt_ms": round(reading.rtt_ms, 3),
                "uncertainty_ms": round(reading.uncertainty_ms, 3),
                "clock_qualified": reading.qualified,
                "capture_window_days_max": MAX_CAPTURE_DAYS,
                "live_orders_supported": False,
            }, sort_keys=True, indent=2))
            return 0 if reading.qualified else 2
        except Exception as exc:
            print(json.dumps({"clock_probe_error": type(exc).__name__, "message": str(exc)[:240]}))
            return 3

    start_epoch = parse_utc_second(args.start_utc)
    capture = BookTickerCapture(Path(args.data_dir), start_epoch=start_epoch, duration_days=args.duration_days)
    result = await capture.run()
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture public BTCUSDT USD-M bookTicker samples; no trading endpoints.")
    parser.add_argument("--start-utc", help="Frozen UTC start instant (ISO-8601, whole second; required for capture).")
    parser.add_argument("--duration-days", type=int, default=MAX_CAPTURE_DAYS)
    parser.add_argument("--data-dir", default=str(Path(__file__).resolve().parents[2] / "data" / "c20_bookticker"))
    parser.add_argument("--preflight", action="store_true", help="Probe only public Binance server time; don't connect or write files.")
    args = parser.parse_args()
    if not args.preflight and not args.start_utc:
        parser.error("--start-utc is required unless --preflight is used")
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
