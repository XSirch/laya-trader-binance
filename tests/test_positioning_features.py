import copy
from datetime import datetime, timezone
import math
import unittest

from jev_trader.positioning_features import DAY_MS, FEATURES, augment


FIELDS = tuple("f"+str(i) for i in range(60))
CUTOFF = int(datetime(2022, 1, 3, tzinfo=timezone.utc).timestamp()*1000)


def fixture():
    state = {**dict.fromkeys(FIELDS, 1.0), "latest_observed_close_ms": CUTOFF, "quote_volume20": 100.0}
    snapshots = {"BTCUSDT": {}}
    for day, oi in (("2021-12-31", 200.0), ("2021-12-24", 100.0), ("2021-12-03", 50.0)):
        timestamp = int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()*1000)+DAY_MS-300_000
        snapshots["BTCUSDT"][day] = {"symbol": "BTCUSDT", "day": day, "available": True, "last_observed_timestamp_ms": timestamp,
            "timezone_assumption": "UTC", "values": {"sum_open_interest": oi,
            "sum_open_interest_value": 400.0, "count_toptrader_long_short_ratio": 2.0,
            "sum_toptrader_long_short_ratio": 4.0, "count_long_short_ratio": 1.0}}
    return {"BTCUSDT": {CUTOFF: state}}, snapshots


class PositioningFeaturesTests(unittest.TestCase):
    def test_exact_lags_units_and_original_fields_preserved(self):
        states, snapshots = fixture()
        out, fields, quality = augment(states, FIELDS, snapshots)
        row = out["BTCUSDT"][CUTOFF]
        expected = (math.log(4), math.log(2), math.log(4), math.log(2), math.log(4), 0, math.log(2), math.log(2))
        for name, value in zip(FEATURES, expected):
            self.assertAlmostEqual(row[name], value)
        self.assertEqual(fields, FIELDS+FEATURES)
        self.assertEqual([row[f] for f in FIELDS], [states["BTCUSDT"][CUTOFF][f] for f in FIELDS])
        self.assertEqual(CUTOFF-row["positioning_latest_economic_ms"], 2*DAY_MS+300_000)
        self.assertFalse(quality["historical_point_in_time_verified"])

    def test_newer_weekend_and_future_data_cannot_change_monday_features(self):
        states, snapshots = fixture()
        expected = augment(states, FIELDS, snapshots)
        snapshots["BTCUSDT"]["2022-01-02"] = {"available": True, "values": {"sum_open_interest": 1e100}}
        snapshots["BTCUSDT"]["2022-01-07"] = {"available": False}
        self.assertEqual(expected, augment(states, FIELDS, snapshots))

    def test_missing_or_bad_quality_does_not_fall_back_to_another_day(self):
        for reason in ("missing", "unavailable"):
            states, snapshots = fixture()
            if reason == "missing":
                del snapshots["BTCUSDT"]["2021-12-24"]
            else:
                snapshots["BTCUSDT"]["2021-12-24"]["available"] = False
            out, _, quality = augment(states, FIELDS, snapshots)
            self.assertFalse(out["BTCUSDT"])
            self.assertEqual(quality["unavailable_observations"][0]["failures"][0]["day"], "2021-12-24")

    def test_symbol_independent_missingness_and_no_input_mutation(self):
        states, snapshots = fixture()
        states["ETHUSDT"] = copy.deepcopy(states["BTCUSDT"])
        before = copy.deepcopy((states, snapshots))
        out, _, quality = augment(states, FIELDS, snapshots)
        self.assertEqual((states, snapshots), before)
        self.assertEqual(len(out["BTCUSDT"]), 1)
        self.assertEqual(out["ETHUSDT"], {})
        self.assertEqual(len(quality["unavailable_observations"]), 1)

    def test_wrong_snapshot_timestamp_or_timezone_rejected(self):
        for key, value in (("last_observed_timestamp_ms", CUTOFF), ("timezone_assumption", "local"),
                           ("symbol", "ETHUSDT"), ("day", "2021-12-24")):
            states, snapshots = fixture()
            snapshots["BTCUSDT"]["2021-12-31"][key] = value
            with self.assertRaises(ValueError):
                augment(states, FIELDS, snapshots)

    def test_nonpositive_and_nonfinite_inputs_rejected(self):
        for invalid in (0, -1, math.nan, math.inf, True):
            states, snapshots = fixture()
            snapshots["BTCUSDT"]["2021-12-31"]["values"]["sum_open_interest"] = invalid
            with self.assertRaises(ValueError):
                augment(states, FIELDS, snapshots)

    def test_non_monday_ignored_but_invalid_cutoff_rejected(self):
        states, snapshots = fixture()
        states["BTCUSDT"][CUTOFF+DAY_MS] = {"latest_observed_close_ms": CUTOFF+DAY_MS}
        out, _, _ = augment(states, FIELDS, snapshots)
        self.assertEqual(list(out["BTCUSDT"]), [CUTOFF])
        states["BTCUSDT"][CUTOFF+1] = {}
        with self.assertRaises(ValueError):
            augment(states, FIELDS, snapshots)


if __name__ == "__main__":
    unittest.main()
