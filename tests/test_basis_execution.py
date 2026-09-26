import copy
import unittest

from jev_trader.basis_execution import evaluate
from jev_trader.binance_data import Bar, HOUR_MS, utc_ms
from jev_trader.derivatives_data import Funding


START = utc_ms("2025-01-06")


def sample(spot, future=None, mark=None, symbols=("BTCUSDT",)):
    future = spot if future is None else future
    mark = future if mark is None else mark
    market = {kind: {} for kind in ("spot", "futures", "mark", "funding")}
    states = {}
    for symbol in symbols:
        for kind, prices in (("spot", spot), ("futures", future), ("mark", mark)):
            market[kind][symbol] = {START+i*HOUR_MS: Bar(START+i*HOUR_MS, p, p, p, p, 1, p, 1, .5)
                                    for i, p in enumerate(prices)}
        market["funding"][symbol] = []
        states[symbol] = {START+i*HOUR_MS: {"latest_observed_close_ms": START+(i-1)*HOUR_MS,
                                          "symbol": symbol, "hour": i}
                          for i in range(len(spot))}
    return market, states


def enter_then_hold(state, position):
    return {"action": "hold", "reason": "maintain"} if position else {
        "action": "enter", "reason": "synthetic_signal", "target_basis": 0.0}


def run(market, states, policy=enter_then_hold, **kwargs):
    end = max(market["spot"][next(iter(market["spot"]))])
    options = {"max_hold_hours": (end-START)//HOUR_MS, "spot_cost": 0, "future_cost": 0}
    options.update(kwargs)
    return evaluate(market, states, policy, START, end, **options)


class BasisExecutionTests(unittest.TestCase):
    def test_equal_quantity_hedge_conserves_capital_without_costs(self):
        market, states = sample([100, 120, 80, 110])
        result = run(market, states)
        self.assertAlmostEqual(result["return_pct"], 0)
        self.assertAlmostEqual(result["basis_pnl_pct_initial"], 0)
        self.assertEqual(result["entries"], 1)
        self.assertAlmostEqual(result["reconciliation_error"], 0)

    def test_all_four_fees_and_cash_spot_purchase(self):
        market, states = sample([100]*3)
        result = run(market, states, spot_cost=.0025, future_cost=.0015)
        q = .5/(100*1.0025)
        expected = 2*q*100*(.0025+.0015)
        self.assertAlmostEqual(result["fees_pct_initial"], expected*100)
        self.assertAlmostEqual(result["return_pct"], -expected*100)
        first = result["wallet_snapshots"][str(START)]["BTCUSDT"]
        self.assertAlmostEqual(first["spot_cash"], 0)
        self.assertAlmostEqual(first["margin_cash"], .5-q*100*.0015)
        self.assertAlmostEqual(first["spot_quantity"], first["short_quantity"])

    def test_basis_realization_uses_both_entry_and_exit_prices(self):
        market, states = sample([100, 103, 110], [105, 106, 111])
        result = run(market, states)
        q = .5/105
        expected = q*((105-100)-(111-110))
        self.assertAlmostEqual(result["return_pct"], 100*expected)
        self.assertAlmostEqual(result["basis_pnl_pct_initial"], 100*expected)
        self.assertEqual(result["trade_events"][-1]["reason"], "terminal")
        self.assertLessEqual(q*105, .5)
        self.assertLessEqual(q*100, .5)

    def test_unrealized_mark_profit_never_becomes_wallet_cash(self):
        market, states = sample([100]*49, [100]*49, [100]+[80]*47+[100])
        result = run(market, states)
        wallet = result["wallet_snapshots"][str(START+24*HOUR_MS)]["BTCUSDT"]
        self.assertAlmostEqual(wallet["margin_cash"], .5)
        self.assertAlmostEqual(wallet["unrealized_perp_pnl"], .1)
        self.assertAlmostEqual(wallet["equity"], 1.1)
        self.assertAlmostEqual(result["return_pct"], 0)
        self.assertEqual(result["transfer_events"], [])

    def test_transfers_use_only_realized_flat_bucket_cash(self):
        market, states = sample([100]*6, [105, 105, 100, 100, 100, 100])
        def policy(state, position):
            if state["hour"] == 2 and position:
                return {"action": "exit", "reason": "signal_exit"}
            return enter_then_hold(state, position)
        result = run(market, states, policy, max_hold_hours=2)
        self.assertEqual(result["entries"], 2)
        self.assertTrue(result["transfer_events"])
        for transfer in result["transfer_events"]:
            self.assertEqual(transfer["position_quantity"], 0)
            self.assertEqual(transfer["timestamp_ms"], START+3*HOUR_MS)
            self.assertAlmostEqual(transfer["spot_cash_change"]+transfer["margin_cash_change"], 0)

    def test_buckets_cannot_share_cash(self):
        market, states = sample([100]*3, symbols=("BTCUSDT", "ETHUSDT"))
        def policy(state, position):
            if state["symbol"] == "ETHUSDT":
                return {"action": "hold", "reason": "cash"}
            return enter_then_hold(state, position)
        result = run(market, states, policy)
        self.assertAlmostEqual(result["trade_events"][0]["quantity"], .0025)
        for snapshot in result["wallet_snapshots"].values():
            self.assertAlmostEqual(snapshot["ETHUSDT"]["spot_cash"], .25)
            self.assertAlmostEqual(snapshot["ETHUSDT"]["margin_cash"], .25)

    def test_funding_sign_and_adverse_marks(self):
        for rate, expected_price in ((.01, 90), (-.01, 110)):
            with self.subTest(rate=rate):
                market, states = sample([100]*3)
                t = START+HOUR_MS
                market["mark"]["BTCUSDT"][t] = Bar(t, 100, 110, 90, 100, 0)
                market["funding"]["BTCUSDT"] = [Funding(t+1, 8, rate)]
                result = run(market, states)
                payment = .005*rate*expected_price
                self.assertAlmostEqual(result["funding_pct_initial"], payment*100)
                self.assertAlmostEqual(result["return_pct"], payment*100)
                self.assertEqual(result["funding_events"][0]["adverse_mark"], expected_price)

    def test_entry_and_exit_collisions_cannot_create_credit_or_avoid_debit(self):
        for rate in (.01, -.01):
            with self.subTest(rate=rate):
                market, states = sample([100]*4)
                market["funding"]["BTCUSDT"] = [Funding(START+1, 8, rate),
                    Funding(START+2*HOUR_MS+1, 8, rate), Funding(START+3*HOUR_MS, 8, -.5)]
                def policy(state, position):
                    if state["hour"] == 2 and position:
                        return {"action": "exit", "reason": "signal_exit"}
                    return enter_then_hold(state, position)
                result = run(market, states, policy)
                self.assertAlmostEqual(result["funding_pct_initial"], 0 if rate > 0 else 1.0*rate*100)
                self.assertEqual(len(result["funding_events"]), 2)

    def test_positive_funding_does_not_relax_intrahour_stress(self):
        market, states = sample([100]*3)
        t = START+HOUR_MS
        market["mark"]["BTCUSDT"][t] = Bar(t, 100, 185, 100, 100, 0)
        market["funding"]["BTCUSDT"] = [Funding(t, 8, .10)]
        result = run(market, states)
        # Without removing the uncertain credit, the stress ratio exceeds 10%.
        self.assertEqual(result["margin_stress_failures"], 1)
        self.assertAlmostEqual(result["adverse_intrahour_drawdown_bound_pct"], 100*(1-.575/1.05))

    def test_terminal_hour_funding_keeps_possible_debit_but_never_credit(self):
        for offset in (0, 1, HOUR_MS-1):
            for rate in (-.01, .01):
                with self.subTest(offset=offset, rate=rate):
                    market, states = sample([100]*3)
                    end = START+2*HOUR_MS
                    market["funding"]["BTCUSDT"] = [Funding(end+offset, 8, rate)]
                    result = run(market, states)
                    self.assertAlmostEqual(result["funding_pct_initial"], -.5 if rate < 0 else 0)
                    self.assertEqual(result["funding_events"][0]["new_quantity"], 0)
                    self.assertEqual(result["funding_events"][0]["accounting_hour_ms"], end)

    def test_payment_after_terminal_hour_is_excluded(self):
        market, states = sample([100]*3)
        market["funding"]["BTCUSDT"] = [Funding(START+3*HOUR_MS, 8, -.5)]
        result = run(market, states)
        self.assertEqual(result["funding_events"], [])
        self.assertAlmostEqual(result["return_pct"], 0)

    def test_intrahour_bound_includes_possible_peak_before_trough(self):
        market, states = sample([100, 100])
        for kind in ("spot", "mark"):
            market[kind]["BTCUSDT"][START] = Bar(START, 100, 110, 90, 100, 1, 100, 1)
        result = run(market, states)
        self.assertAlmostEqual(result["max_drawdown_pct"], 0)
        self.assertAlmostEqual(result["adverse_intrahour_drawdown_bound_pct"], 100*(1-.9/1.1))

    def test_terminal_fees_are_compared_to_prior_possible_intrahour_peak(self):
        market, states = sample([100, 100])
        market["spot"]["BTCUSDT"][START] = Bar(START, 100, 110, 100, 100, 1, 100, 1)
        market["mark"]["BTCUSDT"][START] = Bar(START, 100, 100, 90, 100, 0)
        result = run(market, states, spot_cost=.01, future_cost=.01)
        q = .5/101
        possible_peak = 1-2*q*100*.01+q*20
        terminal_equity = 1-4*q*100*.01
        self.assertAlmostEqual(result["adverse_intrahour_drawdown_bound_pct"], 100*(1-terminal_equity/possible_peak))

    def test_pre_exit_open_equity_uses_prior_possible_intrahour_peak(self):
        market, states = sample([100]*3, [100]*3, [100, 190, 100])
        market["spot"]["BTCUSDT"][START] = Bar(START, 100, 110, 100, 100, 1, 100, 1)
        market["mark"]["BTCUSDT"][START] = Bar(START, 100, 100, 90, 100, 0)
        result = run(market, states)
        self.assertAlmostEqual(result["return_pct"], 0)
        self.assertAlmostEqual(result["adverse_intrahour_drawdown_bound_pct"], 100*(1-.55/1.1))

    def test_zero_or_missing_trade_counts_block_every_fill(self):
        for kind in ("spot", "futures"):
            for trade_count in (0, None):
                with self.subTest(kind=kind, trades=trade_count):
                    market, states = sample([100]*3)
                    t = START+2*HOUR_MS
                    market[kind]["BTCUSDT"][t] = Bar(t, 100, 100, 100, 100, 0, trades=trade_count)
                    with self.assertRaisesRegex(ValueError, "unverified paired execution liquidity"):
                        run(market, states)

    def test_missing_held_price_fails_closed(self):
        market, states = sample([100]*3)
        del market["mark"]["BTCUSDT"][START+HOUR_MS]
        with self.assertRaisesRegex(ValueError, "missing paired held price"):
            run(market, states)

    def test_positive_trade_count_does_not_override_zero_volume(self):
        for kind in ("spot", "futures"):
            with self.subTest(kind=kind):
                market, states = sample([100]*3)
                market[kind]["BTCUSDT"][START] = Bar(START, 100, 100, 100, 100, 0, 0, 1)
                with self.assertRaisesRegex(ValueError, "unverified paired execution liquidity"):
                    run(market, states)

    def test_exit_cannot_spend_spot_proceeds_to_cover_negative_margin(self):
        market, states = sample([100, 150], [100, 150], [100, 100])
        with self.assertRaisesRegex(ValueError, "negative cash wallet BTCUSDT margin_cash after paired exit"):
            run(market, states, spot_fraction=.8)

    def test_funding_debit_after_close_cannot_make_realized_wallet_negative(self):
        market, states = sample([100]*3)
        market["funding"]["BTCUSDT"] = [Funding(START+HOUR_MS+1, 8, -.5)]
        def policy(state, position):
            if position:
                return {"action": "exit", "reason": "signal_exit"}
            return enter_then_hold(state, position)
        with self.assertRaisesRegex(ValueError, "negative cash wallet BTCUSDT margin_cash after funding payment"):
            run(market, states, policy, spot_fraction=.8)

    def test_margin_prevention_before_policy_and_existing_violation_visible(self):
        market, states = sample([100]*3, [100]*3, [100, 190, 100])
        called = []
        def policy(state, position):
            called.append(state["hour"])
            return enter_then_hold(state, position)
        result = run(market, states, policy)
        self.assertEqual(called, [0])
        self.assertEqual(result["trade_events"][-1]["reason"], "preventive_margin")
        self.assertEqual(result["margin_stress_failures"], 1)

    def test_exact_signal_clock_and_future_state_rejection(self):
        for delta in (0, -2*HOUR_MS, 1):
            with self.subTest(delta=delta):
                market, states = sample([100]*3)
                states["BTCUSDT"][START]["latest_observed_close_ms"] = START+delta
                with self.assertRaisesRegex(ValueError, "one full hour"):
                    run(market, states)

    def test_missing_state_still_allows_maximum_hold_exit(self):
        market, states = sample([100]*5)
        states["BTCUSDT"] = {START: states["BTCUSDT"][START]}
        result = run(market, states, max_hold_hours=2)
        self.assertEqual(result["trade_events"][-1]["timestamp_ms"], START+2*HOUR_MS)
        self.assertEqual(result["trade_events"][-1]["reason"], "maximum_holding")

    def test_entry_requires_whole_holding_window_and_terminal_closes(self):
        market, states = sample([100]*3)
        result = run(market, states, max_hold_hours=3)
        self.assertEqual(result["entries"], 0)
        self.assertEqual(result["decision_reason_counts"]["insufficient_holding_window"], 2)
        result = run(market, states, max_hold_hours=2)
        self.assertEqual(result["entries"], 1)
        self.assertEqual(result["trade_events"][-1]["reason"], "terminal")

    def test_trailing_closes_all_and_prevents_same_hour_reentry(self):
        market, states = sample([100, 80, 80, 80, 80], [100]*5, symbols=("BTCUSDT", "ETHUSDT"))
        result = run(market, states, max_hold_hours=2, portfolio_trailing=.04)
        self.assertEqual(len(result["stop_events"]), 1)
        exits = [row for row in result["trade_events"] if row["timestamp_ms"] == START+HOUR_MS]
        self.assertEqual(len(exits), 2)
        self.assertTrue(all(row["action"] == "exit" for row in exits))
        self.assertEqual(result["entries"], 4)
        self.assertEqual(result["trade_events"][4]["timestamp_ms"], START+2*HOUR_MS)
        self.assertGreaterEqual(result["max_drawdown_pct"], 9.99)

    def test_decision_hash_reproducible_and_cash_holds_not_logged(self):
        market, states = sample([100]*4)
        def cash(state, position):
            return {"action": "hold", "reason": "no_signal"}
        result = run(market, states, cash)
        repeat = run(copy.deepcopy(market), copy.deepcopy(states), cash)
        self.assertEqual(result["decision_digest"], repeat["decision_digest"])
        self.assertEqual(result["decision_counts"], {"hold": 4})
        self.assertEqual(result["action_decisions"], [])
        self.assertEqual(result["trade_events"], [])


if __name__ == "__main__":
    unittest.main()
