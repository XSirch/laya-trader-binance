import unittest
from unittest.mock import patch

from jev_trader.hourly_forecast_research import CONFIG, calendar_year_returns, score_forecasts, scenario


class HourlyResearchTests(unittest.TestCase):
    def test_yearly_returns_compound_and_identify_partial_calendar(self):
        monthly = {f"2024-{m:02}": 0 for m in range(1, 13)}
        monthly.update({"2024-01": 10, "2024-02": -10, "2025-01": 20})
        result = calendar_year_returns(monthly)
        self.assertAlmostEqual(result["2024"]["return_pct"], -1)
        self.assertTrue(result["2024"]["complete_calendar_year"])
        self.assertAlmostEqual(result["2025"]["return_pct"], 20)
        self.assertFalse(result["2025"]["complete_calendar_year"])

    def test_scores_do_not_include_future_labels_or_other_periods(self):
        errors = [
            {"execution_ms": 10, "label_end_ms": 20, "actual_return": .1,
             "rolling_mean_prediction": 0., "hgb_prediction": .1},
            {"execution_ms": 20, "label_end_ms": 30, "actual_return": -.1,
             "rolling_mean_prediction": 0., "hgb_prediction": -.1},
            {"execution_ms": 29, "label_end_ms": 31, "actual_return": 999,
             "rolling_mean_prediction": 0., "hgb_prediction": 0.},
        ]
        result = score_forecasts(errors, 10, 30)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["models"]["hgb"]["skill_vs_zero"], 1)
        self.assertEqual(result["models"]["rolling_mean"]["skill_vs_zero"], 0)
        self.assertLess(result["hgb_mse_minus_mean_mse"], 0)
        self.assertEqual(score_forecasts(errors, 30, 31)["count"], 0)

    def test_unverified_fill_invalidates_scenario_not_all_experiments(self):
        for message in ("unverified spot execution liquidity at 1", "missing execution spot price at 1",
                        "missing held spot price at 1"):
            with self.subTest(message=message), patch("jev_trader.hourly_forecast_research.evaluate", side_effect=ValueError(message)):
                row = scenario({}, {}, "hgb", "sign", .0012, 1, None, "later")
            self.assertEqual(row["status"], "invalid_execution")
            self.assertIsNone(row["metrics"])
            self.assertFalse(row["meets_nominal_target"])
        with patch("jev_trader.hourly_forecast_research.evaluate", side_effect=ValueError("causal clock bug")):
            with self.assertRaisesRegex(ValueError, "causal clock bug"):
                scenario({}, {}, "hgb", "sign", .0012, 1, None, "later")

    def test_observed_drawdown_pass_does_not_hide_adverse_bound_failure(self):
        # Exact one calendar year; a conservative intrahour bound can still fail.
        config = {**CONFIG, "periods": {"test": ["2024-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"]}}
        with patch("jev_trader.hourly_forecast_research.CONFIG", config), patch(
                "jev_trader.hourly_forecast_research.evaluate", return_value={"return_pct": 60,
                    "max_drawdown_pct": 9, "adverse_intrahour_drawdown_bound_pct": 11, "monthly_returns_pct": {}}):
            row = scenario({}, {}, "hgb", "sign", .0012, 1, None, "test")
        self.assertTrue(row["meets_nominal_target"])
        self.assertFalse(row["meets_target_and_adverse_bound"])


if __name__ == "__main__":
    unittest.main()
