"""Independent synthetic arithmetic for barrier labels and paid-spot execution."""

import copy
from dataclasses import replace
import math
import unittest
from unittest.mock import patch

from jev_trader.binance_data import Bar, HOUR_MS, utc_ms
from jev_trader.barrier_payoff_execution import (
    ATR_FIELD, ExecutionUnavailable, assess_bar, episode, evaluate,
)


START = utc_ms("2024-01-01")


def fixture(count=10, *, price=100., prediction=.1, atr_pct=10.):
    spot = {START + i * HOUR_MS: Bar(START + i * HOUR_MS, price, price, price, price,
                                   10., price * 10, 5, 5.) for i in range(count)}
    signals = {t: {"prediction": prediction, "latest_observed_close_ms": t - HOUR_MS,
                   "context_sha256": "a" * 64} for t in spot}
    states = {t: {ATR_FIELD: atr_pct, "execution_ms": t,
                  "latest_observed_close_ms": t - HOUR_MS, "context_sha256": "a" * 64} for t in spot}
    return spot, signals, states


def run(spot, signals, states, **changes):
    options = dict(start_ms=START, end_ms=max(spot, default=START + 9 * HOUR_MS),
                   side_cost=0., allocation=1., mode="forecast")
    options.update(changes)
    return evaluate(spot, signals, states, **options)


class BarrierEpisodeTests(unittest.TestCase):
    def test_both_barriers_same_entry_bar_choose_stop_and_unknown_time(self):
        spot, _, _ = fixture()
        spot[START] = replace(spot[START], high=125., low=85.)
        result = episode(spot, START, .1)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["barriers"], {"stop": 90., "target": 120.})
        self.assertEqual((result["exit_price"], result["exit_phase"], result["reason"]), (90., "intrabar", "stop"))
        self.assertTrue(result["ambiguous_bar"])
        self.assertEqual(result["available_ms"], START + HOUR_MS)
        self.assertAlmostEqual(result["gross_return"], -.1)

    def test_intrabar_target_is_fixed_entry_relative_atr(self):
        spot, _, _ = fixture()
        spot[START] = replace(spot[START], high=150., low=95., close=130.)
        result = episode(spot, START, .1)
        self.assertEqual(result["reason"], "target")
        self.assertEqual(result["exit_price"], 120.)
        self.assertAlmostEqual(result["gross_return"], .2)
        self.assertFalse(result["ambiguous_bar"])

    def test_gap_stop_uses_worse_open_and_target_gets_no_favorable_gap(self):
        for opening, expected, reason in ((80., 80., "stop_open"), (130., 120., "target_open")):
            with self.subTest(opening=opening):
                spot, _, _ = fixture()
                t = START + HOUR_MS
                spot[t] = replace(spot[t], open=opening, high=opening, low=opening, close=opening)
                result = episode(spot, START, .1)
                self.assertEqual(result["exit_price"], expected)
                self.assertEqual(result["reason"], reason)
                self.assertEqual(result["exit_phase"], "open")
                self.assertEqual(result["available_ms"], START + 2 * HOUR_MS)

    def test_exact_deadline_open_precedes_that_bar_intrabar_extremes(self):
        spot, _, _ = fixture()
        t = START + 8 * HOUR_MS
        spot[t] = replace(spot[t], open=105., high=200., low=1., close=100.)
        result = episode(spot, START, .1)
        self.assertEqual((result["exit_bar_open_ms"], result["exit_price"], result["reason"]), (t, 105., "timeout"))
        self.assertEqual(result["available_ms"], START + 9 * HOUR_MS)
        self.assertFalse(result["ambiguous_bar"])

    def test_deadline_gap_target_and_stop_preserve_kernel_price_priority(self):
        for opening, expected, reason in ((140., 120., "target_open"), (80., 80., "stop_open")):
            spot, _, _ = fixture()
            t = START + 8 * HOUR_MS
            spot[t] = replace(spot[t], open=opening, high=opening, low=opening, close=opening)
            result = episode(spot, START, .1)
            self.assertEqual((result["exit_price"], result["reason"]), (expected, reason))

    def test_missing_or_invalid_path_invalidates_label_without_skipping(self):
        for field, value in (("trades", 0), ("volume", 0), ("quote_volume", 0), ("high", 90.)):
            with self.subTest(field=field):
                spot, _, _ = fixture()
                t = START + 2 * HOUR_MS
                spot[t] = replace(spot[t], **{field: value})
                result = episode(spot, START, .1)
                self.assertEqual(result["status"], "unavailable")
                self.assertIsNone(result["gross_return"])
                self.assertIsNone(result["available_ms"])
                self.assertEqual(result["failed_bar_open_ms"], t)
        spot, _, _ = fixture()
        del spot[START + HOUR_MS]
        self.assertEqual(episode(spot, START, .1)["failed_bar_open_ms"], START + HOUR_MS)

    def test_quality_of_exit_bar_required_but_post_exit_bar_not_read(self):
        spot, _, _ = fixture()
        spot[START] = replace(spot[START], low=89.)
        result = episode({START: spot[START]}, START, .1)
        self.assertEqual(result["status"], "complete")
        spot[START] = replace(spot[START], trades=0)
        self.assertEqual(episode(spot, START, .1)["status"], "unavailable")

    def test_later_entry_can_have_earlier_availability(self):
        spot, _, _ = fixture()
        t1, t2, t5 = (START + n * HOUR_MS for n in (1, 2, 5))
        spot[t1] = replace(spot[t1], open=110., high=110., low=110., close=110.)
        spot[t2] = replace(spot[t2], low=98.)
        spot[t5] = replace(spot[t5], high=121.)
        early, late = episode(spot, START, .1), episode(spot, t1, .1)
        self.assertEqual(early["available_ms"], START + 6 * HOUR_MS)
        self.assertEqual(late["available_ms"], START + 3 * HOUR_MS)
        self.assertLess(late["available_ms"], early["available_ms"])

    def test_invalid_api_contract_does_not_become_unavailable_label(self):
        spot, _, _ = fixture()
        for atr in (0., -1., 1., math.nan, True, None):
            with self.subTest(atr=atr), self.assertRaises(ValueError):
                episode(spot, START, atr)
        for hours in (0, -1, True, 1.5):
            with self.subTest(hours=hours), self.assertRaises(ValueError):
                episode(spot, START, .1, max_hours=hours)
        with self.assertRaisesRegex(ValueError, "entry price differs"):
            assess_bar(99., .1, START, spot[START])
        with self.assertRaisesRegex(ValueError, "outside episode"):
            assess_bar(100., .1, START, spot[START + 9 * HOUR_MS])


class BarrierExecutionTests(unittest.TestCase):
    def test_paid_allocation_price_pnl_two_fees_and_exact_reconciliation(self):
        spot, signals, states = fixture(count=9)
        t = START + 8 * HOUR_MS
        spot[t] = replace(spot[t], open=105., high=105., low=105., close=105.)
        result = run(spot, signals, states, side_cost=.01, allocation=.5)
        q = .5 / (100 * 1.01)
        fees, pnl = q * 205 * .01, q * 5
        self.assertEqual(result["entries"], 1)
        self.assertEqual(len(result["trade_events"]), 2)
        self.assertAlmostEqual(result["trade_events"][0]["quantity"], q)
        self.assertAlmostEqual(result["trade_events"][-1]["quantity"], q)
        self.assertAlmostEqual(result["fees_pct_initial"], 100 * fees)
        self.assertAlmostEqual(result["price_pnl_pct_initial"], 100 * pnl)
        self.assertAlmostEqual(result["return_pct"], 100 * (pnl - fees))
        self.assertAlmostEqual(result["turnover"], q * 205)
        self.assertAlmostEqual(result["reconciliation_error"], 0)
        self.assertAlmostEqual(result["wallet_snapshots"][str(START)]["cash"], .5)
        self.assertEqual(result["wallet_snapshots"][str(t)]["quantity"], 0)
        self.assertEqual(result["trade_events"][-1]["reason"], "timeout")

    def test_forecast_gate_exact_cost_equality_holds_strictly(self):
        cost = .01
        hurdle = 2 * cost / (1 - cost)
        spot, signals, states = fixture(prediction=hurdle)
        self.assertEqual(run(spot, signals, states, side_cost=cost)["entries"], 0)
        signals[START]["prediction"] = math.nextafter(hurdle, math.inf)
        result = run(spot, signals, states, side_cost=cost)
        self.assertEqual(result["entries"], 1)
        self.assertEqual(result["decision_trace"][0]["hurdle"], hurdle)
        signals[START]["prediction"] = 0.
        self.assertEqual(run(spot, {START: signals[START]}, states)["entries"], 0)

    def test_known_payoff_cap_prevents_impossible_predicted_profit(self):
        spot, signals, states = fixture(atr_pct=.1, prediction=10.)
        result = run(spot, signals, states, side_cost=.0012)
        first = result["decision_trace"][0]
        self.assertEqual(first["raw_prediction"], 10.)
        self.assertEqual(first["effective_prediction"], .002)
        self.assertEqual(first["payoff_cap"], .002)
        self.assertEqual(first["reason"], "barrier_upside_below_cost")
        self.assertEqual(result["entries"], 0)

    def test_atr_percent_is_divided_by_one_hundred(self):
        spot, signals, states = fixture(atr_pct=2.)
        spot[START] = replace(spot[START], high=110., low=99.)
        result = run(spot, {START: signals[START]}, states)
        exit_event = result["trade_events"][-1]
        self.assertEqual(exit_event["price"], 104.)
        self.assertEqual(exit_event["atr_fraction"], .02)

    def test_controls_ignore_score_but_wait_for_same_valid_forecast_and_atr(self):
        for mode in ("always", "buy_hold"):
            with self.subTest(mode=mode):
                spot, signals, states = fixture(count=11, prediction=-1., atr_pct=.1)
                del signals[START]
                states[START + HOUR_MS][ATR_FIELD] = None
                result = run(spot, signals, states, mode=mode, side_cost=.0024)
                self.assertEqual(result["trade_events"][0]["bar_open_ms"], START + 2 * HOUR_MS)
                self.assertEqual(result["entries"], 1)

    def test_buy_hold_ignores_barriers_and_deadline_and_pays_terminal_fee(self):
        spot, signals, states = fixture(count=3, prediction=-1.)
        spot[START] = replace(spot[START], high=150., low=50.)
        terminal = START + 2 * HOUR_MS
        spot[terminal] = replace(spot[terminal], open=120., high=120., low=120., close=120.)
        result = run(spot, signals, states, mode="buy_hold", side_cost=.01)
        q = 1 / 101
        self.assertEqual(result["stop_count"], 0)
        self.assertEqual(result["entries"], 1)
        self.assertEqual(result["trade_events"][-1]["reason"], "terminal")
        self.assertEqual(result["trade_events"][-1]["price"], 120.)
        self.assertAlmostEqual(result["return_pct"], 100 * (q * 120 * .99 - 1))
        self.assertAlmostEqual(result["trade_events"][0]["cash_after"], 0)

    def test_terminal_horizon_known_at_entry_does_not_read_future_outcome(self):
        spot, signals, states = fixture(count=8)
        self.assertEqual(run(spot, signals, states)["entries"], 0)
        self.assertEqual(run(spot, signals, states, mode="always")["entries"], 0)
        self.assertEqual(run(spot, signals, states, mode="buy_hold")["entries"], 1)
        spot, signals, states = fixture(count=9)
        self.assertEqual(run(spot, signals, states)["entries"], 1)

    def test_quantity_fixed_no_overlap_and_no_reentry_on_exit_bar(self):
        spot, signals, states = fixture(count=18)
        result = run(spot, signals, states, allocation=.5)
        self.assertEqual([r["bar_open_ms"] for r in result["trade_events"]],
                         [START + i * HOUR_MS for i in (0, 8, 9, 17)])
        self.assertEqual([r["quantity"] for r in result["trade_events"]], [.005] * 4)
        self.assertEqual(result["exposure_hours"], 16)
        self.assertEqual(result["entries"], 2)

    def test_intrabar_exit_allows_next_bar_entry_but_not_same_bar(self):
        spot, signals, states = fixture(count=10)
        spot[START] = replace(spot[START], low=85.)
        result = run(spot, signals, states)
        self.assertEqual([r["bar_open_ms"] for r in result["trade_events"]],
                         [START, START, START + HOUR_MS, START + 9 * HOUR_MS])
        intrabar = result["trade_events"][1]
        self.assertEqual(intrabar["phase"], "intrabar")
        self.assertIsNone(intrabar["timestamp_ms"])
        self.assertEqual(result["entries"], 2)

    def test_execution_matches_independent_label_at_terminal_gap_target(self):
        spot, signals, states = fixture(count=9)
        terminal = START + 8 * HOUR_MS
        spot[terminal] = replace(spot[terminal], open=140., high=200., low=1., close=140.)
        label = episode(spot, START, .1)
        result = run(spot, signals, states, side_cost=.0012)
        event = result["trade_events"][-1]
        self.assertEqual(event["price"], 120.)
        self.assertEqual(event["price"], label["exit_price"])
        self.assertEqual(event["reason"], label["reason"])
        self.assertAlmostEqual(result["return_pct"], 100 * (1.2 * .9988 / 1.0012 - 1))

    def test_future_paths_do_not_change_initial_entry_or_call_episode(self):
        spot, signals, states = fixture()
        other = copy.deepcopy(spot)
        other[START + HOUR_MS] = replace(other[START + HOUR_MS], high=130.)
        with patch("jev_trader.barrier_payoff_execution.episode", side_effect=AssertionError("future label used")):
            first = run(spot, {START: signals[START]}, states)
            second = run(other, {START: signals[START]}, states)
        self.assertEqual(first["trade_events"][0], second["trade_events"][0])
        self.assertEqual(first["decision_trace"][0], second["decision_trace"][0])
        self.assertNotEqual(first["trade_events"][-1]["reason"], second["trade_events"][-1]["reason"])

    def test_each_entry_held_and_exit_bar_requires_quality_after_fact(self):
        for offset in (0, 3, 8):
            for field, value in (("trades", 0), ("trades", True), ("volume", 0),
                                 ("volume", math.nan), ("quote_volume", -1), ("low", -1)):
                with self.subTest(offset=offset, field=field):
                    spot, signals, states = fixture()
                    t = START + offset * HOUR_MS
                    spot[t] = replace(spot[t], **{field: value})
                    with self.assertRaises(ExecutionUnavailable):
                        run(spot, signals, states)
        for offset in (0, 3, 8):
            spot, signals, states = fixture()
            del spot[START + offset * HOUR_MS]
            with self.assertRaises(ExecutionUnavailable):
                run(spot, signals, states)

    def test_unheld_missing_prices_are_not_quality_based_entry_filters(self):
        spot, signals, states = fixture()
        self.assertEqual(run({}, {}, states, end_ms=START + 9 * HOUR_MS)["entries"], 0)
        del spot[START]
        with self.assertRaises(ExecutionUnavailable):
            run(spot, signals, states)

    def test_optional_quote_volume_not_invented_and_inputs_remain_unchanged(self):
        spot, signals, states = fixture()
        spot = {t: replace(b, quote_volume=None) for t, b in spot.items()}
        original = copy.deepcopy((spot, signals, states))
        first, second = run(spot, signals, states), run(spot, signals, states)
        self.assertEqual(first, second)
        self.assertEqual(original, (spot, signals, states))
        self.assertEqual(sum(first["decision_counts"].values()), 10)
        self.assertEqual(len(first["decision_digest"]), 64)

    def test_absent_state_or_atr_means_no_entry_but_invalid_value_raises(self):
        spot, signals, states = fixture()
        self.assertEqual(run(spot, signals, {})["entries"], 0)
        for state in states.values():
            state[ATR_FIELD] = None
        self.assertEqual(run(spot, signals, states)["entries"], 0)
        for invalid in (0, -1, 100, math.nan, True):
            with self.subTest(invalid=invalid):
                states[START][ATR_FIELD] = invalid
                with self.assertRaises(ValueError) as caught:
                    run(spot, signals, states)
                self.assertNotIsInstance(caught.exception, ExecutionUnavailable)

    def test_signal_state_clock_and_hash_mismatch_abort(self):
        for owner, key, value in (
            ("signal", "latest_observed_close_ms", START),
            ("signal", "latest_observed_close_ms", START - 2 * HOUR_MS),
            ("signal", "context_sha256", "bad"),
            ("signal", "prediction", math.nan),
            ("state", "execution_ms", START + HOUR_MS),
            ("state", "latest_observed_close_ms", START),
            ("state", "context_sha256", "b" * 64),
        ):
            with self.subTest(owner=owner, key=key):
                spot, signals, states = fixture()
                (signals if owner == "signal" else states)[START][key] = value
                with self.assertRaises(ValueError) as caught:
                    run(spot, signals, states)
                self.assertNotIsInstance(caught.exception, ExecutionUnavailable)

    def test_terminal_only_signal_is_not_read_or_traded(self):
        spot, _, states = fixture()
        result = run(spot, {max(spot): {"prediction": 10}}, states)
        self.assertEqual(result["entries"], 0)
        self.assertEqual(result["return_pct"], 0)

    def test_full_bar_bound_retains_extremes_after_intrabar_assumed_stop(self):
        spot, signals, states = fixture()
        spot[START] = replace(spot[START], high=150., low=50.)
        result = run(spot, {START: signals[START]}, states)
        self.assertAlmostEqual(result["max_drawdown_pct"], 10.)
        self.assertAlmostEqual(result["adverse_intrahour_drawdown_bound_pct"], 100 * (1 - .5 / 1.5))
        self.assertEqual(result["exposure_hours"], 1)
        self.assertTrue(result["trade_events"][-1]["ambiguous_bar"])

    def test_open_exit_excludes_later_extremes_but_retains_prior_possible_peak(self):
        spot, signals, states = fixture()
        spot[START] = replace(spot[START], high=110.)
        t = START + HOUR_MS
        spot[t] = replace(spot[t], open=80., high=1000., low=1., close=80.)
        result = run(spot, {START: signals[START]}, states)
        self.assertAlmostEqual(result["max_drawdown_pct"], 20.)
        self.assertAlmostEqual(result["adverse_intrahour_drawdown_bound_pct"], 100 * (1 - .8 / 1.1))
        self.assertEqual(result["exposure_hours"], 1)

    def test_close_marks_are_observed_drawdown_points(self):
        spot, signals, states = fixture(count=3)
        spot[START] = replace(spot[START], high=120., close=120.)
        result = run(spot, signals, states, mode="buy_hold")
        self.assertAlmostEqual(result["max_drawdown_pct"], 100 * (1 - 100 / 120))
        close = [p for p in result["valuation_points"] if p["phase"] == "close" and p["bar_open_ms"] == START][0]
        self.assertEqual(close["timestamp_ms"], START + HOUR_MS)
        self.assertAlmostEqual(close["equity"], 1.2)
        opening = [p for p in result["valuation_points"]
                   if p["kind"] == "open" and p["bar_open_ms"] == START + HOUR_MS][0]
        self.assertEqual(opening["mark_price"], 100.)
        self.assertAlmostEqual(opening["equity"], opening["cash"] + opening["quantity"] * opening["mark_price"])

    def test_terminal_fee_compared_with_possible_prior_peak(self):
        spot, signals, states = fixture(count=2)
        spot[START] = replace(spot[START], high=200.)
        t = START + HOUR_MS
        spot[t] = replace(spot[t], high=1000., low=1.)
        result = run(spot, signals, states, mode="buy_hold", side_cost=.1)
        self.assertAlmostEqual(result["adverse_intrahour_drawdown_bound_pct"], 55.)
        self.assertAlmostEqual(result["max_drawdown_pct"], 100 * (1 - .9 / 1.1))

    def test_daily_wallets_and_months_compound_through_terminal_costs(self):
        start = utc_ms("2024-01-31T23:00:00")
        spot, signals, states = fixture(count=3)
        shift = start - START
        spot = {t + shift: replace(b, open_ms=t + shift) for t, b in spot.items()}
        signals = {t + shift: dict(r, latest_observed_close_ms=r["latest_observed_close_ms"] + shift) for t, r in signals.items()}
        states = {t + shift: dict(r, execution_ms=t + shift, latest_observed_close_ms=r["latest_observed_close_ms"] + shift)
                  for t, r in states.items()}
        result = run(spot, signals, states, start_ms=start, end_ms=max(spot), mode="buy_hold", side_cost=.01)
        self.assertEqual(set(result["monthly_returns_pct"]), {"2024-01", "2024-02"})
        self.assertAlmostEqual(math.prod(1 + r / 100 for r in result["monthly_returns_pct"].values()),
                               1 + result["return_pct"] / 100)
        self.assertEqual(result["wallet_snapshots"][str(max(spot))]["quantity"], 0)
        self.assertEqual(len(result["hourly_equity"]), 3)

    def test_invalid_configuration_raises_without_scenario_invalid_suppression(self):
        spot, signals, states = fixture()
        for changes in ({"side_cost": -1}, {"side_cost": 1}, {"allocation": .75},
                        {"allocation": True}, {"mode": "trailing"}, {"end_ms": START}, {"start_ms": START + 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError) as caught:
                run(spot, signals, states, **changes)
            self.assertNotIsInstance(caught.exception, ExecutionUnavailable)


if __name__ == "__main__":
    unittest.main()
