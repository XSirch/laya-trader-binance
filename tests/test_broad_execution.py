import unittest
from unittest.mock import patch

from jev_trader.binance_data import Bar, HOUR_MS, utc_ms
from jev_trader.broad_execution import evaluate
from jev_trader.derivatives_data import Funding


class HourlyExecutionTests(unittest.TestCase):
    def fixture(self):
        start = utc_ms("2024-01-01")  # Monday
        bars = {start + i * HOUR_MS: Bar(start + i * HOUR_MS, 100 if i < 2 else 110,
                                       100 if i < 2 else 110, 100 if i < 2 else 110,
                                       100 if i < 2 else 110, 100, 10000, 10, 50)
                for i in range(25)}
        return start, {"klines": {"BTCUSDT": bars}, "markPriceKlines": {"BTCUSDT": bars}}

    def test_delayed_fill_costs_and_terminal_settlement(self):
        start, hourly = self.fixture()
        rates = {"BTCUSDT": [Funding(start + 8 * HOUR_MS, 8, .01),
                              Funding(start + 24 * HOUR_MS, 8, .9)]}
        with patch("jev_trader.broad_execution.target_weights", return_value={"BTCUSDT": .5}):
            result = evaluate(hourly, rates, {}, "test", "2024-01-01", "2024-01-02", .001)
        # .005 units bought at 100; +.05 PnL, -.0055 funding,
        # -.0005 entry and -.00055 exit costs. End funding is excluded.
        self.assertAlmostEqual(result["return_pct"], 4.345)
        self.assertAlmostEqual(result["fees_pct_initial"], .105)
        self.assertAlmostEqual(result["funding_pct_initial"], -.55)
        self.assertAlmostEqual(sum(r["net"] for r in result["asset_attribution_pct_initial"].values()),
                               result["return_pct"])

    def test_exact_funding_mark_is_validated_and_accounted(self):
        start, hourly = self.fixture()
        timestamp = start + 8 * HOUR_MS
        rates = {"BTCUSDT": [Funding(timestamp, 8, .01)]}
        with patch("jev_trader.broad_execution.target_weights", return_value={"BTCUSDT": .5}):
            result = evaluate(hourly, rates, {}, "test", "2024-01-01", "2024-01-02", 0,
                              exact_funding_marks={("BTCUSDT", timestamp): 110})
            self.assertAlmostEqual(result["funding_pct_initial"], -.55)
            self.assertEqual(result["funding_observations"]["exact_marks"], 1)
            with self.assertRaisesRegex(ValueError, "outside corresponding"):
                evaluate(hourly, rates, {}, "test", "2024-01-01", "2024-01-02", 0,
                         exact_funding_marks={("BTCUSDT", timestamp): 500})

    def test_delay_changes_execution_price_and_preserves_signal_cutoff(self):
        start, hourly = self.fixture()
        with patch("jev_trader.broad_execution.target_weights", return_value={"BTCUSDT": .5}):
            result = evaluate(hourly, {}, {}, "test", "2024-01-01", "2024-01-02", 0, 2)
        self.assertAlmostEqual(result["return_pct"], 0)
        self.assertEqual(result["execution_audit"][0]["latest_input_close_ms"], start)
        self.assertEqual(result["execution_audit"][0]["execution_ms"], start + 2 * HOUR_MS)

    def test_boundary_settlement_mark_is_counted_separately(self):
        start, hourly = self.fixture()
        timestamp = start + 8 * HOUR_MS
        marks = dict(hourly["markPriceKlines"]["BTCUSDT"])
        marks[timestamp] = Bar(timestamp, 111, 111, 111, 111, 0)
        hourly["markPriceKlines"] = {"BTCUSDT": marks}
        with patch("jev_trader.broad_execution.target_weights", return_value={"BTCUSDT": .5}):
            result = evaluate(hourly, {"BTCUSDT": [Funding(timestamp, 8, .01)]}, {}, "test",
                              "2024-01-01", "2024-01-02", 0,
                              exact_funding_marks={("BTCUSDT", timestamp): 110})
        self.assertEqual(result["funding_observations"]["exact_marks_within_previous_candle_only"], 1)
        self.assertAlmostEqual(result["funding_pct_initial"], -.55)

    def test_funding_collision_does_not_credit_new_position(self):
        start, hourly = self.fixture()
        rates = {"BTCUSDT": [Funding(start + HOUR_MS + 5, 1, -.01)]}
        with patch("jev_trader.broad_execution.target_weights", return_value={"BTCUSDT": .5}):
            result = evaluate(hourly, rates, {}, "test", "2024-01-01", "2024-01-02", 0)
        self.assertEqual(result["funding_pct_initial"], 0)

    def test_missing_held_price_fails_closed(self):
        start, hourly = self.fixture()
        del hourly["klines"]["BTCUSDT"][start + 3 * HOUR_MS]
        with patch("jev_trader.broad_execution.target_weights", return_value={"BTCUSDT": .5}):
            with self.assertRaisesRegex(ValueError, "unresolved held price"):
                evaluate(hourly, {}, {}, "test", "2024-01-01", "2024-01-02", 0)


if __name__ == "__main__":
    unittest.main()
