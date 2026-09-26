"""Synthetic evidence for the fixed, purged monthly histogram-tree forecaster."""

import copy
import importlib.util
import math
from types import SimpleNamespace
import unittest

from jev_trader.tree_prediction import (
    DAY_MS, ESTIMATOR_PARAMETERS, FIRST_LABEL_MS, HOUR_MS, WEEK_MS, build_forecasts,
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
            states[symbol][cutoff] = {**row, "volatility": .02,
                                      "latest_observed_close_ms": cutoff,
                                      "quote_volume20": 20_000_000, "original_marker": "retained"}
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


class TreePredictionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hourly, cls.states, cls.dates = fixture()

    def test_52_completed_weeks_are_strictly_purged_and_fit_monthly(self):
        factory = Factory()
        result = build(self.hourly, self.states, factory=factory)
        first = result["fit_audits"][0]
        self.assertEqual(first["fit_cutoff_ms"], self.dates[53])
        self.assertEqual(first["training_weeks"], 52)
        self.assertEqual(first["training_samples"], 52 * 8)
        self.assertEqual(first["latest_label_end_ms"], self.dates[52] + HOUR_MS)
        self.assertLess(first["latest_label_end_ms"], first["fit_cutoff_ms"])
        self.assertEqual(first["training_signal_dates_ms"], self.dates[:52])
        self.assertNotIn(self.dates[52], result["signals"]["ASSET0"])
        self.assertEqual(len(factory.estimators), len(result["fit_audits"]))
        fit_cutoffs = [row["fit_cutoff_ms"] for row in result["fit_audits"]]
        for row in result["prediction_audits"]:
            self.assertEqual(row["fit_cutoff_ms"], max(t for t in fit_cutoffs if t <= row["signal_ms"]))
        from datetime import datetime, timezone
        months = [datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%Y-%m") for t in fit_cutoffs]
        self.assertEqual(len(months), len(set(months)))

    def test_fixed_parameters_all_raw_fields_original_state_and_centering(self):
        factory = Factory()
        result = build(self.hourly, self.states, factory=factory)
        self.assertEqual(factory.estimators[0].parameters, ESTIMATOR_PARAMETERS)
        self.assertEqual(len(factory.estimators[0].x[0]), 60)
        self.assertEqual(factory.estimators[0].x[0],
                         [self.states["ASSET0"][self.dates[0]][field] for field in FIELDS])
        for cutoff in result["signals"]["ASSET0"]:
            centered = [rows[cutoff]["prediction"] for rows in result["signals"].values()]
            self.assertAlmostEqual(math.fsum(centered), 0, places=13)
            self.assertEqual(result["signals"]["ASSET0"][cutoff]["original_marker"], "retained")
            self.assertIn("raw_prediction", result["signals"]["ASSET0"][cutoff])
        self.assertNotIn("prediction", self.states["ASSET0"][self.dates[53]])
        self.assertFalse(result["design"]["label_funding_included"])
        self.assertFalse(result["design"]["label_costs_included"])

    def test_label_uses_actual_delayed_opens_and_demeans_whole_cross_section(self):
        factory = Factory()
        build(self.hourly, self.states, factory=factory)
        expected = []
        for symbol in sorted(self.states):
            lookup = self.hourly["klines"][symbol]
            expected.append(lookup[self.dates[1] + HOUR_MS].open /
                            lookup[self.dates[0] + HOUR_MS].open - 1)
        mean = math.fsum(expected) / len(expected)
        for actual, raw in zip(factory.estimators[0].y[:8], expected):
            self.assertAlmostEqual(actual, raw - mean, places=14)
        self.assertAlmostEqual(math.fsum(factory.estimators[0].y[:8]), 0, places=14)

    def test_each_training_week_has_equal_weight_with_varying_cross_section(self):
        hourly, states, dates = fixture(weeks=55, assets=9)
        for cutoff in dates[:26]:
            states["ASSET8"][cutoff]["quote_volume20"] = 1
        factory = Factory()
        result = build(hourly, states, factory=factory)
        fit = factory.estimators[0]
        self.assertEqual(result["fit_audits"][0]["training_samples"], 26 * 8 + 26 * 9)
        self.assertAlmostEqual(math.fsum(fit.weights), len(fit.weights), places=10)
        self.assertAlmostEqual(math.fsum(fit.weights[:8]), math.fsum(fit.weights[26 * 8:26 * 8 + 9]))
        self.assertGreater(fit.weights[0], fit.weights[-1])

    def test_future_price_and_feature_mutation_cannot_rewrite_past_predictions(self):
        baseline = build(self.hourly, self.states)
        hourly, states = copy.deepcopy(self.hourly), copy.deepcopy(self.states)
        cutoff = self.dates[57]
        for symbol, lookup in hourly["klines"].items():
            factor = 1 + int(symbol[-1]) * .1
            for timestamp, bar in lookup.items():
                if timestamp >= cutoff:
                    bar.open *= factor
        for rows in states.values():
            for timestamp, row in rows.items():
                if timestamp > cutoff:
                    row["feature_00"] *= 100
        changed = build(hourly, states)
        for symbol in baseline["signals"]:
            self.assertEqual({t: row for t, row in baseline["signals"][symbol].items() if t <= cutoff},
                             {t: row for t, row in changed["signals"][symbol].items() if t <= cutoff})
        self.assertEqual([row for row in baseline["fit_audits"] if row["fit_cutoff_ms"] <= cutoff],
                         [row for row in changed["fit_audits"] if row["fit_cutoff_ms"] <= cutoff])
        self.assertEqual([row for row in baseline["prediction_audits"] if row["signal_ms"] <= cutoff],
                         [row for row in changed["prediction_audits"] if row["signal_ms"] <= cutoff])

    def test_forecast_at_current_week_survives_missing_future_label(self):
        baseline = build(self.hourly, self.states)
        hourly = copy.deepcopy(self.hourly)
        cutoff = self.dates[58]
        del hourly["klines"]["ASSET7"][cutoff + 2 * DAY_MS]
        result = build(hourly, self.states)
        for symbol in self.states:
            self.assertEqual(result["signals"][symbol][cutoff], baseline["signals"][symbol][cutoff])
        self.assertFalse(any(row["signal_ms"] == cutoff for row in result["prediction_errors"]))
        rejected = next(row for row in result["unavailable_label_weeks"] if row["signal_ms"] == cutoff)
        self.assertEqual(rejected["failures"][0]["reason"], "missing_hour")
        self.assertEqual(len(rejected["eligible_symbols"]), 8)

    def test_missing_or_invalid_hour_excludes_entire_week_without_dropping_asset(self):
        for mode in ("missing", "nonfinite", "zero", "wrong_timestamp", "untradable"):
            with self.subTest(mode=mode):
                hourly = {"klines": {s: dict(bars) for s, bars in self.hourly["klines"].items()}}
                timestamp = self.dates[10] + (HOUR_MS if mode == "untradable" else 2 * HOUR_MS)
                if mode == "missing":
                    del hourly["klines"]["ASSET3"][timestamp]
                else:
                    bar = copy.copy(hourly["klines"]["ASSET3"][timestamp])
                    if mode == "nonfinite":
                        bar.open = float("nan")
                    elif mode == "zero":
                        bar.open = 0
                    elif mode == "wrong_timestamp":
                        bar.open_ms += 1
                    else:
                        bar.trades = 0
                    hourly["klines"]["ASSET3"][timestamp] = bar
                result = build(hourly, self.states)
                rejected = next(row for row in result["unavailable_label_weeks"]
                                if row["signal_ms"] == self.dates[10])
                self.assertEqual(rejected["eligible_symbols"], sorted(self.states))
                self.assertEqual(rejected["failures"][0]["symbol"], "ASSET3")
                self.assertTrue(all(self.dates[10] not in row["training_signal_dates_ms"]
                                    for row in result["fit_audits"]))

    def test_interior_zero_trades_retained_but_exit_zero_trades_rejects_label(self):
        hourly = {"klines": {s: dict(bars) for s, bars in self.hourly["klines"].items()}}
        interior = self.dates[10] + 2 * HOUR_MS
        hourly["klines"]["ASSET0"][interior] = SimpleNamespace(open_ms=interior, open=100, trades=0)
        result = build(hourly, self.states)
        self.assertFalse(any(row["signal_ms"] == self.dates[10] for row in result["unavailable_label_weeks"]))
        endpoint = self.dates[11] + HOUR_MS
        hourly["klines"]["ASSET0"][endpoint] = SimpleNamespace(open_ms=endpoint, open=100, trades=0)
        result = build(hourly, self.states)
        rejected = next(row for row in result["unavailable_label_weeks"] if row["signal_ms"] == self.dates[10])
        self.assertEqual(rejected["failures"][0]["reason"], "untradable_endpoint")

    def test_lifecycle_restriction_uses_publication_and_execution_time_only(self):
        hourly, states, dates = fixture(weeks=57, assets=9)
        restricted = dates[55] + HOUR_MS
        events = [{"symbol": "ASSET8", "published_utc": iso(restricted - DAY_MS),
                   "new_positions_stop_utc": iso(restricted),
                   "automatic_settlement_utc": iso(restricted + DAY_MS)}]
        baseline = build(hourly, states)
        result = build(hourly, states, events)
        self.assertEqual(result["signals"]["ASSET8"][dates[54]], baseline["signals"]["ASSET8"][dates[54]])
        self.assertNotIn(dates[55], result["signals"]["ASSET8"])
        self.assertIn(dates[55], result["signals"]["ASSET0"])
        self.assertEqual([row for row in result["prediction_audits"] if row["signal_ms"] < dates[55]],
                         [row for row in baseline["prediction_audits"] if row["signal_ms"] < dates[55]])

    def test_eight_assets_eligibility_and_exact_limits(self):
        states = copy.deepcopy(self.states)
        cutoff = self.dates[54]
        states["ASSET0"][cutoff]["quote_volume20"] = 10_000_000
        states["ASSET0"][cutoff]["volatility"] = .005
        states["ASSET1"][cutoff]["volatility"] = .15
        self.assertIn(cutoff, build(self.hourly, states)["signals"]["ASSET0"])
        states["ASSET0"][cutoff]["quote_volume20"] -= 1
        result = build(self.hourly, states)
        self.assertTrue(all(cutoff not in rows for rows in result["signals"].values()))
        self.assertIn("Fewer than eight", next(row for row in result["unavailable_label_weeks"]
                                              if row["signal_ms"] == cutoff)["reason"])

    def test_deterministic_dictionary_order_and_audit_hashes(self):
        baseline = build(self.hourly, self.states)
        reversed_states = {s: dict(reversed(list(rows.items())))
                           for s, rows in reversed(list(self.states.items()))}
        reversed_hourly = {"klines": {s: dict(reversed(list(rows.items())))
                                     for s, rows in reversed(list(self.hourly["klines"].items()))}}
        changed = build(reversed_hourly, reversed_states)
        self.assertEqual(baseline, changed)
        for audit in baseline["fit_audits"]:
            self.assertEqual(len(audit["training_input_sha256"]), 64)
        for audit in baseline["prediction_audits"]:
            self.assertEqual(len(audit["predictions_sha256"]), 64)

    def test_invalid_fields_nonfinite_state_and_mismatched_cutoff_rejected(self):
        for fields in (FIELDS[:-1], FIELDS[:-1] + (FIELDS[0],), FIELDS[:-1] + ("symbol",),
                       FIELDS[:-1] + ("latest_observed_close_ms",)):
            with self.subTest(fields=fields[-1]), self.assertRaises(ValueError):
                build(self.hourly, self.states, fields=fields)
        for change in ({"feature_58": float("inf")},
                       {"latest_observed_close_ms": self.dates[54] + DAY_MS},
                       {"quote_volume20": float("nan")}, {"volatility": True}):
            states = copy.deepcopy(self.states)
            states["ASSET0"][self.dates[54]].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                build(self.hourly, states)
        states = copy.deepcopy(self.states)
        states["ASSET0"][self.dates[54] + 1] = states["ASSET0"].pop(self.dates[54])
        with self.assertRaisesRegex(ValueError, "UTC midnight"):
            build(self.hourly, states)

    def test_bad_estimator_predictions_rejected(self):
        class BadEstimator(SyntheticEstimator):
            def predict(self, x):
                return [float("nan")] * len(x)
        with self.assertRaisesRegex(ValueError, "nonfinite predictions"):
            build(self.hourly, self.states, factory=BadEstimator)

    def test_pre_2022_labels_do_not_count_towards_minimum(self):
        hourly, states, dates = fixture(weeks=54)
        old = FIRST_MONDAY - WEEK_MS
        for rows in states.values():
            rows[old] = {**rows[dates[0]], "latest_observed_close_ms": old}
        result = build(hourly, states)
        self.assertEqual(result["fit_audits"][0]["training_weeks"], 52)
        self.assertEqual(result["fit_audits"][0]["first_training_signal_ms"], dates[0])

    @unittest.skipUnless(importlib.util.find_spec("sklearn") is not None, "sklearn unavailable in this interpreter")
    def test_genuine_sklearn_fit_is_finite_and_reproducible(self):
        hourly, states, _ = fixture(weeks=55)
        first = build_forecasts(hourly, states, FIELDS, [])
        second = build_forecasts(hourly, states, FIELDS, [])
        self.assertEqual(first, second)
        self.assertFalse(first["design"]["injected_estimator"])
        self.assertGreater(len(first["prediction_audits"]), 0)
        self.assertTrue(all(math.isfinite(row["prediction"])
                            for rows in first["signals"].values() for row in rows.values()))


if __name__ == "__main__":
    unittest.main()
