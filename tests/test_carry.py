import unittest

from jev_trader.binance_data import Bar, HOUR_MS, utc_ms
from jev_trader.carry import annualized_past_funding, evaluate, target_for
from jev_trader.derivatives_data import Funding


def market(prices, rates=()):
    start = utc_ms("2025-01-06")  # Monday, a rebalance boundary.
    bars = [Bar(start + i * HOUR_MS, p, p, p, p, 1) for i, p in enumerate(prices)]
    return {"BTCUSDT": {"spot": bars, "futures": {b.open_ms: b for b in bars},
        "mark": {b.open_ms: b for b in bars},
        "funding": {start + i * HOUR_MS: Funding(start + i * HOUR_MS, 8, rate) for i, rate in rates},
        "past_annualized": {start: .10}}}


class CarryTests(unittest.TestCase):
    def test_matched_quantity_hedge_cancels_directional_move(self):
        result = evaluate(market([100, 120, 80, 140, 100]), "always",
                          "2025-01-06", "2025-01-06T04:00:00", 0, 0)
        self.assertAlmostEqual(result["return_pct"], 0)
        self.assertAlmostEqual(result["max_drawdown_pct"], 0)

    def test_two_legs_charged_on_entry_and_exit(self):
        result = evaluate(market([100, 100, 100]), "always",
                          "2025-01-06", "2025-01-06T02:00:00", .0025, .0015)
        self.assertAlmostEqual(result["return_pct"], -100 * .25 * (.0025 + .0015) * 2)

    def test_short_receives_positive_and_pays_negative_funding(self):
        for rate in (.001, -.001):
            result = evaluate(market([100, 100, 100], [(1, rate)]), "always",
                              "2025-01-06", "2025-01-06T02:00:00", 0, 0)
            self.assertAlmostEqual(result["return_pct"], 100 * .25 * rate)

    def test_no_credit_for_settlement_at_entry_or_exit_boundary(self):
        result = evaluate(market([100, 100, 100], [(0, .1), (2, .1)]), "always",
                          "2025-01-06", "2025-01-06T02:00:00", 0, 0)
        self.assertAlmostEqual(result["return_pct"], 0)

    def test_funding_signal_excludes_current_and_future_payments(self):
        t = utc_ms("2025-01-06")
        past = [Funding(t - i * 8 * HOUR_MS, 8, .0001) for i in range(90, 0, -1)]
        value = annualized_past_funding(past, t)
        self.assertAlmostEqual(value, .0001 * 90 * 365 / 30)
        future = past + [Funding(t, 8, -.1), Funding(t + 8 * HOUR_MS, 8, -.1)]
        self.assertEqual(value, annualized_past_funding(future, t))

    def test_insufficient_funding_history_blocks_entry(self):
        self.assertIsNone(annualized_past_funding([], utc_ms("2025-01-06")))
        self.assertFalse(target_for("always", None, False))

    def test_boundary_ambiguity_cannot_avoid_negative_funding(self):
        result = evaluate(market([100, 100, 100], [(0, -.001)]), "always",
                          "2025-01-06", "2025-01-06T02:00:00", 0, 0)
        self.assertAlmostEqual(result["return_pct"], -.025)


if __name__ == "__main__":
    unittest.main()
