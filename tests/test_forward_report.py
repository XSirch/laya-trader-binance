"""Synthetic fixtures only: these tests do not supply market-performance evidence."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jev_trader.binance_data import HOUR_MS, utc_ms
from jev_trader.forward_observer import ZERO, digest, read_chain
from jev_trader.forward_paper import next_weekly_entry, schedule
from jev_trader.forward_portfolio import advance, initialize
from jev_trader.forward_report import BASE_CODE, SIGNAL_CODE, FREEZE_FILE, audit_records, report


INITIAL = utc_ms("2026-09-26")
ENTRY = utc_ms("2026-09-28") + HOUR_MS
DUMMY_SHA = "a" * 64


def seal(value, key):
    value[key] = digest({k: v for k, v in value.items() if k != key})


def reseal(records, signals):
    previous = ZERO
    for record, signal in zip(records, signals):
        seal(signal["market_observation"], "record_sha256")
        seal(signal, "snapshot_sha256")
        record["signal_snapshot_sha256"] = signal["snapshot_sha256"]
        record["previous_sha256"] = previous
        seal(record, "record_sha256")
        previous = record["record_sha256"]


class SyntheticSeries:
    def __init__(self):
        self.records, self.signals = [], []
        self.config = {"activated_ms": INITIAL, "first_entry_ms": next_weekly_entry(INITIAL),
                       "rule": "synthetic_fixed_rule", "freeze_sha256": DUMMY_SHA,
                       "code_sha256": {name: DUMMY_SHA for name in BASE_CODE | SIGNAL_CODE},
                       "initial_paper_usdt_per_account": 10_000,
                       "variants": {"reference": None, "trailing4": .04},
                       "execution_window": "synthetic fixture", "orders_enabled": False}
        self.add(INITIAL)

    def add(self, now, price=100, funding=None, reconciled=True, quotes=True):
        accepted = ({"SYNTH": {"bidPrice": price, "askPrice": price,
                                "bidQty": 10000, "askQty": 10000,
                                "quote_time_ms": now - 10, "age_ms": 10}} if quotes else {})
        market = {"server_time_ms": now, "previous_sha256": ZERO, "status": "market_observation_only",
                  "orders_sent": 0, "paper_positions": None, "paper_equity": None,
                  "accepted_quotes": accepted, "sources": [],
                  "source_code_sha256": {"forward_observer.py": DUMMY_SHA}}
        signal = {"server_time_ms": now, "market_observation": market,
                  "fixed_rule": self.config["rule"], "freeze_sha256": self.config["freeze_sha256"],
                  "status": "signal_preview_only", "orders_sent": 0, "jev_calls": 0,
                  "funding_boundary_reconciled": reconciled, "funding": funding or [],
                  "source_code_sha256": {name: DUMMY_SHA for name in SIGNAL_CODE},
                  "target_weights": {"SYNTH": .5}, "sources": []}
        status, error, last_hour = "initialized_flat", None, None
        if not self.records:
            accounts = {name: initialize(now, 10000, distance) for name, distance in self.config["variants"].items()}
        else:
            prior = self.records[-1]
            accounts, last_hour = deepcopy(prior["accounts"]), prior["last_processed_hour_ms"]
            timing = schedule(now, self.config["first_entry_ms"], last_hour)
            status = "outside_scheduled_window"
            if timing["due"]:
                status = "processed_hour"
                if not reconciled:
                    status, error = "blocked_accounting", "funding boundary not reconciled"
                else:
                    tick = {"server_time_ms": now, "accepted_quotes": accepted, "funding": funding or []}
                    try:
                        changed = {name: advance(account, tick, signal["target_weights"] if timing["rebalance"] else None)
                                   for name, account in accounts.items()}
                    except ValueError as exc:
                        status, error = "blocked_accounting", str(exc)
                    else:
                        accounts, last_hour = changed, timing["hour_ms"]
        self.records.append({"server_time_ms": now, "config": deepcopy(self.config), "accounts": accounts,
                             "status": status, "error": error, "last_processed_hour_ms": last_hour,
                             "orders_sent": 0, "continuous_service_running": False,
                             "signal_file": str(now) + "-signal.json", "signal_file_sha256": DUMMY_SHA})
        self.signals.append(signal)
        reseal(self.records, self.signals)

    def write(self, root):
        results = root / "results"
        series = results / "synthetic_series"
        series.mkdir(parents=True)
        code = root / "src/jev_trader"
        code.mkdir(parents=True)
        for name in BASE_CODE | SIGNAL_CODE:
            (code / name).write_text("# Synthetic frozen source\n", encoding="utf-8")
        sha = hashlib.sha256((code / "forward_paper.py").read_bytes()).hexdigest()
        freeze_path = root / FREEZE_FILE
        freeze_path.parent.mkdir(parents=True)
        freeze_path.write_text(json.dumps({"rule": "synthetic_fixed_rule",
                                          "source_code_sha256": {"broad_research.py": sha}}), encoding="utf-8")
        freeze_sha = hashlib.sha256(freeze_path.read_bytes()).hexdigest()
        sources = []
        for directory, relative in [("forward_signals", "synthetic/input.json"),
                                    ("forward_observer", "raw/synthetic/quotes.json")]:
            path = results / directory / relative
            path.parent.mkdir(parents=True)
            path.write_bytes(b'{"synthetic": true}\n')
            sources.append({"file": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        for record, signal in zip(self.records, self.signals):
            record["config"]["freeze_sha256"] = signal["freeze_sha256"] = freeze_sha
            record["config"]["code_sha256"] = {name: sha for name in BASE_CODE | SIGNAL_CODE}
            signal["source_code_sha256"] = {name: sha for name in SIGNAL_CODE}
            signal["market_observation"]["source_code_sha256"] = {"forward_observer.py": sha}
            signal["sources"] = [deepcopy(sources[0])]
            signal["market_observation"]["sources"] = [deepcopy(sources[1])]
        self.save(series)
        return results, series

    def save(self, series):
        reseal(self.records, self.signals)
        for record, signal in zip(self.records, self.signals):
            saved = series / record["signal_file"]
            saved.write_text(json.dumps(signal, sort_keys=True) + "\n", encoding="utf-8")
            record["signal_file_sha256"] = hashlib.sha256(saved.read_bytes()).hexdigest()
        reseal(self.records, self.signals)
        (series / "ledger.jsonl").write_text("".join(json.dumps(row) + "\n" for row in self.records), encoding="utf-8")


class ForwardReportReplayTests(unittest.TestCase):
    def test_pre_entry_cash_is_pending_and_not_counted_as_trading_time(self):
        series = SyntheticSeries()
        series.add(INITIAL + HOUR_MS + 60_000)
        result = audit_records(series.records, series.signals)
        self.assertEqual(result["performance_state"], "pending_first_trade")
        self.assertEqual(result["capture_count"], 2)
        self.assertEqual(result["processed_hour_count"], 0)
        self.assertEqual(result["coverage"]["scheduled_hours_in_scope"], 0)
        for account in result["accounts"].values():
            self.assertEqual(account["net_total_return"], 0)
            self.assertEqual(account["observed_duration_hours"], 0)
            self.assertIsNone(account["first_fill_ms"])

    def test_entry_funding_stop_and_repeated_capture_do_not_double_count(self):
        series = SyntheticSeries()
        first = ENTRY + 60_000
        series.add(first)
        series.add(first + HOUR_MS, funding=[{"symbol": "SYNTH", "timestamp_ms": ENTRY + HOUR_MS,
                                            "rate": .1, "mark_price": 100}])
        series.add(first + HOUR_MS + 1_000)
        series.add(first + 2 * HOUR_MS)
        result = audit_records(series.records, series.signals)
        reference, trailing = result["accounts"]["reference"], result["accounts"]["trailing4"]
        self.assertEqual(result["capture_count"], 5)
        self.assertEqual(result["processed_hour_count"], 3)
        self.assertEqual(reference["fill_count"], 1)
        self.assertEqual(trailing["fill_count"], 2)
        self.assertEqual(trailing["stop_tick_count"], 1)
        self.assertEqual(trailing["rebalance_fill_tick_count"], 1)
        self.assertEqual(trailing["funding_pnl"], -500)
        self.assertEqual(trailing["exposed_duration_hours"], 1)
        self.assertEqual(reference["exposed_duration_hours"], 2)
        self.assertEqual(trailing["observed_duration_hours"], 2)
        self.assertEqual(trailing["first_fill_ms"], first)
        self.assertGreater(trailing["max_observed_drawdown"], .05)
        self.assertEqual(trailing["open_positions"], {})
        self.assertAlmostEqual(trailing["equity"], 10000 + trailing["cumulative_price_pnl"] - 500 - trailing["fees"])

    def test_account_tampering_is_rejected_after_rehashing_entire_chain(self):
        series = SyntheticSeries()
        series.add(ENTRY + 60_000)
        state = series.records[-1]["accounts"]["reference"]
        state["equity"] += 10
        state["cumulative_price_pnl"] += 10  # Algebra reconciles, but the actual replay must not.
        reseal(series.records, series.signals)
        with self.assertRaisesRegex(ValueError, "account state differs"):
            audit_records(series.records, series.signals)

    def test_changed_config_or_outside_window_mutation_is_rejected(self):
        for field in ("config", "accounts", "last_processed_hour_ms", "status"):
            with self.subTest(field=field):
                series = SyntheticSeries()
                series.add(INITIAL + HOUR_MS)
                row = series.records[-1]
                if field == "config":
                    row[field]["execution_window"] = "modified"
                elif field == "accounts":
                    row[field]["reference"]["last_ms"] += 1
                elif field == "last_processed_hour_ms":
                    row[field] = INITIAL + HOUR_MS
                else:
                    row[field] = "processed_hour"
                reseal(series.records, series.signals)
                with self.assertRaises(ValueError):
                    audit_records(series.records, series.signals)

    def test_blocked_boundary_and_failed_execution_are_reproduced(self):
        series = SyntheticSeries()
        series.add(ENTRY + 60_000, reconciled=False)
        series.add(ENTRY + 90_000, quotes=False)
        series.add(ENTRY + 120_000)
        result = audit_records(series.records, series.signals)
        self.assertEqual(result["status_counts"]["blocked_accounting"], 2)
        self.assertEqual(result["processed_hour_count"], 1)
        series.records[1]["error"] = "invented failure"
        reseal(series.records, series.signals)
        with self.assertRaisesRegex(ValueError, "status or error"):
            audit_records(series.records, series.signals)

    def test_flat_gaps_are_reported_without_invented_returns_or_duration(self):
        series = SyntheticSeries()
        series.add(ENTRY + HOUR_MS + 60_000)  # Initial Monday entry was missed: stay flat.
        series.add(ENTRY + 3 * HOUR_MS + 60_000)
        result = audit_records(series.records, series.signals)
        self.assertEqual(result["coverage"]["missed_closed_hour_count"], 2)
        self.assertEqual(result["coverage"]["days_with_missed_hours"], 1)
        self.assertEqual(result["coverage"]["complete_utc_days"], 0)
        self.assertEqual(result["performance_state"], "pending_first_trade")
        self.assertEqual(result["accounts"]["reference"]["observed_duration_hours"], 0)
        self.assertEqual(result["accounts"]["reference"]["fill_count"], 0)
        self.assertNotIn("hourly_returns", result)

    def test_open_position_gap_preserves_stale_mark_and_blocks_processing(self):
        series = SyntheticSeries()
        series.add(ENTRY + 60_000)
        series.add(ENTRY + 2 * HOUR_MS + 60_000)
        result = audit_records(series.records, series.signals)
        self.assertEqual(result["status_counts"]["blocked_accounting"], 1)
        self.assertEqual(result["accounts"]["reference"]["last_account_mark_ms"], ENTRY + 60_000)
        self.assertEqual(result["coverage"]["missed_closed_hour_count"], 1)
        self.assertEqual(result["coverage"]["pending_window_hours"], [ENTRY + 2 * HOUR_MS])


class ForwardReportFilesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.fixture = SyntheticSeries()
        self.fixture.add(INITIAL + HOUR_MS)
        self.results, self.series = self.fixture.write(self.root)

    def run_report(self):
        return report("synthetic_series", project_root=self.root, results_root=self.results)

    def test_stable_complete_hash_verified_file_report(self):
        result = self.run_report()
        self.assertEqual(result["capture_count"], 2)
        self.assertEqual(result["raw_source_references_verified"], 4)
        self.assertEqual(result["performance_state"], "pending_first_trade")

    def test_raw_sources_both_layers_and_current_code_are_checked(self):
        paths = [self.results / "forward_signals/synthetic/input.json",
                 self.results / "forward_observer/raw/synthetic/quotes.json",
                 self.root / "src/jev_trader/forward_paper.py"]
        for path in paths:
            original = path.read_bytes()
            path.write_bytes(original + b"changed")
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "hash mismatch"):
                self.run_report()
            path.write_bytes(original)

    def test_resealed_path_escape_is_rejected(self):
        self.fixture.signals[0]["sources"][0]["file"] = "../outside.json"
        self.fixture.save(self.series)
        with self.assertRaisesRegex(ValueError, "path outside"):
            self.run_report()

    def test_tick_lock_incomplete_line_and_concurrent_append_fail_closed(self):
        lock = self.series / "tick.lock"
        lock.touch()
        with self.assertRaisesRegex(ValueError, "tick in progress"):
            self.run_report()
        lock.unlink()
        ledger = self.series / "ledger.jsonl"
        original = ledger.read_bytes()
        ledger.write_bytes(original.rstrip(b"\n"))
        with self.assertRaisesRegex(ValueError, "incomplete final line"):
            self.run_report()
        ledger.write_bytes(original)

        def changed_during_read(path):
            records = read_chain(path)
            with path.open("ab") as handle:
                handle.write(b"\n")
            return records

        with patch("jev_trader.forward_report.read_chain", side_effect=changed_during_read):
            with self.assertRaisesRegex(ValueError, "ledger changed"):
                self.run_report()

    def test_invalid_series_is_rejected_before_read(self):
        for name in ("../synthetic_series", "", "WITH_SPACES ", "C:/absolute"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "invalid explicit"):
                report(name, project_root=self.root, results_root=self.results)


if __name__ == "__main__":
    unittest.main()
