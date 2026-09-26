"""Budget tests use injected transports exclusively; no provider calls."""

import copy
import hashlib
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

from jev_trader.jev import ENDPOINT, MODEL
from jev_trader.jev_budget import BudgetedJevClient, decision_key


QUESTIONS = {
    "trend": {"type": "noul", "instructions": "Score observed trend adherence only."},
    "structure": {"type": "noul", "instructions": "Score observed Fibonacci adherence only."},
}
STATE = {"ema": {"50": 100.5, "200": 90.0}, "fibonacci": [0.382, 0.618],
         "rsi": 55, "funding": -0.0001, "unavailable": ["order_book"]}


def response(cost=0.0002):
    return {"answers": {k: {"type": "noul", "noul": 0.8} for k in QUESTIONS},
            "id": "fake-request-1", "model": MODEL + "-20260917",
            "usage": {"cost": cost, "input_tokens": 1000, "output_tokens": 32}}


def legacy_pair(key=None, cost=0.0002):
    key = key or hashlib.sha256(b"prior request").hexdigest()
    reserved = {"key": key, "status": "reserved", "charged_or_reserved_usd": 0.01}
    complete = {"key": key, "status": "complete", "charged_or_reserved_usd": cost,
                "adherence": {k: 0.8 for k in QUESTIONS},
                "usage": {"cost": cost, "input_tokens": 1000, "output_tokens": 32},
                "request_id": "fake-prior", "model": MODEL + "-20260917",
                "latency_seconds": 0.5, "request_bytes": 1200}
    return [reserved, complete]


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.prior = self.root / "prior.jsonl"
        self.cache = self.root / "new.jsonl"
        self.write_prior(legacy_pair())
        self.calls = []

    def tearDown(self):
        self.temp.cleanup()

    def write_prior(self, rows):
        self.prior.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def fake(self, request, timeout):
        self.calls.append((request, timeout))
        return response()

    def client(self, **kwargs):
        options = {"path": self.cache, "prior_path": self.prior, "questions": QUESTIONS,
                   "api_key": "fake-test-key", "transport": self.fake}
        options.update(kwargs)
        return BudgetedJevClient(**options)

    def rows(self):
        return [json.loads(line) for line in self.cache.read_text(encoding="utf-8").splitlines()]

    def test_single_post_contains_every_field_and_question_cache_reuses_without_charge(self):
        prior_bytes = self.prior.read_bytes()
        with self.client() as client:
            first = client.decide(STATE)
            self.assertEqual(client.key(STATE), decision_key(STATE, QUESTIONS))
            self.assertEqual(first, client.decide(copy.deepcopy(STATE)))
            self.assertEqual(client.spent, Decimal("0.0004"))
            self.assertEqual(client.prior_spent, Decimal("0.0002"))
            first["adherence"]["trend"] = 0
            self.assertEqual(client.cached[client.key(STATE)]["adherence"]["trend"], 0.8)
        self.assertEqual(len(self.calls), 1)
        request, timeout = self.calls[0]
        self.assertEqual(request.full_url, ENDPOINT)
        self.assertEqual(request.method, "POST")
        self.assertEqual(json.loads(request.data), {"model": MODEL, "state": STATE, "questions": QUESTIONS})
        self.assertEqual(timeout, 45)
        self.assertNotIn("fake-test-key", self.cache.read_text(encoding="utf-8"))
        self.assertEqual(self.prior.read_bytes(), prior_bytes)
        self.assertFalse(self.cache.with_suffix(".jsonl.lock").exists())
        with self.client(api_key=None) as client:
            self.assertEqual(client.decide(STATE)["adherence"]["trend"], 0.8)
            self.assertEqual(client.spent, Decimal("0.0004"))
        self.assertEqual(len(self.calls), 1)

    def test_legacy_exact_decimal_total_and_pending_reservations(self):
        rows = []
        for index in range(331):
            rows.extend(legacy_pair(hashlib.sha256(str(index).encode()).hexdigest(), 0.000130578))
        rows.extend(legacy_pair(hashlib.sha256(b"last").hexdigest(), 0.000293832))
        expected = Decimal("0.043515150")
        self.write_prior(rows)
        with self.client(api_key=None) as client:
            self.assertEqual(client.spent, expected)
        rows.append({"key": "f" * 64, "status": "reserved", "charged_or_reserved_usd": 0.01})
        self.write_prior(rows)
        with self.client(api_key=None) as client:
            self.assertEqual(client.spent, expected + Decimal("0.01"))

    def test_budget_includes_prior_and_new_reservations(self):
        with self.client(budget_usd=Decimal("0.0101")) as client:
            with self.assertRaisesRegex(RuntimeError, "cumulative"):
                client.decide(STATE)
        self.assertFalse(self.calls)
        self.assertFalse(self.cache.exists())
        entered, release = threading.Event(), threading.Event()

        def delayed(request, timeout):
            entered.set()
            self.assertTrue(release.wait(5))
            return response()

        with self.client(budget_usd=Decimal("0.0102"), transport=delayed) as client:
            with ThreadPoolExecutor(max_workers=2) as pool:
                future = pool.submit(client.decide, STATE)
                self.assertTrue(entered.wait(5))
                try:
                    self.assertEqual(client.spent, Decimal("0.0102"))
                    with self.assertRaisesRegex(RuntimeError, "cumulative"):
                        client.decide(dict(STATE, rsi=56))
                finally:
                    release.set()
                future.result()

    def test_total_cap_and_boolean_budget_are_rejected(self):
        for budget in (True, -1, float("nan"), float("inf"), Decimal("2.00000001")):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                self.client(budget_usd=budget)

    def test_unknown_charge_survives_reopen_and_never_retries_key(self):
        def failure(request, timeout):
            self.calls.append(request)
            raise TimeoutError("fake transport timeout")

        with self.client(transport=failure) as client:
            with self.assertRaises(TimeoutError):
                client.decide(STATE)
            self.assertEqual(client.spent, Decimal("0.0102"))
            with self.assertRaisesRegex(RuntimeError, "stopped"):
                client.decide(dict(STATE, rsi=56))
        with self.client() as client:
            with self.assertRaisesRegex(RuntimeError, "charge review"):
                client.decide(STATE)
            with self.assertRaisesRegex(RuntimeError, "stopped"):
                client.decide(dict(STATE, rsi=56))
            self.assertEqual(client.spent, Decimal("0.0102"))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual([r["status"] for r in self.rows()], ["reserved"])

    def test_invalid_response_keeps_reserved_cost(self):
        cases = []
        for value in (True, float("nan"), -0.1, 1.1, "0.8"):
            bad = response()
            bad["answers"]["trend"]["noul"] = value
            cases.append(bad)
        for value in (True, float("nan"), -1, "0.0002", None):
            bad = response()
            bad["usage"]["cost"] = value
            cases.append(bad)
        for field, value in (("model", MODEL + "evil"), ("id", None), ("answers", {})):
            bad = response()
            bad[field] = value
            cases.append(bad)
        bad = response()
        bad["usage"]["input_tokens"] = True
        cases.append(bad)
        bad = response()
        bad["usage"]["input_tokens"] = 32769
        cases.append(bad)
        for index, bad in enumerate(cases):
            with self.subTest(index=index):
                path = self.root / f"bad{index}.jsonl"
                with self.client(path=path, transport=lambda request, timeout: bad) as client:
                    with self.assertRaises(ValueError):
                        client.decide(STATE)
                    self.assertEqual(client.spent, Decimal("0.0102"))
                self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 1)

    def test_actual_cost_over_reserve_is_recorded_and_stops_further_calls(self):
        with self.client(transport=lambda request, timeout: response(0.011)) as client:
            with self.assertRaisesRegex(RuntimeError, "exceeds reserve"):
                client.decide(STATE)
            self.assertEqual(client.spent, Decimal("0.0112"))
            self.assertEqual(client.cached[client.key(STATE)]["charged_or_reserved_usd"], "0.011")
            with self.assertRaisesRegex(RuntimeError, "stopped"):
                client.decide(dict(STATE, rsi=56))
        with self.client() as client:
            with self.assertRaisesRegex(RuntimeError, "stopped"):
                client.decide(dict(STATE, rsi=56))
        self.assertEqual(self.rows()[-1]["status"], "complete")

    def test_concurrent_same_key_cannot_double_charge(self):
        entered, release = threading.Event(), threading.Event()

        def delayed(request, timeout):
            self.calls.append(request)
            entered.set()
            self.assertTrue(release.wait(5))
            return response()

        with self.client(transport=delayed) as client:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(client.decide, STATE)
                self.assertTrue(entered.wait(5))
                try:
                    second = pool.submit(client.decide, STATE)
                    with self.assertRaisesRegex(RuntimeError, "charge review"):
                        second.result(timeout=5)
                finally:
                    release.set()
                self.assertEqual(first.result(), client.decide(STATE))
        self.assertEqual(len(self.calls), 1)

    def test_malformed_scores_cannot_understate_known_excess_charge(self):
        bad = response(0.012)
        bad["answers"]["trend"]["noul"] = True
        with self.client(transport=lambda request, timeout: bad) as client:
            with self.assertRaises(ValueError):
                client.decide(STATE)
            self.assertEqual(client.spent, Decimal("0.0122"))
            self.assertFalse(client.cached)
        self.assertEqual(self.rows()[-1]["status"], "charged_invalid")
        with self.client() as client:
            self.assertEqual(client.spent, Decimal("0.0122"))
            with self.assertRaisesRegex(RuntimeError, "stopped"):
                client.decide(dict(STATE, rsi=56))
            with self.assertRaisesRegex(RuntimeError, "charge review"):
                client.decide(STATE)

    def test_at_most_four_distinct_calls_in_flight(self):
        all_started, four_entered, release = threading.Event(), threading.Event(), threading.Event()
        lock = threading.Lock()
        counts = {"started": 0, "active": 0, "peak": 0}

        def delayed(request, timeout):
            with lock:
                counts["active"] += 1
                counts["peak"] = max(counts["peak"], counts["active"])
                if counts["active"] == 4:
                    four_entered.set()
            self.assertTrue(release.wait(5))
            with lock:
                counts["active"] -= 1
            return response()

        with self.client(transport=delayed) as client:
            def run(index):
                with lock:
                    counts["started"] += 1
                    if counts["started"] == 8:
                        all_started.set()
                return client.decide(dict(STATE, rsi=50 + index))

            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = [pool.submit(run, index) for index in range(8)]
                try:
                    self.assertTrue(all_started.wait(5))
                    self.assertTrue(four_entered.wait(5))
                    self.assertEqual(counts["active"], 4)
                    self.assertEqual(client.spent, Decimal("0.0402"))
                finally:
                    release.set()
                for future in futures:
                    future.result(timeout=5)
            self.assertEqual(counts["peak"], 4)
            self.assertEqual(client.spent, Decimal("0.0018"))

    def test_preexisting_lock_refused_and_foreign_replacement_never_deleted(self):
        lock = self.cache.with_suffix(".jsonl.lock")
        lock.write_bytes(b"stale owner\n")
        with self.assertRaises(FileExistsError):
            with self.client():
                pass
        self.assertEqual(lock.read_bytes(), b"stale owner\n")
        lock.unlink()
        with self.assertRaisesRegex(RuntimeError, "ownership"):
            with self.client():
                lock.write_bytes(b"other owner\n")
        self.assertEqual(lock.read_bytes(), b"other owner\n")

    def test_second_client_excluded_until_first_context_exits(self):
        with self.client():
            with self.assertRaises(FileExistsError):
                with self.client():
                    pass
        with self.client():
            pass

    def test_prior_changes_before_reservation_or_completion_stop_spending(self):
        with self.client() as client:
            self.prior.write_bytes(self.prior.read_bytes() + b"\n")
            with self.assertRaisesRegex(RuntimeError, "prior cost ledger changed"):
                client.decide(STATE)
        self.assertFalse(self.calls)
        self.assertFalse(self.cache.exists())
        self.write_prior(legacy_pair())

        def changed_prior(request, timeout):
            self.prior.write_bytes(self.prior.read_bytes() + b"\n")
            return response()

        with self.client(transport=changed_prior) as client:
            with self.assertRaisesRegex(RuntimeError, "prior cost ledger changed"):
                client.decide(STATE)
            self.assertEqual(client.spent, Decimal("0.0102"))
        self.assertEqual([r["status"] for r in self.rows()], ["reserved"])

    def test_prior_shape_cost_and_transitions_are_strictly_validated(self):
        cases = []
        bad = legacy_pair()
        bad[-1]["usage"]["cost"] = 0.0003
        cases.append(bad)
        bad = legacy_pair()
        bad[-1]["charged_or_reserved_usd"] = True
        cases.append(bad)
        bad = legacy_pair()
        bad[-1]["adherence"]["trend"] = True
        cases.append(bad)
        bad = legacy_pair()
        bad[0]["charged_or_reserved_usd"] = 0.001
        cases.append(bad)
        pair = legacy_pair()
        cases.extend(([pair[1]], [pair[0], pair[0]], pair + [pair[1]],
                      [dict(pair[0], secret="unexpected field")]))
        for rows in cases:
            with self.subTest(rows=rows):
                self.write_prior(rows)
                with self.assertRaises(ValueError):
                    with self.client():
                        pass
                self.assertFalse(self.cache.with_suffix(".jsonl.lock").exists())

    def test_corrupted_truncated_or_changed_cache_rejected(self):
        with self.client() as client:
            client.decide(STATE)
        valid = self.cache.read_bytes()
        variants = [valid[:-1], valid + b"\n", valid.replace(b'"trend":0.8', b'"trend":0.7'),
                    valid + valid.splitlines(keepends=True)[-1]]
        for bad in variants:
            with self.subTest(length=len(bad)):
                self.cache.write_bytes(bad)
                with self.assertRaises(ValueError):
                    with self.client():
                        pass
        self.cache.write_bytes(valid)
        with self.client() as client:
            self.cache.write_bytes(valid + b"\n")
            with self.assertRaisesRegex(RuntimeError, "cache changed"):
                client.decide(dict(STATE, rsi=56))

    def test_legacy_matching_complete_reused_and_pending_refused(self):
        key = decision_key(STATE, QUESTIONS)
        self.write_prior(legacy_pair(key))
        with self.client(api_key=None) as client:
            row = client.decide(STATE)
            self.assertEqual(row["charged_or_reserved_usd"], "0.0002")
            self.assertEqual(client.spent, Decimal("0.0002"))
        self.assertFalse(self.cache.exists())
        self.write_prior(legacy_pair(key)[:1])
        with self.client() as client:
            with self.assertRaisesRegex(RuntimeError, "prior incomplete"):
                client.decide(STATE)
        self.assertFalse(self.calls)

    def test_unresolved_prior_stops_new_paid_work_but_preserves_completed_reads(self):
        key = decision_key(STATE, QUESTIONS)
        pending = legacy_pair(hashlib.sha256(b"unresolved prior").hexdigest())[:1]
        self.write_prior(legacy_pair(key) + pending)
        for _ in range(2):
            with self.client() as client:
                self.assertEqual(client.decide(STATE)["adherence"]["trend"], 0.8)
                with self.assertRaisesRegex(RuntimeError, "stopped"):
                    client.decide(dict(STATE, rsi=56))
                self.assertEqual(client.spent, Decimal("0.0102"))
        self.assertFalse(self.calls)
        self.assertFalse(self.cache.exists())

    def test_unresolved_current_cache_stops_new_work_after_reopen_but_reads_complete(self):
        def sometimes_fails(request, timeout):
            self.calls.append(request)
            if json.loads(request.data)["state"]["rsi"] != STATE["rsi"]:
                raise TimeoutError("fake unknown charge")
            return response()

        with self.client(transport=sometimes_fails) as client:
            completed = client.decide(STATE)
            with self.assertRaises(TimeoutError):
                client.decide(dict(STATE, rsi=56))
        self.assertEqual(len(self.calls), 2)
        for _ in range(2):
            with self.client() as client:
                self.assertEqual(client.decide(STATE), completed)
                with self.assertRaisesRegex(RuntimeError, "stopped"):
                    client.decide(dict(STATE, rsi=57))
                with self.assertRaisesRegex(RuntimeError, "charge review"):
                    client.decide(dict(STATE, rsi=56))
                self.assertEqual(client.spent, Decimal("0.0104"))
        self.assertEqual(len(self.calls), 2)

    def test_oversize_and_nonfinite_input_cannot_reserve_or_call(self):
        with self.client() as client:
            for state in ({"all": "x" * 24000}, {"x": float("nan")}, {1: "integer key"}):
                with self.assertRaises(ValueError):
                    client.decide(state)
        self.assertFalse(self.calls)
        self.assertFalse(self.cache.exists())

    def test_prior_fingerprint_stays_bound_on_reopen(self):
        with self.client() as client:
            client.decide(STATE)
        self.write_prior(legacy_pair(cost=0.0003))
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            with self.client():
                pass

    def test_calls_require_active_context(self):
        client = self.client()
        with self.assertRaisesRegex(RuntimeError, "active context"):
            client.decide(STATE)
        with client:
            pass
        with self.assertRaisesRegex(RuntimeError, "active context"):
            client.decide(STATE)


if __name__ == "__main__":
    unittest.main()
