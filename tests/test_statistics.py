import math
import unittest

from jev_trader.statistics import family_bootstrap


class BootstrapTests(unittest.TestCase):
    def test_identical_experts_preserve_cross_strategy_dependence(self):
        path = {str(i * 86_400_000): math.exp(.0001 * i + .01 * math.sin(i / 7)) for i in range(121)}
        one = family_bootstrap({"a": path}, "a", block_days=10, draws=200)
        duplicate = family_bootstrap({"a": path, "b": dict(path)}, "a", block_days=10, draws=200)
        self.assertEqual(one["max_mean_reality_check_pvalue"], duplicate["max_mean_reality_check_pvalue"])
        self.assertEqual(one["selected_annualized_geometric_return_95_interval_pct"],
                         duplicate["selected_annualized_geometric_return_95_interval_pct"])

    def test_calendar_gap_is_not_treated_as_one_day(self):
        path = {str(i * 86_400_000): 1 + i / 10000 for i in range(120) if i != 50}
        with self.assertRaises(ValueError):
            family_bootstrap({"a": path}, "a", block_days=10, draws=200)

    def test_flat_cash_has_no_claim_of_positive_edge(self):
        path = {str(i * 86_400_000): 1.0 for i in range(121)}
        result = family_bootstrap({"cash": path}, "cash", block_days=10, draws=200)
        self.assertEqual(result["max_mean_reality_check_pvalue"], 1)
        self.assertEqual(result["selected_annualized_geometric_return_95_interval_pct"], [0, 0])


if __name__ == "__main__":
    unittest.main()
