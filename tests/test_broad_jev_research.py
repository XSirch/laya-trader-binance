"""Synthetic causal scheduling and whole-basket integration tests only."""

import unittest
from unittest.mock import patch

from jev_trader.binance_data import HOUR_MS, utc_ms
from jev_trader.broad_jev_research import build_events, filtered_policy
from jev_trader.broad_jev_policy import QUESTIONS


PASS = {name: 1.0 for name in QUESTIONS}
FAIL = {name: 0.0 for name in QUESTIONS}
DAY = utc_ms("2024-01-01")  # Monday.


class BroadJevIntegrationTests(unittest.TestCase):
    def test_events_only_closed_monday_states_before_execution(self):
        states = {"SYNTH": {DAY: {"latest_observed_close_ms": DAY},
                            DAY + 86_400_000: {"latest_observed_close_ms": DAY + 86_400_000}}}
        with patch("jev_trader.broad_jev_research.target_weights", side_effect=lambda current, rule: {"SYNTH": .5} if current else {}), \
             patch("jev_trader.broad_jev_research.market_state", return_value={"synthetic": True}), \
             patch("jev_trader.broad_jev_research.numeric_adherence", return_value=PASS):
            events, lookup = build_events(states, ("synthetic",))
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["signal_close_ms"], DAY)
            self.assertEqual(events[0]["execution_ms"], DAY + HOUR_MS)
            self.assertEqual(lookup[(DAY, "SYNTH")], events[0])
            states["SYNTH"][DAY]["latest_observed_close_ms"] += 1
            with self.assertRaisesRegex(ValueError, "noncausal"):
                build_events(states, ("synthetic",))

    def fixture(self):
        weights = {"LONG": .25, "SHORT": -.125, "BTCUSDT": -.125}
        lookup = {(DAY, symbol): {"key": symbol, "base_weight": weight,
                                  "numeric_adherence": FAIL if symbol == "SHORT" else PASS}
                  for symbol, weight in weights.items()}
        states = {symbol: {"latest_observed_close_ms": DAY} for symbol in weights}
        return weights, lookup, states

    def test_filter_preserves_even_unapproved_hedge_legs_and_uses_same_scoring_contract(self):
        weights, lookup, states = self.fixture()
        decisions = {symbol: {"adherence": row["numeric_adherence"]} for (_, symbol), row in lookup.items()}
        with patch("jev_trader.broad_jev_research.target_weights", return_value=weights):
            numeric = filtered_policy(lookup, "numeric", 4)(states, "synthetic")
            jev = filtered_policy(lookup, "jev", 4, decisions)(states, "synthetic")
        self.assertEqual(numeric, {s: w * 4 for s, w in weights.items()})
        self.assertEqual(jev, numeric)
        self.assertIn("SHORT", numeric)
        self.assertEqual(sum(abs(w) for w in numeric.values()), 2)

    def test_missing_jev_scores_never_fall_back_to_numeric_or_cash(self):
        weights, lookup, states = self.fixture()
        with patch("jev_trader.broad_jev_research.target_weights", return_value=weights):
            with self.assertRaises(KeyError):
                filtered_policy(lookup, "jev", 1, {})(states, "synthetic")

    def test_changed_weights_or_mixed_cutoffs_do_not_reuse_old_event(self):
        weights, lookup, states = self.fixture()
        with patch("jev_trader.broad_jev_research.target_weights", return_value={**weights, "LONG": .2}):
            with self.assertRaisesRegex(ValueError, "weights differ"):
                filtered_policy(lookup, "numeric", 1)(states, "synthetic")
        states["BTCUSDT"]["latest_observed_close_ms"] += 86_400_000
        with patch("jev_trader.broad_jev_research.target_weights", return_value=weights):
            with self.assertRaisesRegex(ValueError, "mixed decision"):
                filtered_policy(lookup, "numeric", 1)(states, "synthetic")


if __name__ == "__main__":
    unittest.main()
