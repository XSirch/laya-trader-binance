import unittest
from unittest.mock import patch

from jev_trader.binance_data import Bar, HOUR_MS, utc_ms
from jev_trader.broad_execution import evaluate
from jev_trader.trailing_stop import TrailingStop
from jev_trader.derivatives_data import Funding


class TrailingTests(unittest.TestCase):
    def test_current_hour_high_cannot_retroactively_trigger_long_stop(self):
        stop = TrailingStop("position_pct", .1)
        bars = {"X": {0: Bar(0, 100, 120, 99, 115, 1),
                      HOUR_MS: Bar(HOUR_MS, 115, 116, 109, 110, 1),
                      2 * HOUR_MS: Bar(2 * HOUR_MS, 100, 101, 95, 99, 1)}}
        self.assertEqual(stop.during_hour(0, 1, {"X": .01}, bars), [])
        self.assertEqual(stop.at_open(HOUR_MS, 1, {"X": .01}, bars), [])
        # A resize in the same direction must retain the favorable watermark.
        self.assertEqual(stop.during_hour(HOUR_MS, 1, {"X": .005}, bars), [])
        result = stop.at_open(2 * HOUR_MS, 1, {"X": .005}, bars)
        self.assertAlmostEqual(result[0]["level"], 108)
        self.assertEqual(result[0]["price"], 100)
        self.assertEqual(stop.allowed_targets(2 * HOUR_MS, {"X": .5}), {})
        self.assertEqual(stop.allowed_targets(3 * HOUR_MS, {"X": .5}), {"X": .5})

    def test_short_stop_is_symmetric_and_uses_worse_gap_price(self):
        stop = TrailingStop("position_pct", .1)
        bars = {"X": {0: Bar(0, 100, 101, 80, 85, 1), HOUR_MS: Bar(HOUR_MS, 95, 100, 90, 99, 1)}}
        self.assertEqual(stop.during_hour(0, 1, {"X": -.01}, bars), [])
        result = stop.at_open(HOUR_MS, 1, {"X": -.01}, bars)
        self.assertAlmostEqual(result[0]["level"], 88)
        self.assertEqual(result[0]["price"], 95)

    def test_atr_increase_never_loosens_stop(self):
        t = utc_ms("2024-01-01") + HOUR_MS
        atr = {"X": {t - HOUR_MS: 2, t - HOUR_MS + 24 * HOUR_MS: 10}}
        stop = TrailingStop("position_atr", 2, atr)
        bars = {"X": {t: Bar(t, 100, 101, 97, 100, 1),
                      t + 24 * HOUR_MS: Bar(t + 24 * HOUR_MS, 95, 99, 94, 98, 1)}}
        self.assertEqual(stop.during_hour(t, 1, {"X": .01}, bars), [])
        result = stop.at_open(t + 24 * HOUR_MS, 1, {"X": .01}, bars)
        self.assertEqual(result[0]["level"], 96)

    def test_gap_loss_and_costs_reconcile_with_engine(self):
        start = utc_ms("2024-01-01")
        bars = {start + i * HOUR_MS: Bar(start + i * HOUR_MS, 100, 100, 100, 100, 1, 100, 1, 1)
                for i in range(25)}
        bars[start + HOUR_MS] = Bar(start + HOUR_MS, 100, 110, 99, 105, 1, 100, 1, 1)
        bars[start + 2 * HOUR_MS] = Bar(start + 2 * HOUR_MS, 90, 95, 85, 92, 1, 100, 1, 1)
        hourly = {"klines": {"X": bars}, "markPriceKlines": {"X": bars}}
        with patch("jev_trader.broad_execution.target_weights", return_value={"X": .5}):
            result = evaluate(hourly, {}, {}, "test", "2024-01-01", "2024-01-02", .0015,
                              trailing=TrailingStop("position_pct", .1))
        self.assertAlmostEqual(result["return_pct"], -5.1425)
        self.assertEqual(result["stop_count"], 1)
        self.assertEqual(result["stop_events"][0]["price"], 90)
        self.assertAlmostEqual(result["asset_attribution_pct_initial"]["X"]["net"], result["return_pct"])

    def test_portfolio_stop_closes_all_legs_and_blocks_same_hour(self):
        stop = TrailingStop("portfolio_pct", .04)
        bars = {s: {0: Bar(0, 100, 100, 100, 100, 1), HOUR_MS: Bar(HOUR_MS, 90, 90, 90, 90, 1)}
                for s in ("A", "B")}
        q = {"A": .01, "B": -.005}
        stop.during_hour(0, 1, q, bars)
        exits = stop.at_open(HOUR_MS, .95, q, bars)
        self.assertEqual({e["symbol"] for e in exits}, {"A", "B"})
        self.assertEqual(stop.allowed_targets(HOUR_MS, {"A": .2}), {})
        self.assertEqual(stop.allowed_targets(2 * HOUR_MS, {"A": .2}), {"A": .2})

    def test_uncertain_same_hour_funding_credit_is_withheld_after_stop(self):
        start = utc_ms("2024-01-01")
        bars = {start + i * HOUR_MS: Bar(start + i * HOUR_MS, 100, 100, 100, 100, 1, 100, 1, 1)
                for i in range(25)}
        t = start + 2 * HOUR_MS
        bars[t] = Bar(t, 100, 101, 90, 95, 1, 100, 1, 1)
        hourly = {"klines": {"X": bars}, "markPriceKlines": {"X": bars}}
        with patch("jev_trader.broad_execution.target_weights", return_value={"X": .5}):
            result = evaluate(hourly, {"X": [Funding(t, 1, -.01)]}, {}, "test", "2024-01-01", "2024-01-02", 0,
                              trailing=TrailingStop("position_pct", .04))
        self.assertEqual(result["stop_count"], 1)
        self.assertEqual(result["funding_pct_initial"], 0)


if __name__ == "__main__":
    unittest.main()
