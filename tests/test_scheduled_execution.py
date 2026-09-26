import unittest
from dataclasses import replace

from jev_trader.binance_data import Bar, HOUR_MS, utc_ms
from jev_trader.broad_execution import evaluate as frozen_evaluate
from jev_trader.broad_research import DAY_MS
from jev_trader.derivatives_data import Funding
from jev_trader.scheduled_execution import evaluate
from jev_trader.trailing_stop import TrailingStop


def fixture(start="2024-01-02", days=2, moving=False):
    start_ms = utc_ms(start)
    by_symbol = {}
    for symbol, offset in (("BTCUSDT", 0), ("ETHUSDT", 17)):
        rows = {}
        for hour in range(days * 24 + 1):
            timestamp = start_ms + hour * HOUR_MS
            price = 100.0 if not moving else 100.0 + ((hour + offset) % 37) / 2
            rows[timestamp] = Bar(timestamp, price, price + (1 if moving else 0),
                                  price - (1 if moving else 0), price, 100, 10000, 10, 50)
        by_symbol[symbol] = rows
    return start_ms, {"klines": by_symbol,
                      "markPriceKlines": {s: dict(rows) for s, rows in by_symbol.items()}}


def fixed_policy(state, rule):
    return {"BTCUSDT": .5}


class ScheduledExecutionTests(unittest.TestCase):
    def test_default_weekly_exactly_matches_frozen_accounting(self):
        start, hourly = fixture("2024-01-01", 9, moving=True)
        states = {"BTCUSDT": {start + day * DAY_MS: {"day": day} for day in range(10)}}
        funding = {s: [Funding(start + hour * HOUR_MS + 5, 8,
                               .001 if hour % 16 else -.002)
                       for hour in range(1, 217, 8)] for s in hourly["klines"]}

        def policy(state, rule):
            return {"BTCUSDT": .3 if state["BTCUSDT"]["day"] < 7 else -.2,
                    "ETHUSDT": -.2 if state["BTCUSDT"]["day"] < 7 else .3}

        for delay in (1, 2):
            for scope in (None, "position_pct", "portfolio_pct"):
                with self.subTest(delay=delay, scope=scope):
                    options = dict(delay_hours=delay, target_policy=policy)
                    original = frozen_evaluate(
                        hourly, funding, states, "fixed", "2024-01-01", "2024-01-10", .0015,
                        trailing=TrailingStop(scope, .04) if scope else None, **options)
                    current = evaluate(
                        hourly, funding, states, "fixed", "2024-01-01", "2024-01-10", .0015,
                        trailing=TrailingStop(scope, .04) if scope else None, **options)
                    self.assertEqual(current, original)
                    self.assertEqual(current["rebalances"], 2)
                    self.assertNotEqual(current["funding_pct_initial"], 0)
                    self.assertGreater(current["fees_pct_initial"], 0)
                    if scope:
                        self.assertGreater(current["stop_count"], 0)

    def test_daily_uses_midnight_completed_states_at_delayed_execution(self):
        start, hourly = fixture(days=3)
        states = {"BTCUSDT": {start + day * DAY_MS: {"closed_ms": start + day * DAY_MS}
                               for day in range(4)}}
        for delay in (1, 2):
            with self.subTest(delay=delay):
                seen = []

                def policy(state, rule):
                    seen.append(state["BTCUSDT"]["closed_ms"])
                    return {"BTCUSDT": .5}

                result = evaluate(hourly, {}, states, "fixed", "2024-01-02", "2024-01-05", 0,
                                  delay_hours=delay, target_policy=policy, cadence="daily")
                self.assertEqual(seen, [start + day * DAY_MS for day in range(3)])
                self.assertEqual(result["rebalances"], 3)
                self.assertEqual(result["execution_audit"][0]["execution_ms"], start + delay * HOUR_MS)
                for event in result["execution_audit"]:
                    self.assertEqual(event["execution_ms"] - event["latest_input_close_ms"], delay * HOUR_MS)
                self.assertEqual(result["cash_hours"], delay)

    def test_daily_rebalance_charges_only_the_actual_quantity_change(self):
        start, hourly = fixture()
        states = {"BTCUSDT": {start: {"weight": .5}, start + DAY_MS: {"weight": .25}}}
        result = evaluate(hourly, {}, states, "fixed", "2024-01-02", "2024-01-04", .01,
                          target_policy=lambda state, rule: {"BTCUSDT": state["BTCUSDT"]["weight"]},
                          cadence="daily")
        # Entry: q=.005 and cost=.005. Second target: q=.25*.995/100,
        # so the sale is .0025125 units, not a full exit and reentry.
        self.assertAlmostEqual(result["execution_audit"][1]["actual_cost_fraction"], .0025125 / .995)
        self.assertAlmostEqual(result["fees_pct_initial"], 1)
        self.assertAlmostEqual(result["traded_notional_multiple_initial"], 1)
        self.assertAlmostEqual(result["return_pct"], -1)
        self.assertEqual(result["order_changes"], 3)
        self.assertEqual(result["entries"], 1)

    def test_daily_flip_funding_collision_charges_adverse_old_or_new_position(self):
        start, hourly = fixture()
        states = {"BTCUSDT": {start: {"weight": .5}, start + DAY_MS: {"weight": -.5}}}
        collision = start + DAY_MS + HOUR_MS + 5
        for rate in (.01, -.01):
            with self.subTest(rate=rate):
                result = evaluate(hourly, {"BTCUSDT": [Funding(collision, 8, rate)]}, states,
                                  "fixed", "2024-01-02", "2024-01-04", 0,
                                  target_policy=lambda state, rule: {"BTCUSDT": state["BTCUSDT"]["weight"]},
                                  cadence="daily")
                self.assertAlmostEqual(result["funding_pct_initial"], -.5)
                self.assertAlmostEqual(result["return_pct"], -.5)
                self.assertEqual(result["funding_observations"]["hourly_bounds"], 1)

    def test_daily_entry_collision_does_not_grant_uncertain_funding_credit(self):
        start, hourly = fixture(days=1)
        result = evaluate(hourly, {"BTCUSDT": [Funding(start + HOUR_MS + 5, 8, -.01)]}, {},
                          "fixed", "2024-01-02", "2024-01-03", 0,
                          target_policy=fixed_policy, cadence="daily")
        self.assertEqual(result["funding_pct_initial"], 0)

    def test_daily_missing_held_trade_or_mark_price_fails_closed(self):
        for stream in ("klines", "markPriceKlines"):
            with self.subTest(stream=stream):
                start, hourly = fixture()
                del hourly[stream]["BTCUSDT"][start + 3 * HOUR_MS]
                with self.assertRaisesRegex(ValueError, "unresolved held price BTCUSDT"):
                    evaluate(hourly, {}, {}, "fixed", "2024-01-02", "2024-01-04", 0,
                             target_policy=fixed_policy, cadence="daily")

    def test_terminal_closes_positions_and_excludes_terminal_and_later_funding(self):
        start, hourly = fixture(days=1)
        funding = {"BTCUSDT": [Funding(start + 24 * HOUR_MS, 8, .9),
                               Funding(start + 25 * HOUR_MS, 8, .9)]}
        result = evaluate(hourly, funding, {}, "fixed", "2024-01-02", "2024-01-03", .001,
                          target_policy=fixed_policy, cadence="daily")
        self.assertAlmostEqual(result["return_pct"], -.1)
        self.assertAlmostEqual(result["fees_pct_initial"], .1)
        self.assertEqual(result["funding_pct_initial"], 0)
        self.assertEqual(result["order_changes"], 2)
        self.assertEqual(result["rebalances"], 1)
        self.assertEqual(result["observed_hours"], 24)
        self.assertAlmostEqual(result["daily_equity"][str(start + DAY_MS)], .999)

    def test_terminal_exit_requires_observed_trade_liquidity(self):
        for cadence in ("weekly", "daily"):
            with self.subTest(cadence=cadence):
                start, hourly = fixture("2024-01-01", days=1)
                terminal = start + DAY_MS
                hourly["klines"]["BTCUSDT"][terminal] = replace(
                    hourly["klines"]["BTCUSDT"][terminal], trades=0)
                with self.assertRaisesRegex(ValueError, "unverified execution liquidity BTCUSDT"):
                    evaluate(hourly, {}, {}, "fixed", "2024-01-01", "2024-01-02", 0,
                             target_policy=fixed_policy, cadence=cadence)

    def test_daily_exit_removed_from_targets_still_requires_trade_liquidity(self):
        start, hourly = fixture()
        exit_time = start + DAY_MS + HOUR_MS
        hourly["klines"]["BTCUSDT"][exit_time] = replace(
            hourly["klines"]["BTCUSDT"][exit_time], trades=0)
        states = {"BTCUSDT": {start: {"enter": True}, start + DAY_MS: {"enter": False}}}
        with self.assertRaisesRegex(ValueError, "unverified execution liquidity BTCUSDT"):
            evaluate(hourly, {}, states, "fixed", "2024-01-02", "2024-01-04", 0,
                     target_policy=lambda state, rule: {"BTCUSDT": .5} if state["BTCUSDT"]["enter"] else {},
                     cadence="daily")

    def test_open_and_intrahour_stop_closes_require_trade_liquidity(self):
        for gap in (True, False):
            with self.subTest(gap=gap):
                start, hourly = fixture(days=1)
                stop_time = start + 2 * HOUR_MS
                candle = replace(hourly["klines"]["BTCUSDT"][stop_time],
                                 open=95 if gap else 100, high=95 if gap else 101,
                                 low=95, close=95, trades=0)
                hourly["klines"]["BTCUSDT"][stop_time] = candle
                hourly["markPriceKlines"]["BTCUSDT"][stop_time] = candle
                with self.assertRaisesRegex(ValueError, "unverified execution liquidity BTCUSDT"):
                    evaluate(hourly, {}, {}, "fixed", "2024-01-02", "2024-01-03", 0,
                             target_policy=fixed_policy, cadence="daily",
                             trailing=TrailingStop("position_pct", .04))

    def test_unknown_cadence_and_execution_delays_are_rejected(self):
        _, hourly = fixture()
        for cadence in ("monthly", "", None, 1):
            with self.subTest(cadence=cadence), self.assertRaisesRegex(ValueError, "cadence"):
                evaluate(hourly, {}, {}, "fixed", "2024-01-02", "2024-01-04", 0, cadence=cadence)
        for delay in (0, 3):
            with self.subTest(delay=delay), self.assertRaisesRegex(ValueError, "delay"):
                evaluate(hourly, {}, {}, "fixed", "2024-01-02", "2024-01-04", 0,
                         delay_hours=delay, cadence="daily")


if __name__ == "__main__":
    unittest.main()
