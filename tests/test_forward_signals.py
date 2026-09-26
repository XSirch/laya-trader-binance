import unittest
from dataclasses import replace

from jev_trader.binance_data import Bar, HOUR_MS, utc_ms
from jev_trader.broad_research import DAY_MS
from jev_trader.derivatives_data import Funding
from jev_trader.forward_signals import feature_cutoff, merge_closed_bars, merge_funding


START = utc_ms("2026-09-24")
SYMBOL = "BTCUSDT"


def candle(opening, price=100):
    return Bar(opening, price, price + 2, price - 2, price + 1,
               100, 10_000, 20, 40)


def kline(bar):
    return [bar.open_ms, str(bar.open), str(bar.high), str(bar.low),
            str(bar.close), str(bar.volume), bar.open_ms + DAY_MS - 1,
            str(bar.quote_volume), bar.trades, str(bar.taker_buy_base), "0", "0"]


def funding_row(timestamp, rate=.0001, mark=100):
    return {"symbol": SYMBOL, "fundingTime": timestamp,
            "fundingRate": str(rate), "markPrice": mark}


class ForwardSignalTests(unittest.TestCase):
    def setUp(self):
        self.bars = [candle(START - DAY_MS), candle(START)]
        self.rates = [Funding(START, 8, .0001), Funding(START + 8 * HOUR_MS, 8, .0001)]

    def test_feature_cutoff_preserves_one_hour_availability_delay(self):
        midnight = START + DAY_MS
        self.assertEqual(feature_cutoff(midnight), START)
        self.assertEqual(feature_cutoff(midnight + HOUR_MS - 1), START)
        self.assertEqual(feature_cutoff(midnight + HOUR_MS), midnight)
        self.assertEqual(feature_cutoff(midnight + DAY_MS - 1), midnight)

    def test_daily_merge_preserves_seed_and_excludes_developing_and_future_bars(self):
        completed = candle(START + DAY_MS, 105)
        cutoff = START + 2 * DAY_MS
        future = kline(candle(cutoff + DAY_MS, 999))
        developing = kline(candle(cutoff, 500))
        # Unfinished price/volume values must never influence completed features.
        developing[4] = "NaN"
        prior = list(self.bars)
        merged = merge_closed_bars(self.bars, [kline(self.bars[-1]), kline(completed),
                                              developing, future], cutoff)
        self.assertEqual(merged, prior + [completed])
        self.assertEqual(self.bars, prior)

    def test_daily_merge_rejects_changed_overlap(self):
        overlap = kline(replace(self.bars[-1], quote_volume=10_100))
        with self.assertRaises(ValueError):
            merge_closed_bars(self.bars, [overlap], START + DAY_MS)

    def test_daily_merge_requires_seed_overlap_and_every_completed_day(self):
        next_day = kline(candle(START + DAY_MS))
        later_day = kline(candle(START + 2 * DAY_MS))
        for rows in ([next_day, later_day], [kline(self.bars[-1]), later_day], []):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                merge_closed_bars(self.bars, rows, START + 3 * DAY_MS)

    def test_daily_merge_rejects_duplicate_or_misaligned_completed_rows(self):
        overlap = kline(self.bars[-1])
        misaligned = kline(candle(START + 1))
        short_close = list(overlap)
        short_close[6] -= 1
        for rows in ([overlap, overlap], [misaligned], [short_close]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                merge_closed_bars(self.bars, rows, START + DAY_MS)

    def test_daily_merge_rejects_invalid_completed_market_values(self):
        cases = [(1, "NaN"), (2, "Infinity"), (3, "102"),
                 (5, "0"), (7, "0"), (8, 0), (9, "101")]
        for index, value in cases:
            row = kline(self.bars[-1])
            row[index] = value
            with self.subTest(index=index, value=value), self.assertRaises(ValueError):
                merge_closed_bars(self.bars, [row], START + DAY_MS)

    def test_funding_merge_preserves_overlap_zero_rate_and_observed_mark(self):
        prior = list(self.rates)
        event = START + 16 * HOUR_MS
        merged, events = merge_funding(self.rates,
                                      [funding_row(prior[-1].timestamp_ms), funding_row(event, 0, 101)],
                                      SYMBOL, event)
        self.assertEqual(merged, prior + [Funding(event, 8, 0)])
        self.assertEqual(self.rates, prior)
        self.assertEqual(events[-1], {"symbol": SYMBOL, "timestamp_ms": event,
                                     "rate": 0, "mark_price": 101})

    def test_funding_merge_uses_hour_bins_without_erasing_timestamp_jitter(self):
        seed = [Funding(START + 300, 8, .0001), Funding(START + 8 * HOUR_MS + 500, 8, .0001)]
        event = START + 16 * HOUR_MS + 1200
        merged, events = merge_funding(seed, [funding_row(seed[-1].timestamp_ms), funding_row(event)],
                                      SYMBOL, event + 500)
        self.assertEqual(merged[-1], Funding(event, 8, .0001))
        self.assertEqual(events[-1]["timestamp_ms"], event)

    def test_funding_merge_accepts_observed_decrease_in_cadence(self):
        event = START + 12 * HOUR_MS
        following = START + 16 * HOUR_MS
        merged, _ = merge_funding(self.rates, [funding_row(self.rates[-1].timestamp_ms),
                                              funding_row(event), funding_row(following)],
                                  SYMBOL, following)
        self.assertEqual([row.interval_hours for row in merged[-2:]], [4, 4])

    def test_funding_merge_rejects_ambiguous_missing_eight_hour_event(self):
        event = START + 24 * HOUR_MS
        with self.assertRaises(ValueError):
            merge_funding(self.rates, [funding_row(self.rates[-1].timestamp_ms), funding_row(event)],
                          SYMBOL, event)

    def test_due_funding_must_be_returned_after_first_minute_despite_prior_jitter(self):
        seed = [Funding(START + 50_000, 8, .0001),
                Funding(START + 8 * HOUR_MS + 50_000, 8, .0001)]
        observed = START + 16 * HOUR_MS + 70_000
        overlap = funding_row(seed[-1].timestamp_ms)
        # A missing due settlement must not be skipped by advancing the account
        # timestamp past it, even while elapsed milliseconds fit the old grace.
        with self.assertRaises(ValueError):
            merge_funding(seed, [overlap], SYMBOL, observed)
        due = START + 16 * HOUR_MS + 50_000
        merged, events = merge_funding(seed, [overlap, funding_row(due)], SYMBOL, observed)
        self.assertEqual(merged[-1], Funding(due, 8, .0001))
        self.assertEqual(events[-1]["timestamp_ms"], due)

    def test_funding_merge_requires_matching_latest_seed_overlap(self):
        overlap = self.rates[-1].timestamp_ms
        event = START + 16 * HOUR_MS
        for rows in ([], [funding_row(event)], [funding_row(overlap, .001), funding_row(event)]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                merge_funding(self.rates, rows, SYMBOL, event)

    def test_funding_merge_rejects_duplicate_and_reversed_events(self):
        overlap = funding_row(self.rates[-1].timestamp_ms)
        event = funding_row(START + 16 * HOUR_MS)
        later = funding_row(START + 24 * HOUR_MS)
        for rows in ([overlap, overlap], [overlap, event, event], [overlap, later, event]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                merge_funding(self.rates, rows, SYMBOL, START + DAY_MS)

    def test_funding_merge_rejects_future_or_excessively_jittered_events(self):
        overlap = funding_row(self.rates[-1].timestamp_ms)
        observed = START + 16 * HOUR_MS
        for timestamp in (observed + 1, START + 8 * HOUR_MS + 60_000):
            with self.subTest(timestamp=timestamp), self.assertRaises(ValueError):
                merge_funding(self.rates, [overlap, funding_row(timestamp)], SYMBOL, observed)

    def test_funding_merge_rejects_missing_nonfinite_or_invalid_mark_and_rate(self):
        overlap = funding_row(self.rates[-1].timestamp_ms)
        event = START + 16 * HOUR_MS
        for field, value in (("markPrice", None), ("markPrice", "NaN"),
                             ("markPrice", 0), ("fundingRate", "Infinity"),
                             ("fundingRate", ".11"), ("symbol", "ETHUSDT"),
                             ("rateType", "Special")):
            row = funding_row(event)
            row[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                merge_funding(self.rates, [overlap, row], SYMBOL, event)


if __name__ == "__main__":
    unittest.main()
