"""Synthetic paid-spot bookkeeping and execution-risk checks."""

import copy
from dataclasses import replace
import math
import unittest

from jev_trader.binance_data import Bar, HOUR_MS, utc_ms
from jev_trader.hourly_forecast_execution import evaluate


START = utc_ms("2024-01-01")


def fixture(prices, predictions=None):
    spot = {START + index * HOUR_MS: Bar(START + index * HOUR_MS, price, price, price, price,
                                       10, price * 10, 5, 5)
            for index, price in enumerate(prices)}
    predictions = [1] * len(prices) if predictions is None else predictions
    forecasts = {START + index * HOUR_MS: {
        "prediction": value, "latest_observed_close_ms": START + (index - 1) * HOUR_MS,
        "context_sha256": "a" * 64}
        for index, value in enumerate(predictions) if value is not None}
    return spot, forecasts


def run(spot, forecasts, **changes):
    options = dict(start_ms=START, end_ms=max(spot), side_cost=0.0, allocation=1.0, mode="sign")
    options.update(changes)
    return evaluate(spot, forecasts, **options)


class HourlyForecastExecutionTests(unittest.TestCase):
    def test_buy_hold_paid_purchase_two_fees_and_terminal_reconciliation(self):
        spot, forecasts = fixture([100, 110, 120], [0, -1, 1])
        result = run(spot, forecasts, mode="buy_hold", side_cost=.001, allocation=.5)
        quantity = .5 / (100 * 1.001)
        expected_fees = quantity * (100 + 120) * .001
        expected_price = quantity * 20
        self.assertAlmostEqual(result["return_pct"], 100 * (expected_price - expected_fees))
        self.assertAlmostEqual(result["fees_pct_initial"], 100 * expected_fees)
        self.assertAlmostEqual(result["price_pnl_pct_initial"], 100 * expected_price)
        self.assertAlmostEqual(result["turnover"], quantity * 220)
        self.assertAlmostEqual(result["reconciliation_error"], 0)
        self.assertEqual(result["entries"], 1)
        self.assertEqual(len(result["trade_events"]), 2)
        first = result["wallet_snapshots"][str(START)]
        last = result["wallet_snapshots"][str(START + 2 * HOUR_MS)]
        self.assertAlmostEqual(first["cash"], .5)
        self.assertAlmostEqual(first["quantity"], quantity)
        self.assertEqual(last["quantity"], 0)
        self.assertEqual(result["trade_events"][-1]["reason"], "terminal")

    def test_full_allocation_never_borrows_to_pay_entry_fee(self):
        spot, forecasts = fixture([100, 100, 100])
        result = run(spot, forecasts, side_cost=.01)
        self.assertAlmostEqual(result["wallet_snapshots"][str(START)]["cash"], 0)
        self.assertAlmostEqual(result["trade_events"][0]["quantity"], 1 / 101)
        self.assertAlmostEqual(result["return_pct"], -100 * 2 / 101)
        self.assertAlmostEqual(result["max_drawdown_pct"], 100 * 2 / 101)

    def test_positive_sign_keeps_quantity_without_hourly_rebalancing(self):
        spot, forecasts = fixture([100, 130, 90, 120])
        result = run(spot, forecasts, allocation=.5)
        self.assertEqual(len(result["trade_events"]), 2)
        self.assertAlmostEqual(result["trade_events"][0]["quantity"], .005)
        self.assertAlmostEqual(result["trade_events"][1]["quantity"], .005)
        self.assertEqual(result["exposure_hours"], 3)
        self.assertAlmostEqual(result["return_pct"], 10)

    def test_cost_band_retains_small_forecasts_and_avoids_sign_churn(self):
        spot, forecasts = fixture([100] * 7, [.003, .001, 0, -.001, .004, -.003, .5])
        sign = run(spot, forecasts, side_cost=.001, mode="sign")
        band = run(spot, forecasts, side_cost=.001, mode="cost_band")
        self.assertEqual(sign["entries"], 2)
        self.assertEqual(band["entries"], 1)
        self.assertEqual([event["timestamp_ms"] for event in band["trade_events"]],
                         [START, START + 5 * HOUR_MS])
        self.assertLess(band["fees_pct_initial"], sign["fees_pct_initial"])
        self.assertEqual(band["decision_reason_counts"]["inside_cost_band"], 3)

    def test_cost_band_equal_threshold_holds_both_flat_and_invested(self):
        spot, forecasts = fixture([100] * 6, [.002, .0021, -.002, .002, -.0021, 1])
        result = run(spot, forecasts, side_cost=.001, mode="cost_band")
        self.assertEqual([event["timestamp_ms"] for event in result["trade_events"]],
                         [START + HOUR_MS, START + 4 * HOUR_MS])
        self.assertEqual(result["decision_reason_counts"]["inside_cost_band"], 3)

    def test_sign_zero_never_enters_and_exits_an_existing_position(self):
        spot, forecasts = fixture([100] * 5, [0, 1, 0, 0, 1])
        result = run(spot, forecasts)
        self.assertEqual([event["timestamp_ms"] for event in result["trade_events"]],
                         [START + HOUR_MS, START + 2 * HOUR_MS])
        self.assertEqual(result["entries"], 1)

    def test_absent_forecasts_leave_cash_and_retain_existing_quantity(self):
        spot, forecasts = fixture([100, 110, 120, 130, 140], [None, 1, None, None, None])
        result = run(spot, forecasts)
        self.assertEqual(result["entries"], 1)
        self.assertEqual(result["trade_events"][0]["timestamp_ms"], START + HOUR_MS)
        self.assertEqual(result["trade_events"][-1]["timestamp_ms"], START + 4 * HOUR_MS)
        self.assertAlmostEqual(result["return_pct"], (140 / 110 - 1) * 100)
        self.assertEqual(result["decision_reason_counts"]["unavailable_forecast"], 3)

    def test_buy_hold_waits_for_first_available_forecast_even_if_negative(self):
        spot, forecasts = fixture([100, 120, 150, 180], [None, -.2, -.5, .8])
        result = run(spot, forecasts, mode="buy_hold")
        self.assertEqual(result["trade_events"][0]["timestamp_ms"], START + HOUR_MS)
        self.assertAlmostEqual(result["return_pct"], 50)
        self.assertEqual(result["entries"], 1)

    def test_terminal_forecast_cannot_create_position_or_require_unused_clock(self):
        spot, forecasts = fixture([100, 100], [None, 1])
        forecasts[START + HOUR_MS] = {"prediction": 1}
        result = run(spot, forecasts)
        self.assertEqual(result["entries"], 0)
        self.assertEqual(result["return_pct"], 0)
        self.assertEqual(result["trade_events"], [])

    def test_missing_flat_price_can_be_ignored_but_missing_held_price_fails(self):
        spot, forecasts = fixture([100, 100, 100], [None, None, None])
        del spot[START + HOUR_MS]
        self.assertEqual(run(spot, forecasts)["return_pct"], 0)
        forecasts[START] = {"prediction": 1, "latest_observed_close_ms": START - HOUR_MS,
                            "context_sha256": "a" * 64}
        with self.assertRaisesRegex(ValueError, "missing held spot price"):
            run(spot, forecasts)

    def test_missing_entry_price_fails(self):
        spot, forecasts = fixture([100, 100, 100])
        del spot[START]
        with self.assertRaisesRegex(ValueError, "missing execution spot price"):
            run(spot, forecasts)

    def test_nonpositive_trade_count_or_volume_invalidates_every_fill(self):
        for field, value in (("trades", 0), ("trades", None), ("trades", True),
                             ("volume", 0), ("volume", -1), ("volume", math.nan),
                             ("quote_volume", 0), ("quote_volume", -1), ("quote_volume", math.inf)):
            for index in (0, 2):
                with self.subTest(field=field, value=value, index=index):
                    spot, forecasts = fixture([100] * 3)
                    stamp = START + index * HOUR_MS
                    spot[stamp] = replace(spot[stamp], **{field: value})
                    with self.assertRaisesRegex(ValueError, "unverified spot execution liquidity"):
                        run(spot, forecasts)

    def test_zero_trade_candle_while_holding_does_not_invent_a_fill(self):
        spot, forecasts = fixture([100] * 3)
        stamp = START + HOUR_MS
        spot[stamp] = replace(spot[stamp], trades=0, volume=0)
        result = run(spot, forecasts)
        self.assertEqual(result["entries"], 1)
        self.assertEqual(len(result["trade_events"]), 2)

    def test_optional_quote_volume_absence_does_not_invent_a_zero(self):
        spot, forecasts = fixture([100] * 3)
        spot = {stamp: replace(bar, quote_volume=None) for stamp, bar in spot.items()}
        result = run(spot, forecasts)
        self.assertEqual(result["entries"], 1)
        self.assertEqual(result["return_pct"], 0)

    def test_forecast_cutoff_must_equal_execution_minus_exactly_one_hour(self):
        for offset in (0, -2 * HOUR_MS):
            with self.subTest(offset=offset):
                spot, forecasts = fixture([100] * 3)
                forecasts[START]["latest_observed_close_ms"] = START + offset
                with self.assertRaisesRegex(ValueError, "one full hour after completed close"):
                    run(spot, forecasts)

    def test_invalid_forecast_numbers_context_and_execution_keys_fail(self):
        for key, value in (("prediction", math.nan), ("prediction", True),
                           ("prediction", None), ("context_sha256", "unverified")):
            with self.subTest(key=key, value=value):
                spot, forecasts = fixture([100] * 3)
                forecasts[START][key] = value
                with self.assertRaises(ValueError):
                    run(spot, forecasts)
        spot, forecasts = fixture([100] * 3)
        forecasts[START + 1] = forecasts.pop(START)
        with self.assertRaisesRegex(ValueError, "invalid hourly timestamp"):
            run(spot, forecasts)

    def test_trailing_closes_before_policy_and_cannot_reenter_same_hour(self):
        spot, forecasts = fixture([100, 110, 104, 104, 100, 100])
        result = run(spot, forecasts, trailing=.04)
        first_stop = START + 2 * HOUR_MS
        at_stop = [event for event in result["trade_events"] if event["timestamp_ms"] == first_stop]
        self.assertEqual([event["action"] for event in at_stop], ["exit"])
        self.assertEqual(at_stop[0]["reason"], "portfolio_trailing")
        self.assertEqual(result["trade_events"][2]["timestamp_ms"], first_stop + HOUR_MS)
        self.assertEqual(result["stop_count"], 1)
        self.assertGreater(result["max_drawdown_pct"], 4)

    def test_costs_remain_part_of_initial_trailing_peak(self):
        spot, forecasts = fixture([100, 98, 98])
        result = run(spot, forecasts, side_cost=.03, trailing=.04)
        self.assertEqual(result["stop_count"], 1)
        self.assertEqual(result["stop_events"][0]["timestamp_ms"], START + HOUR_MS)
        self.assertAlmostEqual(result["stop_events"][0]["peak"], 1)

    def test_episode_peak_resets_but_global_drawdown_does_not(self):
        spot, forecasts = fixture([100, 94, 94, 90, 90, 90])
        result = run(spot, forecasts, trailing=.04)
        self.assertEqual(result["stop_count"], 2)
        self.assertEqual([event["timestamp_ms"] for event in result["stop_events"]],
                         [START + HOUR_MS, START + 3 * HOUR_MS])
        self.assertAlmostEqual(result["stop_events"][1]["peak"], .94)
        self.assertAlmostEqual(result["max_drawdown_pct"], 10)

    def test_trailing_does_not_use_future_intrahour_high_or_low(self):
        spot, forecasts = fixture([100] * 3)
        spot[START] = replace(spot[START], high=150, low=50)
        result = run(spot, forecasts, trailing=.04)
        self.assertEqual(result["stop_count"], 0)
        self.assertEqual(result["max_drawdown_pct"], 0)
        self.assertAlmostEqual(result["adverse_intrahour_drawdown_bound_pct"], 100 * (1 - 50 / 150))

    def test_intrahour_bound_uses_possible_peak_before_adverse_low(self):
        spot, forecasts = fixture([100, 100])
        spot[START] = replace(spot[START], high=120, low=90)
        result = run(spot, forecasts)
        self.assertEqual(result["max_drawdown_pct"], 0)
        self.assertAlmostEqual(result["adverse_intrahour_drawdown_bound_pct"], 25)

    def test_terminal_fee_is_compared_to_prior_possible_intrahour_peak(self):
        spot, forecasts = fixture([100, 100])
        spot[START] = replace(spot[START], high=120, low=100)
        # This unheld terminal candle must not add its subsequent extremes.
        spot[START + HOUR_MS] = replace(spot[START + HOUR_MS], high=1000, low=1)
        result = run(spot, forecasts, side_cost=.01)
        quantity = 1 / 101
        final_equity = quantity * 100 * .99
        self.assertAlmostEqual(result["adverse_intrahour_drawdown_bound_pct"],
                               100 * (1 - final_equity / (quantity * 120)))

    def test_exit_fee_after_signal_still_uses_prior_intrahour_peak(self):
        spot, forecasts = fixture([100, 100, 100], [1, 0, 0])
        spot[START] = replace(spot[START], high=120, low=100)
        result = run(spot, forecasts, side_cost=.01)
        quantity = 1 / 101
        self.assertAlmostEqual(result["adverse_intrahour_drawdown_bound_pct"],
                               100 * (1 - (quantity * 100 * .99) / (quantity * 120)))
        self.assertEqual(result["exposure_hours"], 1)

    def test_daily_wallets_and_monthly_chain_include_terminal_costs(self):
        start = utc_ms("2024-01-31T23:00:00")
        spot, forecasts = fixture([100, 110, 120])
        delta = start - START
        shifted_spot = {stamp + delta: replace(bar, open_ms=stamp + delta) for stamp, bar in spot.items()}
        shifted_forecasts = {stamp + delta: dict(row, latest_observed_close_ms=row["latest_observed_close_ms"] + delta)
                             for stamp, row in forecasts.items()}
        result = run(shifted_spot, shifted_forecasts, start_ms=start, end_ms=start + 2 * HOUR_MS, side_cost=.001)
        self.assertEqual(set(result["monthly_returns_pct"]), {"2024-01", "2024-02"})
        compounded = math.prod(1 + value / 100 for value in result["monthly_returns_pct"].values())
        self.assertAlmostEqual(compounded, 1 + result["return_pct"] / 100)
        final = result["wallet_snapshots"][str(start + 2 * HOUR_MS)]
        self.assertEqual(final["quantity"], 0)
        self.assertAlmostEqual(final["cash"], result["hourly_equity"][-1][1])

    def test_deterministic_decision_digest_preserves_inputs(self):
        spot, forecasts = fixture([100, 101, 100, 99], [1, None, 0, 1])
        before = copy.deepcopy((spot, forecasts))
        first, second = run(spot, forecasts), run(spot, forecasts)
        self.assertEqual(first, second)
        self.assertEqual((spot, forecasts), before)
        self.assertEqual(sum(first["decision_counts"].values()), 4)
        self.assertEqual(len(first["decision_digest"]), 64)
        forecasts[START]["context_sha256"] = "b" * 64
        self.assertNotEqual(first["decision_digest"], run(spot, forecasts)["decision_digest"])

    def test_invalid_configuration_fails_without_replay(self):
        spot, forecasts = fixture([100] * 3)
        for changes in ({"allocation": 1.1}, {"allocation": .75}, {"allocation": True},
                        {"side_cost": -1}, {"side_cost": 1}, {"mode": "short"},
                        {"trailing": 0}, {"mode": "buy_hold", "trailing": .04},
                        {"end_ms": START}, {"start_ms": START + 1}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    run(spot, forecasts, **changes)


if __name__ == "__main__":
    unittest.main()
