import unittest
from unittest.mock import patch

from jev_trader.regime_risk import scale_for, select


class RegimeRiskTests(unittest.TestCase):
    def test_alignment_accounts_for_short_direction(self):
        states = {s: {"quote_volume20": 20_000_000, "volatility": .02, "score": score}
                  for s, score in (("long", 1), ("short", -1))}
        with patch("jev_trader.regime_risk.directional_score", side_effect=lambda r: r["score"]):
            self.assertEqual(scale_for(states, {"long": .25, "short": -.25}, "confluence"), 1)
            self.assertEqual(scale_for(states, {"long": -.25, "short": .25}, "confluence"), .25)

    def test_volatility_reduces_but_never_amplifies_exposure(self):
        with patch("jev_trader.regime_risk.directional_score", return_value=0):
            for vol, expected in ((.01, 1), (.03, 1), (.06, .5), (.12, .25)):
                state = {"A": {"quote_volume20": 20_000_000, "volatility": vol}}
                self.assertAlmostEqual(scale_for(state, {"A": .5}, "volatility"), expected)
                self.assertAlmostEqual(scale_for(state, {"A": .5}, "combined"), expected * .625)

    def test_selection_rejects_invalid_and_nonpositive_results(self):
        development = {"invalid": {"stress": {"status": "invalid_execution", "return_pct": 999}},
                       "loss": {"stress": {"status": "complete", "return_pct": -1}},
                       "valid": {"stress": {"status": "complete", "return_pct": 2}}}
        self.assertEqual(select(development), "valid")
        del development["valid"]
        self.assertIsNone(select(development))
