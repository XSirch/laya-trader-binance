"""Synthetic point-in-time lifecycle checks; no market files or network."""

import copy
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import math
import unittest

from jev_trader.binance_data import HOUR_MS
from jev_trader.residual_lifecycle import LifecyclePolicy
from jev_trader.residual_policy import DAY_MS, ResidualPolicy, WINDOW


START = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


def iso(timestamp):
    return datetime.fromtimestamp(timestamp / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def notice(symbol="ALTUSDT", published=START + DAY_MS,
           restriction=START + 3 * DAY_MS + HOUR_MS):
    return {"symbol": symbol, "published_utc": iso(published),
            "new_positions_stop_utc": iso(restriction),
            "automatic_settlement_utc": iso(restriction + HOUR_MS)}


def states_at(cutoff):
    common = {"latest_observed_close_ms": cutoff, "quote_volume20": 20_000_000,
              "volatility": .02, "carry30": 0.0}
    btc = [.01 * math.sin(i) for i in range(WINDOW)]
    eth = [.008 * math.cos(i * .7) for i in range(WINDOW)]
    model = {"beta_btc": .3, "beta_eth": .2, "intercept_daily": 0.0,
             "equilibrium_std": .02, "z": 2.0, "expected_reversion_10d": .05}
    return {
        "BTCUSDT": {**common, "residual_model": None, "return_history60": btc},
        "ETHUSDT": {**common, "residual_model": None, "return_history60": eth},
        "ALTUSDT": {**common, "residual_model": model,
                    "return_history60": [.3 * b + .2 * e + .001 * (-1 if i % 2 else 1)
                                         for i, (b, e) in enumerate(zip(btc, eth))]},
    }


class RecordingPolicy:
    def __init__(self):
        self.audit, self.calls = [], []

    def __call__(self, states, rule):
        self.calls.append((states, rule))
        self.audit.append({"symbols": sorted(states)})
        return {symbol: .1 for symbol in states}


class LifecyclePolicyTests(unittest.TestCase):
    def test_future_notice_does_not_delete_earlier_history(self):
        base = RecordingPolicy()
        wrapper = LifecyclePolicy([notice()], base)
        states = states_at(START)
        original = copy.deepcopy(states)
        weights = wrapper(states, "same-rule")
        self.assertIn("ALTUSDT", weights)
        self.assertEqual(states, original)
        self.assertEqual(wrapper.lifecycle_audit[-1]["excluded_symbols"], [])
        forwarded, rule = base.calls[-1]
        self.assertEqual(rule, "same-rule")
        for symbol, row in states.items():
            self.assertIs(forwarded[symbol], row)

    def test_published_notice_alone_does_not_preempt_restriction(self):
        wrapper = LifecyclePolicy([notice()], RecordingPolicy())
        self.assertIn("ALTUSDT", wrapper(states_at(START + 2 * DAY_MS), "rule"))
        self.assertEqual(wrapper.lifecycle_audit[-1]["excluded_symbols"], [])

    def test_exact_execution_boundary_includes_one_hour_delay(self):
        wrapper = LifecyclePolicy([notice()], RecordingPolicy())
        boundary = START + 3 * DAY_MS
        self.assertIn("ALTUSDT", wrapper(states_at(boundary - 1), "rule"))
        self.assertNotIn("ALTUSDT", wrapper(states_at(boundary), "rule"))
        self.assertEqual(wrapper.lifecycle_audit[-1], {
            "cutoff_ms": boundary, "execution_ms": boundary + HOUR_MS,
            "excluded_symbols": ["ALTUSDT"],
        })
        self.assertNotIn("ALTUSDT", wrapper(states_at(boundary + DAY_MS), "rule"))

    def test_notice_and_restriction_can_become_known_at_same_instant(self):
        timestamp = START + DAY_MS + HOUR_MS
        wrapper = LifecyclePolicy([notice(published=timestamp, restriction=timestamp)], RecordingPolicy())
        self.assertIn("ALTUSDT", wrapper(states_at(timestamp - HOUR_MS - 1), "rule"))
        self.assertNotIn("ALTUSDT", wrapper(states_at(timestamp - HOUR_MS), "rule"))

    def test_unrestricted_assets_have_identical_base_weights_signals_and_audit(self):
        plain = ResidualPolicy(2)
        wrapper = LifecyclePolicy([notice()], risk_scale=2)
        for day in (0, 1, 2):
            states = states_at(START + day * DAY_MS)
            self.assertEqual(wrapper(states, "rule"), plain(states, "rule"))
            self.assertEqual(wrapper.base_policy.active, plain.active)
            self.assertEqual(wrapper.audit, plain.audit)
        self.assertIs(wrapper.audit, wrapper.base_policy.audit)

    def test_restriction_extinguishes_retained_signal_using_underlying_exit(self):
        base = ResidualPolicy()
        wrapper = LifecyclePolicy([notice()], base)
        self.assertIn("ALTUSDT", wrapper(states_at(START + 2 * DAY_MS), "rule"))
        self.assertIn("ALTUSDT", base.active)
        self.assertEqual(wrapper(states_at(START + 3 * DAY_MS), "rule"), {})
        self.assertNotIn("ALTUSDT", base.active)
        self.assertEqual(base.audit[-1]["closed_signals"], ["ALTUSDT"])
        self.assertEqual(wrapper(states_at(START + 4 * DAY_MS), "rule"), {})
        self.assertEqual(base.audit[-1]["new_candidates"], 0)

    def test_restricted_factor_uses_underlying_unavailable_hedge_handling(self):
        wrapper = LifecyclePolicy([notice(symbol="BTCUSDT")])
        self.assertTrue(wrapper(states_at(START + 2 * DAY_MS), "rule"))
        self.assertEqual(wrapper(states_at(START + 3 * DAY_MS), "rule"), {})
        self.assertEqual(wrapper.base_policy.active, {})
        self.assertEqual(wrapper.audit[-1]["reason"], "hedge_unavailable")

    def test_event_snapshot_is_immutable_and_external_edits_do_not_change_history(self):
        event = notice()
        events = [event]
        wrapper = LifecyclePolicy(events, RecordingPolicy())
        event["symbol"] = "BTCUSDT"
        events.clear()
        self.assertEqual(len(wrapper.events), 1)
        self.assertEqual(wrapper.events[0].symbol, "ALTUSDT")
        with self.assertRaises(FrozenInstanceError):
            wrapper.events[0].symbol = "ETHUSDT"
        with self.assertRaises(AttributeError):
            wrapper.events = ()
        weights = wrapper(states_at(START + 3 * DAY_MS), "rule")
        self.assertIn("BTCUSDT", weights)
        self.assertNotIn("ALTUSDT", weights)

    def test_duplicate_or_malformed_symbols_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            LifecyclePolicy([notice(), notice()])
        for symbol in (None, "", "altusdt", "ALT USDT", "../ALT"):
            with self.subTest(symbol=symbol), self.assertRaisesRegex(ValueError, "symbol"):
                LifecyclePolicy([notice(symbol=symbol)])

    def test_times_require_explicit_utc_and_publication_restriction_settlement_order(self):
        for field in ("published_utc", "new_positions_stop_utc", "automatic_settlement_utc"):
            for timestamp in (None, "not-a-date", "2025-01-01", "2025-01-01T00:00:00+03:00"):
                with self.subTest(field=field, timestamp=timestamp), self.assertRaises(ValueError):
                    LifecyclePolicy([{**notice(), field: timestamp}])
        late_publication = notice(published=START + 5 * DAY_MS)
        early_settlement = {**notice(), "automatic_settlement_utc": iso(START + DAY_MS)}
        for event in (late_publication, early_settlement):
            with self.assertRaisesRegex(ValueError, "order"):
                LifecyclePolicy([event])

    def test_cutoff_failures_do_not_append_successful_lifecycle_audit(self):
        wrapper = LifecyclePolicy([notice()])
        states = states_at(START)
        wrapper(states, "rule")
        with self.assertRaisesRegex(ValueError, "advance in time"):
            wrapper(states, "rule")
        mixed = states_at(START + DAY_MS)
        mixed["ALTUSDT"]["latest_observed_close_ms"] += 1
        with self.assertRaisesRegex(ValueError, "one completed daily cutoff"):
            wrapper(mixed, "rule")
        self.assertEqual(len(wrapper.lifecycle_audit), 1)

    def test_execution_delay_cannot_drift_from_frozen_one_hour_protocol(self):
        for delay in (0, 2, -1, .5, True):
            with self.subTest(delay=delay), self.assertRaisesRegex(ValueError, "one hour"):
                LifecyclePolicy([notice()], delay_hours=delay)


if __name__ == "__main__":
    unittest.main()
