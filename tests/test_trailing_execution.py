import unittest

from jev_trader.binance_data import Bar, HOUR_MS
from jev_trader.trailing_execution import DelayedPortfolioStop


class DelayedStopTests(unittest.TestCase):
    def bars(self):
        return {s: {i * HOUR_MS: Bar(i * HOUR_MS, p, p, p, p, 1) for i, p in enumerate((100, 90, 120, 80))}
                for s in ("A", "B")}

    def test_delayed_exit_does_not_cancel_after_recovery(self):
        stop = DelayedPortfolioStop(.04, 2)
        bars, q = self.bars(), {"A": .01, "B": -.005}
        stop.during_hour(0, 1, q, bars)
        self.assertEqual(stop.at_open(HOUR_MS, .95, q, bars), [])
        self.assertEqual(stop.pending["execute_ms"], 3 * HOUR_MS)
        self.assertEqual(stop.at_open(2 * HOUR_MS, 1.2, q, bars), [])
        held = stop.allowed_targets(2 * HOUR_MS, {"NEW": .5})
        self.assertAlmostEqual(held["A"], q["A"] * 120 / 1.2)
        self.assertNotIn("NEW", held)
        exits = stop.at_open(3 * HOUR_MS, .9, q, bars)
        self.assertEqual(len(exits), 2)
        self.assertTrue(all(e["price"] == 80 for e in exits))
        self.assertEqual(stop.allowed_targets(3 * HOUR_MS, {"A": .5}), {})

    def test_slippage_is_adverse_for_both_sides(self):
        stop = DelayedPortfolioStop(.04, 0, .0025)
        bars, q = self.bars(), {"A": .01, "B": -.005}
        stop.during_hour(0, 1, q, bars)
        exits = {e["symbol"]: e for e in stop.at_open(HOUR_MS, .95, q, bars)}
        self.assertAlmostEqual(exits["A"]["price"], 90 * .9975)
        self.assertAlmostEqual(exits["B"]["price"], 90 * 1.0025)


if __name__ == "__main__":
    unittest.main()
