import json
import tempfile
import unittest
from pathlib import Path
from xml.sax.saxutils import escape

from jev_trader.metrics_catalog import calendar, compact_report, coverage, load_catalog, parse_page, weekly_candidates


PREFIX = "data/futures/um/daily/metrics/BTCUSDT/"
KEY = PREFIX + "BTCUSDT-metrics-2021-12-03.zip"


def page(keys, *, marker="", truncated=False, next_marker=None, prefix=PREFIX):
    contents = "".join(f"<Contents><Key>{escape(key)}</Key><LastModified>2026-03-18T12:30:27.000Z</LastModified>"
                       '<ETag>"abc"</ETag><Size>42</Size></Contents>' for key in keys)
    next_xml = "" if next_marker is None else f"<NextMarker>{escape(next_marker)}</NextMarker>"
    return (f'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Prefix>{prefix}</Prefix>'
            f"<Marker>{escape(marker)}</Marker><IsTruncated>{str(truncated).lower()}</IsTruncated>"
            f"{contents}{next_xml}</ListBucketResult>").encode()


class CatalogTests(unittest.TestCase):
    def test_metadata_and_fallback_marker(self):
        result = parse_page(page([KEY], truncated=True), PREFIX)
        self.assertEqual(result["next_marker"], KEY)
        self.assertEqual(result["objects"][0], {"key": KEY, "size": 42,
                         "last_modified": "2026-03-18T12:30:27.000Z", "etag": '"abc"'})

    def test_empty_terminal_listing(self):
        self.assertFalse(parse_page(page([]), PREFIX)["is_truncated"])

    def test_pagination_stall_and_duplicate_rejected(self):
        for raw, marker in [(page([], truncated=True), ""),
                            (page([KEY], truncated=True, next_marker="a"), ""),
                            (page([KEY, KEY]), ""), (page([KEY], marker=KEY), KEY)]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_page(raw, PREFIX, marker)

    def test_bad_metadata_and_request_rejected(self):
        for raw in [page([KEY]).replace(b"<Size>42", b"<Size>-1"),
                    page([KEY]).replace(b".000Z", b".000"),
                    page([KEY]).replace(b"<IsTruncated>false", b"<IsTruncated>maybe"),
                    page([KEY], prefix="wrong"), page([KEY], marker="wrong"),
                    page([KEY]).replace(b"<ETag>", b"<NoETag>").replace(b"</ETag>", b"</NoETag>")]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_page(raw, PREFIX)

    def test_valid_explicit_next_marker(self):
        result = parse_page(page([KEY], truncated=True, next_marker=KEY), PREFIX)
        self.assertEqual(result["next_marker"], KEY)

    def test_two_pages_resume_and_no_repeat_network(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def fetch(url):
                calls.append(url)
                if len(calls) == 1:
                    return page([KEY], truncated=True)
                return page([KEY + ".CHECKSUM"], marker=KEY)
            result = load_catalog("BTCUSDT", directory, fetcher=fetch)
            self.assertEqual(len(result["objects"]), 2)
            self.assertIn("marker=", calls[1])
            again = load_catalog("BTCUSDT", directory, fetcher=lambda _: self.fail("cached network call"))
            self.assertEqual(result, again)
            self.assertEqual(len(again["raw_sources"]), 2)

    def test_interrupted_pagination_resumes(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def fetch(url):
                calls.append(url)
                if len(calls) == 1:
                    return page([KEY], truncated=True)
                raise OSError("temporary outage")
            with self.assertRaises(OSError):
                load_catalog("BTCUSDT", directory, fetcher=fetch)
            result = load_catalog("BTCUSDT", directory,
                                  fetcher=lambda url: page([KEY + ".CHECKSUM"], marker=KEY))
            self.assertEqual(len(result["objects"]), 2)

    def test_cache_corruption_and_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            result = load_catalog("BTCUSDT", directory, fetcher=lambda _: page([KEY]))
            path = Path(directory) / "BTCUSDT" / result["raw_sources"][0]["raw_file"]
            path.write_bytes(b"corrupted")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                load_catalog("BTCUSDT", directory)
            meta = Path(directory) / "BTCUSDT/page-00000.json"
            content = json.loads(meta.read_text())
            content["raw_file"] = "../escape.xml"
            meta.write_text(json.dumps(content))
            with self.assertRaisesRegex(ValueError, "filename"):
                load_catalog("BTCUSDT", directory)

    def test_bad_symbol_rejected(self):
        for symbol in ["../BTCUSDT", "btc", "BTC_USDT"]:
            with self.assertRaises(ValueError):
                load_catalog(symbol)

    def test_complete_calendar_not_observed_bounds(self):
        catalog = {"symbol": "BTCUSDT", "prefix": PREFIX,
                   "objects": {KEY: {"key": KEY, "size": 42}, KEY + ".CHECKSUM": {"size": 64}}}
        actual = coverage(catalog, "2021-12-01", "2021-12-05", settlement_date="2021-12-03")
        self.assertEqual(actual["expected_days"], 5)
        self.assertEqual(actual["paired_days"], 1)
        self.assertEqual(actual["missing_pair_other_dates"], ["2021-12-01", "2021-12-02"])
        self.assertEqual(actual["missing_pair_post_settlement_dates"], ["2021-12-04", "2021-12-05"])
        self.assertEqual(len(weekly_candidates(catalog)), 1)

    def test_unpaired_and_settlement_day_are_explicit(self):
        catalog = {"symbol": "BTCUSDT", "prefix": PREFIX, "objects": {KEY: {"size": 42}}}
        result = coverage(catalog, "2021-12-03", "2021-12-04", settlement_date="2021-12-03")
        self.assertEqual(result["zip_only_dates"], ["2021-12-03"])
        self.assertEqual(result["missing_pair_other_dates"], ["2021-12-03"])
        self.assertEqual(weekly_candidates(catalog), [])

    def test_friday_calendar_bounds(self):
        actual = calendar("2021-12-03", "2026-09-18", 4)
        self.assertEqual(actual[0], "2021-12-03")
        self.assertEqual(actual[-1], "2026-09-18")
        self.assertEqual(len(actual), 251)
        with self.assertRaises(ValueError):
            calendar("2026-09-18", "2021-12-03")

    def test_compact_report_discloses_projection_and_post_settlement_pairs(self):
        catalog = {"symbol": "BTCUSDT", "prefix": PREFIX,
                   "objects": {KEY: {"size": 42}, KEY + ".CHECKSUM": {"size": 64}}}
        scope = coverage(catalog, "2021-12-03", "2021-12-03", settlement_date="2021-12-02")
        report = {"assets": {"BTCUSDT": {"full_calendar": scope, "weekly_fridays": scope}},
                  "weekly_candidates": [1]}
        compact = compact_report(report, b"preserved exact full bytes")
        self.assertEqual(compact["weekly_candidate_count"], 1)
        self.assertEqual(compact["assets"]["BTCUSDT"]["full_calendar"]["paired_post_settlement_days"], 1)
        self.assertNotIn("paired_dates", compact["assets"]["BTCUSDT"]["full_calendar"])
        self.assertNotIn("weekly_candidates", compact)
        self.assertIn("paired_dates", scope)


if __name__ == "__main__":
    unittest.main()
