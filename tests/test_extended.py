import math
import unittest

from jev_trader.backtest import evaluate_window
from jev_trader.binance_data import Bar, HOUR_MS, utc_ms
from jev_trader.extended import (DAY_MS, daily_bars, features, forecast_signals,
                                 solve, train_rows, robustness)


def sample_days(count):
    start = utc_ms("2023-04-01")
    return [Bar(start + i * DAY_MS, 100 + i + math.sin(i),
                103 + i + math.sin(i), 98 + i + math.sin(i),
                101 + i + math.sin(i), 10) for i in range(count)]


class ExtendedTests(unittest.TestCase):
    def test_entry_fee_precedes_market_return(self):
        start = utc_ms("2025-01-01")
        bars = [Bar(start + (i - 1) * HOUR_MS, price, price, price, price, 1)
                for i, price in enumerate([100, 100, 200])]
        result = evaluate_window({"BTC": bars}, {"BTC": [True] * 3},
                                 "2025-01-01", "2025-01-01T01:00:00", 0.01)
        self.assertAlmostEqual(result.return_pct, 100 * (0.99 * 2 * 0.99 - 1))

    def test_missing_window_start_rejected(self):
        bars = sample_days(5)
        with self.assertRaises(ValueError):
            evaluate_window({"BTC": bars}, {"BTC": [True] * 5},
                            "2023-04-02T12:00:00", "2023-04-05", 0)

    def test_daily_aggregation_rejects_missing_hour(self):
        start = utc_ms("2023-04-01")
        bars = [Bar(start + i * HOUR_MS, 100, 101, 99, 100, 1) for i in range(24)]
        self.assertEqual(daily_bars(bars)[0].volume, 24)
        with self.assertRaises(ValueError):
            daily_bars(bars[:12] + bars[13:])

    def test_training_labels_exclude_unobserved_future(self):
        bars = sample_days(250)
        vectors = {"BTC": [features(bars, i) if i >= 60 else None for i in range(250)]}
        before = train_rows({"BTC": bars}, vectors, 220)
        changed = bars[:221] + [Bar(b.open_ms, 9999, 9999, 9999, 9999, 1) for b in bars[221:]]
        after = train_rows({"BTC": changed}, vectors, 220)
        self.assertEqual(before, after)
        self.assertLessEqual(max(j + 8 for j in range(60, 213) if j % 7 == 0), 220)

    def test_model_signals_have_prefix_invariance(self):
        bars = sample_days(260)
        short, audit, _ = forecast_signals({"BTC": bars[:245]})
        altered = bars[:245] + [Bar(b.open_ms, 9999, 9999, 9999, 9999, 1) for b in bars[245:]]
        long, _, _ = forecast_signals({"BTC": altered})
        for name in short:
            self.assertEqual(short[name]["BTC"], long[name]["BTC"][:245])
        self.assertTrue(all(row["max_training_label_open_ms"] <= row["signal_open_ms"] for row in audit))

    def test_linear_system_solution(self):
        result = solve([[2, 1], [1, 3]], [5, 10])
        self.assertAlmostEqual(result[0], 1)
        self.assertAlmostEqual(result[1], 3)

    def test_daily_and_hourly_execution_have_same_final_equity(self):
        # The robustness replay maps a daily signal only after that day closes.
        start = utc_ms("2024-12-30")
        count = (utc_ms("2026-08-02") - start) // HOUR_MS
        hourly = [Bar(start + i * HOUR_MS, 100 + i / 100,
                      101 + i / 100, 99 + i / 100, 100 + i / 100, 1)
                  for i in range(count)]
        daily = daily_bars(hourly)
        signal = [i % 11 < 5 for i in range(len(daily))]
        result = robustness({"BTC": hourly, "ETH": hourly},
                            {"BTC": daily, "ETH": daily},
                            {"BTC": signal, "ETH": signal})
        direct = evaluate_window({"BTC": daily}, {"BTC": signal},
                                 "2025-01-01", "2026-08-01", 0.0025)
        self.assertAlmostEqual(result["hourly_marked"]["stress"]["return_pct"],
                               direct.return_pct, places=9)
        self.assertEqual(result["hourly_marked"]["stress"]["trades"], direct.trades * 2)


if __name__ == "__main__":
    unittest.main()
