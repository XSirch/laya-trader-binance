from copy import deepcopy
import json
import math
import unittest

from jev_trader.binance_data import Bar
from jev_trader.broad_prediction import FIELDS as ECONOMIC_SCHEMA
from jev_trader.broad_technical import flatten
from jev_trader.market_state import states
from jev_trader.broad_jev_policy import (
    CRITERIA, CRITERION_NAMES, FEATURE_FIELDS, QUESTIONS, filter_scale,
    market_state, numeric_adherence, script_accept,
)


def row_for(direction=1):
    row = {field: 0.0 for field in FEATURE_FIELDS}
    row.update({"quote_volume20": 10_000_000, "momentum7": direction * .02,
                "momentum30": direction * .05, "volatility": .03,
                "carry30": direction * .02, "time_series_ensemble": direction})
    row.update({
        "technical.trend.distance_sma_pct.200": direction * 10,
        "technical.trend.distance_ema_pct.50": direction * 5,
        "technical.trend.distance_sma_pct.50": direction,
        "technical.trend.sma50_slope_5bars_pct": direction,
        "technical.trend.plus_di14": 25 + direction * 5,
        "technical.trend.minus_di14": 25 - direction * 5,
        "technical.momentum.macd_histogram_pct": direction * .1,
        "technical.momentum.rsi14": 50 + direction * 10,
        "technical.momentum.stochastic_k14": 50 + direction * 10,
        "technical.participation.relative_volume20": 1,
        "technical.participation.obv_change20_over_volume": direction * .1,
        "technical.participation.taker_buy_fraction20": .5 + direction * .1,
        "technical.participation.distance_vwap20_pct": direction,
        "technical.volatility.atr14_pct": 4,
        "technical.structure.fibonacci.60.high_after_low": direction == 1,
        "technical.structure.fibonacci.60.retracement_fraction": .5,
        "technical.structure.close_position_in_bar": .5 + direction * .1,
    })
    return row


def score_row(**overrides):
    return {**dict.fromkeys(CRITERION_NAMES, 1.0), **overrides}


class BroadJevPolicyTests(unittest.TestCase):
    def adherence(self, row, direction=1):
        return numeric_adherence(market_state(row, direction, FEATURE_FIELDS))

    def test_schema_matches_real_feature_generator_and_preserves_every_field(self):
        bars = [Bar(i * 86_400_000, 100 + i, 103 + i, 98 + i, 101 + i,
                    1000 + i, (1000 + i) * (101 + i), 100 + i, 550 + i / 2)
                for i in range(220)]
        technical = flatten(states(bars)[-1])
        fields = ECONOMIC_SCHEMA + tuple(sorted(technical))
        self.assertEqual(fields, FEATURE_FIELDS)
        row = {**dict.fromkeys(ECONOMIC_SCHEMA, .123456789), **technical,
               "quote_volume20": 12_000_000, "symbol": "SECRET", "latest_observed_close_ms": 100,
               "future_profit": 999}
        state = market_state(row, 1, fields)
        self.assertEqual(len(state["market"]), 60)
        self.assertEqual(set(state["market"]), set(fields))
        for key in fields:
            self.assertEqual(state["market"][key], round(float(row[key]), 8))
        payload = json.dumps(state, allow_nan=False)
        for forbidden in ("SECRET", "latest_observed_close_ms", "future_profit"):
            self.assertNotIn(forbidden, payload)
        self.assertEqual(state["horizon_days"], 7)
        self.assertIn("fraction", state["units"]["carry30"])
        self.assertIn("percent", state["units"]["technical_pct"])

    def test_all_five_typed_questions_form_one_complete_request_mapping(self):
        self.assertEqual(tuple(QUESTIONS), CRITERION_NAMES)
        self.assertEqual(tuple(CRITERIA), CRITERION_NAMES)
        for name, question in QUESTIONS.items():
            self.assertEqual(set(question), {"type", "instructions"})
            self.assertEqual(question["type"], "noul")
            self.assertIn(CRITERIA[name], question["instructions"])
            self.assertIn("Do not predict", question["instructions"])
            self.assertIn("flat keys", question["instructions"])

    def test_directional_long_and_short_all_pass(self):
        for d in (1, -1):
            with self.subTest(direction=d):
                self.assertEqual(self.adherence(row_for(d), d), score_row())
        wrong = self.adherence(row_for(-1), 1)
        self.assertEqual(wrong["trend"], 0)
        self.assertEqual(wrong["participation"], 0)

    def test_trend_requires_three_strict_votes_and_timing_three_mixed_votes(self):
        row = row_for()
        row["technical.trend.distance_sma_pct.200"] = 0
        row["technical.trend.distance_ema_pct.50"] = 0
        self.assertEqual(self.adherence(row)["trend"], 1)
        row["time_series_ensemble"] = 0
        self.assertEqual(self.adherence(row)["trend"], 0)
        row["momentum7"] = row["momentum30"] = 0
        row["technical.momentum.macd_histogram_pct"] = 0
        row["technical.momentum.rsi14"] = 40
        row["technical.momentum.stochastic_k14"] = 85
        self.assertEqual(self.adherence(row)["timing"], 1)
        row["technical.momentum.stochastic_k14"] = 85.00000001
        self.assertEqual(self.adherence(row)["timing"], 0)

    def test_participation_requires_volume_and_two_directional_votes(self):
        row = row_for(-1)
        row["technical.participation.relative_volume20"] = .8
        row["technical.participation.taker_buy_fraction20"] = .5
        row["technical.participation.distance_vwap20_pct"] = 0
        row["technical.participation.obv_change20_over_volume"] = 0
        self.assertEqual(self.adherence(row, -1)["participation"], 1)
        row["technical.participation.relative_volume20"] = .79999999
        self.assertEqual(self.adherence(row, -1)["participation"], 0)
        row["technical.participation.relative_volume20"] = 1
        row["technical.participation.distance_vwap20_pct"] = 1
        self.assertEqual(self.adherence(row, -1)["participation"], 0)

    def test_side_specific_fibonacci_with_other_structure_paths_disabled(self):
        for d, retracement in ((1, .236), (1, .618), (-1, .382), (-1, .764)):
            row = row_for(d)
            row["technical.trend.distance_sma_pct.50"] = 10
            row["technical.structure.fibonacci.60.retracement_fraction"] = retracement
            row["technical.structure.close_position_in_bar"] = .5
            with self.subTest(direction=d, retracement=retracement):
                self.assertEqual(self.adherence(row, d)["structure"], 1)
                row["technical.structure.fibonacci.60.high_after_low"] = d != 1
                self.assertEqual(self.adherence(row, d)["structure"], 0)

    def test_breakout_and_sma_pullback_paths_are_side_specific(self):
        for d in (1, -1):
            row = row_for(d)
            row["technical.structure.fibonacci.60.retracement_fraction"] = 1
            row["technical.trend.distance_sma_pct.50"] = 10
            row["technical.participation.relative_volume20"] = 1.2
            field = "technical.structure.distance_prior_high20_pct" if d == 1 else "technical.structure.distance_prior_low20_pct"
            row[field] = d * 2
            self.assertEqual(self.adherence(row, d)["structure"], 1)
            row[field] = d * 2.00000001
            self.assertEqual(self.adherence(row, d)["structure"], 0)
            row["technical.trend.distance_sma_pct.50"] = d * 2
            self.assertEqual(self.adherence(row, d)["structure"], 1)
            row["technical.trend.sma50_slope_5bars_pct"] = 0
            self.assertEqual(self.adherence(row, d)["structure"], 0)

    def test_risk_uses_fraction_carry_volatility_and_percent_technical_fields(self):
        for d in (1, -1):
            row = row_for(d)
            row.update({"volatility": .05, "carry30": d * -.05,
                        "technical.volatility.atr14_pct": 6,
                        "technical.momentum.return_pct.1": -8})
            self.assertEqual(self.adherence(row, d)["risk"], 1)
            for field, value in (("volatility", .05000001), ("carry30", d * -.05000001),
                                 ("technical.volatility.atr14_pct", 6.00000001),
                                 ("technical.momentum.return_pct.1", -8.00000001),
                                 ("quote_volume20", 9_999_999)):
                with self.subTest(direction=d, field=field):
                    self.assertEqual(self.adherence({**row, field: value}, d)["risk"], 0)
            self.assertEqual(self.adherence({**row, "carry30": d * -5}, d)["risk"], 0)

    def test_numeric_reference_uses_transmitted_rounding_at_boundaries(self):
        row = row_for()
        row["volatility"] = .050000004
        state = market_state(row, 1, FEATURE_FIELDS)
        self.assertEqual(state["market"]["volatility"], .05)
        self.assertEqual(numeric_adherence(state)["risk"], 1)
        state["market"]["volatility"] = .050000004
        with self.assertRaises(ValueError):
            numeric_adherence(state)
        row["volatility"] = .050000006
        self.assertEqual(self.adherence(row)["risk"], 0)

    def test_script_thresholds_apply_locally_and_all_scores_are_required(self):
        scores = score_row(trend=.65, timing=.65, participation=0, structure=0, risk=.75)
        self.assertTrue(script_accept(scores))
        self.assertFalse(script_accept({**scores, "risk": .7499999}))
        self.assertFalse(script_accept({**scores, "timing": .6499999}))
        for invalid in ({k: v for k, v in scores.items() if k != "trend"},
                        {**scores, "action": 1}, {**scores, "risk": True},
                        {**scores, "risk": math.nan}, {**scores, "risk": math.inf},
                        {**scores, "risk": 1.01}, {**scores, "risk": "0.9"}):
            with self.assertRaises(ValueError):
                script_accept(invalid)

    def test_gross_weight_gate_includes_btc_and_uniform_scale_preserves_hedges(self):
        weights = {"A": .2, "B": -.1, "BTCUSDT": -.2}
        scores = {"A": score_row(), "B": score_row(), "BTCUSDT": score_row(risk=0)}
        scale, fraction = filter_scale(weights, scores, 4)
        self.assertAlmostEqual(fraction, .6)
        self.assertEqual(scale, 4)
        scaled = {s: w * scale for s, w in weights.items()}
        self.assertEqual(set(scaled), set(weights))
        self.assertEqual(scaled["BTCUSDT"], -.8)
        self.assertAlmostEqual(sum(abs(w) for w in scaled.values()), 2)
        self.assertEqual(scaled["BTCUSDT"] / scaled["A"], weights["BTCUSDT"] / weights["A"])
        scores["B"] = score_row(risk=0)
        self.assertEqual(filter_scale(weights, scores, 1), (0, .4))
        scores["BTCUSDT"] = score_row()
        self.assertEqual(filter_scale(weights, scores, 1), (1, .8))

    def test_missing_or_invalid_market_and_basket_inputs_fail_closed(self):
        row = row_for()
        for invalid in ({k: v for k, v in row.items() if k != "momentum90"},
                        {**row, "momentum90": math.nan}, {**row, "quote_volume20": math.inf},
                        {**row, "technical.structure.fibonacci.180.high_after_low": .5}):
            with self.assertRaises(ValueError):
                market_state(invalid, 1, FEATURE_FIELDS)
        for d in (0, 2, True, math.nan):
            with self.assertRaises(ValueError):
                market_state(row, d, FEATURE_FIELDS)
        with self.assertRaises(ValueError):
            market_state(row, 1, FEATURE_FIELDS[:-1])
        for weights, scores, scale in (({"A": .2}, {}, 1), ({"A": math.nan}, {}, 1),
                                       ({"A": True}, {}, 1), ({}, {}, 2), ({}, {}, True),
                                       ({"A": .6}, {"A": score_row()}, 4),
                                       ({"A": .2}, {"A": score_row(risk=math.inf)}, 1)):
            with self.assertRaises(ValueError):
                filter_scale(weights, scores, scale)
        self.assertEqual(filter_scale({}, {}, 4), (0, 0))
        self.assertEqual(filter_scale({"A": 0}, {}, 4), (0, 0))


if __name__ == "__main__":
    unittest.main()
