"""Read-only, hash-chained acquisition for future paper execution evidence."""

import hashlib
import json
import math
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .binance_data import _read_url
from .broad_data import CACHE
from .cli import ROOT, RESULTS

API = "https://fapi.binance.com/fapi/v1/"
ALLOWED = {"time", "exchangeInfo", "ticker/bookTicker"}
ZERO = "0" * 64


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def validate_quote(row, server_ms, max_age_ms=30_000):
    values = {k: float(row[k]) for k in ("bidPrice", "askPrice", "bidQty", "askQty")}
    if any(not math.isfinite(v) or v <= 0 for v in values.values()):
        raise ValueError("invalid quote price or quantity")
    if values["bidPrice"] > values["askPrice"]:
        raise ValueError("crossed quote")
    age = server_ms - int(row["time"])
    if not 0 <= age <= max_age_ms:
        raise ValueError("stale or future quote")
    mid = (values["bidPrice"] + values["askPrice"]) / 2
    return {**values, "quote_time_ms": int(row["time"]), "age_ms": age,
            "spread_bps": 10_000 * (values["askPrice"] - values["bidPrice"]) / mid}


def read_chain(path):
    records, previous, timestamp = [], ZERO, -1
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        body = {k: v for k, v in record.items() if k != "record_sha256"}
        if (body["previous_sha256"] != previous or digest(body) != record["record_sha256"]
                or body["server_time_ms"] <= timestamp):
            raise ValueError("observation ledger integrity or chronology failure")
        previous, timestamp = record["record_sha256"], body["server_time_ms"]
        records.append(record)
    return records


def append_record(path, body):
    records = read_chain(path)
    if records and body["server_time_ms"] <= records[-1]["server_time_ms"]:
        raise ValueError("observation clock did not advance")
    body = {**body, "previous_sha256": records[-1]["record_sha256"] if records else ZERO}
    record = {**body, "record_sha256": digest(body)}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return record


def capture(directory=None):
    directory = Path(directory) if directory else RESULTS / "forward_observer"
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / "capture.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.close(descriptor)
        ledger = directory / "observations.jsonl"
        prior = read_chain(ledger)
        # Verify all previously referenced payloads before extending the chain.
        for record in prior:
            for source in record["sources"]:
                payload_path = directory / source["file"]
                if payload_path.resolve().parent.parent != (directory / "raw").resolve():
                    raise ValueError("payload outside capture directory")
                if hashlib.sha256(payload_path.read_bytes()).hexdigest() != source["sha256"]:
                    raise ValueError("prior public response changed")
        capture_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        folder = directory / "raw" / capture_id
        folder.mkdir(parents=True)
        sources = []
        def request(endpoint, label):
            if endpoint not in ALLOWED:
                raise ValueError("only allowlisted public GET endpoints")
            start = time.time_ns() // 1_000_000
            payload = _read_url(API + endpoint)
            finish = time.time_ns() // 1_000_000
            target = folder / (label + ".json")
            target.write_bytes(payload)
            sources.append({"url": API + endpoint, "file": str(target.relative_to(directory)).replace("\\", "/"),
                            "sha256": hashlib.sha256(payload).hexdigest(),
                            "request_started_ms": start, "received_ms": finish})
            return json.loads(payload)
        before = int(request("time", "server_before")["serverTime"])
        exchange = request("exchangeInfo", "exchange")
        quotes = request("ticker/bookTicker", "quotes")
        after = int(request("time", "server_after")["serverTime"])
        last_source = sources[-1]
        if not before <= after or not last_source["request_started_ms"] - 5000 <= after <= last_source["received_ms"] + 5000:
            raise ValueError("server/local clock mismatch")
        if after - before > 30_000:
            raise ValueError("capture interval too wide")
        cohort = json.loads((CACHE / "cohort.json").read_text(encoding="utf-8"))["selected"]
        symbols = {r["symbol"]: r for r in exchange["symbols"]}
        if not isinstance(quotes, list) or len({r["symbol"] for r in quotes}) != len(quotes):
            raise ValueError("invalid quote response or duplicate symbols")
        by_symbol = {r["symbol"]: r for r in quotes}
        accepted, unavailable, rejected = {}, {}, {}
        for symbol in cohort:
            info = symbols.get(symbol)
            if info is None or info["status"] != "TRADING" or info["contractType"] != "PERPETUAL":
                unavailable[symbol] = "absent" if info is None else info["status"]
                continue
            try:
                accepted[symbol] = validate_quote(by_symbol[symbol], after)
            except (KeyError, ValueError) as exc:
                rejected[symbol] = str(exc)
        code = {name: hashlib.sha256((ROOT / "src/jev_trader" / name).read_bytes()).hexdigest()
                for name in ("forward_observer.py", "broad_research.py", "broad_execution.py", "trailing_stop.py")}
        body = {"server_time_ms": after, "capture_start_server_ms": before,
                "received_utc": datetime.now(timezone.utc).isoformat(), "sources": sources,
                "cohort_sha256": hashlib.sha256((CACHE / "cohort.json").read_bytes()).hexdigest(),
                "source_code_sha256": code, "accepted_quotes": accepted,
                "unavailable_contracts": unavailable, "rejected_quotes": rejected,
                "status": "market_observation_only", "orders_sent": 0,
                "paper_positions": None, "paper_equity": None,
                "continuity_gap_ms": after - prior[-1]["server_time_ms"] if prior else None,
                "limits": ["Top-of-book observation is not a fill or a simultaneous tradable basket.",
                           "No signal scheduling, paper portfolio accounting or continuous service in this capture command.",
                           "Local hash chain is tamper-evident when externally anchored, not a trusted timestamp service."]}
        record = append_record(ledger, body)
        print(json.dumps({"server_time_ms": after, "accepted": len(accepted), "unavailable": unavailable,
                          "rejected": rejected, "record_sha256": record["record_sha256"],
                          "ledger": str(ledger)}, indent=2))
        return record
    finally:
        lock.unlink()


if __name__ == "__main__":
    capture()
