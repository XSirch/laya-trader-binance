import asyncio
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
    MAX_START_WAIT_SLEEP_S,
    build_sample_row,
    parse_bookticker,
    parse_clock_response,
    parse_utc_second,
    evaluate_first_14_day_quality,
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
    assert row["receipt_fresh"] == 1
    assert row["event_freshness"] == "unknown"
    assert row["execution_eligible"] == 0
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


def test_recent_receipt_does_not_make_a_stale_event_execution_eligible():
    now_utc_ns = 1_798_000_001_000_000_000
    now_monotonic_ns = 10_000_000_000
    payload = dict(OFFICIAL_BOOK_TICKER)
    payload["E"] = now_utc_ns // 1_000_000 - 60_000
    payload["T"] = now_utc_ns // 1_000_000 - 60_001
    quote = parse_bookticker(
        json.dumps(payload),
        received_utc_ns=now_utc_ns - 100_000_000,
        received_monotonic_ns=now_monotonic_ns - 100_000_000,
    )
    reading = ClockReading(
        server_time_ms=now_utc_ns // 1_000_000,
        offset_ms=0,
        rtt_ms=2,
        uncertainty_ms=2,
        measured_utc_ns=now_utc_ns - 100_000_000,
        qualified=True,
        measured_monotonic_ns=now_monotonic_ns - 100_000_000,
    )

    row = build_sample_row(
        second_epoch=now_utc_ns // 1_000_000_000 - 1,
        quote=quote,
        counters={},
        connection_state="connected",
        connection_generation=1,
        process_instance_id="production-module-test",
        now_utc_ns=now_utc_ns,
        now_monotonic_ns=now_monotonic_ns,
        clock_reading=reading,
    )

    assert row["quote_age_ms"] == "100.000"
    assert row["sample_valid"] == 1  # content/receipt gate remains separate
    assert row["event_freshness"] == "stale"
    assert float(row["event_age_ms"]) >= 60_000
    assert float(row["transaction_age_ms"]) >= 60_001
    assert row["temporal_valid"] == 0
    assert row["execution_eligible"] == 0
    assert row["quality_valid"] == 0


def test_recent_event_passes_only_when_clock_uncertainty_stays_within_five_seconds():
    now_utc_ns = 1_798_000_001_000_000_000
    now_monotonic_ns = 10_000_000_000
    payload = dict(OFFICIAL_BOOK_TICKER)
    payload["E"] = now_utc_ns // 1_000_000 - 4_000
    payload["T"] = now_utc_ns // 1_000_000 - 4_500
    quote = parse_bookticker(
        json.dumps(payload),
        received_utc_ns=now_utc_ns - 100_000_000,
        received_monotonic_ns=now_monotonic_ns - 100_000_000,
    )
    reading = ClockReading(
        server_time_ms=now_utc_ns // 1_000_000,
        offset_ms=0,
        rtt_ms=2,
        uncertainty_ms=2,
        measured_utc_ns=now_utc_ns - 100_000_000,
        qualified=True,
        measured_monotonic_ns=now_monotonic_ns - 100_000_000,
    )
    row = build_sample_row(
        second_epoch=now_utc_ns // 1_000_000_000 - 1,
        quote=quote,
        counters={},
        connection_state="connected",
        connection_generation=1,
        process_instance_id="production-module-test",
        now_utc_ns=now_utc_ns,
        now_monotonic_ns=now_monotonic_ns,
        clock_reading=reading,
    )
    assert row["event_freshness"] == "fresh"
    assert row["temporal_valid"] == 1
    assert row["execution_eligible"] == 1


@pytest.mark.parametrize(
    ("age_ms", "uncertainty_ms", "expected"),
    [(4_999, 1, "fresh"), (5_000, 2, "unknown"), (5_003, 2, "stale")],
)
def test_event_freshness_five_second_boundary_and_uncertainty(age_ms, uncertainty_ms, expected):
    now_utc_ns = 1_798_000_001_000_000_000
    now_monotonic_ns = 10_000_000_000
    payload = dict(OFFICIAL_BOOK_TICKER)
    payload["E"] = now_utc_ns // 1_000_000 - age_ms
    payload["T"] = now_utc_ns // 1_000_000 - age_ms
    quote = parse_bookticker(
        json.dumps(payload),
        received_utc_ns=now_utc_ns - 100_000_000,
        received_monotonic_ns=now_monotonic_ns - 100_000_000,
    )
    reading = ClockReading(
        server_time_ms=now_utc_ns // 1_000_000,
        offset_ms=0,
        rtt_ms=2,
        uncertainty_ms=uncertainty_ms,
        measured_utc_ns=now_utc_ns - 100_000_000,
        qualified=True,
        measured_monotonic_ns=now_monotonic_ns - 100_000_000,
    )

    row = build_sample_row(
        second_epoch=now_utc_ns // 1_000_000_000 - 1,
        quote=quote,
        counters={},
        connection_state="connected",
        connection_generation=1,
        process_instance_id="production-module-test",
        now_utc_ns=now_utc_ns,
        now_monotonic_ns=now_monotonic_ns,
        clock_reading=reading,
    )

    assert row["event_freshness"] == expected
    assert row["temporal_valid"] == int(expected == "fresh")


def test_first_14_day_gate_uses_fixed_window_and_99_percent_threshold():
    start = int(datetime(2026, 9, 30, tzinfo=UTC).timestamp())
    # 99 of 100 valid observations is exactly the threshold. Later days do not
    # replace the fixed first-14-day qualification window.
    audits = [
        {"day_index": day, "rows": 100, "valid_rows": 99, "structural_complete": True,
         "integrity_errors": []}
        for day in range(14)
    ]
    audits[13]["valid_rows"] = 98
    audits.extend(
        {"day_index": day, "rows": 100, "valid_rows": 100, "structural_complete": True,
         "integrity_errors": []}
        for day in range(14, 18)
    )

    report = evaluate_first_14_day_quality(
        audits,
        start_epoch=start,
        seconds_per_day=100,
        minimum_valid_fraction=0.99,
    )

    assert report["status"] == "qualified"
    assert report["days_in_window"] == 14
    assert report["qualified_days"] == 13
    assert report["threshold_valid_rows_per_day"] == 99
    assert report["decision_window_end_epoch"] == start + 14 * 100


def test_first_14_day_gate_fails_at_twelve_days_and_requires_review_for_integrity_defects():
    start = int(datetime(2026, 9, 30, tzinfo=UTC).timestamp())
    audits = [
        {"day_index": day, "rows": 100, "valid_rows": 99, "structural_complete": True,
         "integrity_errors": []}
        for day in range(14)
    ]
    audits[13]["valid_rows"] = 98
    audits[12]["valid_rows"] = 98
    failed = evaluate_first_14_day_quality(
        audits, start_epoch=start, seconds_per_day=100, minimum_valid_fraction=0.99,
    )
    assert failed["status"] == "failed"
    assert failed["qualified_days"] == 12

    audits[0]["integrity_errors"] = ["daily_csv_order_or_date_mismatch"]
    review = evaluate_first_14_day_quality(
        audits, start_epoch=start, seconds_per_day=100, minimum_valid_fraction=0.99,
    )
    assert review["status"] == "review_required"
    assert "daily_csv_order_or_date_mismatch" in review["integrity_errors"]


def test_failed_quality_decision_survives_restart_and_prevents_capture(tmp_path: Path, monkeypatch):
    start = int(datetime(2026, 9, 30, tzinfo=UTC).timestamp())
    store = DailyStore(tmp_path, start_epoch=start)
    audits = [
        {"day_index": day, "rows": 100, "valid_rows": 99, "structural_complete": True,
         "integrity_errors": []}
        for day in range(14)
    ]
    audits[12]["valid_rows"] = 98
    audits[13]["valid_rows"] = 98
    failed = evaluate_first_14_day_quality(
        audits, start_epoch=start, seconds_per_day=100, minimum_valid_fraction=0.99,
    )
    store._append_quality_report(failed)

    resumed = BookTickerCapture(tmp_path, start_epoch=start, duration_days=112)
    monkeypatch.setattr(
        "binance_multistrategy.c20_capture.connect",
        lambda *args, **kwargs: pytest.fail("quality failure must stop before websocket connection"),
    )
    result = asyncio.run(resumed.run())

    assert resumed.store.source_quality_status == "failed"
    assert result["reason"] == "source_quality_gate_failed"
    assert result["websocket_opened"] is False


def test_handshake_and_receive_crossing_exclusive_end_stop_without_accepting_a_message(tmp_path: Path, monkeypatch):
    start = int(datetime(2026, 9, 30, tzinfo=UTC).timestamp())
    capture = BookTickerCapture(tmp_path, start_epoch=start, duration_days=1)
    capture.active_second = capture.end_epoch - 1
    capture.store.last_second_epoch = capture.end_epoch - 2
    monkeypatch.setattr("binance_multistrategy.c20_capture.time.time", lambda: capture.end_epoch)
    assert capture._on_connection_opened() is False
    assert capture.connected is False

    capture.stop_reason = ""
    capture.connected = True
    times = iter((capture.end_epoch - 0.2, capture.end_epoch - 0.2, capture.end_epoch + 0.1))
    monkeypatch.setattr("binance_multistrategy.c20_capture.time.time", lambda: next(times))
    monkeypatch.setattr("binance_multistrategy.c20_capture.time.monotonic", lambda: 1.0)

    class FakeWebSocket:
        async def recv(self):
            return "message_received_after_Tend"

    async def immediate_wait_for(awaitable, timeout):
        return await awaitable

    monkeypatch.setattr("binance_multistrategy.c20_capture.asyncio.wait_for", immediate_wait_for)
    result = asyncio.run(capture._read_connection(FakeWebSocket()))

    assert result == "capture_window_expired"
    assert capture.counters.messages_received == 0
    assert capture.quote is None
    capture.store.close_without_finalizing()


def test_resume_after_exclusive_end_does_not_open_a_websocket(tmp_path: Path, monkeypatch):
    start = int(datetime(2026, 9, 30, tzinfo=UTC).timestamp())
    capture = BookTickerCapture(tmp_path, start_epoch=start, duration_days=1)
    capture.store.last_second_epoch = capture.end_epoch - 1
    monkeypatch.setattr("binance_multistrategy.c20_capture.time.time", lambda: capture.end_epoch + 1)
    monkeypatch.setattr(
        "binance_multistrategy.c20_capture.connect",
        lambda *args, **kwargs: pytest.fail("resume after Tend must not connect"),
    )

    result = asyncio.run(capture.run())

    assert result["reason"] == "capture_window_already_complete"
    assert result["websocket_opened"] is False


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
    assert store.finalize_day("2026-09-29") == record

    reopened = DailyStore(tmp_path, start_epoch=start)
    assert reopened.last_second_epoch == start
    with reopened.csv_path("2026-09-29").open("a", encoding="utf-8") as handle:
        handle.write("tamper\n")
    with pytest.raises(RuntimeError, match="daily_csv_hash_mismatch"):
        DailyStore(tmp_path, start_epoch=start)
    review = json.loads((tmp_path / "source_quality_report.json").read_text(encoding="utf-8"))
    assert review["status"] == "review_required"
    assert "daily_csv_hash_mismatch" in review["integrity_errors"][0]


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


def test_wait_until_start_uses_bounded_low_frequency_sleep(tmp_path: Path, monkeypatch):
    start = 1_798_000_000
    capture = BookTickerCapture(tmp_path, start_epoch=start, duration_days=1)
    now = [float(start - 95)]
    delays = []

    async def fake_sleep(delay):
        delays.append(delay)
        now[0] += delay

    monkeypatch.setattr("binance_multistrategy.c20_capture.time.time", lambda: now[0])
    monkeypatch.setattr("binance_multistrategy.c20_capture.asyncio.sleep", fake_sleep)
    asyncio.run(capture._wait_until_start())

    assert MAX_START_WAIT_SLEEP_S == 30
    assert delays == [30, 30, 30, 5]
    assert now[0] == start


def test_real_capture_flush_respects_exclusive_end_and_is_idempotent(tmp_path: Path):
    start = int(datetime(2026, 9, 30, tzinfo=UTC).timestamp())
    capture = BookTickerCapture(tmp_path, start_epoch=start, duration_days=1)
    capture.store.last_second_epoch = capture.end_epoch - 2
    capture.active_second = capture.end_epoch - 1
    capture._new_second(capture.end_epoch - 1)

    capture._flush_until(capture.end_epoch + 2)
    capture._flush_until(capture.end_epoch)

    assert capture.store.last_second_epoch == capture.end_epoch - 1
    assert capture.active_second == capture.end_epoch
    capture.store.close_without_finalizing()
    with capture.store.csv_path("2026-09-30").open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert int(datetime.fromisoformat(rows[0]["second_utc"].replace("Z", "+00:00")).timestamp()) == capture.end_epoch - 1
