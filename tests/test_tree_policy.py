"""Synthetic portfolio policy checks without market files or provider calls."""

import copy
from datetime import datetime, timezone
import math
import unittest

from jev_trader.tree_policy import HOUR_MS, MIN_BTC_BETA, TreePolicy


START = int(datetime(2025, 1, 6, tzinfo=timezone.utc).timestamp() * 1000)


def iso(timestamp):
    return datetime.fromtimestamp(timestamp / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def states_at(cutoff=START, count=10):
    symbols = ["BTCUSDT", *(f"ALT{i}USDT" for i in range(count - 1))]
    return {symbol: {"latest_observed_close_ms": cutoff, "quote_volume20": 20_000_000,
                     "volatility": .02, "beta60": 1.0, "carry30": 0.0,
                     "technical.rsi14": 50.0,
                     "prediction": 0.0 if symbol == "BTCUSDT" else (index - count / 2) * .025}
            for index, symbol in enumerate(symbols)}


def notice(symbol="ALT8USDT", published=START, restriction=START + HOUR_MS):
    return {"symbol": symbol, "published_utc": iso(published),
            "new_positions_stop_utc": iso(restriction),
            "automatic_settlement_utc": iso(restriction + HOUR_MS)}


class TreePolicyTests(unittest.TestCase):
    def test_empty_and_insufficient_states_return_audited_cash(self):
        policy = TreePolicy([])
        self.assertEqual(policy({}, "tree"), {})
        self.assertEqual(policy.audit[-1]["reason"], "empty_states")
        self.assertIsNone(policy.audit[-1]["cutoff_ms"])
        self.assertEqual(policy(states_at(count=7), "tree"), {})
        self.assertEqual(policy.audit[-1]["reason"], "insufficient_eligible")
        self.assertEqual(policy.audit[-1]["gross"], 0)

    def test_missing_prediction_is_warmup(self):
        states = states_at()
        del states["ALT0USDT"]["prediction"]
        states["ALT1USDT"]["prediction"] = None
        policy = TreePolicy([])
        self.assertTrue(policy(states, "tree"))
        self.assertEqual(policy.audit[-1]["excluded_warmup"], ["ALT0USDT", "ALT1USDT"])
        self.assertEqual(policy.audit[-1]["eligible_count"], 8)
        states["ALT2USDT"]["prediction"] = None
        self.assertEqual(policy(states, "tree"), {})
        self.assertEqual(policy.audit[-1]["reason"], "insufficient_eligible")

    def test_btc_missing_unfunded_or_nearzero_beta_returns_cash(self):
        for change in ("absent", "prediction", "liquidity", "volatility", "beta"):
            with self.subTest(change=change):
                states = states_at()
                if change == "absent":
                    del states["BTCUSDT"]
                elif change == "prediction":
                    del states["BTCUSDT"]["prediction"]
                elif change == "liquidity":
                    states["BTCUSDT"]["quote_volume20"] = 0
                elif change == "volatility":
                    states["BTCUSDT"]["volatility"] = .2
                else:
                    states["BTCUSDT"]["beta60"] = MIN_BTC_BETA
                policy = TreePolicy([])
                self.assertEqual(policy(states, "tree"), {})
                self.assertIn(policy.audit[-1]["reason"], ("btc_unavailable", "btc_beta_unavailable"))

    def test_identical_predictions_do_not_create_symbol_alpha(self):
        states = states_at()
        for row in states.values():
            row["prediction"] = .1
        policy = TreePolicy([])
        self.assertEqual(policy(states, "tree"), {})
        self.assertEqual(policy.audit[-1]["reason"], "identical_predictions")

    def test_inverse_volatility_and_equal_side_gross_before_hedge(self):
        states = states_at()
        states["ALT8USDT"]["volatility"] = .04
        policy = TreePolicy([])
        policy(states, "tree")
        raw = policy.audit[-1]["raw_proposed_weights"]
        self.assertEqual(set(raw), {"ALT0USDT", "ALT1USDT", "ALT7USDT", "ALT8USDT"})
        self.assertAlmostEqual(raw["ALT7USDT"] / raw["ALT8USDT"], 2)
        self.assertAlmostEqual(sum(weight for weight in raw.values() if weight > 0), .5)
        self.assertAlmostEqual(sum(weight for weight in raw.values() if weight < 0), -.5)

    def test_btc_hedge_cancels_beta_and_caps_gross_for_both_scales(self):
        states = states_at()
        states["ALT7USDT"]["beta60"] = 3.0
        states["ALT8USDT"]["beta60"] = 2.0
        for limit in (1, 2):
            with self.subTest(limit=limit):
                policy = TreePolicy([], limit)
                weights = policy(states, "tree")
                self.assertTrue(weights)
                self.assertLess(weights["BTCUSDT"], 0)
                self.assertAlmostEqual(math.fsum(w * states[s]["beta60"] for s, w in weights.items()), 0)
                self.assertLessEqual(math.fsum(abs(w) for w in weights.values()), limit + 1e-14)
                self.assertAlmostEqual(policy.audit[-1]["gross"], limit)

    def test_hedge_adjusts_existing_btc_weight(self):
        states = states_at()
        states["BTCUSDT"]["prediction"] = .2
        states["ALT8USDT"]["beta60"] = 2
        policy = TreePolicy([])
        weights = policy(states, "tree")
        audit = policy.audit[-1]
        self.assertIn("BTCUSDT", audit["raw_proposed_weights"])
        self.assertAlmostEqual(math.fsum(w * states[s]["beta60"] for s, w in weights.items()), 0)
        self.assertNotIn("BTCUSDT", weights)

    def test_small_spread_returns_cash_and_preserves_proposal_audit(self):
        states = states_at()
        for row in states.values():
            row["prediction"] *= .001
        policy = TreePolicy([])
        self.assertEqual(policy(states, "tree"), {})
        audit = policy.audit[-1]
        self.assertEqual(audit["reason"], "below_cost_hurdle")
        self.assertFalse(audit["hurdle_pass"])
        self.assertGreater(audit["proposed_gross"], 0)
        self.assertAlmostEqual(audit["roundtrip_cost"], .003 * audit["proposed_gross"])
        self.assertTrue(audit["raw_proposed_weights"])
        self.assertTrue(audit["hedged_proposed_weights"])
        self.assertEqual(audit["final_target_weights"], {})
        self.assertEqual(audit["gross"], 0)

    def test_exact_hurdle_is_rejected(self):
        states = states_at()
        for row in states.values():
            row["prediction"] = 0
        for symbol in ("ALT0USDT", "ALT1USDT"):
            states[symbol]["prediction"] = -.003
        for symbol in ("ALT7USDT", "ALT8USDT"):
            states[symbol]["prediction"] = .003
        policy = TreePolicy([])
        self.assertEqual(policy(states, "tree"), {})
        self.assertEqual(policy.audit[-1]["expected_alpha"], .003)
        self.assertEqual(policy.audit[-1]["roundtrip_cost"], .003)

    def test_adverse_carry_uses_long_return_sign_for_both_sides(self):
        states = states_at()
        states["ALT8USDT"]["carry30"] = -2.0
        states["ALT0USDT"]["carry30"] = 3.0
        policy = TreePolicy([])
        policy(states, "tree")
        audit = policy.audit[-1]
        weights = audit["hedged_proposed_weights"]
        expected = (weights["ALT8USDT"] * 2 + abs(weights["ALT0USDT"]) * 3) * 7 / 365
        self.assertAlmostEqual(audit["adverse_carry"], expected)

    def test_favorable_carry_is_ignored_and_cannot_rescue_negative_hurdle(self):
        states = states_at()
        for row in states.values():
            row["prediction"] *= .001
        for symbol in ("ALT7USDT", "ALT8USDT"):
            states[symbol]["carry30"] = 1000
        for symbol in ("ALT0USDT", "ALT1USDT"):
            states[symbol]["carry30"] = -1000
        policy = TreePolicy([])
        self.assertEqual(policy(states, "tree"), {})
        self.assertEqual(policy.audit[-1]["adverse_carry"], 0)
        self.assertFalse(policy.audit[-1]["hurdle_pass"])

    def test_large_adverse_carry_can_prevent_an_otherwise_profitable_proposal(self):
        states = states_at()
        self.assertTrue(TreePolicy([])(states, "tree"))
        states["ALT8USDT"]["carry30"] = -1000
        policy = TreePolicy([])
        self.assertEqual(policy(states, "tree"), {})
        self.assertGreater(policy.audit[-1]["adverse_carry"], policy.audit[-1]["expected_alpha"])

    def test_lifecycle_is_point_in_time_at_delayed_execution_boundary(self):
        policy = TreePolicy([notice()])
        self.assertIn("ALT8USDT", policy(states_at(START - 1), "tree"))
        self.assertNotIn("ALT8USDT", policy(states_at(START), "tree"))
        self.assertEqual(policy.audit[-1]["excluded_lifecycle"], ["ALT8USDT"])
        self.assertEqual(policy.audit[-1]["execution_ms"], START + HOUR_MS)

    def test_known_notice_does_not_restrict_before_stop_time(self):
        policy = TreePolicy([notice(restriction=START + 2 * HOUR_MS)])
        self.assertIn("ALT8USDT", policy(states_at(), "tree"))
        self.assertEqual(policy.audit[-1]["excluded_lifecycle"], [])

    def test_btc_lifecycle_restriction_returns_cash(self):
        policy = TreePolicy([notice(symbol="BTCUSDT")])
        self.assertEqual(policy(states_at(), "tree"), {})
        self.assertEqual(policy.audit[-1]["reason"], "btc_unavailable")

    def test_symbol_ties_and_insertion_order_are_deterministic(self):
        states = states_at()
        states["ALT6USDT"]["prediction"] = states["ALT7USDT"]["prediction"]
        states["ALT2USDT"]["prediction"] = states["ALT1USDT"]["prediction"]
        a, b = TreePolicy([]), TreePolicy([])
        expected = a(states, "tree")
        actual = b(dict(reversed(list(states.items()))), "tree")
        self.assertEqual(expected, actual)
        self.assertEqual(a.audit, b.audit)

    def test_inputs_and_returned_weights_cannot_mutate_recorded_target(self):
        states = states_at()
        original = copy.deepcopy(states)
        event = notice(restriction=START + 2 * HOUR_MS)
        policy = TreePolicy([event])
        event["symbol"] = "BTCUSDT"
        weights = policy(states, "tree")
        self.assertEqual(states, original)
        snapshot = dict(weights)
        weights.clear()
        self.assertEqual(policy.audit[-1]["final_target_weights"], snapshot)
        self.assertEqual(policy.events[0].symbol, "ALT8USDT")

    def test_nonfinite_supplied_values_are_rejected_even_on_ineligible_rows(self):
        for field in ("prediction", "quote_volume20", "volatility", "beta60", "carry30", "technical.rsi14"):
            for value in (math.nan, math.inf, -math.inf):
                with self.subTest(field=field, value=value):
                    states = states_at()
                    states["ALT0USDT"]["quote_volume20"] = 0
                    states["ALT0USDT"][field] = value
                    policy = TreePolicy([])
                    with self.assertRaisesRegex(ValueError, "finite"):
                        policy(states, "tree")
                    self.assertEqual(policy.audit, [])

    def test_boolean_or_string_required_values_are_rejected(self):
        for field in ("prediction", "quote_volume20", "volatility", "beta60", "carry30"):
            for value in (True, ".1"):
                with self.subTest(field=field, value=value):
                    states = states_at()
                    states["ALT0USDT"][field] = value
                    with self.assertRaises(ValueError):
                        TreePolicy([])(states, "tree")

    def test_cutoffs_must_be_shared_integer_milliseconds(self):
        for value in (START + 1, float(START), True, None):
            with self.subTest(value=value):
                states = states_at()
                states["ALT0USDT"]["latest_observed_close_ms"] = value
                with self.assertRaisesRegex(ValueError, "cutoff"):
                    TreePolicy([])(states, "tree")

    def test_invalid_configuration_and_lifecycle_are_rejected(self):
        for gross in (0, .5, 3, True, math.nan, math.inf, "1"):
            with self.subTest(gross=gross), self.assertRaises(ValueError):
                TreePolicy([], gross)
        for events in ([notice(), notice()], [{**notice(), "symbol": "bad symbol"}],
                       [{**notice(), "published_utc": "2025-01-01"}],
                       [notice(published=START + 2 * HOUR_MS)],
                       [{**notice(), "automatic_settlement_utc": iso(START)}]):
            with self.subTest(events=events), self.assertRaises(ValueError):
                TreePolicy(events)


if __name__ == "__main__":
    unittest.main()
