"""Deterministic synthetic checks for causal factor-residual portfolio decisions."""

import copy
import math
import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from jev_trader.residual_policy import (
    DAY_MS, FACTORS, MODEL_RETURNS, WINDOW, ResidualPolicy, enrich_states,
    fit_residual,
)


def fitted_series():
    """Known older-window betas and a separate stationary residual episode."""
    rng = random.Random(481)
    btc = [rng.gauss(0, .01) for _ in range(MODEL_RETURNS)]
    eth = [rng.gauss(0, .008) for _ in range(MODEL_RETURNS)]
    residual = [0.0] * WINDOW
    level = 0.0
    for _ in range(WINDOW):
        next_level = .65 * level + rng.gauss(0, .002)
        residual.append(next_level - level)
        level = next_level
    asset = [.0003 + .7 * b - .4 * e + r
             for b, e, r in zip(btc, eth, residual)]
    return asset, btc, eth


def bars_from_returns(values):
    close = 100.0
    bars = [SimpleNamespace(open_ms=0, close=close)]
    for index, value in enumerate(values, 1):
        close *= math.exp(value)
        bars.append(SimpleNamespace(open_ms=index * DAY_MS, close=close))
    return bars


def portfolio_states(day=200 * DAY_MS, count=1, amplitude=.001,
                     beta_btc=.3, beta_eth=.2, **model_changes):
    btc = [.01 * math.sin(i) for i in range(WINDOW)]
    eth = [.008 * math.cos(i * .7) for i in range(WINDOW)]
    model = {"beta_btc": beta_btc, "beta_eth": beta_eth,
             "intercept_daily": 0.0, "phi": .65,
             "equilibrium_std": .02, "z": 2.0,
             "expected_reversion_10d": .05, **model_changes}
    common = {"latest_observed_close_ms": day, "quote_volume20": 20_000_000,
              "volatility": .02, "carry30": 0.0}
    states = {
        FACTORS[0]: {**common, "residual_model": None, "return_history60": btc},
        FACTORS[1]: {**common, "residual_model": None, "return_history60": eth},
    }
    for number in range(count):
        history = [beta_btc * b + beta_eth * e + amplitude * (-1 if i % 2 else 1)
                   for i, (b, e) in enumerate(zip(btc, eth))]
        states[f"ALT{number}"] = {**common, "residual_model": dict(model),
                                  "return_history60": history}
    return states


def advance(states, days=1, z=None):
    updated = copy.deepcopy(states)
    for row in updated.values():
        row["latest_observed_close_ms"] += days * DAY_MS
        if row["residual_model"] is not None and z is not None:
            row["residual_model"]["z"] = z
    return updated


class ResidualFitTests(unittest.TestCase):
    def test_factor_fit_uses_only_older_sixty_returns(self):
        asset, btc, eth = fitted_series()
        model = fit_residual(asset, btc, eth)
        self.assertIsNotNone(model)
        self.assertAlmostEqual(model["beta_btc"], .7, places=12)
        self.assertAlmostEqual(model["beta_eth"], -.4, places=12)
        self.assertAlmostEqual(model["intercept_daily"], .0003, places=12)
        self.assertGreater(model["phi"], 0)
        self.assertLess(model["reversion_days"], 30)
        # Later factor observations must not move the earlier regression.
        changed_btc = btc[:WINDOW] + [value * 1.1 for value in btc[WINDOW:]]
        changed_asset = asset[:WINDOW] + [a + .7 * (new - old)
                                        for a, new, old in zip(
                                            asset[WINDOW:], changed_btc[WINDOW:], btc[WINDOW:])]
        changed = fit_residual(changed_asset, changed_btc, eth)
        self.assertIsNotNone(changed)
        for name in ("beta_btc", "beta_eth", "intercept_daily", "phi", "z"):
            self.assertAlmostEqual(model[name], changed[name], places=11)

    def test_singular_factors_and_excessive_betas_are_rejected(self):
        asset, btc, eth = fitted_series()
        self.assertIsNone(fit_residual(asset, btc, [2 * v for v in btc]))
        self.assertIsNone(fit_residual(asset, [0] * MODEL_RETURNS, eth))
        excessive = [a + 6 * b for a, b in zip(asset, btc)]
        self.assertIsNone(fit_residual(excessive, btc, eth))

    def test_model_requires_exact_finite_aligned_history(self):
        asset, btc, eth = fitted_series()
        for length in (WINDOW, MODEL_RETURNS - 1, MODEL_RETURNS + 1):
            with self.subTest(length=length), self.assertRaisesRegex(ValueError, "120 aligned"):
                fit_residual(([0] * length), btc, eth)
        for bad in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "nonfinite"):
                fit_residual([bad] + asset[1:], btc, eth)


class ResidualEnrichmentTests(unittest.TestCase):
    def fixture(self):
        asset, btc, eth = fitted_series()
        values = {"ALT": asset, FACTORS[0]: btc, FACTORS[1]: eth}
        data = {"klines": {s: bars_from_returns(v) for s, v in values.items()}}
        cutoff = (MODEL_RETURNS + 1) * DAY_MS
        base = {s: {cutoff: {"latest_observed_close_ms": cutoff}}
                for s in values}
        return data, base, values, cutoff

    def test_exact_120_fit_returns_and_latest_60_portfolio_returns(self):
        data, base, values, cutoff = self.fixture()
        with patch("jev_trader.residual_policy.fit_residual", return_value={"synthetic": True}) as fit:
            enriched, quality = enrich_states(data, base)
        fit.assert_called_once()
        for actual, expected in zip(fit.call_args.args,
                                    (values["ALT"], values[FACTORS[0]], values[FACTORS[1]])):
            self.assertEqual(len(actual), MODEL_RETURNS)
            for got, wanted in zip(actual, expected):
                self.assertAlmostEqual(got, wanted, places=13)
        for symbol, rows in enriched.items():
            history = rows[cutoff]["return_history60"]
            self.assertEqual(len(history), WINDOW)
            for got, wanted in zip(history, values[symbol][-WINDOW:]):
                self.assertAlmostEqual(got, wanted, places=13)
            self.assertEqual(rows[cutoff]["factor_fit_end_ms"], cutoff - WINDOW * DAY_MS)
        self.assertEqual(quality, {"models_valid": 1, "models_rejected": 0, "history_missing": 0})

    def test_prefix_and_future_price_perturbation_leave_past_models_unchanged(self):
        data, base, values, cutoff = self.fixture()
        expected = enrich_states(data, base)
        future_data = {"klines": {s: bars_from_returns(v + [.1, -.2, .4, -.3])
                                    for s, v in values.items()}}
        self.assertEqual(enrich_states(future_data, base), expected)
        for bars in future_data["klines"].values():
            for bar in bars:
                if bar.open_ms >= cutoff:
                    bar.close *= 1000
        self.assertEqual(enrich_states(future_data, base), expected)
        self.assertNotIn("residual_model", base["ALT"][cutoff])

    def test_gap_in_training_window_cannot_be_filled_by_future_or_recent_returns(self):
        data, base, _, cutoff = self.fixture()
        del data["klines"][FACTORS[0]][20]
        enriched, quality = enrich_states(data, base)
        self.assertNotIn(cutoff, enriched["ALT"])
        self.assertEqual(quality["history_missing"], 3)
        self.assertEqual(quality["models_valid"], 0)

    def test_state_cutoff_must_equal_observed_completed_close(self):
        data, base, _, cutoff = self.fixture()
        base["ALT"][cutoff]["latest_observed_close_ms"] -= DAY_MS
        with self.assertRaisesRegex(ValueError, "timestamp differs"):
            enrich_states(data, base)


class ResidualDecisionTests(unittest.TestCase):
    def test_cost_hurdle_includes_all_hedge_legs_and_requires_strict_surplus(self):
        hurdle = .003 * (1 + .3 + .2)
        for gain, accepted in ((hurdle - .0001, False), (hurdle, False),
                               (hurdle + .0001, True)):
            with self.subTest(gain=gain):
                policy = ResidualPolicy()
                weights = policy(portfolio_states(expected_reversion_10d=gain), "synthetic")
                self.assertEqual(bool(weights), accepted)
                self.assertEqual(policy.audit[-1]["passed_cost_hurdle"], int(accepted))

    def test_adverse_funding_and_drift_reject_an_otherwise_economic_signal(self):
        baseline = portfolio_states(expected_reversion_10d=.01)
        self.assertTrue(ResidualPolicy()(baseline, "synthetic"))
        adverse_funding = copy.deepcopy(baseline)
        adverse_funding["ALT0"]["carry30"] = .365
        self.assertEqual(ResidualPolicy()(adverse_funding, "synthetic"), {})
        adverse_drift = copy.deepcopy(baseline)
        adverse_drift["ALT0"]["residual_model"]["intercept_daily"] = .001
        self.assertEqual(ResidualPolicy()(adverse_drift, "synthetic"), {})
        # Favorable drift/funding cannot subsidize a residual below trading costs.
        favorable = portfolio_states(expected_reversion_10d=.004, intercept_daily=-.01)
        favorable["ALT0"]["carry30"] = -3.65
        self.assertEqual(ResidualPolicy()(favorable, "synthetic"), {})

    def test_funding_hurdle_accounts_for_factor_positions_and_direction(self):
        states = portfolio_states(expected_reversion_10d=.01)
        states[FACTORS[0]]["carry30"] = -2.0
        self.assertEqual(ResidualPolicy()(states, "synthetic"), {})
        states["ALT0"]["residual_model"]["z"] = -2.0
        self.assertTrue(ResidualPolicy()(states, "synthetic"))

    def test_entry_hysteresis_exit_and_sign_change_prevent_same_day_reentry(self):
        policy = ResidualPolicy()
        states = portfolio_states(z=1.24)
        self.assertEqual(policy(states, "synthetic"), {})
        states = advance(states, z=1.25)
        self.assertLess(policy(states, "synthetic")["ALT0"], 0)
        opened = policy.active["ALT0"]["opened"]
        states = advance(states, z=.75)
        self.assertLess(policy(states, "synthetic")["ALT0"], 0)
        self.assertEqual(policy.active["ALT0"]["opened"], opened)
        states = advance(states, z=.5)
        self.assertEqual(policy(states, "synthetic"), {})
        self.assertEqual(policy.audit[-1]["closed_signals"], ["ALT0"])
        states = advance(states, z=2.0)
        self.assertLess(policy(states, "synthetic")["ALT0"], 0)
        states = advance(states, z=-2.0)
        self.assertEqual(policy(states, "synthetic"), {})
        self.assertEqual(policy.audit[-1]["new_candidates"], 0)
        states = advance(states)
        self.assertGreater(policy(states, "synthetic")["ALT0"], 0)

    def test_episode_expires_after_ten_calendar_days_without_same_day_restart(self):
        policy = ResidualPolicy()
        states = portfolio_states()
        self.assertTrue(policy(states, "synthetic"))
        states = advance(states, days=9)
        self.assertTrue(policy(states, "synthetic"))
        states = advance(states)
        self.assertEqual(policy(states, "synthetic"), {})
        self.assertEqual(policy.audit[-1]["closed_signals"], ["ALT0"])
        states = advance(states)
        self.assertTrue(policy(states, "synthetic"))
        self.assertEqual(policy.active["ALT0"]["opened"], states["ALT0"]["latest_observed_close_ms"])

    def test_unavailable_hedge_clears_signals_instead_of_leaving_unhedged_assets(self):
        policy = ResidualPolicy()
        states = portfolio_states()
        self.assertTrue(policy(states, "synthetic"))
        states = advance(states)
        states[FACTORS[0]]["quote_volume20"] = 9_999_999
        self.assertEqual(policy(states, "synthetic"), {})
        self.assertEqual(policy.active, {})
        self.assertEqual(policy.audit[-1]["reason"], "hedge_unavailable")

    def test_cutoffs_must_be_uniform_and_strictly_increasing(self):
        policy = ResidualPolicy()
        states = portfolio_states()
        policy(states, "synthetic")
        for wrong in (states, advance(states, days=-1)):
            with self.assertRaisesRegex(ValueError, "advance in time"):
                policy(wrong, "synthetic")
        mixed = advance(states)
        mixed["ALT0"]["latest_observed_close_ms"] += 1
        with self.assertRaisesRegex(ValueError, "one completed daily cutoff"):
            policy(mixed, "synthetic")
        self.assertTrue(policy(advance(states), "synthetic"))


class ResidualSizingTests(unittest.TestCase):
    def assert_neutral_and_capped(self, weights, states, risk_scale):
        self.assertLessEqual(math.fsum(abs(w) for w in weights.values()), risk_scale + 1e-12)
        for symbol, weight in weights.items():
            cap = (.5 if symbol in FACTORS else .1) * risk_scale
            self.assertLessEqual(abs(weight), cap + 1e-12)
        for factor, beta_name in zip(FACTORS, ("beta_btc", "beta_eth")):
            exposure = weights.get(factor, 0) + math.fsum(
                weight * states[symbol]["residual_model"][beta_name]
                for symbol, weight in weights.items() if symbol not in FACTORS)
            self.assertAlmostEqual(exposure, 0.0, places=13)

    def test_uniform_caps_preserve_zero_modeled_factor_exposures(self):
        scenarios = (
            (dict(count=1), "ALT0", .1),
            (dict(count=10, beta_btc=3, beta_eth=0), FACTORS[0], .5),
            (dict(count=10), None, 1.0),
        )
        for risk_scale in (1, 2):
            for options, cap_symbol, expected in scenarios:
                with self.subTest(risk_scale=risk_scale, options=options):
                    states = portfolio_states(amplitude=.0001, **options)
                    policy = ResidualPolicy(risk_scale)
                    weights = policy(states, "synthetic")
                    self.assert_neutral_and_capped(weights, states, risk_scale)
                    observed = abs(weights[cap_symbol]) if cap_symbol else sum(abs(w) for w in weights.values())
                    self.assertAlmostEqual(observed, expected * risk_scale, places=12)

    def test_historical_risk_target_is_ten_or_twenty_percent_after_hedging(self):
        states = portfolio_states(count=20, amplitude=.1)
        outputs = []
        for risk_scale in (1, 2):
            policy = ResidualPolicy(risk_scale)
            weights = policy(states, "synthetic")
            self.assert_neutral_and_capped(weights, states, risk_scale)
            returns = [math.fsum(w * states[s]["return_history60"][i] for s, w in weights.items())
                       for i in range(WINDOW)]
            average = math.fsum(returns) / WINDOW
            realized_vol = math.sqrt(math.fsum((r - average) ** 2 for r in returns) / (WINDOW - 1) * 365)
            self.assertAlmostEqual(realized_vol, .1 * risk_scale, places=12)
            self.assertAlmostEqual(policy.audit[-1]["estimated_annual_volatility"], realized_vol, places=12)
            outputs.append(weights)
        for symbol, weight in outputs[0].items():
            self.assertAlmostEqual(outputs[1][symbol], 2 * weight, places=12)

    def test_only_predeclared_risk_scales_are_accepted(self):
        for scale in (0, -1, .5, 3):
            with self.subTest(scale=scale), self.assertRaisesRegex(ValueError, "fixed risk scales"):
                ResidualPolicy(scale)


if __name__ == "__main__":
    unittest.main()
