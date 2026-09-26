import unittest

from jev_trader.binance_data import HOUR_MS, utc_ms
from jev_trader.forward_paper import next_weekly_entry, schedule


class ForwardScheduleTests(unittest.TestCase):
    def test_first_entry_is_strictly_future(self):
        monday = utc_ms("2026-09-28") + HOUR_MS
        self.assertEqual(next_weekly_entry(utc_ms("2026-09-26")), monday)
        self.assertEqual(next_weekly_entry(monday), monday + 7 * 24 * HOUR_MS)

    def test_hourly_window_has_funding_grace_and_no_backfill(self):
        monday = utc_ms("2026-09-28") + HOUR_MS
        self.assertFalse(schedule(monday + 59_999, monday, None)["due"])
        self.assertTrue(schedule(monday + 60_000, monday, None)["rebalance"])
        self.assertFalse(schedule(monday + 300_000, monday, None)["due"])
        self.assertFalse(schedule(monday + 60_000, monday, monday)["due"])
        self.assertFalse(schedule(monday - HOUR_MS + 60_000, monday, None)["due"])
        self.assertTrue(schedule(monday + HOUR_MS + 60_000, monday, monday)["due"])
        self.assertFalse(schedule(monday + HOUR_MS + 60_000, monday, monday)["rebalance"])
