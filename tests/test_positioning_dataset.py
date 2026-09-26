import copy
from datetime import datetime, timedelta
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from jev_trader.metrics_fetch import fetch
from jev_trader.positioning_dataset import canonical_bytes, load_verified
from jev_trader.positioning_metrics import CSV_FIELDS, METRIC_FIELDS


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.cache = Path(self.temporary.name)
        self.jobs, self.records = [], []
        for symbol, day, complete in (("BTCUSDT", "2023-12-29", True),
                                      ("ETHUSDT", "2024-01-05", False)):
            basename = f"{symbol}-metrics-{day}.zip"
            key = f"data/futures/um/daily/metrics/{symbol}/{basename}"
            lines = [",".join(CSV_FIELDS)]
            for index in range(288 if complete else 1):
                stamp = datetime.fromisoformat(day) + timedelta(minutes=5 * index)
                lines.append(f"{stamp:%Y-%m-%d %H:%M:%S},{symbol},1,2,1,1,1,{1 if complete else 0}")
            if complete:
                lines.append(lines[-1])
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(basename.replace(".zip", ".csv"), "\n".join(lines) + "\n")
            payload = stream.getvalue()
            checksum = (hashlib.sha256(payload).hexdigest() + "  " + basename + "\n").encode("ascii")
            job = {"symbol": symbol, "day": day,
                   "zip": {"key": key, "size": len(payload), "etag": '"zip"',
                           "last_modified": "2026-09-20T01:00:00Z"},
                   "checksum": {"key": key + ".CHECKSUM", "size": len(checksum), "etag": '"checksum"',
                                "last_modified": "2026-09-21T01:00:00Z"}}
            result = fetch(job, self.cache, reader=lambda url, limit: checksum if url.endswith("CHECKSUM") else payload)
            self.jobs.append(job)
            self.records.append(result)
        self.plan = {"config": {"first_friday": "2023-12-29", "last_friday": "2024-01-05",
                                "historical_point_in_time_verified": False},
                     "historical_point_in_time_verified": False,
                     "expected_fridays_per_symbol": 2, "cohort": ["BTCUSDT", "ETHUSDT"],
                     "jobs": self.jobs,
                     "missing_pairs": [{"symbol": "BTCUSDT", "day": "2024-01-05"},
                                       {"symbol": "ETHUSDT", "day": "2023-12-29"}],
                     "post_settlement_exclusions": []}
        self.save_plan()

    def save_plan(self):
        (self.cache / "acquisition_plan.json").write_bytes(canonical_bytes(self.plan))

    def test_complete_cache_has_deterministic_quality_and_source_manifest(self):
        before = {path: path.read_bytes() for path in self.cache.rglob("*") if path.is_file()}
        snapshots, audit = load_verified(self.plan, self.cache)
        self.assertEqual(audit["total_records"], 2)
        self.assertEqual(audit["usable_snapshots"], 1)
        self.assertEqual(audit["unavailable_snapshots"], 1)
        self.assertEqual(audit["totals"]["minimum_unique_rows"], 1)
        self.assertEqual(audit["totals"]["unique_rows"], 289)
        self.assertEqual(audit["totals"]["raw_rows"], 290)
        self.assertEqual(audit["totals"]["identical_duplicate_rows"], 1)
        self.assertEqual(audit["totals"]["field_zero_counts"][METRIC_FIELDS[-1]], 1)
        self.assertEqual(audit["totals"]["minimum_field_positive_counts"][METRIC_FIELDS[-1]], 0)
        self.assertEqual(audit["by_year"]["2023"]["usable_snapshots"], 1)
        self.assertEqual(audit["by_symbol"]["ETHUSDT"]["unavailable_snapshots"], 1)
        self.assertEqual(audit["by_symbol_year"]["BTCUSDT"]["2023"]["records"], 1)
        self.assertEqual(audit["unavailable_details"][0]["symbol"], "ETHUSDT")
        self.assertTrue(audit["unavailable_details"][0]["reasons"])
        self.assertTrue(snapshots["BTCUSDT"]["2023-12-29"]["available"])
        self.assertFalse(audit["historical_point_in_time_verified"])
        self.assertEqual(audit["network_requests"], 0)
        self.assertEqual(audit["source_last_modified_min_utc"], "2026-09-20T01:00:00+00:00")
        self.assertEqual(audit["source_last_modified_max_utc"], "2026-09-21T01:00:00+00:00")
        self.assertEqual(audit["records_with_any_last_modified_after_archive_day"], 2)
        self.assertEqual(audit["manifest_sha256"], hashlib.sha256(canonical_bytes(audit["manifest"])).hexdigest())
        self.assertEqual(audit["totals"]["zip_bytes"], sum(record["zip"]["bytes"] for record in self.records))
        for row, record in zip(audit["manifest"], self.records):
            self.assertEqual(row["files"]["record"]["sha256"],
                             hashlib.sha256(Path(record["record_path"]).read_bytes()).hexdigest())
        self.assertEqual((snapshots, audit), load_verified(self.plan, self.cache))
        self.assertEqual(before, {path: path.read_bytes() for path in self.cache.rglob("*") if path.is_file()})

    def test_missing_last_record_is_detected_before_verifying_first_record(self):
        Path(self.records[-1]["record_path"]).unlink()
        with patch("jev_trader.positioning_dataset.fetch") as verifier:
            with self.assertRaisesRegex(ValueError, "required files missing"):
                load_verified(self.plan, self.cache)
        verifier.assert_not_called()

    def test_missing_source_is_detected_before_any_verification(self):
        Path(self.records[-1]["checksum"]["path"]).unlink()
        with patch("jev_trader.positioning_dataset.fetch") as verifier:
            with self.assertRaisesRegex(ValueError, "required files missing"):
                load_verified(self.plan, self.cache)
        verifier.assert_not_called()

    def test_extra_record_is_rejected(self):
        (self.cache / "BTCUSDT" / "extra.record.json").write_text("{}", encoding="utf-8")
        with patch("jev_trader.positioning_dataset.fetch") as verifier:
            with self.assertRaisesRegex(ValueError, "unexpected record"):
                load_verified(self.plan, self.cache)
        verifier.assert_not_called()

    def test_orphan_source_is_rejected(self):
        (self.cache / "BTCUSDT" / "unplanned.zip").write_bytes(b"archive")
        with self.assertRaisesRegex(ValueError, "orphan source"):
            load_verified(self.plan, self.cache)

    def test_duplicate_or_overlapping_plan_identity_is_rejected(self):
        self.plan["jobs"].append(copy.deepcopy(self.plan["jobs"][0]))
        self.save_plan()
        with self.assertRaisesRegex(ValueError, "duplicate or overlapping"):
            load_verified(self.plan, self.cache)

    def test_unaccounted_calendar_slot_is_rejected(self):
        self.plan["missing_pairs"].pop()
        self.save_plan()
        with self.assertRaisesRegex(ValueError, "complete cohort calendar"):
            load_verified(self.plan, self.cache)

    def test_supplied_plan_must_match_preserved_plan(self):
        changed = copy.deepcopy(self.plan)
        changed["jobs"][0]["zip"]["etag"] = '"new-version"'
        with self.assertRaisesRegex(ValueError, "supplied plan differs"):
            load_verified(changed, self.cache)

    def test_plan_file_is_required(self):
        (self.cache / "acquisition_plan.json").unlink()
        with self.assertRaisesRegex(ValueError, "preserved acquisition_plan"):
            load_verified(self.plan, self.cache)

    def test_catalogue_change_is_not_accepted_even_with_a_rewritten_plan(self):
        self.plan["jobs"][0]["zip"]["etag"] = '"new-version"'
        self.save_plan()
        with self.assertRaisesRegex(ValueError, "catalogue version changed"):
            load_verified(self.plan, self.cache)

    def test_source_corruption_is_detected_without_changing_existing_bytes(self):
        path = Path(self.records[0]["zip"]["path"])
        path.write_bytes(b"x" * path.stat().st_size)
        before = {item: item.read_bytes() for item in self.cache.rglob("*") if item.is_file()}
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            load_verified(self.plan, self.cache)
        self.assertTrue(all(path.read_bytes() == raw for path, raw in before.items()))

    def test_fetch_receives_a_reader_that_rejects_network(self):
        def attempted_download(job, cache, reader):
            return reader("https://example.invalid/archive", 100)
        with patch("jev_trader.positioning_dataset.fetch", side_effect=attempted_download):
            with self.assertRaisesRegex(ValueError, "network is disabled"):
                load_verified(self.plan, self.cache)

    def test_changed_snapshot_identity_is_rejected(self):
        def wrong_snapshot(job, cache, reader):
            result = fetch(job, cache, reader=reader)
            result["snapshot"]["day"] = "2020-01-01"
            return result
        with patch("jev_trader.positioning_dataset.fetch", side_effect=wrong_snapshot):
            with self.assertRaisesRegex(ValueError, "snapshot identity"):
                load_verified(self.plan, self.cache)

    def test_late_mutation_of_already_verified_record_is_detected(self):
        calls = 0
        def mutate_earlier(job, cache, reader):
            nonlocal calls
            result = fetch(job, cache, reader=reader)
            calls += 1
            if calls == 2:
                path = Path(self.records[0]["record_path"])
                path.write_bytes(path.read_bytes() + b" ")
            return result
        with patch("jev_trader.positioning_dataset.fetch", side_effect=mutate_earlier):
            with self.assertRaisesRegex(ValueError, "before audit completion"):
                load_verified(self.plan, self.cache)

    def test_false_point_in_time_claim_is_rejected(self):
        self.plan["historical_point_in_time_verified"] = True
        self.save_plan()
        with self.assertRaisesRegex(ValueError, "point-in-time"):
            load_verified(self.plan, self.cache)

    def test_extra_record_added_during_verification_is_rejected(self):
        def add_record(job, cache, reader):
            result = fetch(job, cache, reader=reader)
            (cache / "BTCUSDT" / "late.record.json").write_text("{}", encoding="utf-8")
            return result
        with patch("jev_trader.positioning_dataset.fetch", side_effect=add_record):
            with self.assertRaisesRegex(ValueError, "inventory changed"):
                load_verified(self.plan, self.cache)


if __name__ == "__main__":
    unittest.main()
