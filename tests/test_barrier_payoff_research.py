"""Runner boundaries for the fixed lifecycle comparison."""
import unittest
from unittest.mock import patch

from jev_trader import barrier_payoff_research as research


class BarrierRunnerTests(unittest.TestCase):
    def test_protocol_runtime_and_32_scenario_grid_are_fixed(self):
        anchors = research.anchors()
        self.assertEqual(anchors["runtime"], research.RUNTIME)
        config = research.CONFIG
        self.assertEqual(len(config["models"])*len(config["side_costs"])*len(config["allocations"])*len(config["periods"]), 32)
        self.assertEqual((config["stop_atr"], config["target_atr"], config["max_hours"]), (1, 2, 8))

    def test_controls_use_matched_mean_signals_and_correct_mode(self):
        mean, hgb = {1: "mean"}, {1: "hgb"}
        forecasts = {"models": {"rolling_mean": {"signals": mean}, "hgb": {"signals": hgb}}}
        metrics = {"return_pct": 0., "max_drawdown_pct": 0., "adverse_intrahour_drawdown_bound_pct": 0.,
                   "monthly_returns_pct": {}}
        for model in research.CONFIG["models"]:
            with self.subTest(model=model), patch.object(research, "evaluate", return_value=dict(metrics)) as call:
                result = research.scenario({}, {}, forecasts, model, .0012, 1., "development")
                self.assertIs(call.call_args.args[1], hgb if model == "hgb" else mean)
                self.assertEqual(call.call_args.kwargs["mode"], model if model in ("always", "buy_hold") else "forecast")
                self.assertFalse(result["meets_nominal_target"])

    def test_only_expected_unavailable_execution_is_preserved_as_invalid(self):
        forecasts = {"models": {"rolling_mean": {"signals": {}}}}
        with patch.object(research, "evaluate", side_effect=research.ExecutionUnavailable("missing candle")):
            row = research.scenario({}, {}, forecasts, "always", .0012, .5, "later")
        self.assertEqual(row["status"], "invalid_execution")
        self.assertIsNone(row["metrics"])
        with patch.object(research, "evaluate", side_effect=ValueError("causality defect")), self.assertRaisesRegex(ValueError, "causality"):
            research.scenario({}, {}, forecasts, "always", .0012, .5, "later")

    def test_compact_report_preserves_metric_and_hashes_large_curves(self):
        original = {"model": "hgb", "metrics": {"return_pct": 2., "valuation_points": [{"equity": 1.}],
                    "hourly_equity": [[0, 1.]]}}
        compact = research.compact(original)
        self.assertEqual(compact["metrics"], {"return_pct": 2.})
        self.assertEqual(compact["event_counts"], {"hourly_equity": 1, "valuation_points": 1})
        self.assertEqual(len(compact["series_sha256"]["valuation_points"]), 64)
        self.assertIn("valuation_points", original["metrics"])


if __name__ == "__main__":
    unittest.main()
