"""Synthetic matched daily forecasts without market data or financial replay."""

import copy
from datetime import datetime, timezone
import importlib.util
import json
import math
from types import SimpleNamespace
import unittest

from jev_trader.funding_event_prediction import DAY_MS, HOUR_MS, build_forecasts
from jev_trader.positioning_features import FEATURES as POSITIONING_FIELDS
from jev_trader.tree_prediction import ESTIMATOR_PARAMETERS, _hash


FIRST_DAY = int(datetime(2022, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
CONTROL = ("volatility", "beta60", "quote_volume20") + tuple(f"feature{i}" for i in range(64)) + POSITIONING_FIELDS
EVENT = ("event.funding_rate", "event.magnitude", "event.percentile", "event.change", "event.divergence")


def fixture(days=400, assets=8):
    dates = [FIRST_DAY + day * DAY_MS for day in range(days)]
    symbols = ["BTCUSDT", *(f"ALT{i}USDT" for i in range(assets - 1))]
    states, prices = {}, {}
    for index, symbol in enumerate(symbols):
        states[symbol] = {}
        for day, timestamp in enumerate(dates):
            row = {field: .001 * (index + number + day / 100) for number, field in enumerate(CONTROL + EVENT)}
            row.update(volatility=.02, beta60=1.25 if symbol == "BTCUSDT" else 1.25 * (.5 + index * .12),
                       quote_volume20=20_000_000, latest_observed_close_ms=timestamp + HOUR_MS,
                       event_timestamp_ms=timestamp + 47, original_marker="preserved")
            for field in POSITIONING_FIELDS:
                row[field] = None if day % 2 == 0 else row[field]
            states[symbol][timestamp] = row
        prices[symbol] = {}
        for hour in range(days * 24 + 27):
            timestamp = FIRST_DAY + hour * HOUR_MS
            value = 100 * math.exp(index * .00001 * hour + .001 * math.sin(hour / (20 + index)))
            prices[symbol][timestamp] = SimpleNamespace(open_ms=timestamp, open=value, trades=10)
    return {"klines": prices}, states, dates


class Estimator:
    def __init__(self, **parameters):
        self.parameters = parameters

    def fit(self, x, y, sample_weight):
        self.x, self.y, self.weights = [list(row) for row in x], list(y), list(sample_weight)
        self.mean = math.fsum(target * weight for target, weight in zip(y, sample_weight)) / math.fsum(sample_weight)
        return self

    def predict(self, x):
        return [self.mean + row[3] * .01 for row in x]


class Factory:
    def __init__(self):
        self.estimators = []

    def __call__(self, **parameters):
        model = Estimator(**parameters)
        self.estimators.append(model)
        return model


def build(hourly, states, events=(), factory=None, control=CONTROL, event=EVENT):
    return build_forecasts(hourly, states, control, event, events, factory if factory is not None else Factory())


def clean(values):
    return [[None if math.isnan(value) else value for value in row] for row in values]


class FundingEventPredictionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hourly, cls.states, cls.dates = fixture()

    def test_365_completed_days_strict_end_cutoff_and_monthly_fit(self):
        result = build(self.hourly, self.states)
        for name in ("control75", "augmented80"):
            first = result[name]["fit_audits"][0]
            self.assertEqual(first["fit_cutoff_ms"], self.dates[366] + HOUR_MS)
            self.assertEqual(first["training_days"], 365)
            self.assertEqual(first["training_samples"], 365 * 7)
            self.assertEqual(first["latest_label_end_ms"], self.dates[365] + 2 * HOUR_MS)
            self.assertLess(first["latest_label_end_ms"], first["fit_cutoff_ms"])
            self.assertNotIn(self.dates[365], result[name]["signals"]["ALT0USDT"])
            months = [datetime.fromtimestamp(row["fit_cutoff_ms"] / 1000, timezone.utc).strftime("%Y-%m")
                      for row in result[name]["fit_audits"]]
            self.assertEqual(len(months), len(set(months)))

    def test_pair_label_uses_frozen_beta_and_24_hour_delayed_prices_without_centering(self):
        factory = Factory()
        result = build(self.hourly, self.states, factory=factory)
        day = self.dates[0]
        btc = self.hourly["klines"]["BTCUSDT"]
        btc_return = btc[day + 26 * HOUR_MS].open / btc[day + 2 * HOUR_MS].open - 1
        for index, symbol in enumerate(sorted(s for s in self.states if s != "BTCUSDT")):
            lookup = self.hourly["klines"][symbol]
            asset_return = lookup[day + 26 * HOUR_MS].open / lookup[day + 2 * HOUR_MS].open - 1
            beta = self.states[symbol][day]["beta60"] / self.states["BTCUSDT"][day]["beta60"]
            self.assertAlmostEqual(factory.estimators[0].y[index], (asset_return - beta * btc_return) / (1 + abs(beta)), places=15)
        for name in ("control75", "augmented80"):
            self.assertTrue(all(row["prediction"] == 0 for row in result[name]["signals"]["BTCUSDT"].values()))
            self.assertTrue(all(row["symbol"] != "BTCUSDT" for row in result[name]["prediction_errors"]))
            self.assertTrue(any(abs(sum(rows[d]["prediction"] for rows in result[name]["signals"].values() if d in rows)) > 1e-8
                                for d in result[name]["signals"]["BTCUSDT"]))

    def test_paired_labels_weights_prefix_and_equal_aggregate_daily_weight(self):
        hourly, states, dates = fixture(days=370, assets=9)
        for day in dates[:100]:
            del states["ALT7USDT"][day]
        factory = Factory()
        result = build(hourly, states, factory=factory)
        for control, augmented in zip(factory.estimators[::2], factory.estimators[1::2]):
            self.assertEqual(control.parameters, ESTIMATOR_PARAMETERS)
            self.assertEqual(augmented.parameters, ESTIMATOR_PARAMETERS)
            self.assertEqual(control.y, augmented.y)
            self.assertEqual(control.weights, augmented.weights)
            self.assertEqual(clean(control.x), [row[:75] for row in clean(augmented.x)])
            self.assertEqual(len(control.x[0]), 75)
            self.assertEqual(len(augmented.x[0]), 80)
            self.assertAlmostEqual(math.fsum(control.weights[:7]), math.fsum(control.weights[700:708]))
        for control, augmented in zip(result["control75"]["fit_audits"], result["augmented80"]["fit_audits"]):
            self.assertEqual(control["training_identity_label_weight_sha256"], augmented["training_identity_label_weight_sha256"])
            self.assertEqual(control["training_signal_dates_ms"], augmented["training_signal_dates_ms"])
        self.assertEqual(result["control75"]["prediction_errors"], result["augmented80"]["prediction_errors"])

    def test_nullable_positioning_encoded_as_nan_only_inside_model(self):
        factory = Factory()
        result = build(self.hourly, self.states, factory=factory)
        self.assertTrue(math.isnan(factory.estimators[0].x[0][-1]))
        self.assertIsNone(self.states["ALT0USDT"][self.dates[0]][POSITIONING_FIELDS[-1]])
        json.dumps(result, allow_nan=False)
        states = copy.deepcopy(self.states)
        states["ALT0USDT"][self.dates[0]]["feature0"] = None
        with self.assertRaises(ValueError):
            build(self.hourly, states)
        states["ALT0USDT"][self.dates[0]]["feature0"] = .1
        states["ALT0USDT"][self.dates[0]][POSITIONING_FIELDS[0]] = math.nan
        with self.assertRaises(ValueError):
            build(self.hourly, states)

    def test_future_missing_hour_removes_training_group_not_current_prediction(self):
        baseline = build(self.hourly, self.states)
        hourly = copy.deepcopy(self.hourly)
        day = self.dates[370]
        del hourly["klines"]["ALT5USDT"][day + 6 * HOUR_MS]
        result = build(hourly, self.states)
        for name in ("control75", "augmented80"):
            for symbol in self.states:
                self.assertEqual(result[name]["signals"][symbol][day], baseline[name]["signals"][symbol][day])
            self.assertFalse(any(row["day_ms"] == day for row in result[name]["prediction_errors"]))
            excluded = next(row for row in result[name]["unavailable_label_days"] if row["day_ms"] == day)
            self.assertEqual(len(excluded["eligible_symbols"]), 8)
            self.assertEqual(excluded["failures"][0]["symbol"], "ALT5USDT")
            self.assertTrue(all(day + HOUR_MS not in row["training_signal_dates_ms"] for row in result[name]["fit_audits"]))

    def test_future_mutations_do_not_change_past_fits_or_predictions(self):
        baseline = build(self.hourly, self.states)
        hourly, states = copy.deepcopy(self.hourly), copy.deepcopy(self.states)
        day = self.dates[372]
        decision = day + HOUR_MS
        for index, (symbol, lookup) in enumerate(hourly["klines"].items()):
            for timestamp, bar in lookup.items():
                if timestamp >= decision:
                    bar.open *= 1 + index * .01
        for rows in states.values():
            for timestamp, row in rows.items():
                if timestamp > day:
                    row[EVENT[-1]] *= 1000
                    row["feature0"] *= 100
        changed = build(hourly, states)
        for name in ("control75", "augmented80"):
            for symbol in self.states:
                self.assertEqual({t: row for t, row in baseline[name]["signals"][symbol].items() if t <= day},
                                 {t: row for t, row in changed[name]["signals"][symbol].items() if t <= day})
            self.assertEqual([row for row in baseline[name]["fit_audits"] if row["fit_cutoff_ms"] <= decision],
                             [row for row in changed[name]["fit_audits"] if row["fit_cutoff_ms"] <= decision])

    def test_announced_restriction_during_holding_window_applies_before_labels(self):
        hourly, states, dates = fixture(days=370, assets=9)
        decision = dates[366] + HOUR_MS
        stamp = lambda value: datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()
        events = [{"symbol": "ALT7USDT", "published_utc": stamp(decision),
                   "new_positions_stop_utc": stamp(dates[366] + 20 * HOUR_MS),
                   "automatic_settlement_utc": stamp(dates[366] + 21 * HOUR_MS)}]
        result = build(hourly, states, events)
        for name in ("control75", "augmented80"):
            self.assertNotIn(dates[366], result[name]["signals"]["ALT7USDT"])
            self.assertIn(dates[366], result[name]["signals"]["BTCUSDT"])

    def test_btc_eligibility_and_endpoint_trades_are_required(self):
        states = copy.deepcopy(self.states)
        states["BTCUSDT"][self.dates[366]]["beta60"] = 0
        result = build(self.hourly, states)
        self.assertTrue(all(self.dates[366] not in rows for rows in result["control75"]["signals"].values()))
        hourly = copy.deepcopy(self.hourly)
        day = self.dates[0]
        hourly["klines"]["BTCUSDT"][day + 2 * HOUR_MS].trades = 0
        result = build(hourly, self.states)
        excluded = next(row for row in result["control75"]["unavailable_label_days"] if row["day_ms"] == day)
        self.assertEqual(excluded["failures"][0]["reason"], "untradable_endpoint")
        self.assertEqual(result["control75"]["fit_audits"][0]["fit_cutoff_ms"], self.dates[367] + HOUR_MS)

    def test_invalid_fields_and_misaligned_state_clock_rejected(self):
        for control, event in ((CONTROL[:-1], EVENT), (CONTROL, EVENT[:-1]),
                               (CONTROL[:-1] + (CONTROL[0],), EVENT), (CONTROL, EVENT[:-1] + ("target",))):
            with self.subTest(control=control, event=event), self.assertRaises(ValueError):
                build(self.hourly, self.states, control=control, event=event)
        for field, value in (("event_timestamp_ms", self.dates[0] + 60_000),
                             ("latest_observed_close_ms", self.dates[0]), (EVENT[0], math.inf)):
            states = copy.deepcopy(self.states)
            states["ALT0USDT"][self.dates[0]][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                build(self.hourly, states)

    def test_optional_progress_reports_completed_paired_fits_only(self):
        calls = []
        result = build_forecasts(self.hourly, self.states, CONTROL, EVENT, [], Factory(), progress=calls.append)
        expected = [{key: row[key] for key in ("fit_cutoff_ms", "training_days", "training_samples")}
                    for row in result["matching_audit"]["training_audits"]]
        self.assertEqual(calls, expected)
        with self.assertRaisesRegex(ValueError, "progress must"):
            build_forecasts(self.hourly, self.states, CONTROL, EVENT, [], Factory(), progress=0)

    def test_inputs_unchanged_and_dictionary_order_deterministic(self):
        before = copy.deepcopy((self.hourly, self.states))
        baseline = build(self.hourly, self.states)
        self.assertEqual((self.hourly, self.states), before)
        states = {symbol: dict(reversed(list(rows.items()))) for symbol, rows in reversed(list(self.states.items()))}
        hourly = {"klines": {symbol: dict(reversed(list(rows.items())))
                             for symbol, rows in reversed(list(self.hourly["klines"].items()))}}
        self.assertEqual(baseline, build(hourly, states))

    def test_all_null_mask_is_training_only_and_fixed_until_next_monthly_fit(self):
        class SpyEstimator(Estimator):
            def fit(self, x, y, sample_weight):
                super().fit(x, y, sample_weight)
                self.seen_predictions = []
                return self

            def predict(self, x):
                self.seen_predictions.append([list(row) for row in x])
                return super().predict(x)

        class SpyFactory(Factory):
            def __call__(self, **parameters):
                model = SpyEstimator(**parameters)
                self.estimators.append(model)
                return model

        states = copy.deepcopy(self.states)
        newly_observed = self.dates[366]
        masked_fields = POSITIONING_FIELDS[:-1]
        for rows in states.values():
            for day, row in rows.items():
                for index, field in enumerate(masked_fields):
                    row[field] = None if day < newly_observed else 5.0 + index
        before = copy.deepcopy(states)
        factory = SpyFactory()
        result = build(self.hourly, states, factory=factory)
        self.assertEqual(states, before)
        for name, length in (("control75", 75), ("augmented80", 80)):
            fits = result[name]["fit_audits"]
            self.assertEqual(fits[0]["all_missing_training_fields"], list(masked_fields))
            self.assertEqual(fits[1]["all_missing_training_fields"], [])
            self.assertNotEqual(fits[0]["training_input_sha256"], fits[0]["transformed_training_input_sha256"])
            self.assertEqual(fits[1]["training_input_sha256"], fits[1]["transformed_training_input_sha256"])
            self.assertEqual(fits[0]["feature_transform_sha256"], _hash(fits[0]["feature_transform"]))
            fields = (CONTROL + EVENT)[:length]
            for audit in result[name]["prediction_audits"]:
                day, symbols = audit["day_ms"], audit["predicted_symbols"]
                raw_vectors = [[None if states[symbol][day][field] is None else float(states[symbol][day][field])
                                for field in fields] for symbol in symbols]
                active_mask = masked_fields if audit["signal_ms"] < fits[1]["fit_cutoff_ms"] else ()
                effective = [[0.0 if field in active_mask else value for field, value in zip(fields, row)]
                             for row in raw_vectors]
                self.assertEqual(audit["all_missing_training_fields"], list(active_mask))
                self.assertEqual(audit["prediction_input_sha256"],
                                 _hash({"fields": fields, "symbols": symbols, "vectors": raw_vectors}))
                self.assertEqual(audit["transformed_prediction_input_sha256"],
                                 _hash({"fields": fields, "symbols": symbols, "vectors": effective}))
        for model in factory.estimators[:2]:
            for field in masked_fields:
                index = CONTROL.index(field)
                self.assertTrue(all(row[index] == 0 for row in model.x))
                self.assertTrue(all(row[index] == 0 for batch in model.seen_predictions for row in batch))
            partial_index = CONTROL.index(POSITIONING_FIELDS[-1])
            self.assertTrue(any(math.isnan(row[partial_index]) for row in model.x))
            self.assertTrue(any(not math.isnan(row[partial_index]) for row in model.x))
        for model in factory.estimators[2:4]:
            first_index = CONTROL.index(masked_fields[0])
            self.assertTrue(any(math.isnan(row[first_index]) for row in model.x))
            self.assertTrue(any(row[first_index] == 5.0 for row in model.x))
            self.assertTrue(all(row[first_index] == 5.0 for batch in model.seen_predictions for row in batch))
        json.dumps(result, allow_nan=False)

    @unittest.skipUnless(importlib.util.find_spec("sklearn") is not None, "sklearn unavailable in this interpreter")
    def test_real_hgb_accepts_nullable_positioning_and_is_deterministic(self):
        hourly, states, _ = fixture(days=368)
        first = build_forecasts(hourly, states, CONTROL, EVENT, [])
        second = build_forecasts(hourly, states, CONTROL, EVENT, [])
        self.assertEqual(first, second)
        for name in ("control75", "augmented80"):
            self.assertFalse(first[name]["design"]["injected_estimator"])
            self.assertEqual(first[name]["fit_audits"][0]["training_days"], 365)
            self.assertTrue(first[name]["prediction_errors"])

    @unittest.skipUnless(importlib.util.find_spec("sklearn") is not None, "sklearn unavailable in this interpreter")
    def test_real_hgb_handles_all_eight_positioning_columns_absent_from_training(self):
        hourly, states, _ = fixture(days=368)
        for rows in states.values():
            for row in rows.values():
                for field in POSITIONING_FIELDS:
                    row[field] = None
        first = build_forecasts(hourly, states, CONTROL, EVENT, [])
        second = build_forecasts(hourly, states, CONTROL, EVENT, [])
        self.assertEqual(first, second)
        for name in ("control75", "augmented80"):
            self.assertEqual(first[name]["fit_audits"][0]["all_missing_training_fields"], list(POSITIONING_FIELDS))
            self.assertTrue(first[name]["prediction_errors"])
            self.assertTrue(all(row[field] is None for rows in first[name]["signals"].values()
                                for row in rows.values() for field in POSITIONING_FIELDS))
        json.dumps(first, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
