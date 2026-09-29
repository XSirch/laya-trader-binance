"""Isolated review reproductions, not the repository test suite.
Source: c20_capture.py at 43ee00f948b87c0bedd2749b09c9639b3a514bf8.
The two method bodies below were transcribed from the GitHub connector.
Network, store and data objects are synthetic; no collection is started.
"""
from __future__ import annotations
from datetime import UTC, datetime
from decimal import Decimal
import json
import math
from pathlib import Path
from types import SimpleNamespace

MAX_QUOTE_AGE_MS = 5_000
CLOCK_PROBE_MAX_AGE_MS = 60_000
BookTicker = ClockReading = SimpleNamespace

def _decimal_text(value: Decimal) -> str:
    return format(value, "f")

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
    if clock_reading is not None:
        clock_age_ms = (now_utc_ns - clock_reading.measured_utc_ns) / 1_000_000
    else:
        clock_age_ms = math.inf
    clock_is_fresh = clock_age_ms <= CLOCK_PROBE_MAX_AGE_MS
    row["clock_server_time_ms"] = clock_reading.server_time_ms if clock_reading else ""
    row["clock_offset_ms"] = f"{clock_reading.offset_ms:.3f}" if clock_reading else ""
    row["clock_rtt_ms"] = f"{clock_reading.rtt_ms:.3f}" if clock_reading else ""
    row["clock_uncertainty_ms"] = f"{clock_reading.uncertainty_ms:.3f}" if clock_reading else ""
    row["clock_qualified"] = int(bool(clock_reading and clock_is_fresh and clock_reading.qualified))
    quote_fresh = quote is not None and 0 <= age_ms <= MAX_QUOTE_AGE_MS
    valid = (
        connection_state == "connected"
        and quote_fresh
        and int(counters.get("parse_errors", 0)) == 0
        and int(counters.get("duplicate_update_ids", 0)) == 0
        and int(counters.get("regression_update_ids", 0)) == 0
        and int(counters.get("connection_disruptions", 0)) == 0
    )
    row["sample_valid"] = int(valid)
    return row

class SyntheticStore:
    def __init__(self, last_second):
        self.last_second_epoch = last_second
        self.rows = []
        self.events = []
    def append_row(self, row, *, second_epoch):
        self.rows.append((second_epoch, row))
        self.last_second_epoch = second_epoch
    def log_event(self, *args, **kwargs):
        self.events.append((args, kwargs))

class SyntheticCounters:
    def as_dict(self):
        return {}

class IsolatedCapture:
    def _new_second(self, second):
        self.active_second = second
        self.counters = SyntheticCounters()

    # Original _flush_until body from c20_capture.py; helpers above are synthetic.
    def _flush_until(self, current_second: int) -> None:
        if self.active_second is None:
            self.active_second = max(self.start_epoch, self.store.last_second_epoch + 1)
        if current_second < self.active_second:
            self.store.log_event(
                "wall_clock_regression",
                observed_second=current_second,
                previous_active_second=self.active_second,
                process_instance_id=self.process_instance_id,
            )
            raise RuntimeError("wall_clock_regressed_during_capture")
        while self.active_second < current_second:
            second = self.active_second
            row = build_sample_row(
                second_epoch=second,
                quote=self.quote,
                counters=self.counters.as_dict(),
                connection_state="connected" if self.connected else "disconnected",
                connection_generation=self.connection_generation,
                process_instance_id=self.process_instance_id,
                now_utc_ns=(second + 1) * 1_000_000_000,
                clock_reading=self.clock_reading,
            )
            self.store.append_row(row, second_epoch=second)
            self._new_second(second + 1)
        if self.active_second < current_second:
            raise RuntimeError("sample_clock_advance_failed")

now_ns = 1_798_000_001_000_000_000
quote = SimpleNamespace(
    update_id=42, event_time_ms=now_ns//1_000_000-60_000,
    transaction_time_ms=now_ns//1_000_000-60_001,
    bid=Decimal('100'), ask=Decimal('101'), bid_qty=Decimal('1'), ask_qty=Decimal('1'),
    received_utc_ns=now_ns-100_000_000, received_monotonic_ns=5_000_000_000,
)
clock = SimpleNamespace(server_time_ms=now_ns//1_000_000, offset_ms=0.,rtt_ms=2.,uncertainty_ms=2.,
                        measured_utc_ns=now_ns-100_000_000,qualified=True)
row = build_sample_row(second_epoch=now_ns//1_000_000_000-1,quote=quote,counters={},
    connection_state='connected',connection_generation=1,process_instance_id='isolated-test',
    now_utc_ns=now_ns,clock_reading=clock)
assert row['sample_valid'] == 1 and row['clock_qualified'] == 1

cap=IsolatedCapture()
cap.start_epoch=1_798_000_000
cap.end_epoch=cap.start_epoch+86_400
cap.store=SyntheticStore(cap.end_epoch-2)
cap.active_second=cap.end_epoch-1
cap.counters=SyntheticCounters()
cap.quote=None
cap.clock_reading=None
cap.connected=False
cap.connection_generation=1
cap.process_instance_id='isolated-test'
cap._flush_until(cap.end_epoch+2)
outside=[sec for sec,_ in cap.store.rows if sec>=cap.end_epoch]
try:
    cap._flush_until(cap.end_epoch)
except RuntimeError as exc:
    end_error=str(exc)
else:
    end_error=None
assert len(outside) == 2 and end_error == 'wall_clock_regressed_during_capture'
result={
    'commit':'43ee00f948b87c0bedd2749b09c9639b3a514bf8',
    'scope':'isolated transcribed methods with synthetic inputs, not full module or repository suite',
    'live_network_or_orders':False,
    'delayed_event':{'event_age_ms':60_000,'receipt_age_ms':row['quote_age_ms'],
                     'clock_qualified':row['clock_qualified'],'sample_valid':row['sample_valid']},
    'end_of_window':{'samples_after_exclusive_end':len(outside),'final_flush_error':end_error},
}
print(json.dumps(result,indent=2))
Path(__file__).with_name('isolated_review_results.json').write_text(json.dumps(result,indent=2)+'\n')
