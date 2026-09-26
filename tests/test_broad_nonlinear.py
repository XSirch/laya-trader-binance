import math
import copy
import unittest

from jev_trader.broad_nonlinear import FourierVectors
from jev_trader.broad_prediction import FIELDS, WEEK, forecasts
from jev_trader.binance_data import utc_ms
from test_broad_prediction import states_at


class FourierTests(unittest.TestCase):
    def test_fixed_design_is_reproducible_and_does_not_refit(self):
        one, two = FourierVectors(3, 2), FourierVectors(3, 2)
        vector = [.1, -.2, .4]
        expected = one.transform(vector)
        self.assertEqual(expected, two.transform(vector))
        one.transform([100, 200, 300])
        self.assertEqual(expected, one.transform(vector))
        self.assertEqual(len(expected), 64)
        self.assertTrue(all(abs(x) <= math.sqrt(2 / 64) for x in expected))

    def test_scales_reuse_same_random_directions(self):
        one, two = FourierVectors(3, 1), FourierVectors(3, 2)
        self.assertEqual(one.phases, two.phases)
        for a, b in zip(one.weights, two.weights):
            for x, y in zip(a, b):
                self.assertEqual(x, 2 * y)

    def test_wrong_dimension_or_nonfinite_rejected(self):
        vectorizer = FourierVectors(3, 1)
        for row in ([1, 2], [1, 2, float("nan")]):
            with self.assertRaises(ValueError):
                vectorizer.transform(row)

    def test_nonlinear_forecasts_do_not_read_future_labels(self):
        start = utc_ms("2021-01-04")
        dates = [start + i * WEEK for i in range(60)]
        state = {s: {} for s in states_at(start)}
        for t in dates:
            for s, row in states_at(t).items():
                state[s][t] = row
        projection = FourierVectors(len(FIELDS), 2, components=4)
        weeks = [{"signal_ms": t, "label_end_ms": t + WEEK,
                  "gram": [[float(a == b) for b in range(4)] for a in range(4)],
                  "rhs": [.01] * 4, "targets": {}} for t in dates]
        original, audits, _ = forecasts(state, weeks, dates, vectorizer=projection, penalties=(.1,))
        changed = copy.deepcopy(weeks)
        cutoff = dates[56]
        for w in changed:
            if w["label_end_ms"] >= cutoff:
                w["rhs"] = [999] * 4
        modified, _, _ = forecasts(state, changed, dates, vectorizer=projection, penalties=(.1,))
        self.assertTrue(audits)
        for s, rows in original["0.1"].items():
            for t, row in rows.items():
                if t <= cutoff:
                    self.assertEqual(row, modified["0.1"][s][t])
        self.assertNotEqual(original["0.1"]["BTCUSDT"][dates[-1]], modified["0.1"]["BTCUSDT"][dates[-1]])


if __name__ == "__main__":
    unittest.main()
