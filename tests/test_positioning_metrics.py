"""Synthetic ingestion checks without market downloads or strategy evaluation."""

import csv
from datetime import datetime, timedelta, timezone
import io
import unittest
from unittest.mock import patch
import zipfile

from jev_trader.positioning_metrics import CSV_FIELDS, MAX_CSV_BYTES, METRIC_FIELDS, parse_metrics, snapshot


SYMBOL = "BTCUSDT"
DAY = "2024-01-01"
MEMBER = f"{SYMBOL}-metrics-{DAY}.csv"
START = datetime(2024, 1, 1, tzinfo=timezone.utc)


def rows(count=288):
    return [[(START + timedelta(minutes=5 * i)).strftime("%Y-%m-%d %H:%M:%S"),
             SYMBOL, "100", "1000", "1.2", "1.3", "1.4", "1.5"] for i in range(count)]


def packed(records=None, header=CSV_FIELDS, member=MEMBER, extra=None, bom=False, raw=None):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(header)
    writer.writerows(rows() if records is None else records)
    body = stream.getvalue().encode("utf-8-sig" if bom else "utf-8") if raw is None else raw
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as handle:
        handle.writestr(member, body)
        if extra is not None:
            handle.writestr(extra, b"extra")
    return archive.getvalue()


def parsed(records=None, **kwargs):
    return parse_metrics(packed(records, **kwargs), SYMBOL, DAY)


class PositioningMetricsTests(unittest.TestCase):
    def test_complete_day_has_exact_daily_medians_and_explicit_utc_assumption(self):
        result = parsed()
        summary = snapshot(result)
        self.assertTrue(summary["available"])
        self.assertEqual(summary["values"], dict(zip(METRIC_FIELDS, (100., 1000., 1.2, 1.3, 1.4, 1.5))))
        self.assertEqual(summary["timezone_assumption"], "UTC")
        self.assertFalse(summary["original_publication_time_known"])
        self.assertEqual(summary["quality"]["unique_rows"], 288)
        self.assertEqual(summary["quality"]["expected_slots"], 288)
        self.assertEqual(summary["last_observed_timestamp_ms"], int((START + timedelta(hours=23, minutes=55)).timestamp() * 1000))

    def test_bom_supported_and_reversed_input_sorted(self):
        result = parsed(list(reversed(rows())), bom=True)
        timestamps = [row["timestamp_ms"] for row in result["observations"]]
        self.assertEqual(timestamps, sorted(timestamps))
        self.assertTrue(snapshot(result)["available"])

    def test_identical_duplicates_do_not_inflate_coverage(self):
        observations = rows()
        result = parsed(observations + observations)
        self.assertEqual(result["quality"]["duplicate_rows"], 288)
        self.assertEqual(result["quality"]["raw_rows"], 576)
        self.assertEqual(result["quality"]["unique_rows"], 288)
        self.assertTrue(snapshot(result)["available"])
        short = parsed(rows(150) * 2)
        self.assertEqual(short["quality"]["unique_rows"], 150)
        self.assertFalse(snapshot(short)["available"])

    def test_conflicting_duplicate_rejected_even_if_numerically_equivalent(self):
        for replacement in ("101", "100.0", " 100", "1e2"):
            with self.subTest(replacement=replacement):
                observations = rows(1)
                duplicate = observations[0].copy()
                duplicate[2] = replacement
                with self.assertRaisesRegex(ValueError, "conflicting duplicate"):
                    parsed(observations + [duplicate])

    def test_missing_tokens_are_explicit_and_counts_use_unique_rows(self):
        for token in ("", "NaN", "null", "NULL", " nan "):
            with self.subTest(token=token):
                observations = rows()
                observations[1][2] = token
                result = parsed(observations + [observations[1]])
                self.assertIsNone(result["observations"][1][METRIC_FIELDS[0]])
                self.assertEqual(result["quality"]["field_missing_counts"][METRIC_FIELDS[0]], 1)
                self.assertEqual(result["quality"]["field_valid_counts"][METRIC_FIELDS[0]], 287)
                self.assertTrue(snapshot(result)["available"])

    def test_four_missing_slots_allowed_but_five_unavailable(self):
        enough = rows()[4:]
        result = parsed(enough)
        self.assertEqual(result["quality"]["missing_slots"], 4)
        self.assertTrue(snapshot(result)["available"])
        short = snapshot(parsed(rows()[5:]))
        self.assertFalse(short["available"])
        self.assertIn("unique_slots_below_284", short["reasons"])
        self.assertIsNone(short["values"])

    def test_each_field_needs_284_strictly_positive_observations(self):
        for column, field in enumerate(METRIC_FIELDS, 2):
            with self.subTest(field=field):
                observations = rows()
                for row in observations[:4]:
                    row[column] = "null"
                self.assertTrue(snapshot(parsed(observations))["available"])
                observations[4][column] = "null"
                summary = snapshot(parsed(observations))
                self.assertFalse(summary["available"])
                self.assertIn(f"positive_coverage_below_284:{field}", summary["reasons"])

    def test_zero_open_interest_flagged_and_not_positive_coverage(self):
        for column in (2, 3):
            with self.subTest(column=column):
                observations = rows()
                for row in observations[:4]:
                    row[column] = "0"
                result = parsed(observations)
                self.assertEqual(result["quality"]["zero_oi_counts"][METRIC_FIELDS[column - 2]], 4)
                self.assertEqual(result["quality"]["field_valid_counts"][METRIC_FIELDS[column - 2]], 288)
                self.assertTrue(snapshot(result)["available"])
                observations[4][column] = "0"
                self.assertFalse(snapshot(parsed(observations))["available"])

    def test_final_slot_required_even_with_287_good_rows(self):
        summary = snapshot(parsed(rows(287)))
        self.assertFalse(summary["available"])
        self.assertIn("final_23_55_observation_missing", summary["reasons"])

    def test_empty_archive_day_is_explicitly_unavailable(self):
        summary = snapshot(parsed([]))
        self.assertFalse(summary["available"])
        self.assertEqual(summary["quality"]["missing_slots"], 288)
        self.assertIsNone(summary["last_observed_timestamp_ms"])

    def test_oi_zero_stays_in_median_and_no_missing_value_is_filled(self):
        observations = rows()
        for row in observations[:144]:
            row[2] = "1"
        for row in observations[144:]:
            row[2] = "3"
        observations[0][2] = "0"
        self.assertEqual(snapshot(parsed(observations))["values"][METRIC_FIELDS[0]], 2)
        observations[0][2] = "null"
        self.assertEqual(snapshot(parsed(observations))["values"][METRIC_FIELDS[0]], 3)

    def test_bad_schema_and_field_counts_rejected(self):
        variants = [CSV_FIELDS[:-1], (*CSV_FIELDS, "unknown"),
                    (CSV_FIELDS[1], CSV_FIELDS[0], *CSV_FIELDS[2:])]
        for header in variants:
            with self.subTest(header=header), self.assertRaises(ValueError):
                parsed(header=header)
        for row in (rows(1)[0][:-1], rows(1)[0] + ["extra"], []):
            with self.subTest(row=row), self.assertRaises(ValueError):
                parsed([row])

    def test_wrong_symbol_day_and_grid_rejected(self):
        for column, value in ((1, "ETHUSDT"), (0, "2024-01-02 00:00:00"),
                              (0, "2024-01-01 00:01:00"), (0, "2024-01-01 00:05:01"),
                              (0, "2024-01-01T00:00:00Z"), (0, "2024-01-01 24:00:00"),
                              (0, "2024-01-01 00:00:00.000"), (0, "2024-1-01 00:00:00")):
            with self.subTest(value=value):
                observations = rows(1)
                observations[0][column] = value
                with self.assertRaises(ValueError):
                    parsed(observations)

    def test_bad_numeric_tokens_and_infinity_rejected(self):
        for token in ("inf", "-Infinity", "1e999", "oops", "1_000", "--1", "-1", "nan(1)"):
            for column in range(2, 8):
                with self.subTest(token=token, column=column):
                    observations = rows(1)
                    observations[0][column] = token
                    with self.assertRaises(ValueError):
                        parsed(observations)

    def test_zero_ratios_retained_but_do_not_satisfy_positive_coverage(self):
        for column in range(4, 8):
            with self.subTest(column=column):
                observations = rows()
                for row in observations[:4]:
                    row[column] = "0"
                result = parsed(observations)
                field = METRIC_FIELDS[column - 2]
                self.assertEqual(result["quality"]["field_zero_counts"][field], 4)
                self.assertTrue(snapshot(result)["available"])
                observations[4][column] = "0"
                summary = snapshot(parsed(observations))
                self.assertFalse(summary["available"])
                self.assertIn(f"positive_coverage_below_284:{field}", summary["reasons"])

    def test_finite_extreme_observations_produce_finite_median(self):
        observations = rows()
        for row in observations:
            row[2:] = ["1e308"] * 6
        self.assertEqual(set(snapshot(parsed(observations))["values"].values()), {1e308})

    def test_exact_zip_member_required_no_traversal_or_extra_members(self):
        for member in ("../" + MEMBER, "folder/" + MEMBER, "other.csv", MEMBER + "/"):
            with self.subTest(member=member), self.assertRaises(ValueError):
                parsed(member=member)
        with self.assertRaises(ValueError):
            parsed(extra="other.csv")

    def test_bad_zip_crc_and_encoding_rejected(self):
        with self.assertRaises(ValueError):
            parse_metrics(b"not a zip", SYMBOL, DAY)
        damaged = packed().replace(b"2024-01-01 00:00:00", b"2024-01-01 00:00:01", 1)
        with self.assertRaises(ValueError):
            parse_metrics(damaged, SYMBOL, DAY)
        with self.assertRaises(ValueError):
            parsed(raw=b"\xff\xfe")

    def test_malformed_csv_rejected(self):
        with self.assertRaises(ValueError):
            parsed(raw=(",".join(CSV_FIELDS) + '\n"unterminated').encode())

    def test_oversized_member_rejected_before_crc_decompression(self):
        payload = packed(raw=b"x" * (MAX_CSV_BYTES + 1))
        with patch.object(zipfile.ZipFile, "testzip", side_effect=AssertionError("must not decompress")):
            with self.assertRaisesRegex(ValueError, "uncompressed size limit"):
                parse_metrics(payload, SYMBOL, DAY)

    def test_invalid_arguments_rejected(self):
        for symbol, day in (("../BTCUSDT", DAY), ("btcusdt", DAY), (SYMBOL, "2024-1-1"),
                            (SYMBOL, "2024-02-30"), (SYMBOL, "2024-01-01/../")):
            with self.subTest(symbol=symbol, day=day), self.assertRaises(ValueError):
                parse_metrics(packed(), symbol, day)


if __name__ == "__main__":
    unittest.main()
