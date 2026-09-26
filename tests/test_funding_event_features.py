import copy
from dataclasses import replace
import math
import unittest

from jev_trader.binance_data import Bar
from jev_trader.derivatives_data import Funding
from jev_trader.funding_event_features import (
    AVAILABILITY_FIELD, DAY_MS, EVENT_FIELDS, HOUR_MS, INTRADAY_FIELDS, build_states,
)
from jev_trader.positioning_features import FEATURES


DAY = 1_641_168_000_000  # Monday, 2022-01-03 UTC.
FIELDS = ("beta60", "quote_volume20", "volatility") + tuple("base." + str(i) for i in range(57))


def fixture(days=1):
    base = {"BTCUSDT": {}}
    for index in range(days):
        day = DAY + index * DAY_MS
        base["BTCUSDT"][day] = {**dict.fromkeys(FIELDS, 1.0), "latest_observed_close_ms": day,
                                "beta60": .8, "quote_volume20": 20_000_000.0, "volatility": .02}
    funding = [Funding(DAY + index * 8 * HOUR_MS + 7, 999, .001)
               for index in range(-540, days * 3)]
    bars = {}
    for index in range(-23, days * 24):
        timestamp = DAY + index * HOUR_MS
        opening = 100 + index * .1
        close = opening * (1.001 if index % 2 else 1.003)
        bars[timestamp] = Bar(timestamp, opening, close + 1, opening - 1,
                              close, 100.0, 10_000.0, 10, 60.0)
    hourly = {"klines": {"BTCUSDT": bars},
              "markPriceKlines": {"BTCUSDT": {t: replace(bar, close=bar.close * 1.0001)
                                                for t, bar in bars.items()}}}
    positioning = {"BTCUSDT": {DAY: {**base["BTCUSDT"][DAY], **dict.fromkeys(FEATURES, .5),
                                    "positioning_latest_economic_ms": DAY - 2 * DAY_MS - 300_000,
                                    "positioning_source_days": ["2021-12-31", "2021-12-24", "2021-12-03"]}}}
    return {"fundingRate": {"BTCUSDT": funding}}, hourly, base, FIELDS, positioning, FEATURES


class FundingEventFeaturesTests(unittest.TestCase):
    def test_named_schemas_metadata_preserved_base_and_units(self):
        args = fixture()
        before = copy.deepcopy(args)
        states, control, event, audit = build_states(*args)
        row = states["BTCUSDT"][DAY]
        self.assertEqual(args, before)
        self.assertEqual(control, FIELDS + FEATURES + (AVAILABILITY_FIELD,) + INTRADAY_FIELDS)
        self.assertEqual(len(control), 75)
        self.assertEqual(event, EVENT_FIELDS)
        self.assertEqual(len(control + event), 80)
        self.assertEqual([row[f] for f in FIELDS], [args[2]["BTCUSDT"][DAY][f] for f in FIELDS])
        self.assertEqual(row["event_timestamp_ms"], DAY + 7)
        self.assertEqual(row["latest_observed_close_ms"], DAY + HOUR_MS)
        self.assertEqual(row["decision_ms"], DAY + HOUR_MS)
        self.assertEqual(row["execution_ms"], DAY + 2 * HOUR_MS)
        self.assertEqual(row["signal_day_ms"], DAY)
        self.assertFalse(row["historical_point_in_time_verified"])
        self.assertEqual(audit["included_observations"], {"BTCUSDT": 1})
        self.assertEqual(audit["excluded_observations"], [])
        bars = args[1]["klines"]["BTCUSDT"]
        for size in (1, 8, 24):
            self.assertAlmostEqual(row[f"intraday.return{size}h"],
                                   bars[DAY].close / bars[DAY - (size - 1) * HOUR_MS].open - 1)
        logs = [math.log(bars[DAY - i * HOUR_MS].close / bars[DAY - i * HOUR_MS].open) for i in range(24)]
        mean = math.fsum(logs) / 24
        self.assertAlmostEqual(row["intraday.realized_vol24h"],
                               math.sqrt(math.fsum((x - mean) ** 2 for x in logs) / 24))
        self.assertAlmostEqual(row["intraday.taker_flow24h"], .1)
        self.assertAlmostEqual(row["intraday.basis_close"], .0001)

    def test_future_rates_candles_and_positioning_do_not_change_prior_states(self):
        args = fixture()
        expected = build_states(*args)
        rows = args[0]["fundingRate"]["BTCUSDT"]
        args[0]["fundingRate"]["BTCUSDT"] = [replace(row, rate=-.03) if row.timestamp_ms >= DAY + HOUR_MS else row
                                             for row in rows]
        for kind in args[1]:
            args[1][kind]["BTCUSDT"][DAY + HOUR_MS] = None
        args[4]["BTCUSDT"][DAY + 7 * DAY_MS] = {"bad_future_snapshot": True}
        self.assertEqual(build_states(*args), expected)

    def test_midrank_ties_strict_prior_history_and_source_interval_ignored(self):
        args = fixture()
        funding = args[0]["fundingRate"]["BTCUSDT"]
        for index in range(540):
            funding[index] = replace(funding[index], rate=(.0005, .001, .0015)[index % 3])
        states, _, _, _ = build_states(*args)
        row = states["BTCUSDT"][DAY]
        self.assertAlmostEqual(row["event.rank180"], .5)
        self.assertAlmostEqual(row["event.change_previous"], -.0005)
        self.assertAlmostEqual(row["event.minus_mean30"], 0)
        self.assertEqual(row["event.previous_interval_hours"], 8)
        funding[539] = replace(funding[539], timestamp_ms=funding[539].timestamp_ms - 3)
        row = build_states(*args)[0]["BTCUSDT"][DAY]
        self.assertAlmostEqual(row["event.previous_interval_hours"], 8 + 3 / HOUR_MS)

    def test_180_day_lower_boundary_included_and_earlier_rates_excluded(self):
        args = fixture()
        args[0]["fundingRate"]["BTCUSDT"].insert(0, Funding(DAY - 180 * DAY_MS + 6, 8, -.1))
        row = build_states(*args)[0]["BTCUSDT"][DAY]
        self.assertEqual(row["event.rank180"], .5)
        funding = args[0]["fundingRate"]["BTCUSDT"]
        funding[1] = replace(funding[1], rate=-.1)
        row = build_states(*args)[0]["BTCUSDT"][DAY]
        self.assertAlmostEqual(row["event.rank180"], (1 + .5 * 539) / 540)

    def test_minimum_450_prior_events_required(self):
        for prior_count, accepted in ((449, False), (450, True)):
            with self.subTest(prior_count=prior_count):
                args = fixture()
                args[0]["fundingRate"]["BTCUSDT"] = args[0]["fundingRate"]["BTCUSDT"][540 - prior_count:]
                states, _, _, audit = build_states(*args)
                self.assertEqual(bool(states["BTCUSDT"]), accepted)
                if not accepted:
                    self.assertEqual(audit["excluded_observations"][0]["reason"], "insufficient_funding_history180")

    def test_midnight_window_half_open_and_duplicate_event_ambiguity(self):
        for offset, accepted in ((0, True), (59_999, True), (60_000, False), (-1, False)):
            with self.subTest(offset=offset):
                args = fixture()
                rows = args[0]["fundingRate"]["BTCUSDT"]
                rows[540] = replace(rows[540], timestamp_ms=DAY + offset)
                result = build_states(*args)
                self.assertEqual(bool(result[0]["BTCUSDT"]), accepted)
        args = fixture()
        args[0]["fundingRate"]["BTCUSDT"].append(Funding(DAY + 20, 8, .002))
        self.assertEqual(build_states(*args)[3]["exclusion_counts"], {"ambiguous_midnight_funding": 1})

    def test_missing_intraday_hour_never_filled_from_older_or_future(self):
        for offset in (-23, -7, 0):
            with self.subTest(offset=offset):
                args = fixture()
                del args[1]["klines"]["BTCUSDT"][DAY + offset * HOUR_MS]
                result = build_states(*args)
                self.assertFalse(result[0]["BTCUSDT"])
                self.assertEqual(result[3]["exclusion_counts"], {"missing_intraday_hour": 1})

    def test_invalid_intraday_and_zero_total_volume_are_audited(self):
        for change in ({"close": math.nan}, {"taker_buy_base": 101}, {"open_ms": DAY + 1}, {"low": -1}):
            with self.subTest(change=change):
                args = fixture()
                bars = args[1]["klines"]["BTCUSDT"]
                bars[DAY] = replace(bars[DAY], **change)
                self.assertEqual(build_states(*args)[3]["exclusion_counts"], {"invalid_intraday_hour": 1})
        args = fixture()
        bars = args[1]["klines"]["BTCUSDT"]
        args[1]["klines"]["BTCUSDT"] = {t: replace(bar, volume=0, taker_buy_base=0) for t, bar in bars.items()}
        self.assertEqual(build_states(*args)[3]["exclusion_counts"], {"nonpositive_intraday_volume": 1})
        args = fixture()
        del args[1]["markPriceKlines"]["BTCUSDT"][DAY]
        self.assertEqual(build_states(*args)[3]["exclusion_counts"], {"missing_or_invalid_mark_close": 1})

    def test_positioning_carries_within_week_and_resets_when_new_monday_missing(self):
        args = fixture(days=9)
        result = build_states(*args)
        for index in range(9):
            row = result[0]["BTCUSDT"][DAY + index * DAY_MS]
            self.assertEqual(row[AVAILABILITY_FIELD], int(index < 7))
            self.assertEqual([row[f] for f in FEATURES], [.5 if index < 7 else None] * 8)
            self.assertEqual(row["positioning_week_ms"], DAY if index < 7 else DAY + 7 * DAY_MS)
        self.assertEqual(result[3]["positioning_available_observations"], 7)

    def test_missing_positioning_does_not_exclude_observation(self):
        args = fixture()
        args[4].clear()
        row = build_states(*args)[0]["BTCUSDT"][DAY]
        self.assertEqual(row[AVAILABILITY_FIELD], 0)
        self.assertTrue(all(row[f] is None for f in FEATURES))
        self.assertIsNone(row["positioning_latest_economic_ms"])

    def test_invalid_positioning_provenance_rejected(self):
        for key, value in (("latest_observed_close_ms", DAY - DAY_MS),
                           ("positioning_latest_economic_ms", DAY), (FEATURES[0], math.inf)):
            with self.subTest(key=key):
                args = fixture()
                args[4]["BTCUSDT"][DAY][key] = value
                with self.assertRaisesRegex(ValueError, "positioning"):
                    build_states(*args)

    def test_field_schemas_cutoff_and_funding_corruption_fail_closed(self):
        args = fixture()
        with self.assertRaisesRegex(ValueError, "sixty"):
            build_states(*args[:3], FIELDS[:-1], *args[4:])
        with self.assertRaisesRegex(ValueError, "positioning"):
            build_states(*args[:5], FEATURES[::-1])
        args[2]["BTCUSDT"][DAY]["latest_observed_close_ms"] += 1
        with self.assertRaisesRegex(ValueError, "cutoff"):
            build_states(*args)
        args = fixture()
        args[0]["fundingRate"]["BTCUSDT"].append(args[0]["fundingRate"]["BTCUSDT"][0])
        with self.assertRaisesRegex(ValueError, "duplicate funding"):
            build_states(*args)
        args = fixture()
        args[0]["fundingRate"]["BTCUSDT"][0] = Funding(DAY, 8, math.nan)
        with self.assertRaisesRegex(ValueError, "funding requires"):
            build_states(*args)

    def test_no_fill_liquidity_or_future_endpoint_filter(self):
        args = fixture()
        bars = args[1]["klines"]["BTCUSDT"]
        bars[DAY] = replace(bars[DAY], trades=0)
        for timestamp in list(bars):
            if timestamp > DAY:
                del bars[timestamp]
        self.assertTrue(build_states(*args)[0]["BTCUSDT"])

    def test_nonchronological_input_order_is_deterministic_and_pre2022_ignored(self):
        args = fixture()
        expected = build_states(*args)
        args[0]["fundingRate"]["BTCUSDT"].reverse()
        self.assertEqual(build_states(*args), expected)
        args[2]["BTCUSDT"][DAY - 10 * DAY_MS] = {"unused_warmup": True}
        result = build_states(*args)
        self.assertEqual(result[0], expected[0])
        self.assertEqual(result[3]["ignored_before_first_day"], 1)


if __name__ == "__main__":
    unittest.main()
