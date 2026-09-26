"""Synthetic integrity checks; no market outcomes or downloads."""

import copy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from jev_trader.basis_data import (
    HOUR_MS, PINS, SYMBOLS, _DERIVATIVES, _SPOT, _SUPPLEMENTS,
    _expected_inventory, _load_inventory, _merge, _source_location, load,
)
from jev_trader.derivatives_data import Funding


START = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


def candle(hour, trades=7, price="100", microseconds=False):
    stamp = START + hour * HOUR_MS
    volume = 0 if trades == 0 else 3
    return f"{stamp * (1000 if microseconds else 1)},{price},{price},{price},{price},{volume},0,{volume * 100},{trades},0\n"


class BasisDataTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.records = {name: [] for name in PINS}
        self.expected = {name: set() for name in PINS}
        self.pins = {}
        self.add(_SPOT, ("spot", "BTCUSDT", "monthly", "2023-01"),
                 candle(0, microseconds=True) + candle(2, trades=0, microseconds=True))
        self.add(_DERIVATIVES, ("futures", "BTCUSDT", "monthly", "2023-01"), candle(0) + candle(1) + candle(2))
        self.add(_DERIVATIVES, ("mark", "BTCUSDT", "monthly", "2023-01"), candle(0) + candle(2))
        self.add(_DERIVATIVES, ("funding", "BTCUSDT", "monthly", "2023-01"),
                 f"calc_time,funding_interval_hours,last_funding_rate\n{START},8,.001\n{START + 16 * HOUR_MS + 1},8,-.001\n")
        self.add(_SUPPLEMENTS, ("mark", "BTCUSDT", "daily", "2023-01-01"), candle(0) + candle(1) + candle(2))
        self.save_manifests()

    def add(self, manifest, identity, csv):
        relative, url = _source_location(identity)
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"symbol": identity[1], "month": identity[3], "frequency": identity[2],
                  "path": str(path), "url": url}
        if identity[0] != "spot":
            record["kind"] = {"futures": "klines", "mark": "markPriceKlines", "funding": "fundingRate"}[identity[0]]
        self.rewrite_zip(record, csv)
        self.records[manifest].append(record)
        self.expected[manifest].add(identity)
        return record

    def rewrite_zip(self, record, csv, member=None):
        path = Path(record["path"])
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(member or path.with_suffix(".csv").name, csv)
        payload = output.getvalue()
        path.write_bytes(payload)
        record.update(sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload))

    def save_manifests(self):
        for name, records in self.records.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = (json.dumps(records, sort_keys=True) + "\n").encode("utf-8")
            path.write_bytes(payload)
            self.pins[name] = hashlib.sha256(payload).hexdigest()

    def read(self):
        return _load_inventory(self.root, self.pins, self.expected)

    def test_preserves_gaps_zero_trades_event_milliseconds_and_original_period(self):
        before = {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        with patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")) as network:
            market, audit = self.read()
        network.assert_not_called()
        self.assertEqual(set(market), {"spot", "futures", "mark", "funding"})
        self.assertEqual(tuple(market["spot"]), SYMBOLS)
        self.assertEqual(list(market["spot"]["BTCUSDT"]), [START, START + 2 * HOUR_MS])
        self.assertEqual(list(market["mark"]["BTCUSDT"]), [START, START + HOUR_MS, START + 2 * HOUR_MS])
        self.assertEqual(market["spot"]["BTCUSDT"][START + 2 * HOUR_MS].trades, 0)
        self.assertEqual(market["funding"]["BTCUSDT"][-1].timestamp_ms, START + 16 * HOUR_MS + 1)
        self.assertEqual(audit["identical_duplicate_rows"], 2)
        self.assertEqual(audit["coverage"]["spot"]["BTCUSDT"]["gaps"], [
            {"after_open_ms": START, "before_open_ms": START + 2 * HOUR_MS, "missing_hours": 1}])
        self.assertEqual(audit["coverage"]["mark"]["BTCUSDT"]["gaps"], [])
        self.assertEqual(len(audit["coverage"]["funding"]["BTCUSDT"]["interval_mismatches"]), 1)
        self.assertEqual(audit["zero_trades"], [{"market": "spot", "symbol": "BTCUSDT",
                                              "open_ms": START + 2 * HOUR_MS, "volume": 0}])
        self.assertEqual(audit["source_count"], 5)
        self.assertEqual(audit["network_requests"], 0)
        self.assertEqual(audit["cache_writes"], 0)
        self.assertFalse(audit["historical_point_in_time_verified"])
        self.assertEqual((market, audit), self.read())
        self.assertEqual(before, {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()})

    def test_public_load_uses_exact_three_pins_and_712_source_identities(self):
        expected = _expected_inventory()
        self.assertEqual([len(expected[name]) for name in PINS], [176, 528, 8])
        with patch("jev_trader.basis_data._load_inventory", return_value=(None, None)) as reader:
            load(self.root)
        reader.assert_called_once_with(self.root, PINS, expected)

    def test_changed_manifest_is_rejected_before_reading_archive(self):
        path = self.root / _SPOT
        path.write_bytes(path.read_bytes() + b" ")
        with patch("jev_trader.basis_data._parse_source") as parse:
            with self.assertRaisesRegex(ValueError, "manifest checksum mismatch"):
                self.read()
        parse.assert_not_called()

    def test_corrupt_archive_hash_is_rejected(self):
        path = Path(self.records[_SPOT][0]["path"])
        payload = path.read_bytes()
        path.write_bytes(bytes([payload[0] ^ 1]) + payload[1:])
        with self.assertRaisesRegex(ValueError, "source checksum/size mismatch"):
            self.read()

    def test_wrong_archive_size_is_rejected(self):
        self.records[_SPOT][0]["bytes"] += 1
        self.save_manifests()
        with self.assertRaisesRegex(ValueError, "source checksum/size mismatch"):
            self.read()

    def test_missing_archive_is_not_replaced_or_downloaded(self):
        Path(self.records[_SPOT][0]["path"]).unlink()
        with patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")) as network:
            with self.assertRaises(FileNotFoundError):
                self.read()
        network.assert_not_called()

    def test_duplicate_manifest_identity_even_if_identical_is_rejected(self):
        self.records[_SPOT].append(copy.deepcopy(self.records[_SPOT][0]))
        self.save_manifests()
        with self.assertRaisesRegex(ValueError, "duplicate source identity"):
            self.read()

    def test_missing_manifest_identity_is_rejected(self):
        self.records[_DERIVATIVES].pop()
        self.save_manifests()
        with self.assertRaisesRegex(ValueError, "incomplete manifest inventory"):
            self.read()

    def test_unplanned_symbol_substitution_is_rejected(self):
        self.records[_SPOT][0]["symbol"] = "ETHUSDT"
        self.save_manifests()
        with self.assertRaisesRegex(ValueError, "unexpected source identity"):
            self.read()

    def test_absolute_path_escape_is_rejected(self):
        self.records[_SPOT][0]["path"] = str(self.root.parent / "outside.zip")
        self.save_manifests()
        with self.assertRaisesRegex(ValueError, "path escapes repository root"):
            self.read()

    def test_parent_traversal_is_rejected(self):
        self.records[_SPOT][0]["path"] = "../outside.zip"
        self.save_manifests()
        with self.assertRaisesRegex(ValueError, "parent traversal"):
            self.read()

    def test_different_internal_file_cannot_substitute_source(self):
        self.records[_SPOT][0]["path"] = self.records[_DERIVATIVES][0]["path"]
        self.save_manifests()
        with self.assertRaisesRegex(ValueError, "identity/path/URL mismatch"):
            self.read()

    def test_url_identity_is_verified(self):
        self.records[_SPOT][0]["url"] += "?different-version=1"
        self.save_manifests()
        with self.assertRaisesRegex(ValueError, "identity/path/URL mismatch"):
            self.read()

    def test_frequency_and_interval_substitution_are_rejected(self):
        original = copy.deepcopy(self.records[_SPOT][0])
        for field, value, message in (("frequency", "daily", "frequency mismatch"),
                                       ("interval", "1d", "interval mismatch"),
                                       ("kind", "fundingRate", "invalid spot source kind")):
            with self.subTest(field=field):
                self.records[_SPOT][0] = dict(original, **{field: value})
                self.save_manifests()
                with self.assertRaisesRegex(ValueError, message):
                    self.read()

    def test_zip_member_must_match_source_identity(self):
        self.rewrite_zip(self.records[_SPOT][0], candle(0), member="ETHUSDT-1h-2023-01.csv")
        self.save_manifests()
        with self.assertRaisesRegex(ValueError, "ZIP member identity mismatch"):
            self.read()

    def test_out_of_period_observation_is_rejected(self):
        self.rewrite_zip(self.records[_SPOT][0], candle(-1))
        self.save_manifests()
        with self.assertRaisesRegex(ValueError, "outside source period"):
            self.read()

    def test_non_hourly_candle_is_rejected(self):
        self.rewrite_zip(self.records[_SPOT][0], candle(0).replace(str(START), str(START + 1), 1))
        self.save_manifests()
        with self.assertRaisesRegex(ValueError, "non-hourly candle"):
            self.read()

    def test_supplement_cannot_replace_conflicting_monthly_value(self):
        self.rewrite_zip(self.records[_SUPPLEMENTS][0], candle(0, price="101"))
        self.save_manifests()
        with self.assertRaisesRegex(ValueError, "conflicting duplicate observation"):
            self.read()

    def test_funding_merge_only_accepts_exact_duplicate_events(self):
        original = Funding(START + 1, 8, .001)
        target = {original.timestamp_ms: original}
        self.assertEqual(_merge(target, [original], funding=True), 1)
        self.assertEqual(len(target), 1)
        with self.assertRaisesRegex(ValueError, "conflicting duplicate observation"):
            _merge(target, [Funding(START + 1, 8, .002)], funding=True)

    def test_funding_source_order_is_not_silently_repaired(self):
        record = next(row for row in self.records[_DERIVATIVES] if row["kind"] == "fundingRate")
        self.rewrite_zip(record, f"calc_time,funding_interval_hours,last_funding_rate\n{START + 8 * HOUR_MS},8,.001\n{START},8,.001\n")
        self.save_manifests()
        with self.assertRaisesRegex(ValueError, "duplicate/reversed source timestamps"):
            self.read()

    def test_non_finite_prices_are_rejected(self):
        self.rewrite_zip(self.records[_SPOT][0], candle(0).replace(",100,100,100,100,", ",100,inf,100,100,"))
        self.save_manifests()
        with self.assertRaisesRegex(ValueError, "non-finite candle value"):
            self.read()


if __name__ == "__main__":
    unittest.main()
