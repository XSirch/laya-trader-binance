"""Synthetic causal-clock and audit checks, without archived market outcomes."""

from contextlib import nullcontext
import copy
from dataclasses import replace
from datetime import datetime, timezone
import importlib.util
import json
import math
import unittest
from unittest.mock import patch

from jev_trader.binance_data import Bar
from jev_trader import hourly_forecast_prediction as prediction
from jev_trader.tree_prediction import _hash


HOUR = prediction.HOUR_MS
DAY = prediction.DAY_MS
BASE = int(datetime(2023, 1, 30, tzinfo=timezone.utc).timestamp() * 1000)
FIELDS = ("return1", "nullable", "absent")


def fixture(hours=80, start=BASE, executions=None):
    dates = [start + index * HOUR for index in range(hours)] if executions is None else executions
    states, bars = {}, {}
    for index, timestamp in enumerate(dates):
        state = {"return1": .001 * index, "nullable": None if index % 2 == 0 else .02,
                 "absent": None, "latest_observed_close_ms": timestamp - HOUR,
                 "execution_ms": timestamp, "historical_point_in_time_verified": False}
        state["context_sha256"] = _hash(state)
        states[timestamp] = state
        for current in (timestamp, timestamp + HOUR):
            hour = (current - start) / HOUR
            opened = 100 + .001 * hour + .1 * math.sin(hour / 7)
            bars[current] = Bar(current, opened, opened + 1, opened - 1, opened + .1,
                                10, quote_volume=1000, trades=20)
    return bars, states, dates


class Estimator:
    def __init__(self, **parameters):
        self.parameters = parameters
        self.predictions = []

    def fit(self, x, y, sample_weight):
        self.x, self.y, self.weights = copy.deepcopy(x), list(y), list(sample_weight)
        self.mean = math.fsum(y) / len(y)
        return self

    def predict(self, x):
        self.predictions.extend(copy.deepcopy(x))
        return [self.mean + sum(value for value in row if math.isfinite(value)) * .0001 for row in x]


class Factory:
    def __init__(self):
        self.estimators = []

    def __call__(self, **parameters):
        model = Estimator(**parameters)
        self.estimators.append(model)
        return model


def build(bars, states, minimum=4, factory=None, fields=FIELDS, progress=None):
    factory = factory if factory is not None else Factory()
    runtime = (factory, nullcontext, lambda rows: rows, {"injected_estimator": True})
    with patch.object(prediction, "_runtime", return_value=runtime), \
            patch.object(prediction, "MIN_TRAINING_ROWS", minimum):
        return prediction.build_forecasts(bars, states, fields, progress)


class HourlyForecastPredictionTests(unittest.TestCase):
    def test_strict_label_availability_purge_and_one_hour_target(self):
        bars, states, dates = fixture()
        factory = Factory()
        result = build(bars, states, factory=factory)
        fit = result["fit_audits"][0]
        self.assertEqual(fit["first_forecast_execution_ms"], dates[7])
        self.assertEqual(fit["fit_cutoff_ms"], dates[6])
        self.assertEqual(fit["training_execution_dates_ms"], dates[:4])
        self.assertEqual(fit["latest_label_available_ms"], dates[5])
        self.assertLess(fit["latest_label_available_ms"], fit["fit_cutoff_ms"])
        self.assertNotIn(dates[4], fit["training_execution_dates_ms"])
        expected = [bars[t + HOUR].open / bars[t].open - 1 for t in dates[:4]]
        self.assertEqual(factory.estimators[0].y, expected)
        self.assertEqual(factory.estimators[0].weights, [1.0] * 4)
        self.assertEqual(factory.estimators[0].parameters, prediction.ESTIMATOR_PARAMETERS)
        self.assertEqual(fit["rolling_mean"], math.fsum(expected) / 4)
        self.assertEqual(result["models"]["rolling_mean"]["signals"][dates[7]]["prediction"], fit["rolling_mean"])
        error = result["prediction_errors"][0]
        self.assertEqual(error["actual_return"], bars[dates[8]].open / bars[dates[7]].open - 1)
        self.assertEqual(error["label_end_ms"] - error["label_start_ms"], HOUR)

    def test_production_minimum_is_4320_complete_hourly_labels(self):
        self.assertEqual(prediction.MIN_TRAINING_ROWS, 4320)
        bars, states, dates = fixture(hours=4324)
        result = build(bars, states, minimum=4320)
        self.assertEqual(result["fit_audits"][0]["training_samples"], 4320)
        self.assertEqual(list(result["models"]["hgb"]["signals"]), [dates[4323]])

    def test_365_day_window_uses_label_execution_and_inclusive_lower_boundary(self):
        cutoff = BASE + 366 * DAY
        dates = [BASE, cutoff - 365 * DAY, cutoff - 365 * DAY + HOUR,
                 cutoff - 4 * HOUR, cutoff - 3 * HOUR, cutoff - 2 * HOUR, cutoff + HOUR]
        bars, states, _ = fixture(executions=dates)
        result = build(bars, states, minimum=4)
        fit = result["fit_audits"][-1]
        self.assertEqual(fit["fit_cutoff_ms"], cutoff)
        self.assertEqual(fit["training_execution_dates_ms"], dates[1:5])
        self.assertEqual(fit["training_window_start_ms"], dates[1])
        self.assertNotIn(dates[0], fit["training_execution_dates_ms"])
        self.assertNotIn(dates[5], fit["training_execution_dates_ms"])

    def test_monthly_fit_uses_first_eligible_cutoff_not_execution_month(self):
        bars, states, dates = fixture()
        result = build(bars, states)
        fits = result["fit_audits"]
        february = int(datetime(2023, 2, 1, tzinfo=timezone.utc).timestamp() * 1000)
        self.assertEqual([fit["fit_cutoff_ms"] for fit in fits], [dates[6], february])
        audits = {row["execution_ms"]: row for row in result["models"]["hgb"]["prediction_audits"]}
        self.assertEqual(audits[february]["fit_cutoff_ms"], dates[6])
        self.assertEqual(audits[february + HOUR]["fit_cutoff_ms"], february)
        del states[february + HOUR]
        delayed = build(bars, states)
        self.assertEqual(delayed["fit_audits"][1]["fit_cutoff_ms"], february + HOUR)

    def test_models_share_training_rows_labels_and_forecast_identity(self):
        bars, states, _ = fixture()
        factory = Factory()
        result = build(bars, states, factory=factory)
        self.assertEqual(len(factory.estimators), len(result["fit_audits"]))
        control, hgb = (result["models"][name] for name in ("rolling_mean", "hgb"))
        self.assertEqual(set(control["signals"]), set(hgb["signals"]))
        for left, right in zip(control["prediction_audits"], hgb["prediction_audits"]):
            self.assertEqual({k: v for k, v in left.items() if k != "prediction_sha256"},
                             {k: v for k, v in right.items() if k != "prediction_sha256"})
        for model, fit in zip(factory.estimators, result["fit_audits"]):
            self.assertEqual(fit["training_labels_sha256"], _hash(model.y))
            self.assertEqual(fit["training_weights_sha256"], _hash([1.0] * len(model.y)))
            self.assertEqual(fit["rolling_mean"], math.fsum(model.y) / len(model.y))
        for row in result["prediction_errors"]:
            timestamp = row["execution_ms"]
            self.assertEqual(row["rolling_mean_prediction"], control["signals"][timestamp]["prediction"])
            self.assertEqual(row["hgb_prediction"], hgb["signals"][timestamp]["prediction"])

    def test_future_mutations_do_not_change_past_fit_or_signal(self):
        bars, states, dates = fixture()
        baseline = build(bars, states)
        execution = dates[53]
        cutoff = execution - HOUR
        changed_bars, changed_states = copy.deepcopy((bars, states))
        for timestamp, bar in list(changed_bars.items()):
            if timestamp >= cutoff:
                changed_bars[timestamp] = replace(bar, open=bar.open * 2, high=bar.high * 2,
                                                 low=bar.low * 2, close=bar.close * 2)
        for timestamp, row in changed_states.items():
            if timestamp > execution:
                row["return1"] *= 1000
                row["context_sha256"] = _hash(row)
        result = build(changed_bars, changed_states)
        for name in baseline["models"]:
            self.assertEqual({t: row for t, row in baseline["models"][name]["signals"].items() if t <= execution},
                             {t: row for t, row in result["models"][name]["signals"].items() if t <= execution})
        self.assertEqual([row for row in baseline["fit_audits"] if row["fit_cutoff_ms"] <= cutoff],
                         [row for row in result["fit_audits"] if row["fit_cutoff_ms"] <= cutoff])

    def test_no_future_label_required_to_generate_forecast(self):
        bars, states, dates = fixture(hours=10)
        baseline = build(bars, states)
        changed = {t: bar for t, bar in bars.items() if t < dates[8]}
        result = build(changed, states)
        for name in baseline["models"]:
            self.assertEqual(result["models"][name]["signals"], baseline["models"][name]["signals"])
        self.assertEqual(result["prediction_errors"], [])
        self.assertIn(dates[9], {row["execution_ms"] for row in result["unavailable_labels"]})

    def test_label_quality_requires_complete_ohlc_and_positive_trades_and_volume(self):
        bars, states, dates = fixture(hours=12)
        cases = ({"trades": 0}, {"trades": None}, {"trades": .5}, {"volume": 0}, {"volume": math.inf},
                 {"quote_volume": 0}, {"quote_volume": -1}, {"quote_volume": math.nan},
                 {"close": math.nan}, {"high": 1}, {"low": 500}, {"open_ms": dates[0] + 1})
        for changes in cases:
            changed = dict(bars)
            changed[dates[0]] = replace(bars[dates[0]], **changes)
            with self.subTest(changes=changes):
                result = build(changed, states)
                self.assertEqual(result["unavailable_labels"][0]["execution_ms"], dates[0])
                self.assertEqual(result["fit_audits"][0]["first_forecast_execution_ms"], dates[8])
                self.assertNotIn(dates[0], result["fit_audits"][0]["training_execution_dates_ms"])
        changed = dict(bars)
        changed[dates[1]] = replace(bars[dates[1]], volume=0)
        result = build(changed, states)
        self.assertEqual({row["execution_ms"] for row in result["unavailable_labels"]}, set(dates[:2]))
        no_quote = {t: replace(bar, quote_volume=None) for t, bar in bars.items()}
        self.assertEqual(build(no_quote, states), build(bars, states))

    def test_partial_missing_is_nan_and_all_missing_mask_is_fixed_until_refit(self):
        bars, states, dates = fixture()
        for timestamp in dates[7:]:
            states[timestamp]["absent"] = .5
        factory = Factory()
        result = build(bars, states, factory=factory)
        first, second = factory.estimators
        self.assertTrue(math.isnan(first.x[0][1]))
        self.assertTrue(all(row[2] == 0 for row in first.x))
        self.assertTrue(all(row[2] == 0 for row in first.predictions))
        self.assertEqual(second.predictions[0][2], .5)
        self.assertTrue(math.isnan(second.x[0][2]))
        self.assertEqual(result["fit_audits"][0]["all_missing_training_fields"], ["absent"])
        self.assertEqual(result["fit_audits"][1]["all_missing_training_fields"], [])
        self.assertIsNone(states[dates[0]]["nullable"])
        self.assertEqual(states[dates[7]]["absent"], .5)
        self.assertNotEqual(result["fit_audits"][0]["raw_training_matrix_sha256"],
                            result["fit_audits"][0]["effective_training_matrix_sha256"])
        json.dumps(result, allow_nan=False)

    def test_inputs_unchanged_and_order_independent_deterministic_hashes(self):
        bars, states, _ = fixture()
        before = copy.deepcopy((bars, states))
        baseline = build(bars, states)
        self.assertEqual((bars, states), before)
        result = build(dict(reversed(list(bars.items()))), dict(reversed(list(states.items()))))
        self.assertEqual(result, baseline)
        for fit in baseline["fit_audits"]:
            self.assertEqual(fit["fit_sha256"], _hash({k: v for k, v in fit.items() if k != "fit_sha256"}))

    def test_invalid_fields_metadata_and_clock_rejected(self):
        bars, states, dates = fixture(hours=10)
        for fields in ((), ("return1", "return1"), ("execution_ms",), ("context_sha256",),
                       ("target",), ("nested.prediction",), ("historical_point_in_time_verified",)):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                build(bars, states, fields=fields)
        for field, value in (("latest_observed_close_ms", dates[0]), ("execution_ms", dates[0] + HOUR),
                             ("latest_observed_close_ms", float(dates[0] - HOUR)),
                             ("return1", math.nan), ("return1", True), ("context_sha256", "bad")):
            changed = copy.deepcopy(states)
            changed[dates[0]][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                build(bars, changed)
        changed = copy.deepcopy(states)
        changed[dates[0] + 1] = changed.pop(dates[0])
        with self.assertRaisesRegex(ValueError, "integer UTC hours"):
            build(bars, changed)
        with self.assertRaisesRegex(ValueError, "nonnegative cutoffs"):
            build(bars, {0: states[dates[0]]})
        with self.assertRaisesRegex(ValueError, "progress must"):
            build(bars, states, progress=1)

    def test_progress_reports_completed_fit_and_nonfinite_predictions_fail(self):
        bars, states, _ = fixture(hours=10)
        calls = []
        result = build(bars, states, progress=calls.append)
        self.assertEqual(calls, [{k: row[k] for k in ("fit_cutoff_ms", "training_samples", "fit_sha256")}
                                 for row in result["fit_audits"]])
        class BadEstimator(Estimator):
            def predict(self, x):
                return [math.nan]
        with self.assertRaisesRegex(ValueError, "malformed or nonfinite"):
            build(bars, states, factory=BadEstimator)

    def test_no_forecasts_when_history_is_insufficient(self):
        bars, states, dates = fixture(hours=5)
        result = build(bars, states)
        self.assertEqual(result["fit_audits"], [])
        self.assertEqual(result["prediction_errors"], [])
        self.assertEqual(len(result["unavailable_predictions"]), len(dates))
        self.assertTrue(all(not model["signals"] for model in result["models"].values()))

    @unittest.skipUnless(importlib.util.find_spec("sklearn"), "optional tree environment required")
    def test_small_real_hgb_fit_is_finite_reproducible_and_single_thread_design(self):
        bars, states, _ = fixture(hours=105)
        with patch.object(prediction, "MIN_TRAINING_ROWS", 80):
            first = prediction.build_forecasts(bars, states, FIELDS)
            second = prediction.build_forecasts(bars, states, FIELDS)
        self.assertEqual(first, second)
        self.assertTrue(first["models"]["hgb"]["signals"])
        self.assertTrue(all(math.isfinite(row["prediction"]) for row in first["models"]["hgb"]["signals"].values()))
        self.assertFalse(first["design"]["injected_estimator"])
        self.assertEqual(first["design"]["native_thread_limit"], 1)
        self.assertIn("sklearn_version", first["fit_audits"][0])
        json.dumps(first, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
