"""Synthetic pair allocation checks without orders, downloads, or backtests."""

import copy
from datetime import datetime, timezone
import math
import unittest

from jev_trader.funding_event_policy import DAY_MS, HOUR_MS, EventPolicy


DAY = int(datetime(2025, 1, 2, tzinfo=timezone.utc).timestamp() * 1000)


def iso(timestamp):
    return datetime.fromtimestamp(timestamp / 1000, timezone.utc).isoformat()


def states(count=8):
    symbols = ["BTCUSDT", *(f"ALT{i}USDT" for i in range(count - 1))]
    return {symbol: {"latest_observed_close_ms": DAY + HOUR_MS, "event_timestamp_ms": DAY + 47,
                     "quote_volume20": 20_000_000, "volatility": .02, "beta60": 1.0,
                     "event.funding_rate": 0.0, "prediction": 0.0 if symbol == "BTCUSDT" else .02}
            for symbol in symbols}


def notice(symbol="ALT0USDT", published=DAY, restricted=DAY + 26 * HOUR_MS):
    return {"symbol": symbol, "published_utc": iso(published), "new_positions_stop_utc": iso(restricted),
            "automatic_settlement_utc": iso(restricted + HOUR_MS)}


class FundingEventPolicyTests(unittest.TestCase):
    def test_top_three_tie_break_pair_budget_and_beta_hedge(self):
        source = states()
        source["BTCUSDT"]["beta60"] = 2.0
        policy = EventPolicy([], gross_limit=2, side_cost=.0015)
        result = policy(source, "test")
        self.assertEqual([row["symbol"] for row in policy.audit[-1]["chosen"]], ["ALT0USDT", "ALT1USDT", "ALT2USDT"])
        for symbol in ("ALT0USDT", "ALT1USDT", "ALT2USDT"):
            self.assertAlmostEqual(result[symbol], (2 / 3) / 1.5)
        self.assertAlmostEqual(result["BTCUSDT"], -2 / 3)
        self.assertLessEqual(math.fsum(map(abs, result.values())), 2)
        self.assertAlmostEqual(math.fsum(w * source[s]["beta60"] for s, w in result.items()), 0)

    def test_funding_expense_sign_is_per_leg_and_benefits_are_not_counted(self):
        cases = ((.02, .001, .0002, .001), (-.02, .001, .0002, .0004),
                 (.02, -.001, -.0002, .0004), (-.02, -.001, -.0002, .001))
        for prediction, alt_rate, btc_rate, adverse in cases:
            with self.subTest(prediction=prediction, alt_rate=alt_rate, btc_rate=btc_rate):
                source = states()
                source["ALT0USDT"].update(prediction=prediction, beta60=2, **{"event.funding_rate": alt_rate})
                source["BTCUSDT"]["event.funding_rate"] = btc_rate
                policy = EventPolicy([])
                policy(source, "test")
                row = next(row for row in policy.audit[-1]["candidates"] if row["symbol"] == "ALT0USDT")
                self.assertAlmostEqual(row["adverse_funding"], adverse)
                self.assertAlmostEqual(row["hurdle"], .003 + adverse)

    def test_side_cost_stress_changes_hurdle_before_selection(self):
        source = states()
        for symbol, row in source.items():
            if symbol != "BTCUSDT":
                row["prediction"] = .004
        normal, stress = EventPolicy([], side_cost=.0015), EventPolicy([], side_cost=.003)
        self.assertTrue(normal(source, "test"))
        self.assertEqual(stress(source, "test"), {})
        self.assertTrue(all(row["hurdle"] == .006 for row in stress.audit[-1]["candidates"]))

    def test_strict_positive_edge_and_no_centering(self):
        source = states()
        for symbol, row in source.items():
            if symbol != "BTCUSDT":
                row["prediction"] = .003
        self.assertEqual(EventPolicy([])(source, "test"), {})
        source["ALT0USDT"]["prediction"] = .0030000001
        result = EventPolicy([])(source, "test")
        self.assertGreater(result["ALT0USDT"], 0)

    def test_hedge_netting_does_not_reinflate_gross(self):
        source = states()
        for symbol, row in source.items():
            row["prediction"] = 0
        source["ALT0USDT"]["prediction"] = .03
        source["ALT1USDT"]["prediction"] = -.03
        result = EventPolicy([])(source, "test")
        self.assertEqual(result, {"ALT0USDT": .25, "ALT1USDT": -.25})
        self.assertEqual(math.fsum(map(abs, result.values())), .5)

    def test_rank_is_net_edge_not_absolute_forecast(self):
        source = states()
        source["ALT0USDT"].update(prediction=.025, **{"event.funding_rate": .02})
        policy = EventPolicy([])
        policy(source, "test")
        self.assertEqual([row["symbol"] for row in policy.audit[-1]["chosen"]], ["ALT1USDT", "ALT2USDT", "ALT3USDT"])

    def test_announced_restriction_before_planned_exit_excludes_now(self):
        source = states(9)
        policy = EventPolicy([notice()])
        result = policy(source, "test")
        self.assertNotIn("ALT0USDT", result)
        self.assertEqual(policy.audit[-1]["excluded_lifecycle"], ["ALT0USDT"])
        unpublished = EventPolicy([notice(published=DAY + 2 * HOUR_MS)])
        self.assertIn("ALT0USDT", unpublished(source, "test"))
        later = EventPolicy([notice(restricted=DAY + 26 * HOUR_MS + 1)])
        self.assertIn("ALT0USDT", later(source, "test"))

    def test_end_window_exact_exit_allowed_but_later_exit_returns_cash(self):
        source = states()
        self.assertTrue(EventPolicy([], end_ms=DAY + 26 * HOUR_MS)(source, "test"))
        policy = EventPolicy([], end_ms=DAY + 26 * HOUR_MS - 1)
        self.assertEqual(policy(source, "test"), {})
        self.assertEqual(policy.audit[-1]["reason"], "planned_exit_after_end")

    def test_btc_missing_low_beta_or_fewer_than_eight_returns_cash(self):
        for change in ("missing", "low_beta", "low_volume", "few"):
            with self.subTest(change=change):
                source = states()
                if change == "missing":
                    del source["BTCUSDT"]
                elif change == "low_beta":
                    source["BTCUSDT"]["beta60"] = 1e-8
                elif change == "low_volume":
                    source["BTCUSDT"]["quote_volume20"] = 9_999_999
                else:
                    del source["ALT0USDT"]
                self.assertEqual(EventPolicy([])(source, "test"), {})
        self.assertEqual(EventPolicy([])({}, "test"), {})

    def test_missing_predictions_are_not_filled(self):
        source = states()
        source["ALT0USDT"]["prediction"] = None
        self.assertEqual(EventPolicy([])(source, "test"), {})
        source = states()
        del source["BTCUSDT"]["prediction"]
        self.assertEqual(EventPolicy([])(source, "test"), {})

    def test_invalid_inputs_and_event_boundary_rejected(self):
        for field, value in (("event_timestamp_ms", DAY + 60_000), ("event_timestamp_ms", DAY - 1),
                             ("latest_observed_close_ms", DAY), ("beta60", math.inf),
                             ("event.funding_rate", math.nan), ("prediction", True)):
            with self.subTest(field=field):
                source = states()
                source["ALT0USDT"][field] = value
                with self.assertRaises(ValueError):
                    EventPolicy([])(source, "test")
        for kwargs in ({"gross_limit": 3}, {"side_cost": 0}, {"end_ms": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                EventPolicy([], **kwargs)

    def test_inputs_unchanged_and_dictionary_order_stable(self):
        source = states()
        before = copy.deepcopy(source)
        first, second = EventPolicy([]), EventPolicy([])
        self.assertEqual(first(source, "test"), second(dict(reversed(list(source.items()))), "test"))
        self.assertEqual(first.audit, second.audit)
        self.assertEqual(source, before)


if __name__ == "__main__":
    unittest.main()
