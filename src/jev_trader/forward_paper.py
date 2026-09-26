"""One scheduled paper tick with persistent, hash-chained accounting."""

import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

from .binance_data import HOUR_MS
from .cli import ROOT, RESULTS
from .forward_observer import append_record, digest, read_chain
from .forward_portfolio import advance, initialize
from .forward_signals import build_snapshot


def next_weekly_entry(server_ms):
    now = datetime.fromtimestamp(server_ms / 1000, timezone.utc)
    monday = (now + timedelta(days=(7 - now.weekday()) % 7)).replace(hour=1, minute=0, second=0, microsecond=0)
    if monday <= now:
        monday += timedelta(days=7)
    return int(monday.timestamp() * 1000)


def schedule(server_ms, activation_ms, last_hour_ms):
    hour = server_ms // HOUR_MS * HOUR_MS
    offset = server_ms - hour
    # Allow funding publication during the first minute; never backfill a
    # missing hourly decision from prices learned later.
    due = server_ms >= activation_ms and 60_000 <= offset < 300_000 and hour != last_hour_ms
    now = datetime.fromtimestamp(server_ms / 1000, timezone.utc)
    return {"hour_ms": hour, "due": due, "rebalance": due and now.weekday() == 0 and now.hour == 1}


def run(series="forward_paper"):
    if not series or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in series):
        raise ValueError("invalid explicit paper series name")
    root = RESULTS / series
    root.mkdir(parents=True, exist_ok=True)
    lock = root / "tick.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(descriptor)
    try:
        path = root / "ledger.jsonl"
        records = read_chain(path)
        for record in records:
            saved = root / record["signal_file"]
            if saved.resolve().parent != root.resolve():
                raise ValueError("paper snapshot path outside series")
            if hashlib.sha256(saved.read_bytes()).hexdigest() != record["signal_file_sha256"]:
                raise ValueError("prior signal snapshot changed")
            signal_body = json.loads(saved.read_text(encoding="utf-8"))
            if digest({k: v for k, v in signal_body.items() if k != "snapshot_sha256"}) != record["signal_snapshot_sha256"]:
                raise ValueError("prior signal content hash changed")
            for source in signal_body["sources"]:
                raw = RESULTS / "forward_signals" / source["file"]
                if raw.resolve().parent.parent != (RESULTS / "forward_signals").resolve():
                    raise ValueError("raw signal source outside observation directory")
                if hashlib.sha256(raw.read_bytes()).hexdigest() != source["sha256"]:
                    raise ValueError("prior raw signal source changed")
        signal = build_snapshot()
        if digest({k: v for k, v in signal.items() if k != "snapshot_sha256"}) != signal["snapshot_sha256"]:
            raise ValueError("signal snapshot hash mismatch")
        now = signal["server_time_ms"]
        code = {name: hashlib.sha256((ROOT / "src/jev_trader" / name).read_bytes()).hexdigest()
                for name in ("forward_portfolio.py", "forward_paper.py", "forward_observer.py")}
        code.update(signal["source_code_sha256"])
        if not records:
            config = {"activated_ms": now, "first_entry_ms": next_weekly_entry(now),
                      "rule": signal["fixed_rule"], "freeze_sha256": signal["freeze_sha256"],
                      "code_sha256": code, "initial_paper_usdt_per_account": 10_000,
                      "variants": {"reference": None, "trailing4": .04},
                      "execution_window": "Hourly minute 1 inclusive through minute 5 exclusive; Monday 01h rebalance",
                      "orders_enabled": False}
            accounts = {name: initialize(now, 10_000, distance) for name, distance in config["variants"].items()}
            last_hour, status, error = None, "initialized_flat", None
        else:
            prior = records[-1]
            config, accounts, last_hour = prior["config"], prior["accounts"], prior["last_processed_hour_ms"]
            if config["code_sha256"] != code or config["freeze_sha256"] != signal["freeze_sha256"]:
                raise ValueError("paper rules changed; explicit new observation series required")
            timing = schedule(now, config["first_entry_ms"], last_hour)
            status, error = "outside_scheduled_window", None
            if timing["due"]:
                status = "processed_hour"
                if not signal["funding_boundary_reconciled"]:
                    status, error = "blocked_accounting", "funding boundary not reconciled"
                else:
                    tick = {"server_time_ms": now,
                            "accepted_quotes": signal["market_observation"]["accepted_quotes"],
                            "funding": signal["funding"]}
                    targets = signal["target_weights"] if timing["rebalance"] else None
                    try:
                        changed = {name: advance(account, tick, targets) for name, account in accounts.items()}
                    except ValueError as exc:
                        status, error = "blocked_accounting", str(exc)
                    else:
                        accounts, last_hour = changed, timing["hour_ms"]
        snapshot_path = root / (str(now) + "-signal.json")
        with snapshot_path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(signal, indent=2, sort_keys=True) + "\n")
        record = append_record(path, {"server_time_ms": now, "config": config, "accounts": accounts,
                                      "last_processed_hour_ms": last_hour, "status": status, "error": error,
                                      "signal_snapshot_sha256": signal["snapshot_sha256"],
                                      "signal_file": snapshot_path.name,
                                      "signal_file_sha256": hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
                                      "orders_sent": 0, "continuous_service_running": False,
                                      "limits": ["Fills are paper assumptions at observed quotes, not confirmed executions.",
                                                 "The command performs one acquisition/tick and exits.",
                                                 "Held positions require timely hourly observations; gaps block accounting.",
                                                 "Midpoint marks, top-of-book size and stated fees omit liquidation/tax/account-specific rules."]})
        print(json.dumps({"status": status, "error": error, "first_entry_utc": datetime.fromtimestamp(
            config["first_entry_ms"] / 1000, timezone.utc).isoformat(),
                          "accounts": {n: {"equity": a["equity"], "positions": len(a["positions"])} for n, a in accounts.items()},
                          "record_sha256": record["record_sha256"]}, indent=2))
        return record
    finally:
        lock.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--series", default="forward_paper", help="Explicit separate paper series; never resets an existing ledger")
    run(parser.parse_args().series)
