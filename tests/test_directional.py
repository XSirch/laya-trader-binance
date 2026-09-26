import unittest

from jev_trader.adaptive import build_adaptive
from jev_trader.binance_data import Bar, HOUR_MS, utc_ms
from jev_trader.derivatives_data import Funding
from jev_trader.directional import DAY_MS, evaluate, signals


class DirectionalTests(unittest.TestCase):
    def test_short_pnl_and_funding_signs(self):
        start = utc_ms("2025-01-01")
        bars = [Bar(start + i * HOUR_MS, p, p, p, p, 1)
                for i, p in enumerate([100, 100, 80, 80])]
        data = {"klines": {"BTC": bars}, "markPriceKlines": {"BTC": bars},
                "fundingRate": {"BTC": [Funding(start + 2 * HOUR_MS, 8, .001)]}}
        result = evaluate(data, {"BTC": {start + HOUR_MS: -.5}},
                          "2025-01-01", "2025-01-01T03:00:00", 0)
        self.assertAlmostEqual(result["return_pct"], 10.04)
        self.assertAlmostEqual(result["funding_pct_initial"], .04)

    def test_futures_entry_and_exit_cost_use_actual_notional(self):
        start = utc_ms("2025-01-01")
        bars = [Bar(start + i * HOUR_MS, 100, 100, 100, 100, 1) for i in range(4)]
        data = {"klines": {"BTC": bars}, "markPriceKlines": {"BTC": bars}, "fundingRate": {"BTC": []}}
        result = evaluate(data, {"BTC": {start + HOUR_MS: .5}},
                          "2025-01-01", "2025-01-01T03:00:00", .0015)
        self.assertAlmostEqual(result["return_pct"], -.15)

    def test_adaptive_future_performance_cannot_change_prior_weights(self):
        start = utc_ms("2025-01-01")
        experts = {"a": {"BTC": {start + d * DAY_MS + HOUR_MS: .3 for d in range(50)}},
                   "b": {"BTC": {start + d * DAY_MS + HOUR_MS: -.3 for d in range(50)}}}
        histories = {"a": {str(start + d * DAY_MS): 1 + d / 100 for d in range(50)},
                     "b": {str(start + d * DAY_MS): 1 - d / 1000 for d in range(50)}}
        before, audit = build_adaptive(experts, histories, 10, False)
        histories["a"].update({str(start + d * DAY_MS): 1000 for d in range(40, 50)})
        after, _ = build_adaptive(experts, histories, 10, False)
        for t in before["BTC"]:
            if t < start + 40 * DAY_MS:
                self.assertEqual(before["BTC"][t], after["BTC"][t])
        self.assertTrue(all(row["latest_observed_equity_ms"] < row["execution_ms"] for row in audit))

    def test_directional_signal_prefix_and_exposure_cap(self):
        start = utc_ms("2023-04-01")
        original = [Bar(start + i * HOUR_MS, 100 + i / 100, 101 + i / 100,
                        99 + i / 100, 100 + i / 100, 1) for i in range(24 * 230)]
        prefix = signals({"BTC": original[:24 * 220], "ETH": original[:24 * 220]})
        altered = original[:24 * 220] + [Bar(b.open_ms, 1, 1, 1, 1, 1) for b in original[24 * 220:]]
        whole = signals({"BTC": altered, "ETH": altered})
        for name, assets in prefix.items():
            for symbol, values in assets.items():
                for timestamp, value in values.items():
                    self.assertEqual(value, whole[name][symbol][timestamp])
                    self.assertLessEqual(abs(value), .5)


if __name__ == "__main__":
    unittest.main()
