from copy import deepcopy
import json
import math
import unittest

from jev_trader.forward_portfolio import advance, initialize, MAX_OBSERVATION_GAP_MS


def snapshot(timestamp, prices=None, funding=None):
    return {"server_time_ms": timestamp,
            "accepted_quotes": {
                symbol: {"bidPrice": price - .1, "askPrice": price + .1,
                         "bidQty": 1000.0, "askQty": 1000.0,
                         "quote_time_ms": timestamp - 10, "age_ms": 10}
                for symbol, price in (prices or {}).items()},
            "funding": funding or []}


class ForwardPortfolioTests(unittest.TestCase):
    def assert_reconciles(self, state):
        self.assertAlmostEqual(state["equity"], state["initial_equity"] +
                               state["cumulative_price_pnl"] + state["funding_pnl"] - state["fees"])
        json.dumps(state, allow_nan=False)

    def test_long_short_fills_marks_and_funding_reconcile(self):
        initial = initialize(0)
        first = snapshot(1000, {"LONG": 100, "SHORT": 200})
        first["funding"] = [{"symbol": "LONG", "timestamp_ms": 900, "rate": .01, "mark_price": 100}]
        entered = advance(initial, first, {"LONG": .25, "SHORT": -.25})
        self.assertEqual(entered["positions"]["LONG"]["quantity"], 25)
        self.assertEqual(entered["positions"]["SHORT"]["quantity"], -12.5)
        self.assertEqual(entered["funding_pnl"], 0)  # Positions did not exist at funding.
        long_fill = 100.1 * 1.0005
        short_fill = 199.9 * .9995
        expected_fills = 25 * (100 - long_fill) - 12.5 * (200 - short_fill)
        expected_fees = (25 * long_fill + 12.5 * short_fill) * .001
        self.assertAlmostEqual(entered["cumulative_price_pnl"], expected_fills)
        self.assertAlmostEqual(entered["fees"], expected_fees)
        rows = [{"symbol": "LONG", "timestamp_ms": 1500, "rate": .01, "mark_price": 110},
                {"symbol": "SHORT", "timestamp_ms": 1600, "rate": .02, "mark_price": 180}]
        observed = advance(entered, snapshot(2000, {"LONG": 110, "SHORT": 180}, rows))
        self.assertAlmostEqual(observed["funding_pnl"], -27.5 + 45)
        self.assertAlmostEqual(observed["cumulative_price_pnl"], expected_fills + 500)
        self.assertEqual(observed["fees"], entered["fees"])
        self.assertEqual(observed["positions"]["LONG"]["quantity"], 25)
        self.assert_reconciles(observed)
        closed = advance(observed, snapshot(3000, {"LONG": 110, "SHORT": 180}, rows), {})
        self.assertEqual(closed["positions"], {})
        self.assertIsNone(closed["portfolio_peak"])
        self.assertEqual(closed["funding_pnl"], observed["funding_pnl"])
        exits = [e for e in closed["events"][len(observed["events"]):] if e["type"] == "paper_fill"]
        self.assertTrue(all(e["price_pnl"] < 0 and e["fee"] > 0 for e in exits))
        self.assert_reconciles(closed)

    def test_trailing_exits_all_legs_and_blocks_same_tick_reentry(self):
        entered = advance(initialize(0, trailing_distance=.04),
                          snapshot(1000, {"A": 100, "B": 100}), {"A": .25, "B": -.25})
        previous_peak = entered["portfolio_peak"]
        stopped = advance(entered, snapshot(2000, {"A": 80, "B": 110}), {"UNQUOTED": .5})
        self.assertEqual(stopped["positions"], {})
        self.assertIsNone(stopped["portfolio_peak"])
        trigger = next(e for e in stopped["events"] if e["type"] == "portfolio_trailing")
        self.assertAlmostEqual(trigger["prior_peak"], previous_peak)
        self.assertTrue(trigger["targets_suppressed"])
        stop_fills = [e for e in stopped["events"] if e.get("reason") == "portfolio_trailing"]
        self.assertEqual({e["symbol"] for e in stop_fills}, {"A", "B"})
        self.assert_reconciles(stopped)
        held_flat = advance(stopped, snapshot(3000))
        self.assertFalse(held_flat["positions"])
        reentered = advance(held_flat, snapshot(4000, {"A": 100}), {"A": .25})
        self.assertTrue(reentered["positions"])
        self.assertAlmostEqual(reentered["portfolio_peak"], reentered["equity"])

    def test_unfillable_stop_rejects_every_leg_atomically(self):
        entered = advance(initialize(0, trailing_distance=.04),
                          snapshot(1000, {"A": 100, "B": 100}), {"A": .25, "B": -.25})
        original = deepcopy(entered)
        tick = snapshot(2000, {"A": 80, "B": 110})
        tick["accepted_quotes"]["B"]["askQty"] = 24
        with self.assertRaisesRegex(ValueError, "insufficient top-of-book quantity: B"):
            advance(entered, tick)
        self.assertEqual(entered, original)

    def test_funding_before_exit_can_trigger_stop(self):
        entered = advance(initialize(0, trailing_distance=.04), snapshot(1000, {"A": 100}), {"A": .5})
        funding = [{"symbol": "A", "timestamp_ms": 1500, "rate": .1, "mark_price": 100}]
        stopped = advance(entered, snapshot(2000, {"A": 100}, funding))
        self.assertEqual(stopped["funding_pnl"], -500)
        self.assertFalse(stopped["positions"])
        self.assertTrue(stopped["history"][-1]["trailing_triggered"])

    def test_rebalance_sizes_both_legs_from_one_pre_cost_equity(self):
        entered = advance(initialize(0), snapshot(1000, {"A": 100}), {"A": .25})
        changed = advance(entered, snapshot(2000, {"A": 120, "B": 50}), {"A": -.2, "B": .3})
        reference = entered["equity"] + 25 * 20
        self.assertAlmostEqual(changed["positions"]["A"]["quantity"], -.2 * reference / 120)
        self.assertAlmostEqual(changed["positions"]["B"]["quantity"], .3 * reference / 50)
        self.assert_reconciles(changed)

    def test_held_rebalance_costs_do_not_lower_observed_peak(self):
        entered = advance(initialize(0, trailing_distance=.04),
                          snapshot(1000, {"A": 100}), {"A": .5})
        changed = advance(entered, snapshot(2000, {"A": 110, "B": 100}), {"B": .5})
        observed_high = entered["equity"] + 50 * 10
        self.assertGreater(observed_high, entered["portfolio_peak"])
        self.assertLess(changed["equity"], observed_high)
        self.assertAlmostEqual(changed["portfolio_peak"], observed_high)
        held = advance(changed, snapshot(3000, {"B": 100}))
        self.assertAlmostEqual(held["portfolio_peak"], observed_high)
        self.assert_reconciles(held)

    def test_rejection_has_no_partial_fill_or_input_mutation(self):
        initial = initialize(0)
        quotes = snapshot(1000, {"A": 100, "B": 100})
        quotes["accepted_quotes"]["B"]["askQty"] = 1
        before_state, before_snapshot = deepcopy(initial), deepcopy(quotes)
        with self.assertRaisesRegex(ValueError, "insufficient top-of-book"):
            advance(initial, quotes, {"A": .25, "B": .25})
        self.assertEqual(initial, before_state)
        self.assertEqual(quotes, before_snapshot)
        entered = advance(initial, snapshot(1000, {"A": 100}), {"A": .5})
        copied = deepcopy(entered)
        after = advance(entered, snapshot(2000, {"A": 110}))
        after["events"][0]["symbol"] = "CHANGED"
        self.assertEqual(entered, copied)

    def test_open_gap_and_missing_quote_fail_closed(self):
        entered = advance(initialize(0), snapshot(1000, {"A": 100}), {"A": .5})
        for tick, message in [(snapshot(2000), "missing quote"),
                              (snapshot(1001 + MAX_OBSERVATION_GAP_MS, {"A": 100}), "observation gap"),
                              (snapshot(1000, {"A": 100}), "nonmonotonic")]:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                advance(entered, tick)
        advance(initialize(0), snapshot(MAX_OBSERVATION_GAP_MS + 1000))

    def test_bad_quotes_are_rejected_instead_of_trusted(self):
        cases = [({"age_ms": 30_001, "quote_time_ms": 9_999}, "stale quote"),
                 ({"quote_time_ms": 40_001, "age_ms": 0}, "future quote"),
                 ({"age_ms": 0}, "inconsistent quote age"),
                 ({"bidPrice": 101, "askPrice": 100}, "crossed quote"),
                 ({"askPrice": math.nan}, "invalid ask price"),
                 ({"bidQty": -1}, "invalid bid quantity")]
        for updates, message in cases:
            tick = snapshot(40_000, {"A": 100})
            tick["accepted_quotes"]["A"].update(updates)
            with self.subTest(updates=updates), self.assertRaisesRegex(ValueError, message):
                advance(initialize(0), tick, {"A": .25})

    def test_duplicate_funding_invalid_exposure_and_state_are_rejected(self):
        row = {"symbol": "A", "timestamp_ms": 500, "rate": .001, "mark_price": 100}
        with self.assertRaisesRegex(ValueError, "duplicate funding"):
            advance(initialize(0), snapshot(1000, {"A": 100}, [row, deepcopy(row)]))
        with self.assertRaisesRegex(ValueError, "target gross"):
            advance(initialize(0), snapshot(1000, {"A": 100, "B": 100}), {"A": .3, "B": -.3})
        bad = initialize(0)
        bad["equity"] += 1
        with self.assertRaisesRegex(ValueError, "does not reconcile"):
            advance(bad, snapshot(1000))


if __name__ == "__main__":
    unittest.main()
