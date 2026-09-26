import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from jev_trader import positioning_acquire as acquire


def job(number, symbol="BTCUSDT", day=None):
    day = day or f"2022-01-{number + 1:02d}"
    key = f"data/futures/um/daily/metrics/{symbol}/{symbol}-metrics-{day}.zip"
    item = {"key": key, "size": 42, "last_modified": "2026-09-26T00:00:00Z", "etag": '"example"'}
    return {"symbol": symbol, "day": day, "zip": item,
            "checksum": {**item, "key": key + ".CHECKSUM"}}


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.frozen = {"synthetic_anchors": True}
        self.jobs = [job(i) for i in range(10)]
        self.plan = {"jobs": self.jobs, "anchors": self.frozen,
                     "missing_pairs": [], "post_settlement_exclusions": []}
        (self.cache / "acquisition_plan.json").write_bytes(acquire.encoded(self.plan))

    def result(self, item, *, available=True):
        target = self.cache / item["symbol"] / (Path(item["zip"]["key"]).name + ".record.json")
        hit = target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        if not hit:
            target.write_bytes(b"synthetic record")
        return {"snapshot": {"available": available}, "cache_hit": hit,
                "record_path": str(target), "zip": {"sha256": "a" * 64}}

    def patched(self, fetcher):
        stack = ExitStack()
        stack.enter_context(patch.object(acquire, "CACHE", self.cache))
        stack.enter_context(patch.object(acquire, "prepare", return_value=self.plan))
        stack.enter_context(patch.object(acquire, "anchors", return_value=self.frozen))
        stack.enter_context(patch.object(acquire, "fetch", side_effect=fetcher))
        return stack

    def assert_bounded_failure(self, exception):
        all_started = threading.Event()
        release_other_workers = threading.Event()
        failure_recorded = threading.Event()
        finished = threading.Event()
        guard = threading.Lock()
        calls, submitted, result, errors = [], [], [], []
        original_write = acquire._write

        class TrackingExecutor(ThreadPoolExecutor):
            def submit(self, function, *args, **kwargs):
                submitted.append(args[0]["day"])
                return super().submit(function, *args, **kwargs)

        def fetcher(item, _root):
            with guard:
                calls.append(item["day"])
                if len(calls) == 4:
                    all_started.set()
            if item == self.jobs[0]:
                if not all_started.wait(5):
                    raise AssertionError("four initial workers were not started")
                raise exception("synthetic first failure")
            if not release_other_workers.wait(5):
                raise AssertionError("test failed to release in-flight workers")
            return self.result(item)

        def observed_write(path, value):
            original_write(path, value)
            if value.get("failures"):
                failure_recorded.set()

        def runner():
            try:
                result.append(acquire.run(download=True, workers=4))
            except BaseException as exc:
                errors.append(exc)
            finally:
                finished.set()

        with self.patched(fetcher) as stack:
            stack.enter_context(patch.object(acquire, "ThreadPoolExecutor", TrackingExecutor))
            stack.enter_context(patch.object(acquire, "_write", side_effect=observed_write))
            thread = threading.Thread(target=runner, daemon=True)
            thread.start()
            try:
                self.assertTrue(failure_recorded.wait(5), "failure was not recorded")
                self.assertEqual(len(submitted), 4, "rest of the batch must not be queued")
                self.assertEqual(len(calls), 4)
                self.assertFalse(finished.is_set(), "in-flight workers must be drained")
            finally:
                release_other_workers.set()
                thread.join(5)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(submitted), 4)
        status = result[0]
        self.assertEqual(status["phase"], "stopped_after_failure")
        self.assertEqual(status["submitted"], 4)
        self.assertEqual(status["unattempted"], 6)
        self.assertEqual(status["complete_records"], 3)
        self.assertEqual(status["usable_snapshots"], 3)
        self.assertEqual(status["failures"][0]["error_type"], exception.__name__)
        self.assertFalse(status["all_planned_records_verified"])
        self.assertFalse((self.cache / "acquisition.lock").exists())
        journal = self.cache / "runs" / status["run_id"] / "records.jsonl"
        rows = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sum(row["status"] == "failed" for row in rows), 1)
        self.assertEqual(sum(row["status"] == "verified" for row in rows), 3)
        summary = journal.with_name("summary.json")
        self.assertEqual(json.loads(summary.read_text(encoding="utf-8")), status)

    def test_first_validation_failure_stops_submission_and_drains_workers(self):
        self.assert_bounded_failure(ValueError)

    def test_unexpected_programming_exception_is_recorded_and_stops_queue(self):
        self.assert_bounded_failure(KeyError)

    def test_successful_batch_and_resume_reverify_every_cached_record(self):
        calls = []
        def fetcher(item, _root):
            calls.append(item["day"])
            return self.result(item, available=item != self.jobs[0])
        with self.patched(fetcher):
            first = acquire.run(download=True, workers=3)
            self.assertEqual(first["complete_records"], 10)
            self.assertEqual(first["usable_snapshots"], 9)
            self.assertEqual(first["cache_hits"], 0)
            self.assertEqual(first["submitted"], 10)
            self.assertEqual(first["unattempted"], 0)
            self.assertTrue(first["all_planned_records_verified"])
            calls.clear()
            second = acquire.run(download=True, limit=1, workers=2)
        self.assertEqual(sorted(calls), sorted(item["day"] for item in self.jobs))
        self.assertEqual(second["cache_hits"], 10)
        self.assertTrue(second["all_planned_records_verified"])
        self.assertNotEqual(first["run_id"], second["run_id"])

    def test_limit_applies_to_pending_jobs_and_cached_records_are_reverified(self):
        for index in (1, 3):
            self.result(self.jobs[index])
        calls = []
        def fetcher(item, _root):
            calls.append(item["day"])
            return self.result(item)
        with self.patched(fetcher):
            status = acquire.run(download=True, limit=2, workers=1)
        self.assertEqual(calls, [self.jobs[i]["day"] for i in (1, 3, 0, 2)])
        self.assertEqual(status["selected"], 4)
        self.assertEqual(status["not_selected"], 6)
        self.assertEqual(status["submitted"], 4)
        self.assertEqual(status["unattempted"], 6)
        self.assertEqual(status["cache_hits"], 2)
        self.assertFalse(status["all_planned_records_verified"])

    def test_dry_run_never_fetches_and_cleans_own_lock(self):
        with self.patched(lambda *_: self.fail("dry run called fetch")):
            self.assertEqual(acquire.run(), self.plan)
        self.assertFalse((self.cache / "acquisition.lock").exists())
        self.assertFalse((self.cache / "runs").exists())

    def test_existing_lock_is_not_removed_or_bypassed(self):
        lock = self.cache / "acquisition.lock"
        lock.write_bytes(b"another process")
        with self.patched(lambda *_: self.fail("locked run called fetch")):
            with self.assertRaises(FileExistsError):
                acquire.run(download=True)
        self.assertEqual(lock.read_bytes(), b"another process")

    def test_invalid_limits_and_worker_counts_rejected_before_mutation(self):
        with self.patched(lambda *_: self.fail("invalid call fetched data")):
            for workers in (True, 0, 5):
                with self.subTest(workers=workers), self.assertRaises(ValueError):
                    acquire.run(workers=workers)
            for limit in (True, 0, -1, 1.5):
                with self.subTest(limit=limit), self.assertRaises(ValueError):
                    acquire.run(limit=limit)
        self.assertFalse((self.cache / "acquisition.lock").exists())


class AcquisitionPlanTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cache = self.root / "data/binance/positioning"
        self.symbols = ["BTCUSDT", "EOSUSDT"]
        self.frozen = {"synthetic_anchors": True}
        self.write("data/binance/broad/cohort.json", {"selected": self.symbols})
        self.write("docs/broad_candidate_freeze_2026-09-26.json", {"cohort": self.symbols})
        self.write("docs/contract_lifecycle_sources_2026-09-26.json", {"events": [
            {"symbol": "EOSUSDT", "automatic_settlement_utc": "2021-12-10T09:00:00Z"}]})
        self.catalogs = {}
        for symbol in self.symbols:
            self.catalogs[symbol] = {"symbol": symbol}
            self.write(f"data/binance/metrics_catalog/{symbol}/catalog.json", self.catalogs[symbol])

    def write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(acquire.encoded(value))
        return path

    def patched(self):
        def candidates(catalog, start, end):
            self.assertEqual((start, end), ("2021-12-03", "2026-09-18"))
            rows = []
            for day in acquire.calendar(start, end, 4):
                item = job(0, catalog["symbol"], day)
                rows.append({"symbol": item["symbol"], "date": day,
                             "zip": item["zip"], "checksum": item["checksum"]})
            return rows
        def load(symbol, *, fetcher):
            with self.assertRaisesRegex(ValueError, "network is disabled"):
                fetcher("synthetic invalid URL")
            return self.catalogs[symbol]
        stack = ExitStack()
        stack.enter_context(patch.object(acquire, "ROOT", self.root))
        stack.enter_context(patch.object(acquire, "CACHE", self.cache))
        stack.enter_context(patch.object(acquire, "anchors", return_value=self.frozen))
        stack.enter_context(patch.object(acquire, "load_catalog", side_effect=load))
        stack.enter_context(patch.object(acquire, "weekly_candidates", side_effect=candidates))
        return stack

    def test_plan_reconstructs_exact_calendar_lifecycle_and_identical_resume(self):
        with self.patched():
            first = acquire.prepare()
            path = self.cache / "acquisition_plan.json"
            original = path.read_bytes()
            second = acquire.prepare()
        self.assertEqual(first, second)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(first["expected_fridays_per_symbol"], 251)
        self.assertEqual(len(first["jobs"]), 253)
        self.assertEqual(len(first["post_settlement_exclusions"]), 249)
        self.assertEqual(first["missing_pairs"], [])
        self.assertEqual([row["day"] for row in first["jobs"] if row["symbol"] == "EOSUSDT"],
                         ["2021-12-03", "2021-12-10"])

    def test_changed_plan_jobs_rejected_even_when_anchors_and_config_match(self):
        with self.patched():
            plan = copy.deepcopy(acquire.prepare())
            plan["jobs"][0]["day"] = "2021-12-04"
            self.write("data/binance/positioning/acquisition_plan.json", plan)
            with self.assertRaisesRegex(ValueError, "fixed calendar"):
                acquire.prepare()

    def test_changed_catalog_bytes_rejected_on_resume(self):
        with self.patched():
            acquire.prepare()
            self.write("data/binance/metrics_catalog/BTCUSDT/catalog.json", {"changed": True})
            with self.assertRaisesRegex(ValueError, "catalog changed"):
                acquire.prepare()

    def test_cohort_drift_rejected_before_plan_creation(self):
        self.write("data/binance/broad/cohort.json", {"selected": ["BTCUSDT"]})
        with self.patched(), self.assertRaisesRegex(ValueError, "historical cohort changed"):
            acquire.prepare()
        self.assertFalse((self.cache / "acquisition_plan.json").exists())


if __name__ == "__main__":
    unittest.main()
