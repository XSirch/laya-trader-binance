"""Synthetic calendar and freeze gates, with no historical strategy replay."""

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jev_trader import basis_research as research
from jev_trader.basis_features import canonical
from jev_trader.binance_data import Bar, HOUR_MS
from jev_trader.derivatives_data import Funding


START = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
END = START + 8 * HOUR_MS
SMALL_CONFIG = dict(research.CONFIG, periods={
    "synthetic": ["2024-01-01T00:00:00+00:00", "2024-01-01T08:00:00+00:00"],
})


def fixture():
    bars = {stamp: Bar(stamp, 100, 100, 100, 100, 1, 100, 1, .5)
            for stamp in range(START, END + 1, HOUR_MS)}
    return {**{kind: {"BTCUSDT": dict(bars)} for kind in ("spot", "futures", "mark")},
            "funding": {"BTCUSDT": [Funding(START + 3, 8, 0.0), Funding(END + 7, 8, 0.0)]}}


class CalendarTests(unittest.TestCase):
    def setUp(self):
        config = patch.object(research, "CONFIG", copy.deepcopy(SMALL_CONFIG))
        config.start()
        self.addCleanup(config.stop)

    def test_zero_rate_is_a_present_payment_and_milliseconds_are_preserved(self):
        market = fixture()
        before = copy.deepcopy(market)
        audit = research.verify_calendar(market)
        self.assertEqual(audit["BTCUSDT"]["events"], 2)
        self.assertEqual(audit["BTCUSDT"]["first_slot"], START // HOUR_MS)
        self.assertEqual(audit["BTCUSDT"]["last_slot"], END // HOUR_MS)
        self.assertEqual(audit["BTCUSDT"]["maximum_timestamp_offset_ms"], 7)
        self.assertEqual(market, before)

    def test_missing_initial_or_terminal_payment_is_not_assumed_zero(self):
        for missing_index in (0, 1):
            with self.subTest(missing_index=missing_index):
                market = fixture()
                market["funding"]["BTCUSDT"].pop(missing_index)
                with self.assertRaisesRegex(ValueError, "missing evaluation funding BTCUSDT synthetic"):
                    research.verify_calendar(market)

    def test_empty_funding_history_is_rejected(self):
        market = fixture()
        market["funding"]["BTCUSDT"] = []
        with self.assertRaisesRegex(ValueError, "incomplete or unsupported funding calendar"):
            research.verify_calendar(market)

    def test_internal_funding_gap_is_detected_even_outside_evaluation_window(self):
        market = fixture()
        market["funding"]["BTCUSDT"].insert(0, Funding(START - 16 * HOUR_MS, 8, 0))
        with self.assertRaisesRegex(ValueError, "incomplete or unsupported funding calendar"):
            research.verify_calendar(market)

    def test_unsupported_slot_interval_and_offset_are_rejected(self):
        replacements = (Funding(START + HOUR_MS, 8, 0), Funding(START, 4, 0),
                        Funding(START + 60_000, 8, 0))
        for event in replacements:
            with self.subTest(event=event):
                market = fixture()
                market["funding"]["BTCUSDT"][0] = event
                with self.assertRaisesRegex(ValueError, "incomplete or unsupported funding calendar"):
                    research.verify_calendar(market)

    def test_all_three_price_series_require_every_hour_including_terminal(self):
        for kind in ("spot", "futures", "mark"):
            for missing in (START, START + 4 * HOUR_MS, END):
                with self.subTest(kind=kind, missing=missing):
                    market = fixture()
                    del market[kind]["BTCUSDT"][missing]
                    with self.assertRaisesRegex(ValueError, "incomplete evaluation prices BTCUSDT " + kind):
                        research.verify_calendar(market)

    def test_prepare_rejects_price_gap_before_flat_strategy_can_hide_it(self):
        market = fixture()
        del market["mark"]["BTCUSDT"][START + 4 * HOUR_MS]
        with patch.object(research, "anchors", return_value={"synthetic": True}), \
                patch.object(research, "load", return_value=(market, {})), \
                patch.object(research, "build_states", return_value=({}, {})) as build, \
                patch.object(research, "evaluate") as evaluate, \
                patch.object(research, "write_new_or_equal") as write:
            with self.assertRaisesRegex(ValueError, "incomplete evaluation prices"):
                research.prepare()
        build.assert_not_called()
        evaluate.assert_not_called()
        write.assert_not_called()


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_write_creates_canonical_bytes_and_equal_replay_never_opens_for_write(self):
        path = self.root / "artifact.json"
        value = {"b": [2, 1], "a": "teste"}
        research.write_new_or_equal(path, value)
        self.assertEqual(path.read_bytes(), canonical(value) + b"\n")
        original_mtime = path.stat().st_mtime_ns
        original_open = Path.open

        def read_only_open(target, mode="r", *args, **kwargs):
            self.assertNotIn("w", mode)
            self.assertNotIn("x", mode)
            self.assertNotIn("a", mode)
            return original_open(target, mode, *args, **kwargs)

        with patch.object(Path, "open", new=read_only_open):
            research.write_new_or_equal(path, {"a": "teste", "b": [2, 1]})
        self.assertEqual(path.stat().st_mtime_ns, original_mtime)

    def test_different_value_cannot_replace_frozen_artifact(self):
        path = self.root / "artifact.json"
        research.write_new_or_equal(path, {"return": 1})
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "refusing to replace different frozen artifact"):
            research.write_new_or_equal(path, {"return": 2})
        self.assertEqual(path.read_bytes(), before)

    def test_semantically_equal_json_with_different_bytes_is_not_rewritten(self):
        path = self.root / "artifact.json"
        payload = b'{ "a": 1 }\r\n'
        path.write_bytes(payload)
        with self.assertRaisesRegex(ValueError, "refusing to replace different frozen artifact"):
            research.write_new_or_equal(path, {"a": 1})
        self.assertEqual(path.read_bytes(), payload)


class AnchorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.protocol = self.root / "docs/basis_protocol_2026-09-26.md"
        self.relative_files = (
            "docs/basis_protocol_2026-09-26.md", "docs/basis_sources_2026-09-26.md",
            "docs/basis_data_inventory_2026-09-26.md", "pyproject.toml", "requirements-tree.lock",
            "src/jev_trader/synthetic.py", "tests/test_basis_synthetic.py",
        )
        for relative in self.relative_files:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic fixture\n")
        self.write_protocol(SMALL_CONFIG)
        for attribute, value in (("ROOT", self.root), ("PROTOCOL", self.protocol),
                                 ("CONFIG", copy.deepcopy(SMALL_CONFIG)), ("CODE", ("synthetic.py",))):
            patcher = patch.object(research, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_protocol(self, config):
        self.protocol.write_bytes(("# Synthetic protocol\n\n```json\n" + json.dumps(config)
                                   + "\n```\n").encode("utf-8"))

    def test_matching_protocol_anchors_exact_document_code_and_test_bytes(self):
        result = research.anchors()
        expected = {relative: hashlib.sha256((self.root / relative).read_bytes()).hexdigest()
                    for relative in self.relative_files}
        self.assertEqual(result["files_sha256"], expected)
        self.assertTrue(result["python"])
        self.assertTrue(result["implementation"])
        self.assertEqual(result, research.anchors())
        changed = self.root / "tests/test_basis_synthetic.py"
        changed.write_bytes(changed.read_bytes() + b"changed\n")
        self.assertNotEqual(result, research.anchors())

    def test_protocol_cannot_disagree_with_code_target_cost_or_time_window(self):
        replacements = ({"target_net_cagr_pct": 5}, {"costs": {"base": [0, 0]}},
                        {"periods": {"synthetic": ["2024-01-01T00:00:00+00:00",
                                                   "2024-01-02T00:00:00+00:00"]}})
        for difference in replacements:
            with self.subTest(difference=difference):
                self.write_protocol(dict(SMALL_CONFIG, **difference))
                with self.assertRaisesRegex(ValueError, "protocol configuration differs from code"):
                    research.anchors()

    def test_no_json_or_multiple_json_blocks_cannot_ambiguously_define_protocol(self):
        valid = self.protocol.read_bytes()
        for payload in (b"# No configuration\n", valid + b"\n" + valid):
            with self.subTest(payload_size=len(payload)):
                self.protocol.write_bytes(payload)
                with self.assertRaisesRegex(ValueError, "protocol configuration differs from code"):
                    research.anchors()

    def test_missing_required_source_fails_instead_of_weakening_anchor_set(self):
        (self.root / "requirements-tree.lock").unlink()
        with self.assertRaises(FileNotFoundError):
            research.anchors()


if __name__ == "__main__":
    unittest.main()
