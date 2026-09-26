import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from jev_trader.binance_data import Bar, HOUR_MS, utc_ms
from jev_trader.market_state import aggregate, states
from jev_trader.multifactor import (BudgetedDecisions, CRITERIA, decision_key,
                                   numeric_adherence, script_target)


def bars(count):
    start = utc_ms("2023-04-01")
    return [Bar(start + i * HOUR_MS, 100 + i / 10, 102 + i / 10,
                98 + i / 10, 100 + i / 10 + math.sin(i),
                1000 + i, (1000 + i) * (100 + i / 10), 200, (1000 + i) * .55)
            for i in range(count)]


class MultifactorTests(unittest.TestCase):
    def test_all_indicators_are_prefix_invariant(self):
        original = bars(260)
        before = states(original[:230])
        changed = original[:230] + [Bar(b.open_ms, 1, 2, .5, 1, 99999, 99999, 99999, 50000)
                                    for b in original[230:]]
        self.assertEqual(before, states(changed)[:230])

    def test_aggregate_preserves_extra_exchange_fields(self):
        source = bars(8)
        result = aggregate(source, 4)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].trades, 800)
        self.assertAlmostEqual(result[0].quote_volume, sum(b.quote_volume for b in source[:4]))
        self.assertAlmostEqual(result[0].taker_buy_base, sum(b.taker_buy_base for b in source[:4]))

    def test_script_owns_risk_veto_and_score_validation(self):
        adherence = {name: 1.0 for name in CRITERIA}
        self.assertTrue(script_target(adherence))
        adherence["risk"] = .74
        self.assertFalse(script_target(adherence))
        adherence["risk"] = float("nan")
        with self.assertRaises(ValueError):
            script_target(adherence)

    def test_all_criteria_and_indicators_in_one_call_then_cached(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = BudgetedDecisions(Path(folder) / "cache.jsonl", 2, "redacted")
            state = {"daily": {"rsi": 50, "fibonacci": .5}, "four_hour": {"macd": 1}}
            fake = MagicMock()
            fake.__enter__.return_value = fake
            fake.read.return_value = json.dumps({"model": "typesafe/jev-1.13-test", "id": "test",
                "answers": {name: {"type": "noul", "noul": .8} for name in CRITERIA},
                "usage": {"cost": .0001}}).encode()
            with patch("urllib.request.urlopen", return_value=fake) as request:
                first = cache.decide(state)
                second = cache.decide(state)
                self.assertEqual(first, second)
                self.assertEqual(request.call_count, 1)
                sent = json.loads(request.call_args.args[0].data)
                self.assertEqual(sent["state"], state)
                self.assertEqual(set(sent["questions"]), set(CRITERIA))
                self.assertTrue(all(q["type"] == "noul" for q in sent["questions"].values()))
            self.assertAlmostEqual(cache.spent, .0001)

    def test_budget_blocks_before_network_and_unknown_charge_not_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cache.jsonl"
            cache = BudgetedDecisions(path, .005, "redacted")
            with patch("urllib.request.urlopen") as request:
                with self.assertRaises(RuntimeError):
                    cache.decide({"x": 1})
                request.assert_not_called()
            cache = BudgetedDecisions(path, 2, "redacted")
            with patch("urllib.request.urlopen", side_effect=TimeoutError):
                with self.assertRaises(TimeoutError):
                    cache.decide({"x": 1})
            restored = BudgetedDecisions(path, 2, "redacted")
            self.assertAlmostEqual(restored.spent, .01)
            with patch("urllib.request.urlopen") as request:
                with self.assertRaises(RuntimeError):
                    restored.decide({"x": 1})
                request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
