import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jev_trader.backtest import evaluate_window
from jev_trader.binance_data import Bar, HOUR_MS, _time_ms, months, parse_archive
from jev_trader.jev import DecisionCache, JevClient
from jev_trader.strategies import CANDIDATES, causal_state, make_signals


class ResearchTests(unittest.TestCase):
    def test_month_sequence_and_time_units(self):
        self.assertEqual(months("2024-12", "2025-02"),
                         ["2024-12", "2025-01", "2025-02"])
        self.assertEqual(_time_ms("1735689600000000"), 1735689600000)

    def test_next_open_prevents_same_bar_lookahead(self):
        start = 1735689600000
        bars = [Bar(start + (i - 1) * HOUR_MS, value, value, value, value, 1)
                for i, value in enumerate([100, 100, 100, 200, 200, 200])]
        # A signal from bar 1 can first act at bar 2 open, after the 100->200 jump.
        result = evaluate_window({"BTCUSDT": bars},
                                 {"BTCUSDT": [False, False, True, True, True, True]},
                                 "2025-01-01", "2025-01-01T04:00:00", 0.0)
        self.assertAlmostEqual(result.return_pct, 0.0)
        self.assertEqual(result.trades, 1)

    def test_cost_charged_both_sides(self):
        start = 1735689600000
        bars = [Bar(start + (i - 1) * HOUR_MS, 100, 100, 100, 100, 1)
                for i in range(6)]
        result = evaluate_window({"BTCUSDT": bars},
                                 {"BTCUSDT": [True] * len(bars)},
                                 "2025-01-01", "2025-01-01T04:00:00", 0.0015)
        self.assertAlmostEqual(result.return_pct,
                               100 * ((1 - 0.0015) ** 2 - 1), places=7)

    def test_causal_state_ignores_future_bars(self):
        start = 1735689600000
        bars = [Bar(start + i * HOUR_MS, 100 + i, 101 + i, 99 + i,
                    100 + i, 1) for i in range(210)]
        first = causal_state(bars, 200, "BTCUSDT", "trend")
        bars[209] = Bar(bars[209].open_ms, 999, 999, 999, 999, 1)
        self.assertEqual(first, causal_state(bars, 200, "BTCUSDT", "trend"))

    def test_jev_noul_response_validation(self):
        response = {"model": "typesafe/jev-1.13-snapshot", "id": "req1",
                    "usage": {"cost": 0.01},
                    "answers": {"a": {"type": "noul", "noul": 0.8}}}
        fake = unittest.mock.MagicMock()
        fake.__enter__.return_value = fake
        fake.read.return_value = json.dumps(response).encode()
        with patch("urllib.request.urlopen", return_value=fake):
            decision = JevClient("redacted").decide_many({"a": {"price": 100}})["a"]
        self.assertEqual(decision.matches_probability, 0.8)

    def test_jev_rejects_multi_record_request(self):
        with self.assertRaises(ValueError):
            JevClient("redacted").decide_many({"a": {}, "b": {}})

    def test_fixed_candidates_have_no_future_dependency(self):
        start = 1735689600000
        bars = [Bar(start + i * HOUR_MS, 100 + i, 101 + i, 99 + i,
                    100 + i, 1) for i in range(230)]
        for candidate in CANDIDATES:
            first = make_signals(bars[:220], candidate)
            modified = list(bars)
            modified[-1] = Bar(modified[-1].open_ms, 1, 1, 1, 1, 1)
            self.assertEqual(first, make_signals(modified, candidate)[:220])


if __name__ == "__main__":
    unittest.main()
