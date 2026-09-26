"""Synthetic boundaries for the frozen positioning comparison orchestrator."""

from contextlib import ExitStack, contextmanager, redirect_stdout
import copy
import hashlib
import io
import itertools
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from jev_trader import positioning_research as research


class RunBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.results = self.root / "results"
        self.results.mkdir()
        (self.root / "docs").mkdir()
        (self.root / "docs/contract_lifecycle_sources_2026-09-26.json").write_text(
            '{"events": []}', encoding="utf-8")
        self.input_path = self.results / "positioning_prediction_inputs.json"
        self.input_path.write_text('{"synthetic": true}', encoding="utf-8")
        self.frozen = {"tree_anchors": {"synthetic": True}}
        self.states = {"BTCUSDT": {0: {"sample": 1.0}}}
        self.fields = tuple(f"field{i}" for i in range(60))
        self.inputs = {"synthetic": True, "positioning_dataset": {"manifest": [1]},
                       "positioning_quality": {"unavailable_observations": [1]}}
        self.prepared = ({"fundingRate": {}}, {"klines": {}}, {}, self.states, self.fields, self.inputs)
        self.prediction = {model: {"signals": self.states, "fit_audits": [{"fit": "synthetic"}],
                                  "prediction_audits": [{"prediction": "synthetic"}],
                                  "prediction_errors": []}
                           for model in ("control60", "augmented68")}
        self.prediction["matching_audit"] = {"same_sample": True}
        self.metrics = {"return_pct": 70.0, "max_drawdown_pct": 9.0,
                        "margin_stress_failures": 0, "adverse_intrahour_drawdown_bound_pct": 11.0,
                        "bounded_settlements": [], "daily_equity": [1]}
        self.anchor_mock = Mock(return_value=self.frozen)
        self.prepare_mock = Mock(return_value=self.prepared)
        self.forecast_mock = Mock(side_effect=lambda *args: copy.deepcopy(self.prediction))
        self.evaluate_mock = Mock(side_effect=lambda *args, **kwargs: copy.deepcopy(self.metrics))

    def patched(self):
        stack = ExitStack()
        for name, value in (("ROOT", self.root), ("RESULTS", self.results), ("INPUTS", self.input_path),
                            ("anchors", self.anchor_mock), ("prepare_inputs", self.prepare_mock),
                            ("build_forecasts", self.forecast_mock), ("evaluate", self.evaluate_mock)):
            stack.enter_context(patch.object(research, name, value))
        stack.enter_context(patch.object(research, "TreePolicy", side_effect=lambda *args, **kwargs: SimpleNamespace(audit=[])))
        stack.enter_context(patch.object(research, "summarize_errors", return_value={"count": 0}))
        stack.enter_context(patch.object(research, "annualized_return", return_value=55.0))
        stack.enter_context(redirect_stdout(io.StringIO()))
        return stack

    def assert_unlocked(self):
        self.assertFalse((self.results / "positioning_research.lock").exists())

    def test_prepare_only_preserves_input_and_never_trains_or_replays(self):
        before = self.input_path.read_bytes()
        with self.patched():
            result = research.run(prepare_only=True)
        self.prepare_mock.assert_called_once_with(self.frozen)
        self.forecast_mock.assert_not_called()
        self.evaluate_mock.assert_not_called()
        self.assertEqual(result, research.compact(self.inputs))
        self.assertEqual(self.input_path.read_bytes(), before)
        self.assertFalse((self.results / "positioning_prediction_research.json").exists())
        self.assert_unlocked()

    def test_exact_thirty_two_scenarios_share_execution_contract_and_stay_research_only(self):
        with self.patched():
            result = research.run()
        expected = set(itertools.product(("control60", "augmented68"), ("development", "combined"),
                                         (1.0, 2.0), (None, .04), (.0015, .003)))
        rows = result["scenarios"]
        actual = {(row["model"], row["period"], row["gross_limit"], row["portfolio_trailing"], row["side_cost"])
                  for row in rows}
        self.assertEqual(len(rows), 32)
        self.assertEqual(actual, expected)
        self.assertEqual(self.evaluate_mock.call_count, 32)
        for call in self.evaluate_mock.call_args_list:
            self.assertEqual(call.kwargs["cadence"], "weekly")
            self.assertEqual(call.kwargs["delay_hours"], 1)
            self.assertEqual(call.kwargs["settlement_bounds"], {})
        self.assertEqual(sum(call.kwargs["trailing"] is not None for call in self.evaluate_mock.call_args_list), 16)
        self.assertTrue(all(row["meets_nominal_target"] for row in rows))
        self.assertFalse(any(row["meets_target_and_adverse_bound"] for row in rows))
        self.assertFalse(result["goal_achieved"])
        self.assertFalse(result["deployable"])
        self.assertIsNone(result["selected_winner"])
        self.assertEqual((result["jev_calls"], result["orders_sent"], result["new_market_downloads"]), (0, 0, 0))
        self.assertFalse(result["historical_point_in_time_verified"])
        self.assertEqual(self.anchor_mock.call_count, 2)
        self.assertEqual(result["full_report_sha256"], research.sha(self.results / "positioning_prediction_research.json"))
        self.assert_unlocked()

    def test_only_documented_execution_errors_are_retained_as_invalid_scenarios(self):
        for message in ("insolvent account", "unresolved held price: BTCUSDT", "unverified execution liquidity: BTCUSDT"):
            with self.subTest(message=message):
                self.evaluate_mock.side_effect = [ValueError(message)] + [copy.deepcopy(self.metrics) for _ in range(31)]
                with self.patched():
                    result = research.run()
                self.assertEqual(result["scenarios"][0]["status"], "invalid_execution")
                self.assertEqual(result["scenarios"][0]["error"], message)
                self.assertIsNone(result["scenarios"][0]["metrics"])
                self.assertFalse(result["scenarios"][0]["meets_nominal_target"])
                self.assertEqual(sum(row["status"] == "complete" for row in result["scenarios"]), 31)
                self.assert_unlocked()

    def test_unexpected_evaluator_errors_propagate_without_partial_report(self):
        for error in (ValueError("bad feature schema"), RuntimeError("execution bug"), KeyError("field")):
            with self.subTest(error=type(error).__name__):
                self.evaluate_mock.side_effect = error
                with self.patched(), self.assertRaises(type(error)):
                    research.run()
                self.assertFalse((self.results / "positioning_prediction_research.json").exists())
                self.assert_unlocked()

    def test_initial_anchor_and_preparation_failures_release_lock_before_forecast(self):
        for which in ("anchors", "prepare"):
            with self.subTest(which=which):
                self.anchor_mock.side_effect = ValueError("anchor failure") if which == "anchors" else None
                self.prepare_mock.side_effect = ValueError("preparation failure") if which == "prepare" else None
                with self.patched(), self.assertRaises(ValueError):
                    research.run()
                self.forecast_mock.assert_not_called()
                self.evaluate_mock.assert_not_called()
                self.assert_unlocked()

    def test_changed_post_replay_anchor_prevents_report_and_releases_lock(self):
        self.anchor_mock.side_effect = [self.frozen, {"changed": True}]
        with self.patched(), self.assertRaisesRegex(ValueError, "changed during replay"):
            research.run()
        self.assertEqual(self.evaluate_mock.call_count, 32)
        self.assertFalse((self.results / "positioning_prediction_research.json").exists())
        self.assert_unlocked()

    def test_prediction_and_report_write_failures_also_release_lock(self):
        self.forecast_mock.side_effect = RuntimeError("fitting failed")
        with self.patched(), self.assertRaisesRegex(RuntimeError, "fitting failed"):
            research.run()
        self.assert_unlocked()
        self.forecast_mock.side_effect = lambda *args: copy.deepcopy(self.prediction)
        with self.patched(), patch.object(research, "write_json", side_effect=OSError("disk unavailable")):
            with self.assertRaisesRegex(OSError, "disk unavailable"):
                research.run()
        self.assert_unlocked()

    def test_existing_lock_is_never_removed_by_rejected_second_run(self):
        lock = self.results / "positioning_research.lock"
        lock.write_bytes(b"another active process")
        with self.patched(), self.assertRaises(FileExistsError):
            research.run(prepare_only=True)
        self.assertEqual(lock.read_bytes(), b"another active process")
        self.anchor_mock.assert_not_called()


class PreparationBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.inputs = self.root / "positioning_inputs.json"
        self.baseline_path = self.root / "baseline.json"
        self.frozen = {"tree_anchors": {"fixed_tree": True}}
        self.fields = tuple(f"f{i}" for i in range(60))
        self.states = {"BTCUSDT": {0: dict.fromkeys(self.fields, 1.0)}}
        self.augmented = {"BTCUSDT": {0: {**self.states["BTCUSDT"][0], "positioning": 2.0}}}
        self.data = {"fundingRate": {}}
        self.cohort = {"selected": ["BTCUSDT"]}
        self.quality = {"base": True}
        self.dataset_audit = {"verified": 1, "manifest": [{"sha256": "original"}]}
        self.positioning_quality = {"unavailable_observations": []}
        self.records = {label: [{"symbol": "BTCUSDT", "sha256": label, "path": "excluded-local-path"}]
                        for label in ("daily", "hourly", "training_hourly", "rest")}
        self.sources = {label: {"count": 1, "manifest_sha256": hashlib.sha256(research.canonical([
            {key: value for key, value in row.items() if key != "path"} for row in rows])).hexdigest()}
                        for label, rows in self.records.items()}
        self.baseline = {"anchors": self.frozen["tree_anchors"], "cohort": ["BTCUSDT"],
                         "fields": list(self.fields), "feature_quality": self.quality,
                         "state_sha256": research.digest_states(self.states), "sources": self.sources,
                         "overlap": {"same": True}, "settlement_evidence": {"fixed": True}}
        self.baseline_path.write_text(json.dumps(self.baseline), encoding="utf-8")
        self.anchor_mock = Mock(return_value=self.frozen)
        self.offline_active = False
        self.augment_mock = Mock(return_value=(self.augmented, self.fields + tuple(f"p{i}" for i in range(8)),
                                               self.positioning_quality))

    @contextmanager
    def offline(self):
        self.assertFalse(self.offline_active)
        self.offline_active = True
        try:
            yield
        finally:
            self.offline_active = False

    def load_daily(self):
        self.assertTrue(self.offline_active)
        return self.data, self.records["daily"], self.cohort

    def load_hourly(self, data, manifest=None):
        self.assertTrue(self.offline_active)
        self.assertIs(data, self.data)
        training = manifest is not None
        return ({"klines": {"BTCUSDT": {0 if training else 1: "synthetic hour"}}},
                self.records["training_hourly" if training else "hourly"])

    def extend(self, data, hourly):
        self.assertTrue(self.offline_active)
        self.assertEqual(set(hourly["klines"]["BTCUSDT"]), {0, 1})
        return self.records["rest"], {"same": True}, None

    def patched(self):
        stack = ExitStack()
        for name, value in (("INPUTS", self.inputs), ("BASELINE_INPUTS", self.baseline_path),
                            ("anchors", self.anchor_mock), ("_offline_inputs", self.offline),
                            ("load_daily", self.load_daily), ("load_hourly", self.load_hourly),
                            ("extend", self.extend), ("augment", self.augment_mock)):
            stack.enter_context(patch.object(research, name, value))
        stack.enter_context(patch.object(research, "acquisition_plan", return_value={"synthetic": True}))
        stack.enter_context(patch.object(research, "load_verified", return_value=({}, self.dataset_audit)))
        stack.enter_context(patch.object(research, "verified_bounds", return_value=({}, {"fixed": True})))
        stack.enter_context(patch.object(research, "feature_bundle", return_value=(self.states, self.fields, self.quality)))
        stack.enter_context(redirect_stdout(io.StringIO()))
        return stack

    def test_baseline_reproduced_and_existing_inputs_reused_without_rewrite(self):
        with self.patched():
            first = research.prepare_inputs(self.frozen)
            raw = self.inputs.read_bytes()
            second = research.prepare_inputs(self.frozen)
        self.assertEqual(first, second)
        self.assertEqual(self.inputs.read_bytes(), raw)
        self.assertEqual(first[-1]["baseline_state_sha256"], self.baseline["state_sha256"])
        self.assertEqual(first[-1]["matched_state_sha256"], research.digest_states(self.augmented))
        self.assertEqual(len(first[-1]["base_fields"]), 60)
        self.assertEqual(len(first[-1]["augmented_fields"]), 68)
        self.assertFalse(self.offline_active)
        self.assertEqual(self.anchor_mock.call_count, 2)

    def test_divergent_existing_inputs_are_never_overwritten(self):
        with self.patched():
            research.prepare_inputs(self.frozen)
            original = self.inputs.read_bytes()
            self.dataset_audit["manifest"][0]["sha256"] = "changed"
            with self.assertRaisesRegex(ValueError, "explicit new revision"):
                research.prepare_inputs(self.frozen)
        self.assertEqual(self.inputs.read_bytes(), original)

    def test_mismatched_preserved_baseline_aborts_before_augmentation_or_input_write(self):
        changed = {**self.baseline, "state_sha256": "different"}
        self.baseline_path.write_text(json.dumps(changed), encoding="utf-8")
        original = self.baseline_path.read_bytes()
        with self.patched(), self.assertRaisesRegex(ValueError, "baseline mismatch: state_sha256"):
            research.prepare_inputs(self.frozen)
        self.augment_mock.assert_not_called()
        self.assertFalse(self.inputs.exists())
        self.assertEqual(self.baseline_path.read_bytes(), original)

    def test_changed_preparation_anchor_aborts_before_input_write(self):
        self.anchor_mock.return_value = {"changed": True}
        with self.patched(), self.assertRaisesRegex(ValueError, "changed during preparation"):
            research.prepare_inputs(self.frozen)
        self.assertFalse(self.inputs.exists())

    def test_incomplete_dataset_never_reaches_market_preparation(self):
        with self.patched(), patch.object(research, "load_verified", side_effect=ValueError("missing archive")):
            with patch.object(research, "load_daily") as loader:
                with self.assertRaisesRegex(ValueError, "missing archive"):
                    research.prepare_inputs(self.frozen)
                loader.assert_not_called()
        self.assertFalse(self.inputs.exists())


class ProtocolBoundaryTests(unittest.TestCase):
    def test_committed_protocol_json_matches_fixed_thirty_two_scenario_config(self):
        import re
        blocks = re.findall(r"```json\s*\n(.*?)\n```", research.PROTOCOL.read_text(encoding="utf-8"), re.DOTALL)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(json.loads(blocks[0]), research.CONFIG)
        count = len(research.CONFIG["models"]) * len(research.CONFIG["periods"])
        for field in ("gross_limits", "portfolio_trailing", "side_costs"):
            count *= len(research.CONFIG[field])
        self.assertEqual(count, 32)
        self.assertEqual((research.CONFIG["target_net_cagr_pct"], research.CONFIG["maximum_drawdown_pct"]), (50, 10))


if __name__ == "__main__":
    unittest.main()
