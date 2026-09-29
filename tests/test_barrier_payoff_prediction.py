"""Synthetic causal checks for variable-duration, overlapping event labels."""
from contextlib import nullcontext
import copy
from dataclasses import replace
from datetime import datetime, timezone
import math
import unittest
from unittest.mock import patch

from jev_trader import barrier_payoff_prediction as prediction
from jev_trader.binance_data import Bar
from jev_trader.tree_prediction import _hash

H = prediction.HOUR_MS
BASE = int(datetime(2023, 1, 30, tzinfo=timezone.utc).timestamp()*1000)
FIELDS = (prediction.ATR_FIELD, "momentum", "partial", "absent")


def fixture(hours=80):
    states, bars = {}, {}
    for i in range(hours+9):
        t = BASE+i*H
        value = 100 + .02*math.sin(i/7)
        bars[t] = Bar(t, value, value+.05, value-.05, value+.01, 100,
                      quote_volume=10_000, trades=10)
        if i < hours:
            row = {prediction.ATR_FIELD: 1., "momentum": i*.001,
                   "partial": None if i % 2 == 0 else .01, "absent": None,
                   "execution_ms": t, "latest_observed_close_ms": t-H}
            row["context_sha256"] = _hash(row)
            states[t] = row
    return bars, states


class Estimator:
    def __init__(self, **kwargs):
        self.parameters = kwargs
        self.predictions = []

    def fit(self, x, y, sample_weight):
        self.x, self.y, self.weights = copy.deepcopy(x), list(y), list(sample_weight)
        self.mean = math.fsum(y)/len(y)

    def predict(self, x):
        self.predictions.extend(copy.deepcopy(x))
        return [self.mean+sum(v for v in row if math.isfinite(v))*1e-5 for row in x]


class Factory:
    def __init__(self):
        self.models = []

    def __call__(self, **kwargs):
        model = Estimator(**kwargs)
        self.models.append(model)
        return model


def build(bars, states, minimum=4, factory=None):
    factory = Factory() if factory is None else factory
    runtime = (factory, nullcontext, lambda data: data, {"injected_estimator": True})
    with patch.object(prediction, "_runtime", return_value=runtime), \
            patch.object(prediction, "MIN_TRAINING_ROWS", minimum):
        return prediction.build_forecasts(bars, states, FIELDS)


class BarrierPredictionTests(unittest.TestCase):
    def test_timeout_availability_is_exit_candle_close_and_strict(self):
        bars, states = fixture()
        result = build(bars, states)
        label = result["label_outcomes"][BASE]
        self.assertEqual(label["exit_bar_open_ms"], BASE+8*H)
        self.assertEqual(label["available_ms"], BASE+9*H)
        self.assertEqual(label["true_return"], bars[BASE+8*H].open/bars[BASE].open-1)
        first = result["fit_audits"][0]
        self.assertEqual(first["first_forecast_execution_ms"], BASE+14*H)
        self.assertEqual(first["training_execution_dates_ms"], [BASE+i*H for i in range(4)])
        self.assertEqual(first["latest_label_available_ms"], BASE+12*H)
        self.assertLess(first["latest_label_available_ms"], first["fit_cutoff_ms"])

    def test_newer_completed_event_can_train_before_older_unfinished_event(self):
        bars, states = fixture(15)

        def unequal(_bars, t, atr, max_hours):
            index = (t-BASE)//H
            delay = 2 if index in (1, 2) else 9
            return {"status": "complete", "gross_return": index*.001,
                    "exit_bar_open_ms": t+(delay-1)*H, "exit_phase": "open", "available_ms": t+delay*H}

        with patch.object(prediction, "episode", side_effect=unequal):
            result = build(bars, states, minimum=2)
        first = result["fit_audits"][0]
        self.assertEqual(first["first_forecast_execution_ms"], BASE+6*H)
        self.assertEqual(first["training_execution_dates_ms"], [BASE+H, BASE+2*H])
        self.assertNotIn(BASE, first["training_execution_dates_ms"])

    def test_future_bars_and_states_do_not_change_past_forecasts(self):
        bars, states = fixture()
        baseline = build(bars, states)
        execution = BASE+53*H
        cutoff = execution-H
        other_bars, other_states = copy.deepcopy((bars, states))
        for t, bar in list(other_bars.items()):
            if t >= cutoff:
                other_bars[t] = replace(bar, open=bar.open*2, close=bar.close*2,
                                        high=bar.high*2, low=bar.low*2)
        for t, state in other_states.items():
            if t > execution:
                state["momentum"] += 100
                state["context_sha256"] = _hash(state)
        changed = build(other_bars, other_states)
        for name in baseline["models"]:
            self.assertEqual({t: s for t, s in baseline["models"][name]["signals"].items() if t <= execution},
                             {t: s for t, s in changed["models"][name]["signals"].items() if t <= execution})
        self.assertEqual([f for f in baseline["fit_audits"] if f["fit_cutoff_ms"] <= cutoff],
                         [f for f in changed["fit_audits"] if f["fit_cutoff_ms"] <= cutoff])

    def test_forecast_does_not_require_current_future_episode(self):
        bars, states = fixture(20)
        baseline = build(bars, states)
        shortened = {t: b for t, b in bars.items() if t < BASE+19*H}
        changed = build(shortened, states)
        self.assertEqual(baseline["models"], changed["models"])
        self.assertEqual(changed["prediction_errors"], [])
        self.assertTrue(changed["unavailable_labels"])

    def test_training_window_uses_entry_dates_and_includes_lower_boundary(self):
        bars, states = fixture()
        with patch.object(prediction, "TRAINING_WINDOW_MS", 20*H):
            result = build(bars, states)
        february = BASE+48*H
        fit = result["fit_audits"][1]
        self.assertEqual(fit["fit_cutoff_ms"], february)
        self.assertEqual(fit["training_execution_dates_ms"], [BASE+i*H for i in range(28, 39)])
        self.assertEqual(fit["training_window_start_ms"], BASE+28*H)

    def test_monthly_fit_and_shared_labels_and_hashes(self):
        bars, states = fixture()
        factory = Factory()
        result = build(bars, states, factory=factory)
        self.assertEqual(len(factory.models), 2)
        self.assertEqual([f["fit_cutoff_ms"] for f in result["fit_audits"]], [BASE+13*H, BASE+48*H])
        for model, fit in zip(factory.models, result["fit_audits"]):
            self.assertEqual(model.parameters, prediction.ESTIMATOR_PARAMETERS)
            self.assertEqual(fit["training_labels_sha256"], _hash(model.y))
            self.assertEqual(model.weights, [1.]*len(model.y))
            self.assertEqual(fit["rolling_mean"], math.fsum(model.y)/len(model.y))
        mean, hgb = (result["models"][m] for m in ("rolling_mean", "hgb"))
        self.assertEqual(mean["signals"].keys(), hgb["signals"].keys())
        for a, b in zip(mean["prediction_audits"], hgb["prediction_audits"]):
            self.assertEqual({k: v for k, v in a.items() if k != "prediction_sha256"},
                             {k: v for k, v in b.items() if k != "prediction_sha256"})

    def test_missing_transform_uses_training_only_and_inputs_unchanged(self):
        bars, states = fixture()
        for t, state in states.items():
            if t >= BASE+14*H:
                state["absent"] = .5
        original = copy.deepcopy(states)
        factory = Factory()
        result = build(bars, states, factory=factory)
        first, second = factory.models
        self.assertTrue(all(v[3] == 0 for v in first.x+first.predictions))
        self.assertTrue(math.isnan(first.x[0][2]))
        self.assertEqual(second.predictions[0][3], .5)
        self.assertEqual(result["fit_audits"][0]["all_missing_training_fields"], ["absent"])
        self.assertEqual(states, original)

    def test_missing_current_atr_skips_forecast_and_invalid_atr_rejected(self):
        bars, states = fixture(20)
        states[BASE+15*H][prediction.ATR_FIELD] = None
        result = build(bars, states)
        self.assertNotIn(BASE+15*H, result["models"]["hgb"]["signals"])
        self.assertEqual(next(r for r in result["unavailable_predictions"] if r["execution_ms"] == BASE+15*H)["reason"],
                         "missing_observed_atr")
        for value in (0, -1, 100, math.inf, True):
            states[BASE+15*H][prediction.ATR_FIELD] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                build(bars, states)


if __name__ == "__main__":
    unittest.main()
