import copy
import unittest

from jev_trader.broad_research import target_weights
from jev_trader.trailing_universe import exclusion_policy


class ExclusionTests(unittest.TestCase):
    def states(self):
        return {s: {"quote_volume20": 20_000_000, "volatility": .02,
                    "beta60": 1, "carry30": i, "low_volatility30": -i}
                for i, s in enumerate(["BTCUSDT"] + [f"ASSET{i}" for i in range(10)])}

    def test_exclusion_reranks_without_mutating_states(self):
        states = self.states()
        original = copy.deepcopy(states)
        rule = "blend:low_volatility30+carry30_betahedged"
        targets = exclusion_policy("ASSET9")(states, rule)
        self.assertNotIn("ASSET9", targets)
        self.assertEqual(states, original)
        self.assertEqual(targets, target_weights({s: v for s, v in states.items() if s != "ASSET9"}, rule))
        self.assertLessEqual(sum(abs(v) for v in targets.values()), .5 + 1e-12)

    def test_btc_removal_disables_carry_hedge_without_reallocating(self):
        states = self.states()
        policy = exclusion_policy("BTCUSDT")
        self.assertEqual(policy(states, "carry30_betahedged"), {})
        remaining = {s: v for s, v in states.items() if s != "BTCUSDT"}
        expected = {s: v / 2 for s, v in target_weights(remaining, "low_volatility30").items()}
        self.assertEqual(policy(states, "blend:low_volatility30+carry30_betahedged"), expected)
