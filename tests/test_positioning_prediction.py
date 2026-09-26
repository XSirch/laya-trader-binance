"""Paired synthetic tree tests; no market files, network, or financial replay."""

import copy
import importlib.util
import math
from types import SimpleNamespace
import unittest

from jev_trader.positioning_features import FEATURES
from jev_trader.positioning_prediction import build_forecasts
from jev_trader.tree_prediction import (
    DAY_MS, ESTIMATOR_PARAMETERS, FIRST_LABEL_MS, HOUR_MS, WEEK_MS,
    _hash, build_forecasts as frozen_forecasts,
)


FIELDS = ("volatility",) + tuple(f"feature_{index:02d}" for index in range(59))
FIRST_MONDAY = FIRST_LABEL_MS + 2 * DAY_MS


def fixture(weeks=66, assets=8):
    dates = [FIRST_MONDAY + week * WEEK_MS for week in range(weeks)]
    states, prices = {}, {}
    for index in range(assets):
        symbol = f"ASSET{index}"
        states[symbol] = {}
        for week, cutoff in enumerate(dates):
            row = {field: index * .1 + week * .001 + number * .0001
                   for number, field in enumerate(FIELDS)}
            extra = {field: index * .03 + week * .002 + number * .0003
                     for number, field in enumerate(FEATURES)}
            states[symbol][cutoff] = {
                **row, **extra, "volatility": .02, "latest_observed_close_ms": cutoff,
                "quote_volume20": 20_000_000, "original_marker": "retained",
                "positioning_source_days": ["lagged fixture"],
                "historical_point_in_time_verified": False}
        lookup = {}
        for hour in range(weeks * 168 + 1):
            timestamp = FIRST_MONDAY + HOUR_MS + hour * HOUR_MS
            price = 100 * math.exp(index * .0000001 * hour + .003 * math.sin(hour / (20 + index)))
            lookup[timestamp] = SimpleNamespace(open_ms=timestamp, open=price, trades=10)
        prices[symbol] = lookup
    return {"klines": prices}, states, dates


class SyntheticEstimator:
    def __init__(self, **parameters):
        self.parameters = parameters

    def fit(self, x, y, sample_weight):
        self.x = [list(row) for row in x]
        self.y = list(y)
        self.weights = list(sample_weight)
        numerator = math.fsum(row[1] * target * weight
                              for row, target, weight in zip(x, y, sample_weight))
        denominator = math.fsum(row[1] ** 2 * weight for row, weight in zip(x, sample_weight))
        self.scale = numerator / denominator if denominator else 0
        return self

    def predict(self, x):
        return [.4 + self.scale * row[1] for row in x]


class Factory:
    def __init__(self):
        self.estimators = []

    def __call__(self, **parameters):
        estimator = SyntheticEstimator(**parameters)
        self.estimators.append(estimator)
        return estimator


def build(hourly, states, events=(), factory=None, fields=FIELDS):
    return build_forecasts(hourly, states, fields, events,
                           estimator_factory=factory if factory is not None else Factory())


def iso(timestamp):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(timestamp / 1000, timezone.utc).isoformat()


class PositioningPredictionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hourly, cls.states, cls.dates = fixture()

    def test_control_matches_entire_frozen_report_with_synthetic_estimator(self):
        paired = build(self.hourly, self.states)
        reference = frozen_forecasts(self.hourly, self.states, FIELDS, [], estimator_factory=Factory())
        self.assertEqual(paired["control60"], reference)
        self.assertEqual(paired["control60"]["signals"], paired["augmented68"]["signals"])
        self.assertFalse(paired["matching_audit"]["historical_point_in_time_verified"])

    def test_same_labels_weights_folds_and_original_vector_prefix(self):
        hourly, states, dates = fixture(weeks=58, assets=9)
        for cutoff in dates[:26]:
            del states["ASSET8"][cutoff]
        factory = Factory()
        result = build(hourly, states, factory=factory)
        self.assertEqual(len(factory.estimators), 2 * len(result["matching_audit"]["training_audits"]))
        for control, augmented in zip(factory.estimators[::2], factory.estimators[1::2]):
            self.assertEqual(control.parameters, ESTIMATOR_PARAMETERS)
            self.assertEqual(augmented.parameters, ESTIMATOR_PARAMETERS)
            self.assertEqual(control.y, augmented.y)
            self.assertEqual(control.weights, augmented.weights)
            self.assertEqual(control.x, [row[:60] for row in augmented.x])
            self.assertTrue(all(len(row) == 60 for row in control.x))
            self.assertTrue(all(len(row) == 68 for row in augmented.x))
        control_fits, augmented_fits = result["control60"]["fit_audits"], result["augmented68"]["fit_audits"]
        for control, augmented, common in zip(control_fits, augmented_fits,
                                               result["matching_audit"]["training_audits"]):
            self.assertEqual({k: v for k, v in control.items() if k not in ("fields", "training_input_sha256")},
                             {k: v for k, v in augmented.items() if k not in ("fields", "training_input_sha256")})
            self.assertEqual(control["training_samples"], common["training_samples"])
            self.assertEqual(len(common["training_identity_label_weight_sha256"]), 64)
        for name in ("control60", "augmented68"):
            projection = [{key: value for key, value in row.items() if key != "prediction"}
                          for row in result[name]["prediction_errors"]]
            self.assertEqual(_hash(projection), result["matching_audit"]["shared_evaluation_identity_actual_sha256"])

    def test_expanding_52_completed_weeks_strict_embargo_and_monthly_refits(self):
        result = build(self.hourly, self.states)
        for name in ("control60", "augmented68"):
            first = result[name]["fit_audits"][0]
            self.assertEqual(first["fit_cutoff_ms"], self.dates[53])
            self.assertEqual(first["training_weeks"], 52)
            self.assertEqual(first["latest_label_end_ms"], self.dates[52] + HOUR_MS)
            self.assertLess(first["latest_label_end_ms"], first["fit_cutoff_ms"])
            self.assertEqual(first["training_signal_dates_ms"], self.dates[:52])
            self.assertNotIn(self.dates[52], result[name]["signals"]["ASSET0"])
            from datetime import datetime, timezone
            months = [datetime.fromtimestamp(row["fit_cutoff_ms"] / 1000, timezone.utc).strftime("%Y-%m")
                      for row in result[name]["fit_audits"]]
            self.assertEqual(len(months), len(set(months)))

    def test_future_prices_and_extra_fields_cannot_rewrite_past_predictions(self):
        baseline = build(self.hourly, self.states)
        hourly, states = copy.deepcopy(self.hourly), copy.deepcopy(self.states)
        cutoff = self.dates[57]
        for symbol, lookup in hourly["klines"].items():
            for timestamp, bar in lookup.items():
                if timestamp >= cutoff:
                    bar.open *= 1 + int(symbol[-1]) * .1
        for rows in states.values():
            for timestamp, row in rows.items():
                if timestamp > cutoff:
                    row["feature_00"] *= 100
                    row[FEATURES[0]] *= 1000
        changed = build(hourly, states)
        for name in ("control60", "augmented68"):
            for symbol in baseline[name]["signals"]:
                self.assertEqual({t: row for t, row in baseline[name]["signals"][symbol].items() if t <= cutoff},
                                 {t: row for t, row in changed[name]["signals"][symbol].items() if t <= cutoff})
            for key, date_key in (("fit_audits", "fit_cutoff_ms"), ("prediction_audits", "signal_ms")):
                self.assertEqual([row for row in baseline[name][key] if row[date_key] <= cutoff],
                                 [row for row in changed[name][key] if row[date_key] <= cutoff])
        self.assertEqual([row for row in baseline["matching_audit"]["training_audits"] if row["fit_cutoff_ms"] <= cutoff],
                         [row for row in changed["matching_audit"]["training_audits"] if row["fit_cutoff_ms"] <= cutoff])

    def test_missing_future_label_excludes_whole_week_but_not_current_forecast(self):
        baseline = build(self.hourly, self.states)
        hourly = copy.deepcopy(self.hourly)
        cutoff = self.dates[58]
        del hourly["klines"]["ASSET7"][cutoff + 2 * DAY_MS]
        changed = build(hourly, self.states)
        for name in ("control60", "augmented68"):
            for symbol in self.states:
                self.assertEqual(changed[name]["signals"][symbol][cutoff], baseline[name]["signals"][symbol][cutoff])
            self.assertFalse(any(row["signal_ms"] == cutoff for row in changed[name]["prediction_errors"]))
            rejected = next(row for row in changed[name]["unavailable_label_weeks"] if row["signal_ms"] == cutoff)
            self.assertEqual(rejected["failures"][0]["reason"], "missing_hour")
            self.assertEqual(rejected["eligible_symbols"], sorted(self.states))
        self.assertEqual(changed["control60"]["unavailable_label_weeks"],
                         changed["augmented68"]["unavailable_label_weeks"])

    def test_lifecycle_and_missing_state_apply_to_both_models(self):
        hourly, states, dates = fixture(weeks=58, assets=10)
        del states["ASSET8"][dates[54]]
        restricted = dates[55] + HOUR_MS
        events = [{"symbol": "ASSET9", "published_utc": iso(restricted - DAY_MS),
                   "new_positions_stop_utc": iso(restricted),
                   "automatic_settlement_utc": iso(restricted + DAY_MS)}]
        result = build(hourly, states, events)
        for name in ("control60", "augmented68"):
            self.assertNotIn(dates[54], result[name]["signals"]["ASSET8"])
            self.assertIn(dates[54], result[name]["signals"]["ASSET9"])
            self.assertNotIn(dates[55], result[name]["signals"]["ASSET9"])
        self.assertEqual({s: sorted(rows) for s, rows in result["control60"]["signals"].items()},
                         {s: sorted(rows) for s, rows in result["augmented68"]["signals"].items()})
        reference = frozen_forecasts(hourly, states, FIELDS, events, estimator_factory=Factory())
        self.assertEqual(result["control60"], reference)

    def test_nonfinite_missing_augmented_fields_and_bad_schema_rejected(self):
        for field, value in ((FEATURES[0], float("nan")), (FEATURES[1], float("inf")),
                             (FEATURES[2], True), ("latest_observed_close_ms", self.dates[54] + DAY_MS)):
            with self.subTest(field=field):
                states = copy.deepcopy(self.states)
                states["ASSET0"][self.dates[54]][field] = value
                with self.assertRaises(ValueError):
                    build(self.hourly, states)
        states = copy.deepcopy(self.states)
        del states["ASSET0"][self.dates[54]][FEATURES[-1]]
        with self.assertRaises(ValueError):
            build(self.hourly, states)
        for fields in (FIELDS[:-1], FIELDS + FEATURES, FIELDS[:-1] + (FIELDS[0],),
                       FIELDS[:-1] + (FEATURES[0],), FIELDS[:-1] + ("timestamp",)):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                build(self.hourly, self.states, fields=fields)

    def test_inputs_remain_unchanged_and_dictionary_order_does_not_matter(self):
        before = copy.deepcopy((self.hourly, self.states))
        baseline = build(self.hourly, self.states)
        self.assertEqual((self.hourly, self.states), before)
        states = {s: dict(reversed(list(rows.items()))) for s, rows in reversed(list(self.states.items()))}
        hourly = {"klines": {s: dict(reversed(list(rows.items())))
                             for s, rows in reversed(list(self.hourly["klines"].items()))}}
        self.assertEqual(baseline, build(hourly, states))

    def test_augmented_predictions_can_change_without_changing_matched_targets(self):
        class ExtraEstimator(SyntheticEstimator):
            def predict(self, x):
                return [row[-1] if len(row) == 68 else .4 + self.scale * row[1] for row in x]
        result = build(self.hourly, self.states, factory=ExtraEstimator)
        self.assertNotEqual(result["control60"]["signals"], result["augmented68"]["signals"])
        for control, augmented in zip(result["control60"]["prediction_errors"], result["augmented68"]["prediction_errors"]):
            self.assertEqual({k: v for k, v in control.items() if k != "prediction"},
                             {k: v for k, v in augmented.items() if k != "prediction"})

    def test_bad_estimator_predictions_rejected(self):
        class BadEstimator(SyntheticEstimator):
            def predict(self, x):
                return [float("nan")] * len(x)
        with self.assertRaisesRegex(ValueError, "nonfinite predictions"):
            build(self.hourly, self.states, factory=BadEstimator)

    @unittest.skipUnless(importlib.util.find_spec("sklearn") is not None, "sklearn unavailable in this interpreter")
    def test_genuine_sklearn_control_matches_frozen_and_pair_is_reproducible(self):
        hourly, states, _ = fixture(weeks=55)
        first = build_forecasts(hourly, states, FIELDS, [])
        reference = frozen_forecasts(hourly, states, FIELDS, [])
        second = build_forecasts(hourly, states, FIELDS, [])
        self.assertEqual(first["control60"], reference)
        self.assertEqual(first, second)
        for name in ("control60", "augmented68"):
            self.assertFalse(first[name]["design"]["injected_estimator"])
            self.assertGreater(len(first[name]["prediction_audits"]), 0)
            self.assertTrue(all(math.isfinite(row["prediction"])
                                for rows in first[name]["signals"].values() for row in rows.values()))


if __name__ == "__main__":
    unittest.main()
