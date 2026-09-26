import copy
import unittest

from jev_trader.binance_data import utc_ms
from jev_trader.broad_prediction import FIELDS, WEEK, forecasts, portfolio, rank_vectors


def states_at(t, count=10):
    result = {}
    for i in range(count):
        s = "BTCUSDT" if i == 0 else f"C{i}USDT"
        result[s] = {**{f: i / 20 for f in FIELDS}, "quote_volume20": 20_000_000,
                     "volatility": .01 + i / 100, "beta60": .5 + i / 10,
                     "prediction": (i - 4.5) / 100, "latest_observed_close_ms": t}
    return result


class PredictionTests(unittest.TestCase):
    def test_midranks_do_not_break_ties_by_symbol(self):
        state = states_at(0)
        for f in state.values():
            f["momentum7"] = 7
        vectors = rank_vectors(state)
        self.assertTrue(all(v[0] == 0 for v in vectors.values()))
        self.assertAlmostEqual(sum(v[1] for v in vectors.values()), 0)

    def test_portfolios_are_beta_neutral_and_gross_capped(self):
        state = states_at(0)
        for sizing in ("equal", "inverse_vol"):
            weights = portfolio(state, sizing)
            self.assertLessEqual(sum(abs(v) for v in weights.values()), .5000000001)
            self.assertAlmostEqual(sum(v * state[s]["beta60"] for s, v in weights.items()), 0)
        self.assertEqual(portfolio(state, "zero"), {})
        for f in state.values():
            f["prediction"] = 0
        self.assertEqual(portfolio(state, "equal"), {})

    def test_future_labels_cannot_change_prior_forecasts(self):
        start = utc_ms("2021-01-04")
        dates = [start + i * WEEK for i in range(62)]
        state = {s: {} for s in states_at(start)}
        for t in dates:
            for s, row in states_at(t).items():
                state[s][t] = row
        n = len(FIELDS)
        weeks = [{"signal_ms": t, "label_end_ms": t + WEEK,
                  "gram": [[1.0 if a == b else 0 for b in range(n)] for a in range(n)],
                  "rhs": [.01] * n, "targets": {}} for t in dates]
        original, audits, _ = forecasts(state, weeks, dates)
        cutoff = dates[57]
        altered = copy.deepcopy(weeks)
        for w in altered:
            if w["label_end_ms"] >= cutoff:
                w["rhs"] = [999] * n
        changed, _, _ = forecasts(state, altered, dates)
        self.assertTrue(audits)
        for audit in audits:
            self.assertLess(audit["latest_label_end_ms"], audit["signal_ms"])
            self.assertGreaterEqual(audit["training_weeks"], 52)
        for penalty in original:
            for symbol, rows in original[penalty].items():
                for t, row in rows.items():
                    if t <= cutoff:
                        self.assertEqual(row, changed[penalty][symbol][t])
        self.assertNotEqual(original["0.1"]["BTCUSDT"][dates[-1]], changed["0.1"]["BTCUSDT"][dates[-1]])


if __name__ == "__main__":
    unittest.main()
