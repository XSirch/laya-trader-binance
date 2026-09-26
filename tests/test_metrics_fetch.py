import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error
import zipfile

from jev_trader.metrics_fetch import (
    BASE_URL, CHECKSUM_LIMIT, ZIP_LIMIT, _NoRedirect, _read_url, fetch,
)
from jev_trader.positioning_metrics import CSV_FIELDS


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.basename = "BTCUSDT-metrics-2024-01-07.zip"
        self.key = "data/futures/um/daily/metrics/BTCUSDT/" + self.basename
        self.payload = self.archive(",".join(CSV_FIELDS) + "\n"
                                    "2024-01-07 23:55:00,BTCUSDT,1,2,1,1,1,1\n")
        self.checksum = (hashlib.sha256(self.payload).hexdigest()
                         + "  " + self.basename + "\n").encode("ascii")
        self.record = self.metadata(self.payload, self.checksum)
        self.reader = Mock(side_effect=lambda url, limit: self.checksum if url.endswith("CHECKSUM")
                           else self.payload)

    def archive(self, csv):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(self.basename.replace(".zip", ".csv"), csv)
        return stream.getvalue()

    def metadata(self, payload, checksum):
        return {"symbol": "BTCUSDT", "day": "2024-01-07",
                "zip": {"key": self.key, "size": len(payload),
                        "last_modified": "2026-09-20T00:00:00Z", "etag": '"zip-etag"'},
                "checksum": {"key": self.key + ".CHECKSUM", "size": len(checksum),
                             "last_modified": "2026-09-20T00:00:00Z", "etag": '"checksum-etag"'}}

    def acquire(self, record=None, reader=None, sleeper=None):
        return fetch(record or self.record, self.root, reader=reader or self.reader,
                     sleeper=sleeper or Mock())

    def test_acquisition_persists_verified_bytes_quality_and_unavailable_snapshot(self):
        result = self.acquire()
        self.assertFalse(result["cache_hit"])
        self.assertEqual(Path(result["zip"]["path"]).read_bytes(), self.payload)
        self.assertEqual(Path(result["checksum"]["path"]).read_bytes(), self.checksum)
        self.assertEqual(result["quality"]["unique_rows"], 1)
        self.assertFalse(result["snapshot"]["available"])
        persisted = json.loads(Path(result["record_path"]).read_text(encoding="utf-8"))
        self.assertNotIn("cache_hit", persisted)
        self.assertEqual(persisted["zip"]["current_version_metadata"], self.record["zip"])
        self.assertEqual(self.reader.call_count, 2)
        self.assertFalse(list(self.root.rglob("*.part")))
        self.assertFalse(list(self.root.rglob("*.lock")))

    def test_complete_cache_is_rehashed_without_network_or_timestamp_change(self):
        first = self.acquire()
        self.reader.reset_mock()
        self.reader.side_effect = AssertionError("network must not be used")
        second = self.acquire()
        self.assertTrue(second["cache_hit"])
        self.assertEqual(first["first_observed_utc"], second["first_observed_utc"])
        self.reader.assert_not_called()

    def test_resume_partial_checksum_cache_downloads_only_zip(self):
        target = self.root / "BTCUSDT" / (self.basename + ".CHECKSUM")
        target.parent.mkdir()
        target.write_bytes(self.checksum)
        result = self.acquire()
        self.assertFalse(result["cache_hit"])
        self.reader.assert_called_once_with(BASE_URL + self.key, ZIP_LIMIT)

    def test_resume_missing_verified_file_preserves_record(self):
        first = self.acquire()
        record_bytes = Path(first["record_path"]).read_bytes()
        Path(first["zip"]["path"]).unlink()
        self.reader.reset_mock()
        second = self.acquire()
        self.assertEqual(Path(first["record_path"]).read_bytes(), record_bytes)
        self.assertEqual(first["first_observed_utc"], second["first_observed_utc"])
        self.reader.assert_called_once_with(BASE_URL + self.key, ZIP_LIMIT)

    def test_cached_corruption_is_quarantined_and_never_silently_redownloaded(self):
        first = self.acquire()
        record_bytes = Path(first["record_path"]).read_bytes()
        path = Path(first["zip"]["path"])
        path.write_bytes(b"x" * len(self.payload))
        self.reader.reset_mock()
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            self.acquire()
        self.reader.assert_not_called()
        self.assertEqual(Path(first["record_path"]).read_bytes(), record_bytes)
        self.assertEqual(path.read_bytes(), b"x" * len(self.payload))
        self.assertEqual(len(list((self.root / "quarantine").rglob("*.failure.json"))), 1)

    def test_changed_catalogue_cannot_overwrite_verified_record(self):
        first = self.acquire()
        initial = Path(first["record_path"]).read_bytes()
        self.reader.reset_mock()
        changed = copy.deepcopy(self.record)
        changed["zip"]["etag"] = '"revised"'
        with self.assertRaisesRegex(ValueError, "catalogue version changed"):
            self.acquire(changed)
        self.reader.assert_not_called()
        self.assertEqual(Path(first["record_path"]).read_bytes(), initial)

    def test_invalid_cache_record_fails_before_network(self):
        first = self.acquire()
        path = Path(first["record_path"])
        record = json.loads(path.read_text(encoding="utf-8"))
        record.pop("first_observed_utc")
        payload = json.dumps(record).encode("utf-8")
        path.write_bytes(payload)
        self.reader.reset_mock()
        with self.assertRaisesRegex(ValueError, "invalid verified cache record"):
            self.acquire()
        self.reader.assert_not_called()
        self.assertEqual(path.read_bytes(), payload)

    def test_injected_oversized_response_is_rejected(self):
        self.reader.side_effect = lambda url, limit: b"x" * (limit + 1)
        with self.assertRaisesRegex(ValueError, "exceeds byte limit"):
            self.acquire()
        self.assertEqual(self.reader.call_count, 1)
        self.assertFalse(list(self.root.rglob("*.record.json")))

    def test_catalogue_size_must_match_actual_bytes(self):
        changed = copy.deepcopy(self.record)
        changed["zip"]["size"] += 1
        with self.assertRaisesRegex(ValueError, "byte count differs"):
            self.acquire(changed)
        self.assertFalse(list(self.root.rglob("*.record.json")))

    def test_checksum_filename_mismatch_fails_even_when_digest_matches(self):
        self.checksum = self.checksum.replace(b"BTCUSDT", b"ETHUSDT")
        self.record = self.metadata(self.payload, self.checksum)
        with self.assertRaisesRegex(ValueError, "expected ZIP basename"):
            self.acquire()

    def test_checksum_digest_mismatch_is_quarantined(self):
        self.checksum = b"0" * 64 + self.checksum[64:]
        with self.assertRaisesRegex(ValueError, "SHA256"):
            self.acquire()
        self.assertTrue(list((self.root / "quarantine").rglob("*.failure.json")))

    def test_valid_checksum_does_not_bypass_parser(self):
        self.payload = self.archive("wrong,header\n")
        self.checksum = (hashlib.sha256(self.payload).hexdigest()
                         + "  " + self.basename + "\n").encode("ascii")
        self.record = self.metadata(self.payload, self.checksum)
        with self.assertRaisesRegex(ValueError, "CSV columns"):
            self.acquire()
        self.assertFalse(list(self.root.rglob("*.record.json")))
        self.assertTrue(list((self.root / "quarantine").rglob("*.failure.json")))

    def test_path_host_and_size_injections_fail_before_network(self):
        for key in ("https://evil.invalid/file.zip", "../../escape.zip",
                    self.key + "?query=x", self.key.replace("BTCUSDT/", "../")):
            record = copy.deepcopy(self.record)
            record["zip"]["key"] = key
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.acquire(record)
        for value in (True, -1, ZIP_LIMIT + 1):
            record = copy.deepcopy(self.record)
            record["zip"]["size"] = value
            with self.subTest(size=value), self.assertRaises(ValueError):
                self.acquire(record)
        self.reader.assert_not_called()

    def test_transient_failures_retry_at_most_three_times(self):
        sleeper = Mock()
        reader = Mock(side_effect=[
            urllib.error.HTTPError(BASE_URL, 429, "rate limited", {}, None),
            TimeoutError("timeout"), self.checksum, self.payload])
        self.acquire(reader=reader, sleeper=sleeper)
        self.assertEqual([call.args[0] for call in sleeper.call_args_list], [1.0, 2.0])
        self.assertEqual(reader.call_count, 4)

    def test_exhausted_timeout_and_http_404_have_bounded_attempts(self):
        for failure, calls in ((TimeoutError("timeout"), 3),
                               (urllib.error.HTTPError(BASE_URL, 404, "missing", {}, None), 1)):
            reader = Mock(side_effect=failure)
            with self.subTest(failure=failure), self.assertRaises(RuntimeError):
                self.acquire(reader=reader)
            self.assertEqual(reader.call_count, calls)
            self.assertFalse(list(self.root.rglob("*.lock")))

    def test_existing_lock_prevents_duplicate_download_and_is_preserved(self):
        directory = self.root / "BTCUSDT"
        directory.mkdir()
        lock = directory / (self.basename + ".lock")
        lock.write_bytes(b"other fetch")
        with self.assertRaisesRegex(RuntimeError, "already locked"):
            self.acquire()
        self.reader.assert_not_called()
        self.assertEqual(lock.read_bytes(), b"other fetch")

    def test_default_transport_bounds_read_and_binds_etag(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.geturl.return_value = BASE_URL + self.key
        response.headers = {"ETag": '"abc"'}
        response.read.return_value = b"ok"
        opener = Mock()
        opener.open.return_value = response
        with patch("jev_trader.metrics_fetch.urllib.request.build_opener", return_value=opener):
            self.assertEqual(_read_url(BASE_URL + self.key, 10, '"abc"'), b"ok")
        response.read.assert_called_once_with(11)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.headers["If-match"], '"abc"')
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 30)

    def test_default_transport_rejects_oversized_body_and_version_change(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.geturl.return_value = BASE_URL + self.key
        opener = Mock()
        opener.open.return_value = response
        for headers, payload in (({"ETag": '"changed"'}, b"ok"),
                                  ({"Content-Length": "11"}, b"ok"), ({}, b"x" * 11)):
            response.headers = headers
            response.read.return_value = payload
            with self.subTest(headers=headers), patch(
                    "jev_trader.metrics_fetch.urllib.request.build_opener", return_value=opener):
                with self.assertRaises(ValueError):
                    _read_url(BASE_URL + self.key, 10, '"abc"')

    def test_redirect_is_rejected_before_following_another_host(self):
        with self.assertRaisesRegex(ValueError, "redirect"):
            _NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://evil.invalid")


if __name__ == "__main__":
    unittest.main()
