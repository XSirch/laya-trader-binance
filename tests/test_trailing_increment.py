import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "trailing_increment", Path(__file__).resolve().parents[1] / "scripts/analyze_trailing_increment.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PairedPathTests(unittest.TestCase):
    def test_identical_portfolios_have_no_increment(self):
        path = {"0": 1.0, "1": .8, "2": 1.2}
        self.assertEqual(module.relative_path(path, path), {"0": 1, "1": 1, "2": 1})

    def test_ratio_is_relative_wealth_not_return_difference(self):
        path = module.relative_path({"0": 1, "1": 1.2}, {"0": 1, "1": 1.1})
        self.assertAlmostEqual(path["1"] - 1, .09090909090909)

    def test_invalid_pairs_fail_closed(self):
        for candidate, reference in (({"0": 1}, {"1": 1}),
                                     ({"0": 1}, {"0": 0}),
                                     ({"0": float("nan")}, {"0": 1})):
            with self.assertRaises(ValueError):
                module.relative_path(candidate, reference)
