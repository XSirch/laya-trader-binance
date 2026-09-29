import csv
from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path

import pytest

from binance_multistrategy.c20_capture import (
    BookTickerParseError,
    BookTickerCapture,
    ClockReading,
    DailyStore,
    build_sample_row,
    parse_bookticker,
    parse_clock_response,
    parse_utc_second,
)


OFFICIAL_BOOK_TICKER = {
    "e": "bookTicker",
    "u": 400900217,
    "E": 1568014460893,
    "T": 1568014460891,
    "s": "BTCUSDT",
    "ps": "BTCUSDT",
    "b": "25.35190000",
    "B": "31.21000000",
    "a": "25.36520000",
    "A": "40.66000000",
    "st": 1,
}


def quote_from(payload=OFFICIAL_BOOK_TICKER, received_utc_ns=1_798_000_000_000_000_000):
    return parse_bookticker(
        json.dumps(payload),
        received_utc_ns=received_utc_ns,
        received_monotonic_ns=9_000_000_000,
    )


def test_parser_preserves_official_fields_and_decimals():
    quote = quote_from()
    assert quote.update_id == 400900217
    assert quote.event_time_ms == 1568014460893
    assert quote.transaction_time_ms == 1568014460891
    assert str(quote.bid) == "25.35190000"
    assert str(quote.ask_qty) == "40.66000000"


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("s", "ETHUSDT", "unexpected_symbol"),
        ("ps", None, "unexpected_pair"),
        ("st", 2, "unexpected_symbol_type"),
        ("st", 1.0, "unexpected_symbol_type"),
        ("a", "25.30000000", "crossed_quote"),
        ("B", "-1", "B_out_of_range"),
        ("u", True, "u_not_nonnegative_integer"),
    ],
)
def test_parser_rejects_bad_symbol_type_or_quote(field, value, error):
    payload = dict(OFFICIAL_BOOK_TICKER)
    payload[field] = value
    with pytest.raises(BookTickerParseError, match=error):
        quote_from(payload)


def test_parser_rejects_bad_json_and_non_object_payload():
    for body, expected in ((b"{", "invalid_json_or_utf8"), ("[]", "payload_not_object")):
        with pytest.raises(BookTickerParseError, match=expected):
            parse_bookticker(body, received_utc_ns=1, received_monotonic_ns=1)


def test_clock_qualification_includes_round_trip_uncertainty():
    body = json.dumps({"serverTime": 1_000_000}).encode()
    reading = parse_clock_response(
        body,
        request_start_utc_ns=1_000_030_000_000,
        request_start_monotonic_ns=100,
        request_end_monotonic_ns=80_000_100,
    )
    assert reading.rtt_ms == pytest.approx(80)
    assert reading.uncertainty_ms == pytest.approx(41)
    assert reading.offset_ms == pytest.approx(-70)
    assert not reading.qualified


def test_sample_requires_fresh_connected_quote_and_keeps_clock_gate_separate():
    quote = quote_from(received_utc_ns=1_798_000_000_000_000_000)
    reading = ClockReading(
        server_time_ms=1,
        offset_ms=150,
        rtt_ms=10,
        uncertainty_ms=6,
        measured_utc_ns=quote.received_utc_ns,
        qualified=False,
    )
    row = build_sample_row(
        second_epoch=1_798_000_000,
        quote=quote,
        counters={},
        connection_state="connected",
        connection_generation=1,
        process_instance_id="process-test",
        now_utc_ns=quote.received_utc_ns + 1_000_000_000,
        clock_reading=reading,
    )
    assert row["sample_valid"] == 1
    assert row["clock_qualified"] == 0
    assert Decimal(row["mid"]) == Decimal("25.35855000")


def test_stale_or_unconnected_quote_is_not_a_valid_sample():
    quote = quote_from(received_utc_ns=1_798_000_000_000_000_000)
    base = dict(
        second_epoch=1_798_000_000,
        quote=quote,
        counters={},
        connection_generation=1,
        process_instance_id="process-test",
        now_utc_ns=quote.received_utc_ns + 6_000_000_000,
        clock_reading=None,
    )
    assert build_sample_row(**base, connection_state="connected")["sample_valid"] == 0
    fresh = dict(base, now_utc_ns=quote.received_utc_ns + 1_000_000_000)
    assert build_sample_row(**fresh, connection_state="disconnected")["sample_valid"] == 0


def test_gap_row_stays_empty_instead_of_carrying_a_quote():
    row = build_sample_row(
        second_epoch=1_798_000_000,
        quote=None,
        counters={},
        connection_state="process_inactive",
        connection_generation=0,
        process_instance_id="process-test",
        now_utc_ns=1_798_000_001_000_000_000,
        clock_reading=None,
    )
    assert row["bid"] == ""
    assert row["sample_valid"] == 0
    assert row["connection_state"] == "process_inactive"


def test_daily_manifest_records_hash_and_detects_tampering(tmp_path: Path):
    start = int(datetime(2026, 9, 29, tzinfo=UTC).timestamp())
    store = DailyStore(tmp_path, start_epoch=start)
    row = build_sample_row(
        second_epoch=start,
        quote=None,
        counters={},
        connection_state="process_inactive",
        connection_generation=0,
        process_instance_id="process-test",
        now_utc_ns=(start + 1) * 1_000_000_000,
        clock_reading=None,
    )
    store.append_row(row, second_epoch=start)
    record = store.finalize_day("2026-09-29")
    assert record is not None
    assert record["rows"] == 1
    assert record["complete_utc_day"] is False

    reopened = DailyStore(tmp_path, start_epoch=start)
    assert reopened.last_second_epoch == start
    with reopened.csv_path("2026-09-29").open("a", encoding="utf-8") as handle:
        handle.write("tamper\n")
    with pytest.raises(RuntimeError, match="daily_csv_hash_mismatch"):
        DailyStore(tmp_path, start_epoch=start)


def test_daily_store_reopens_unmanifested_csv_for_resume(tmp_path: Path):
    start = int(datetime(2026, 9, 29, tzinfo=UTC).timestamp())
    store = DailyStore(tmp_path, start_epoch=start)
    for second in (start, start + 1):
        row = build_sample_row(
            second_epoch=second,
            quote=None,
            counters={},
            connection_state="process_inactive",
            connection_generation=0,
            process_instance_id="process-test",
            now_utc_ns=(second + 1) * 1_000_000_000,
            clock_reading=None,
        )
        store.append_row(row, second_epoch=second)
    store.close_without_finalizing()

    resumed = DailyStore(tmp_path, start_epoch=start)
    row = build_sample_row(
        second_epoch=start + 2,
        quote=None,
        counters={},
        connection_state="process_inactive",
        connection_generation=0,
        process_instance_id="process-test",
        now_utc_ns=(start + 3) * 1_000_000_000,
        clock_reading=None,
    )
    resumed.append_row(row, second_epoch=start + 2)
    record = resumed.finalize_day("2026-09-29")
    assert record is not None
    assert record["rows"] == 3


def test_reconnect_flushes_handshake_as_disconnected_and_drops_old_quote(tmp_path: Path, monkeypatch):
    start = int(datetime(2026, 9, 29, tzinfo=UTC).timestamp())
    capture = BookTickerCapture(tmp_path, start_epoch=start, duration_days=1)
    capture.quote = quote_from(received_utc_ns=start * 1_000_000_000)
    monkeypatch.setattr("binance_multistrategy.c20_capture.time.time", lambda: start + 2.25)

    capture._on_connection_opened()

    assert capture.connected is True
    assert capture.quote is None
    capture.store.close_without_finalizing()
    with capture.store.csv_path("2026-09-29").open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["connection_state"] for row in rows] == ["disconnected", "disconnected"]
    assert all(row["sample_valid"] == "0" for row in rows)


def test_start_must_be_utc_and_whole_second():
    assert parse_utc_second("2026-09-29T00:00:00Z") == int(datetime(2026, 9, 29, tzinfo=UTC).timestamp())
    with pytest.raises(ValueError, match="timezone_aware_utc_whole_second"):
        parse_utc_second("2026-09-29T00:00:00")
    with pytest.raises(ValueError, match="timezone_aware_utc_whole_second"):
        parse_utc_second("2026-09-29T00:00:00.500Z")
