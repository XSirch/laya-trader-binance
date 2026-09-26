"""Synthetic unit checks; they are not evidence of historical profitability."""

import math
import unittest
from unittest.mock import patch

from jev_trader.target50_research import ScaledTargets, annualized_return, classify, verify_reproduction


class Target50ResearchTests(unittest.TestCase):
    def test_multiplier_rejects_invalid_and_excessive_values(self):
        for value in (None, True, "2", 0, -1, 6.0001, math.nan, math.inf):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ScaledTargets(value)

    def test_fresh_signed_targets_are_scaled_with_frozen_gross_limits(self):
        policy = ScaledTargets(6)
        with patch("jev_trader.target50_research.target_weights", return_value={"LONG": .25, "SHORT": -.25}):
            self.assertEqual(policy({}, "synthetic"), {"LONG": 1.5, "SHORT": -1.5})
            self.assertEqual(policy.max_unscaled_gross, .5)
            self.assertEqual(policy.max_scaled_gross, 3)
        for targets in ({"OVER": .501}, {"BAD": math.nan}, {"BAD": True}):
            with patch("jev_trader.target50_research.target_weights", return_value=targets):
                with self.assertRaises(ValueError):
                    policy({}, "synthetic")

    def test_multi_year_total_return_is_not_annual_return(self):
        result = annualized_return(50, 3 * 365)
        self.assertAlmostEqual(result, 100 * (1.5 ** (1 / 3) - 1))
        self.assertLess(result, 15)
        self.assertAlmostEqual(annualized_return(237.5, 3 * 365), 50)
        self.assertAlmostEqual(annualized_return(50, 365), 50)
        self.assertAlmostEqual(annualized_return(-50, 3 * 365), 100 * (.5 ** (1 / 3) - 1))
        for total, days in ((-100, 365), (-101, 365), (1, 0), (1, -1), (math.inf, 365), (1, math.nan)):
            with self.subTest(total=total, days=days), self.assertRaises(ValueError):
                annualized_return(total, days)

    def test_target_needs_cagr_drawdown_and_no_margin_stress_failure(self):
        metrics = {"return_pct": 51, "max_drawdown_pct": 10,
                   "adverse_intrahour_drawdown_bound_pct": 10, "margin_stress_failures": 0}
        self.assertTrue(classify(metrics, 365)["meets_target_and_adverse_bound"])
        self.assertFalse(classify(metrics, 3 * 365)["meets_nominal_target"])
        self.assertFalse(classify({**metrics, "max_drawdown_pct": 10.001}, 365)["meets_nominal_target"])
        self.assertFalse(classify({**metrics, "margin_stress_failures": 1}, 365)["meets_nominal_target"])
        adverse = classify({**metrics, "adverse_intrahour_drawdown_bound_pct": 10.001}, 365)
        self.assertTrue(adverse["meets_nominal_target"])
        self.assertFalse(adverse["meets_target_and_adverse_bound"])

    def test_baseline_check_includes_costs_and_individual_stop_fill_count(self):
        baseline = {"return_pct": 12, "max_drawdown_pct": 8, "fees_pct_initial": 2, "stop_count": 5}
        self.assertTrue(verify_reproduction(dict(baseline), baseline)["passed"])
        for field in baseline:
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "reproduction failed"):
                verify_reproduction({**baseline, field: baseline[field] + .000001}, baseline)


if __name__ == "__main__":
    unittest.main()
