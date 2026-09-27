import copy
import math
import unittest

from jev_trader.hourly_forecast_features import ECONOMIC, flatten_contexts


def context():
    return {**dict.fromkeys(ECONOMIC, .01), "latest_observed_close_ms": 0,
            "context_sha256": "synthetic", "spot_close": 1000,
            "quote_volume24": {"spot": 1e8, "futures": 2e8},
            "spot_hourly": {"structure": {"fibonacci": {"60": {"high_after_low": True,
                "distance_to_level_pct": {"0.618": .2}}}}, "participation": {"distance_vwap20_pct": None}},
            "futures_hourly": {"trend": {"distance_sma_pct": {"200": -.1}}}}


class HourlyFeaturesTests(unittest.TestCase):
    def test_all_leaves_funding_and_calendar_preserved_without_nominal_price_or_timestamps(self):
        row = context()
        before = copy.deepcopy(row)
        states, fields, digest = flatten_contexts({3_600_000: row})
        output = states[3_600_000]
        self.assertEqual(row, before)
        self.assertEqual(output["spot.structure.fibonacci.60.high_after_low"], 1.)
        self.assertEqual(output["spot.structure.fibonacci.60.distance_to_level_pct.0.618"], .2)
        self.assertIsNone(output["spot.participation.distance_vwap20_pct"])
        self.assertEqual(output["hour_cos"], 1)
        self.assertEqual(output["hour_sin"], 0)
        self.assertAlmostEqual(output["weekday_sin"], math.sin(2*math.pi*3/7))
        self.assertTrue(set(ECONOMIC).issubset(fields))
        self.assertNotIn("latest_observed_close_ms", fields)
        self.assertNotIn("spot_close", fields)
        self.assertEqual(output["context_sha256"], "synthetic")
        self.assertEqual(len(digest), 64)

    def test_deterministic_order_and_future_append_preserves_earlier_states(self):
        one = context()
        two = {**context(), "latest_observed_close_ms": 3_600_000}
        old, fields, _ = flatten_contexts({3_600_000: one})
        new, new_fields, digest = flatten_contexts({7_200_000: two, 3_600_000: one})
        self.assertEqual(old[3_600_000], new[3_600_000])
        self.assertEqual(fields, new_fields)
        self.assertEqual(digest, flatten_contexts({3_600_000: one, 7_200_000: two})[2])

    def test_nonfinite_and_schema_drift_rejected(self):
        row = context()
        row["basis_fraction"] = float("nan")
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            flatten_contexts({1: row})
        row = context()
        row["spot_hourly"]["new_field"] = 1
        with self.assertRaisesRegex(ValueError, "schema changed"):
            flatten_contexts({1: context(), 2: row})


if __name__ == "__main__":
    unittest.main()
