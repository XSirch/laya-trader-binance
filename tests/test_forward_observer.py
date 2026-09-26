import json
import tempfile
import unittest
from pathlib import Path

from jev_trader.forward_observer import append_record, read_chain, validate_quote


class ObserverTests(unittest.TestCase):
    def quote(self):
        return {"bidPrice": "99", "askPrice": "101", "bidQty": "3", "askQty": "2", "time": 1000}

    def test_quote_rejects_stale_future_crossed_and_nonfinite_values(self):
        self.assertEqual(validate_quote(self.quote(), 1100)["spread_bps"], 200)
        for row, now in ((self.quote(), 32000), (self.quote(), 999),
                         ({**self.quote(), "bidPrice": "102"}, 1100),
                         ({**self.quote(), "bidQty": "nan"}, 1100)):
            with self.assertRaises(ValueError):
                validate_quote(row, now)

    def test_chain_detects_edit_and_rejects_duplicate_clock(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ledger.jsonl"
            first = append_record(path, {"server_time_ms": 1, "value": "observed"})
            second = append_record(path, {"server_time_ms": 2, "value": "new"})
            self.assertEqual(second["previous_sha256"], first["record_sha256"])
            self.assertEqual(len(read_chain(path)), 2)
            with self.assertRaises(ValueError):
                append_record(path, {"server_time_ms": 2})
            lines = path.read_text(encoding="utf-8").splitlines()
            edited = json.loads(lines[0])
            edited["value"] = "rewritten"
            lines[0] = json.dumps(edited)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_chain(path)
