import unittest
from unittest.mock import patch

from jev_trader.binance_data import Bar, HOUR_MS, utc_ms
from jev_trader.broad_execution import evaluate
from jev_trader.settlement_bounds import bound


class SettlementBoundsTests(unittest.TestCase):
    def rows(self):
        return [[str(i * 60_000), "100", str(102 + i), str(99 + i)] for i in range(30)]

    def test_mean_bounds_use_all_thirty_minutes(self):
        result = bound(self.rows(), 30 * 60_000)
        self.assertAlmostEqual(result["lower"], 113.5)
        self.assertAlmostEqual(result["upper"], 116.5)
        self.assertEqual(result["minute_count"], 30)

    def test_missing_or_duplicate_minute_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "incomplete"):
            bound(self.rows()[:-1], 30 * 60_000)
        with self.assertRaisesRegex(ValueError, "invalid"):
            bound(self.rows() + self.rows()[-1:], 30 * 60_000)

    def test_adverse_side_and_accounting_without_invented_trade(self):
        start = utc_ms("2024-01-01")
        candles = {start + i * HOUR_MS: Bar(start + i * HOUR_MS, 100, 100, 100, 100, 1, 100, 1, 1)
                   for i in range(25)}
        traded = dict(candles)
        del traded[start + 2 * HOUR_MS]
        data = {"klines": {"X": traded}, "markPriceKlines": {"X": candles}}
        bounds = {("X", start + 2 * HOUR_MS): {"lower": 90, "upper": 120}}
        for weight, expected in ((.5, -5.095), (-.5, -10.11)):
            with patch("jev_trader.broad_execution.target_weights", return_value={"X": weight}):
                result = evaluate(data, {}, {}, "test", "2024-01-01", "2024-01-02", .001,
                                  settlement_bounds=bounds)
            self.assertAlmostEqual(result["return_pct"], expected)
            self.assertEqual(len(result["bounded_settlements"]), 1)
            self.assertAlmostEqual(result["asset_attribution_pct_initial"]["X"]["net"], expected)
        with patch("jev_trader.broad_execution.target_weights", return_value={"X": .5}):
            with self.assertRaisesRegex(ValueError, "unresolved held price"):
                evaluate(data, {}, {}, "test", "2024-01-01", "2024-01-02", .001)


if __name__ == "__main__":
    unittest.main()
