import unittest

from jev_trader.binance_data import HOUR_MS
from jev_trader.broad_extension import parse_bars, aggregate_days


class ExtensionTests(unittest.TestCase):
    def rows(self):
        return [[i * HOUR_MS, "100", "102", "99", "101", "5", (i + 1) * HOUR_MS - 1,
                 "500", 4, "2", "200", "0"] for i in range(25)]

    def test_complete_days_do_not_include_terminal_hour(self):
        rows = self.rows()
        rows[-1][1:5] = ["999", "999", "999", "999"]
        bars = parse_bars(rows, 0, 24 * HOUR_MS)
        daily = aggregate_days(bars, 0, 24 * HOUR_MS)
        self.assertEqual(len(daily), 1)
        self.assertEqual(daily[0].high, 102)
        self.assertEqual(daily[0].volume, 120)
        self.assertEqual(daily[0].trades, 96)

    def test_missing_hour_is_rejected(self):
        rows = self.rows()
        del rows[5]
        with self.assertRaisesRegex(ValueError, "calendar incomplete"):
            parse_bars(rows, 0, 24 * HOUR_MS)

    def test_nonfinite_and_duplicate_are_rejected(self):
        rows = self.rows()
        rows[3][7] = "NaN"
        with self.assertRaisesRegex(ValueError, "invalid REST candle"):
            parse_bars(rows, 0, 24 * HOUR_MS)
        rows = self.rows()
        rows.append(rows[-1])
        with self.assertRaisesRegex(ValueError, "invalid REST candle"):
            parse_bars(rows, 0, 24 * HOUR_MS)


if __name__ == "__main__":
    unittest.main()
