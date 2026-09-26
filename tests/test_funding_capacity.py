"""Synthetic funding-index checks; no real data, API, or portfolio claims."""

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import unittest

from jev_trader.funding_capacity import DAY_MS, HOUR_MS, evaluate


MONDAY = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


@dataclass(frozen=True)
class Funding:
    timestamp_ms: int
    interval_hours: int
    rate: float


def iso(timestamp):
    return datetime.fromtimestamp(timestamp / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def history(rate=.0001, interval=8, days=30, cutoff=MONDAY):
    return [Funding(timestamp, interval, rate) for timestamp in
            range(cutoff - days * DAY_MS, cutoff, interval * HOUR_MS)]


def state(cutoff=MONDAY, **changes):
    return {"latest_observed_close_ms": cutoff, "carry30": -.1095,
            "quote_volume20": 20_000_000, "volatility": .02, **changes}


def notice(symbol="AAAUSDT", published=MONDAY, restriction=MONDAY + 2 * DAY_MS,
           settlement=MONDAY + 2 * DAY_MS + HOUR_MS):
    return {"symbol": symbol, "published_utc": iso(published),
            "new_positions_stop_utc": iso(restriction),
            "automatic_settlement_utc": iso(settlement)}


def sample(symbols=("AAAUSDT",), events=None):
    funding = {symbol: history() + list((events or {}).get(symbol, ())) for symbol in symbols}
    states = {symbol: {MONDAY: state()} for symbol in symbols}
    return funding, states


def run(funding, states, rule="top5_30", ratio=.5, end=MONDAY + 7 * DAY_MS, lifecycle=()):
    return evaluate(funding, states, rule, MONDAY, end, ratio, lifecycle)


class FundingCapacityTests(unittest.TestCase):
    def test_actual_one_hour_intervals_reproduce_eight_hour_history(self):
        funding, states = sample()
        eight = run(funding, states)
        funding["AAAUSDT"] = history(rate=.0001 / 8, interval=1)
        one = run(funding, states)
        a, b = eight["weekly_audit"][0]["ranking"][0], one["weekly_audit"][0]["ranking"][0]
        self.assertEqual(a["past30_coverage_hours"], 720)
        self.assertEqual(b["past30_coverage_hours"], 720)
        self.assertEqual(a["past30_event_count"], 90)
        self.assertEqual(b["past30_event_count"], 720)
        self.assertAlmostEqual(a["past30_apr"], b["past30_apr"])

    def test_coverage_uses_interval_hours_not_event_count(self):
        funding, states = sample()
        funding["AAAUSDT"] = [Funding(row.timestamp_ms, 1, row.rate) for row in history()]
        result = run(funding, states)
        self.assertEqual(result["weekly_audit"][0]["selected_weights"], {})
        self.assertEqual(result["final_funding_index"], 1)

    def test_coverage_threshold_and_calendar_apr_are_explicit(self):
        funding, states = sample()
        funding["AAAUSDT"] = history(days=28)
        result = run(funding, states)
        rank = result["weekly_audit"][0]["ranking"][0]
        self.assertEqual(rank["past30_coverage_hours"], 28 * 24)
        self.assertAlmostEqual(rank["past30_apr"], 84 * .0001 * 365 / 30)
        funding["AAAUSDT"].pop()
        self.assertEqual(run(funding, states)["weekly_audit"][0]["selected_weights"], {})

    def test_exact_cutoff_and_future_rates_do_not_enter_ranking(self):
        funding, states = sample(events={"AAAUSDT": [Funding(MONDAY, 8, -.5),
                                                    Funding(MONDAY + 8 * HOUR_MS, 8, .001)]})
        original = run(funding, states)
        changed = copy.deepcopy(funding)
        changed["AAAUSDT"][-1] = Funding(MONDAY + 8 * HOUR_MS, 8, -.001)
        changed["AAAUSDT"][-2] = Funding(MONDAY, 8, .5)
        result = run(changed, states)
        self.assertEqual(original["weekly_audit"], result["weekly_audit"])
        self.assertNotEqual(original["final_funding_index"], result["final_funding_index"])
        self.assertLess(original["weekly_audit"][0]["ranking"][0]["last_observed_funding_ms"], MONDAY)

    def test_future_state_changes_do_not_rewrite_prior_decision(self):
        funding, states = sample()
        baseline = run(funding, states)
        states["AAAUSDT"][MONDAY + 7 * DAY_MS] = state(MONDAY + 7 * DAY_MS, carry30=100)
        self.assertEqual(baseline, run(funding, states))

    def test_entry_collision_skips_credit_but_charges_debit(self):
        for rate, expected, count in ((.001, 1, 0), (-.001, .9995, 1)):
            with self.subTest(rate=rate):
                funding, states = sample(events={"AAAUSDT": [Funding(MONDAY + HOUR_MS, 1, rate)]})
                result = run(funding, states)
                self.assertAlmostEqual(result["final_funding_index"], expected)
                self.assertEqual(result["applied_collision_event_count"], count)

    def test_simultaneous_events_use_the_same_prepayment_index(self):
        timestamp = MONDAY + 8 * HOUR_MS
        funding, states = sample(("AAAUSDT", "BBBUSDT"), {
            "AAAUSDT": [Funding(timestamp, 8, .001)],
            "BBBUSDT": [Funding(timestamp, 8, .002)]})
        result = run(funding, states, ratio=1)
        self.assertAlmostEqual(result["final_funding_index"], 1 + .5 * .001 + .5 * .002)
        self.assertNotEqual(result["final_funding_index"], (1 + .5 * .001) * (1 + .5 * .002))
        self.assertEqual(result["applied_funding_event_count"], 2)

    def test_subsequent_events_compound_reset_notional(self):
        funding, states = sample(events={"AAAUSDT": [Funding(MONDAY + 8 * HOUR_MS, 8, .001),
                                                    Funding(MONDAY + 16 * HOUR_MS, 8, -.001)]})
        result = run(funding, states)
        self.assertAlmostEqual(result["final_funding_index"], 1.0005 * .9995)
        self.assertAlmostEqual(result["funding_index_max_drawdown_pct"], .05)
        self.assertEqual(result["credit_event_count"], 1)
        self.assertEqual(result["debit_event_count"], 1)

    def test_terminal_funding_is_excluded(self):
        end = MONDAY + 7 * DAY_MS
        funding, states = sample(events={"AAAUSDT": [Funding(end, 8, -.5)]})
        result = run(funding, states, end=end)
        self.assertEqual(result["final_funding_index"], 1)
        self.assertEqual(result["daily_index"][-1], {
            "timestamp_ms": end, "index": 1, "boundary": "terminal_excluding_events"})

    def test_rebalance_exit_collision_uses_old_weight_for_debit_only(self):
        rebalance = MONDAY + 7 * DAY_MS + HOUR_MS
        for rate, expected in ((.001, 1), (-.001, .9995)):
            funding, states = sample(events={"AAAUSDT": [Funding(rebalance, 8, rate)]})
            # No next-week state means the explicit target is cash.
            result = run(funding, states, end=MONDAY + 8 * DAY_MS)
            self.assertEqual(len(result["weekly_audit"]), 2)
            self.assertEqual(result["weekly_audit"][1]["selected_weights"], {})
            self.assertAlmostEqual(result["final_funding_index"], expected)

    def test_settlement_collision_and_post_settlement_exclusion(self):
        settlement = MONDAY + 2 * DAY_MS + HOUR_MS
        for rate, expected in ((.001, 1), (-.001, .9995)):
            funding, states = sample(events={"AAAUSDT": [Funding(settlement, 1, rate),
                                                        Funding(settlement + HOUR_MS, 1, -.2)]})
            result = run(funding, states, lifecycle=[notice()])
            self.assertAlmostEqual(result["final_funding_index"], expected)
            self.assertEqual(result["lifecycle_audit"][0]["removed_weight"], .5)

    def test_future_notice_does_not_remove_a_past_position(self):
        payment = MONDAY + DAY_MS
        funding, states = sample(events={"AAAUSDT": [Funding(payment, 8, .001)]})
        plain = run(funding, states)
        future_notice = notice(published=MONDAY + 4 * DAY_MS,
                               restriction=MONDAY + 5 * DAY_MS,
                               settlement=MONDAY + 6 * DAY_MS)
        result = run(funding, states, lifecycle=[future_notice])
        self.assertEqual(plain["weekly_audit"], result["weekly_audit"])
        self.assertEqual(plain["final_funding_index"], result["final_funding_index"])

    def test_late_publication_takes_effect_when_known_not_retroactively(self):
        published = MONDAY + 4 * DAY_MS
        funding, states = sample(events={"AAAUSDT": [Funding(MONDAY + 3 * DAY_MS, 8, .001),
                                                    Funding(published, 8, -.001),
                                                    Funding(published + 8 * HOUR_MS, 8, -.2)]})
        result = run(funding, states, lifecycle=[notice(published=published)])
        self.assertAlmostEqual(result["final_funding_index"], 1.0005 * .9995)
        self.assertEqual(result["lifecycle_audit"][0]["effective_ms"], published)

    def test_known_restriction_at_execution_forbids_new_target(self):
        funding, states = sample()
        event = notice(published=MONDAY + HOUR_MS, restriction=MONDAY + HOUR_MS,
                       settlement=MONDAY + 2 * HOUR_MS)
        result = run(funding, states, lifecycle=[event])
        self.assertEqual(result["weekly_audit"][0]["selected_weights"], {})
        self.assertEqual(result["weekly_audit"][0]["excluded_lifecycle_symbols"], ["AAAUSDT"])

    def test_positive_thirty_day_but_negative_week_is_not_persistent(self):
        funding, states = sample()
        funding["AAAUSDT"] = [Funding(row.timestamp_ms, 8,
                                     -.00005 if row.timestamp_ms >= MONDAY - 7 * DAY_MS else .0001)
                              for row in history()]
        self.assertEqual(run(funding, states)["weekly_audit"][0]["selected_weights"], {"AAAUSDT": .5})
        self.assertEqual(run(funding, states, "top5_persistent")["weekly_audit"][0]["selected_weights"], {})

    def test_persistence_requires_six_days_actual_recent_coverage(self):
        funding, states = sample()
        # Keep 28 total days but place the missing two days inside the last week.
        funding["AAAUSDT"] = [row for row in history() if not
                              MONDAY - 2 * DAY_MS <= row.timestamp_ms < MONDAY]
        self.assertTrue(run(funding, states)["weekly_audit"][0]["selected_weights"])
        self.assertFalse(run(funding, states, "top5_persistent")["weekly_audit"][0]["selected_weights"])

    def test_equal_allocation_top_five_stable_tie_and_top_one(self):
        symbols = tuple(f"COIN{i}USDT" for i in reversed(range(6)))
        funding, states = sample(symbols)
        result = run(funding, states, ratio=1)
        weights = result["weekly_audit"][0]["selected_weights"]
        self.assertEqual(list(weights), sorted(symbols)[:5])
        self.assertEqual(set(weights.values()), {.2})
        self.assertAlmostEqual(sum(weights.values()), 1)
        self.assertEqual(run(funding, states, "top1_30")["weekly_audit"][0]["selected_weights"],
                         {sorted(symbols)[0]: .5})
        self.assertEqual(result["reserve_cash_fraction_assumption"], 0)

    def test_liquidity_and_volatility_bounds_are_inclusive(self):
        funding, states = sample(("AAAUSDT", "BBBUSDT", "CCCUSDT"))
        states["AAAUSDT"][MONDAY] = state(quote_volume20=10_000_000, volatility=.005)
        states["BBBUSDT"][MONDAY] = state(volatility=.15)
        states["CCCUSDT"][MONDAY] = state(quote_volume20=9_999_999)
        self.assertEqual(run(funding, states)["weekly_audit"][0]["selected_weights"],
                         {"AAAUSDT": .25, "BBBUSDT": .25})

    def test_daily_marks_and_metrics_are_index_only(self):
        funding, states = sample(events={"AAAUSDT": [Funding(MONDAY + DAY_MS, 8, .001)]})
        result = run(funding, states)
        self.assertEqual(result["daily_index"][0]["index"], 1)
        self.assertAlmostEqual(result["daily_index"][1]["index"], 1.0005)
        self.assertEqual(len(result["daily_index"]), 8)
        self.assertAlmostEqual(result["funding_index_return_pct"], .05)
        self.assertAlmostEqual(result["funding_index_cagr_pct"], (1.0005 ** (365 / 7) - 1) * 100)
        self.assertFalse(result["goal_achieved"])
        self.assertFalse(result["is_trading_backtest"])
        self.assertFalse(result["portfolio_drawdown_measured"])
        self.assertFalse(result["is_net_portfolio_return"])
        json.dumps(result, allow_nan=False)

    def test_input_mutation_and_order_do_not_change_results(self):
        funding, states = sample(("BBBUSDT", "AAAUSDT"))
        original_funding, original_states = copy.deepcopy(funding), copy.deepcopy(states)
        result = run(funding, states)
        self.assertEqual(funding, original_funding)
        self.assertEqual(states, original_states)
        reversed_funding = {symbol: list(reversed(rows)) for symbol, rows in reversed(list(funding.items()))}
        self.assertEqual(result, run(reversed_funding, dict(reversed(list(states.items())))))

    def test_duplicate_funding_and_nonfinite_data_fail(self):
        funding, states = sample()
        funding["AAAUSDT"].append(funding["AAAUSDT"][0])
        with self.assertRaisesRegex(ValueError, "duplicate funding"):
            run(funding, states)
        for field in ("rate", "interval_hours"):
            for invalid in (math.nan, math.inf, -math.inf, True):
                funding, states = sample()
                row = funding["AAAUSDT"][0]
                funding["AAAUSDT"][0] = Funding(row.timestamp_ms,
                                                invalid if field == "interval_hours" else row.interval_hours,
                                                invalid if field == "rate" else row.rate)
                with self.assertRaises(ValueError):
                    run(funding, states)
        for field in ("carry30", "quote_volume20", "volatility", "technical_unused"):
            funding, states = sample()
            states["AAAUSDT"][MONDAY][field] = math.nan
            with self.assertRaises(ValueError):
                run(funding, states)
        funding, states = sample()
        states["AAAUSDT"][MONDAY]["technical"] = {"nested": [math.inf]}
        with self.assertRaises(ValueError):
            run(funding, states)

    def test_state_timestamp_causality_and_naive_time_fail(self):
        funding, states = sample()
        states["AAAUSDT"][MONDAY]["latest_observed_close_ms"] += DAY_MS
        with self.assertRaisesRegex(ValueError, "daily cutoff"):
            run(funding, states)
        funding, states = sample()
        with self.assertRaises(ValueError):
            evaluate(funding, states, "top5_30", "2024-01-01T00:00:00", "2024-01-08", .5, ())
        with self.assertRaises(ValueError):
            run(funding, states, lifecycle=[notice(), notice()])

    def test_period_has_cash_before_first_monday_entry(self):
        funding, states = sample()
        result = evaluate(funding, states, "top5_30", MONDAY + 2 * HOUR_MS,
                          MONDAY + 6 * DAY_MS, .5, ())
        self.assertEqual(result["weekly_rebalance_count"], 0)
        self.assertEqual(result["final_funding_index"], 1)

    def test_positive_funding_is_required_for_allocation(self):
        for rate in (0, -.0001):
            funding, states = sample()
            funding["AAAUSDT"] = history(rate=rate)
            result = run(funding, states)
            self.assertEqual(result["weekly_audit"][0]["selected_weights"], {})

    def test_persistence_ranks_the_weaker_positive_window(self):
        funding, states = sample(("AAAUSDT", "BBBUSDT"))
        funding["AAAUSDT"] = [Funding(row.timestamp_ms, 8,
                                     .00001 if row.timestamp_ms >= MONDAY - 7 * DAY_MS else .0002)
                              for row in history()]
        funding["BBBUSDT"] = history(rate=.00005)
        broad = run(funding, states)["weekly_audit"][0]["ranking"]
        persistent = run(funding, states, "top5_persistent")["weekly_audit"][0]["ranking"]
        self.assertEqual(broad[0]["symbol"], "AAAUSDT")
        self.assertEqual(persistent[0]["symbol"], "BBBUSDT")
        for row in persistent:
            self.assertEqual(row["ranking_apr"], min(row["past7_apr"], row["past30_apr"]))

    def test_cash_period_and_invalid_configuration(self):
        result = run({}, {})
        self.assertEqual(result["funding_index_cagr_pct"], 0)
        self.assertEqual(result["funding_index_max_drawdown_pct"], 0)
        for ratio in (True, .25, 2, math.nan):
            with self.assertRaises(ValueError):
                run({}, {}, ratio=ratio)
        with self.assertRaises(ValueError):
            run({}, {}, rule="new_optimized_rule")
        with self.assertRaises(ValueError):
            run({}, {}, end=MONDAY)


if __name__ == "__main__":
    unittest.main()
