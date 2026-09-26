import copy
import unittest

from jev_trader.basis_policy import BasisPolicy, FUNDAMENTAL_R0


def state():
    return {"basis_fraction": .01, "basis_previous720_median": 0.0,
            "context_sha256": "synthetic", "funding_past30_mean_rate": .0001,
            "quote_volume24": {"spot": 100_000_000, "futures": 100_000_000},
            "spot_hourly": {"participation": {"trade_count": 10}},
            "futures_hourly": {"participation": {"trade_count": 10},
                               "volatility": {"realized20_per_bar_pct": .1, "atr14_pct": .1}}}


class BasisPolicyTests(unittest.TestCase):
    def policy(self, **kw):
        return BasisPolicy(**{"reference": "fundamental_r0", "spot_cost": .0012,
                              "future_cost": .0007, "spot_fraction": .5, "max_hold_hours": 24, **kw})

    def test_four_fees_units_and_no_credit_forecast(self):
        row = state()
        before = copy.deepcopy(row)
        result = self.policy()(row, None)
        self.assertEqual(result["action"], "enter")
        self.assertEqual(result["target_basis"], FUNDAMENTAL_R0)
        self.assertAlmostEqual(result["cost_hurdle_fraction"], 2*.0012+2*.0007*1.01)
        self.assertEqual(result["adverse_funding_hurdle_fraction"], 0)
        self.assertEqual(row, before)
        row["funding_past30_mean_rate"] = -.01
        result = self.policy()(row, None)
        self.assertEqual(result["action"], "hold")
        self.assertAlmostEqual(result["adverse_funding_hurdle_fraction"], 3*.01*1.01)

    def test_margin_and_liquidity_filters(self):
        row = state()
        row["futures_hourly"]["volatility"]["atr14_pct"] = 10
        self.assertEqual(self.policy()(row, None)["reason"], "past_volatility_margin_guard")
        row["quote_volume24"]["spot"] = None
        self.assertEqual(self.policy()(row, None)["reason"], "past_liquidity_guard")

    def test_exit_uses_frozen_entry_reference_even_if_current_median_changes(self):
        row = state()
        row["basis_fraction"] = -.001
        row["basis_previous720_median"] = -.5
        self.assertEqual(self.policy(reference="median720")(row, {"target_basis": 0})["action"], "exit")
        self.assertEqual(self.policy()(row, {"target_basis": -.002})["action"], "hold")

    def test_large_projected_funding_cannot_consume_margin_despite_basis_edge(self):
        row = state()
        row["basis_fraction"] = 2
        row["funding_past30_mean_rate"] = -.02
        result = self.policy(spot_fraction=.75, max_hold_hours=168)(row, None)
        self.assertGreater(result["surplus_fraction"], 0)
        self.assertEqual(result["reason"], "past_volatility_margin_guard")
        self.assertAlmostEqual(result["prospective_funding_margin_debit"], .42)

    def test_equality_does_not_enter(self):
        row = state()
        row["basis_previous720_median"] = row["basis_fraction"]
        self.assertEqual(self.policy(reference="median720", spot_cost=0, future_cost=0)(row, None)["action"], "hold")


if __name__ == "__main__":
    unittest.main()
