import unittest

from jev_trader.binance_data import Bar
from jev_trader.broad_technical import feature_bundle, flatten
from test_broad import sample_data


class TechnicalPredictionTests(unittest.TestCase):
    def test_flatten_preserves_fibonacci_and_boolean_without_imputation(self):
        row = flatten({"fib": {"high_after_low": True, "distance": .382}, "missing": None})
        self.assertEqual(row["technical.fib.high_after_low"], 1.0)
        self.assertEqual(row["technical.fib.distance"], .382)
        self.assertIsNone(row["technical.missing"])

    def test_bundle_includes_every_market_state_field_and_is_causal(self):
        data = sample_data(235)
        original, fields, quality = feature_bundle(data)
        self.assertEqual(quality["economic_fields"], 10)
        self.assertEqual(quality["technical_fields"], 50)
        self.assertTrue(any("fibonacci" in f for f in fields))
        self.assertTrue(any("distance_sma" in f for f in fields))
        cutoff = data["klines"]["C0USDT"][229].open_ms + 86_400_000
        for symbol, bars in data["klines"].items():
            data["klines"][symbol][230:] = [Bar(b.open_ms, 1, 1, 1, 1, 1, 1, 1, 1) for b in bars[230:]]
        changed, changed_fields, _ = feature_bundle(data)
        self.assertEqual(fields, changed_fields)
        for s, rows in original.items():
            for t, row in rows.items():
                if t <= cutoff:
                    self.assertEqual(row, changed[s][t])


if __name__ == "__main__":
    unittest.main()
