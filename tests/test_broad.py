import math
import unittest

from jev_trader.binance_data import Bar, HOUR_MS, utc_ms
from jev_trader.broad_research import DAY_MS, evaluate, features, target_weights, passed
from jev_trader.derivatives_data import Funding


def sample_data(days=235, symbols=8):
    start = utc_ms("2021-01-01")
    result = {kind: {} for kind in ("klines", "markPriceKlines", "fundingRate")}
    for s in range(symbols):
        name = f"C{s}USDT"
        bars = []
        for i in range(days):
            price = 100 + i / 10 + math.sin(i) * (1 + s / 10)
            bars.append(Bar(start + i * DAY_MS, price, price + 1, price - 1, price,
                            100_000, 20_000_000, 100, 50_000 + s * 100))
        result["klines"][name] = bars
        result["markPriceKlines"][name] = bars
        result["fundingRate"][name] = [Funding(start + i * 8 * HOUR_MS, 8, .0001)
                                        for i in range(days * 3)]
    return result


class BroadTests(unittest.TestCase):
    def test_features_do_not_see_future_prices_or_rates(self):
        original = sample_data()
        first = features(original)
        for s in original["klines"]:
            original["klines"][s][230:] = [Bar(b.open_ms, 1, 1, 1, 1, 1, 1, 1, 1)
                                          for b in original["klines"][s][230:]]
            original["fundingRate"][s][690:] = [Funding(r.timestamp_ms, 8, -.01)
                                                for r in original["fundingRate"][s][690:]]
        changed = features(original)
        cutoff = utc_ms("2021-01-01") + 230 * DAY_MS
        for s, records in first.items():
            for t, value in records.items():
                if t <= cutoff:
                    self.assertEqual(value, changed[s][t])

    def test_cross_section_weights_are_neutral_and_liquidity_filtered(self):
        states = {f"C{i}": {"quote_volume20": 20_000_000, "volatility": .03,
                              "momentum30": i} for i in range(20)}
        states["ILLQ"] = {"quote_volume20": 1, "volatility": .03, "momentum30": 999}
        weights = target_weights(states, "momentum30")
        self.assertNotIn("ILLQ", weights)
        self.assertAlmostEqual(sum(weights.values()), 0)
        self.assertAlmostEqual(sum(abs(v) for v in weights.values()), .5)
        self.assertLess(weights["C0"], 0)
        self.assertGreater(weights["C19"], 0)

    def test_insufficient_universe_stays_in_cash(self):
        self.assertEqual(target_weights({}, "momentum30"), {})

    def test_beta_hedge_removes_estimated_exposure_without_leverage(self):
        states = {f"C{i}": {"quote_volume20": 20_000_000, "volatility": .03,
                              "momentum30": i, "beta60": .5 + i / 10} for i in range(20)}
        states["BTCUSDT"] = {"quote_volume20": 1_000_000_000, "volatility": .02,
                             "momentum30": 5, "beta60": 1}
        weights = target_weights(states, "momentum30_betahedged")
        self.assertAlmostEqual(sum(w * states[s]["beta60"] for s, w in weights.items()), 0)
        self.assertLessEqual(sum(abs(v) for v in weights.values()), .50000000001)

    def test_unresolved_disappearance_is_never_a_passing_backtest(self):
        data = sample_data(5)
        start = utc_ms("2021-01-04")  # Monday.
        state = {s: {start: {"quote_volume20": 20_000_000, "volatility": .03,
                            "momentum30": i, "latest_observed_close_ms": start}}
                 for i, s in enumerate(data["klines"])}
        data["klines"]["C7USDT"] = data["klines"]["C7USDT"][:4]
        result = evaluate(data, state, "momentum30", "2021-01-04", "2021-01-05", .0015)
        self.assertEqual(len(result["unresolved_exits"]), 1)
        self.assertFalse(passed(result))


if __name__ == "__main__":
    unittest.main()
