import math
import unittest

from jev_trader.consistency import block_scenarios, daily_returns, rolling_summary


DAY = 86_400_000


class ConsistencyTests(unittest.TestCase):
    def test_daily_returns_sorts_dates_and_attaches_return_to_end_date(self):
        equity = {str(2 * DAY): 99.0, "0": 100.0, str(DAY): 110.0}
        result = daily_returns(equity)
        self.assertEqual([timestamp for timestamp, _ in result], [DAY, 2 * DAY])
        self.assertAlmostEqual(result[0][1], math.log(1.1))
        self.assertAlmostEqual(result[1][1], math.log(.9))
        self.assertAlmostEqual(math.expm1(sum(value for _, value in result)), -.01)

    def test_daily_returns_rejects_gaps_and_non_daily_spacing(self):
        for last_timestamp in (3 * DAY, 2 * DAY + 1):
            with self.subTest(last_timestamp=last_timestamp), self.assertRaises(ValueError):
                daily_returns({"0": 1.0, str(DAY): 1.1, str(last_timestamp): 1.2})

    def test_daily_returns_rejects_invalid_equity_anywhere_in_path(self):
        for value in (0.0, -1.0, math.nan, math.inf, -math.inf):
            for bad_index in range(3):
                equity = {str(index * DAY): 1.0 for index in range(3)}
                equity[str(bad_index * DAY)] = value
                with self.subTest(value=value, bad_index=bad_index), self.assertRaises(ValueError):
                    daily_returns(equity)

    def test_rolling_summary_compounds_complete_overlapping_windows(self):
        returns = [math.log(1.1), math.log(.9), math.log(1.2)]
        result = rolling_summary(returns, horizon=2)
        self.assertEqual(result["windows"], 2)
        self.assertEqual(result["positive_windows"], 1)
        self.assertAlmostEqual(result["worst_return_pct"], -1.0)
        self.assertAlmostEqual(result["best_return_pct"], 8.0)

    def test_constant_positive_path_has_exact_compound_return_and_no_drawdown(self):
        daily = math.log(1.01)
        horizon = 7
        expected = 100 * (1.01 ** horizon - 1)
        result = block_scenarios([daily] * 60, horizon, -1.0, draws=100)
        self.assertEqual(result["loss_frequency"], 0.0)
        self.assertEqual(result["at_or_below_observed_frequency"], 0.0)
        for percentile in ("p05", "p50", "p95"):
            self.assertAlmostEqual(result["return_percentiles_pct"][percentile], expected)
            self.assertEqual(result["drawdown_percentiles_pct"][percentile], 0.0)

    def test_constant_negative_path_measures_drawdown_from_initial_capital(self):
        daily = math.log(.99)
        horizon = 7
        expected = 100 * (.99 ** horizon - 1)
        result = block_scenarios([daily] * 60, horizon, 0.0, draws=100)
        self.assertEqual(result["loss_frequency"], 1.0)
        self.assertEqual(result["at_or_below_observed_frequency"], 1.0)
        for percentile in ("p05", "p50", "p95"):
            self.assertAlmostEqual(result["return_percentiles_pct"][percentile], expected)
            self.assertAlmostEqual(result["drawdown_percentiles_pct"][percentile], -expected)

    def test_flat_cash_is_not_a_loss_and_observed_ties_are_included(self):
        result = block_scenarios([0.0] * 60, 45, 0.0, draws=100)
        self.assertEqual(result["loss_frequency"], 0.0)
        self.assertEqual(result["at_or_below_observed_frequency"], 1.0)
        self.assertEqual(result["return_percentiles_pct"], {"p05": 0.0, "p50": 0.0, "p95": 0.0})
        self.assertEqual(result["drawdown_percentiles_pct"], {"p05": 0.0, "p50": 0.0, "p95": 0.0})

    def test_scenarios_are_repeatable_without_mutating_calibration_returns(self):
        returns = [.015 * math.sin(index / 9) + .0002 for index in range(120)]
        original = list(returns)
        options = {"horizon": 47, "observed_log_return": -.08, "draws": 100, "seed": 42}
        first = block_scenarios(returns, **options)
        self.assertEqual(first, block_scenarios(returns, **options))
        self.assertEqual(returns, original)

    def test_scenarios_reject_invalid_calibration_and_sampling_parameters(self):
        valid = {"logreturns": [.001] * 60, "horizon": 7, "observed_log_return": -.05,
                 "block_days": 30, "draws": 100}
        overrides = [
            {"logreturns": [.001] * 59}, {"horizon": 0}, {"horizon": -1},
            {"block_days": 0}, {"block_days": -1}, {"draws": 99},
        ]
        for value in (math.nan, math.inf, -math.inf):
            overrides.append({"logreturns": [.001] * 59 + [value]})
            overrides.append({"observed_log_return": value})
        for override in overrides:
            with self.subTest(override=override), self.assertRaises(ValueError):
                block_scenarios(**(valid | override))


if __name__ == "__main__":
    unittest.main()
