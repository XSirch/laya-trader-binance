import unittest
from unittest.mock import patch

from jev_trader.binance_data import Bar, HOUR_MS, utc_ms
from jev_trader.broad_cost_policy import choose
from jev_trader.broad_execution import evaluate


class CostPolicyTests(unittest.TestCase):
    def test_small_prediction_does_not_pay_entry_cost(self):
        weights, audit = choose({"A": {"prediction": .001}}, {"A": .5}, {}, .0015)
        self.assertEqual(weights, {})
        self.assertLess(audit["alternatives"]["rebalance"]["net_score"], 0)

    def test_strong_signal_enters_and_negative_signal_exits(self):
        weights, audit = choose({"A": {"prediction": .02}}, {"A": .5}, {}, .0015)
        self.assertEqual(weights, {"A": .5})
        self.assertAlmostEqual(audit["expected_cost_fraction"], .00075)
        weights, audit = choose({"A": {"prediction": -.02}}, {"A": -.5}, {"A": .5}, .1)
        # Closing and reversing both cost more than a one-week expected loss.
        self.assertEqual(audit["chosen"], "hold")
        weights, audit = choose({"A": {"prediction": -.02}}, {}, {"A": .5}, .0015)
        self.assertEqual(audit["chosen"], "cash")
        self.assertEqual(weights, {})

    def test_missing_forecast_or_excess_gross_cannot_be_held(self):
        _, audit = choose({}, {}, {"A": .2}, .0015)
        self.assertFalse(audit["alternatives"]["hold"]["valid"])
        self.assertEqual(audit["chosen"], "cash")
        weights, audit = choose({"A": {"prediction": .02}}, {"A": .5}, {"A": .6}, .0015)
        self.assertFalse(audit["alternatives"]["hold"]["valid"])
        self.assertLessEqual(sum(abs(w) for w in weights.values()), .5)

    def test_execution_cost_reconciles_and_hold_preserves_quantity(self):
        start = utc_ms("2024-01-01")
        bars = {start + i * HOUR_MS: Bar(start + i * HOUR_MS, 100, 100, 100, 100, 1, 100, 1, 1)
                for i in range(24 * 15 + 1)}
        hourly = {"klines": {"A": bars}, "markPriceKlines": {"A": bars}}
        states = {"A": {start + i * 7 * 24 * HOUR_MS: {"prediction": .02} for i in range(3)}}
        # 0.4 avoids a risk reduction after fees push a 0.5 weight slightly above cap.
        with patch("jev_trader.broad_execution.target_weights", return_value={"A": .4}):
            result = evaluate(hourly, {}, states, "test", "2024-01-01", "2024-01-16", .0015,
                              decision_policy=choose)
        self.assertEqual(result["execution_audit"][0]["decision"]["chosen"], "rebalance")
        self.assertEqual(result["execution_audit"][1]["decision"]["chosen"], "hold")
        self.assertEqual(result["execution_audit"][1]["actual_cost_fraction"], 0)
        for row in result["execution_audit"]:
            self.assertAlmostEqual(row["actual_cost_fraction"], row["decision"]["expected_cost_fraction"])
        self.assertAlmostEqual(result["fees_pct_initial"], .12)
        self.assertEqual(result["order_changes"], 2)
        self.assertEqual(result["cash_hours"], 1)


if __name__ == "__main__":
    unittest.main()
