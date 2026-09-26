import unittest
from unittest.mock import Mock

from jev_trader.binance_data import HOUR_MS
from jev_trader.forward_watch import classify_tick, monitor_child, next_slot


class WatchScheduleTests(unittest.TestCase):
    def row(self, status, timestamp, processed=None, record="new", entry=0):
        return {"record_sha256": record, "status": status, "last_processed_hour_ms": processed,
                "server_time_ms": timestamp, "config": {"first_entry_ms": entry}}

    def test_no_backfill_and_one_success_per_hour(self):
        self.assertEqual(next_slot(HOUR_MS)["start_ms"], HOUR_MS + 65_000)
        self.assertEqual(next_slot(HOUR_MS + 290_000)["hour_ms"], 2 * HOUR_MS)
        self.assertEqual(next_slot(HOUR_MS + 70_000, HOUR_MS)["hour_ms"], 2 * HOUR_MS)

    def test_exit_zero_does_not_prove_accounting_success(self):
        old = self.row("outside_scheduled_window", 1, record="old")
        for status, expected in (("blocked_accounting", "blocked_accounting"),
                                 ("outside_scheduled_window", "not_processed")):
            self.assertEqual(classify_tick(old, self.row(status, HOUR_MS + 90_000), HOUR_MS, 0), expected)
        self.assertEqual(classify_tick(old, old, HOUR_MS, 0), "no_new_paper_record")
        self.assertEqual(classify_tick(old, old, HOUR_MS, 1), "failed_child")

    def test_processed_hour_must_match_exchange_time_and_ledger(self):
        valid = self.row("processed_hour", HOUR_MS + 100_000, HOUR_MS)
        self.assertEqual(classify_tick(None, valid, HOUR_MS, 0), "processed_hour")
        self.assertEqual(classify_tick(None, valid, HOUR_MS, 1), "processed_hour_with_child_error")
        wrong = self.row("processed_hour", 2 * HOUR_MS + 100_000, HOUR_MS)
        self.assertEqual(classify_tick(None, wrong, HOUR_MS, 0), "not_processed")

    def test_pre_entry_flat_observation_is_not_counted_as_trading(self):
        row = self.row("outside_scheduled_window", HOUR_MS + 90_000, entry=10 * HOUR_MS)
        self.assertEqual(classify_tick(None, row, HOUR_MS, 0), "pre_entry_observed")
        self.assertEqual(classify_tick(None, row, HOUR_MS, 0, preflight=True), "preflight_observed")

    def child(self):
        child = Mock(pid=123, returncode=None)
        child.poll.side_effect = lambda: child.returncode
        child.kill.side_effect = lambda: setattr(child, "returncode", -9)
        return child

    def test_callback_failure_cannot_orphan_child(self):
        child = self.child()
        def failing_callback(pid):
            raise OSError("heartbeat write failed")
        with self.assertRaises(OSError):
            monitor_child(child, 10**15, lambda: None, failing_callback, lambda pid: None)
        child.kill.assert_called_once()
        child.wait.assert_called_once_with(timeout=15)

    def test_stop_request_and_deadline_kill_then_wait(self):
        for deadline, reason, expected in ((10**15, "stop_requested", "stop_requested"),
                                           (0, None, "child_deadline_exceeded")):
            child = self.child()
            code, forced = monitor_child(child, deadline, lambda: reason, lambda pid: None, lambda pid: None)
            self.assertEqual((code, forced), (-9, expected))
            child.kill.assert_called_once()
            child.wait.assert_called_once_with(timeout=15)
