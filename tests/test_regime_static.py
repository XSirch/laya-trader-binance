import unittest

from jev_trader.binance_data import utc_ms
from jev_trader.regime_static import development_scale


class StaticScaleTests(unittest.TestCase):
    def rows(self, weights, date="2022-01-03"):
        return [{"execution_ms": utc_ms(date), "target_weights": weights}]

    def test_both_sides_count_and_returns_are_not_used(self):
        reference = self.rows({"A": .25, "B": -.25})
        candidate = self.rows({"A": .1, "B": -.1})
        candidate[0]["future_return"] = 999
        self.assertAlmostEqual(development_scale(candidate, reference), .4)

    def test_future_calibration_is_rejected(self):
        rows = self.rows({"A": .1}, "2024-01-01")
        with self.assertRaises(ValueError):
            development_scale(rows, rows)

    def test_calendar_mismatch_and_empty_exposure_fail(self):
        with self.assertRaises(ValueError):
            development_scale(self.rows({"A": .1}), self.rows({"A": .2}, "2022-01-04"))
        with self.assertRaises(ValueError):
            development_scale(self.rows({}), self.rows({}))
