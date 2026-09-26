"""Read-only verification and descriptive reporting of a prospective paper ledger.

Replaying the same frozen accounting proves reproducibility, not independent
correctness of the accounting model, market inputs, or a trading advantage.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import time

from .binance_data import HOUR_MS
from .cli import ROOT, RESULTS
from .forward_observer import ZERO, digest, read_chain
from .forward_paper import next_weekly_entry, schedule
from .forward_portfolio import advance, initialize


FREEZE_FILE = "docs/broad_candidate_freeze_2026-09-26.json"
BASE_CODE = {"forward_portfolio.py", "forward_paper.py", "forward_observer.py"}
SIGNAL_CODE = {"forward_signals.py", "broad_technical.py", "broad_prediction.py",
               "broad_research.py", "market_state.py", "strategies.py", "broad_data.py",
               "broad_extension.py", "binance_data.py", "derivatives_data.py"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _same(left, right):
    # JSON identity distinguishes true from 1 and rejects non-finite floats.
    return digest(left) == digest(right)


def _timestamp(value):
    _require(type(value) is int and value >= 0, "invalid ledger timestamp")
    return value


def _utc(timestamp):
    return datetime.fromtimestamp(timestamp / 1000, timezone.utc).isoformat()


def _chain_record(record, previous, previous_ms):
    now = _timestamp(record["server_time_ms"])
    _require(now > previous_ms and record["previous_sha256"] == previous,
             "ledger chronology or chain mismatch")
    body = {k: v for k, v in record.items() if k != "record_sha256"}
    _require(digest(body) == record["record_sha256"], "ledger record hash mismatch")


def _signal(record, signal, config):
    now = record["server_time_ms"]
    actual = digest({k: v for k, v in signal.items() if k != "snapshot_sha256"})
    _require(actual == signal["snapshot_sha256"] == record["signal_snapshot_sha256"],
             "signal content hash mismatch")
    _require(signal["server_time_ms"] == now and type(signal["server_time_ms"]) is int,
             "signal timestamp mismatch")
    _require(signal["fixed_rule"] == config["rule"] and signal["freeze_sha256"] == config["freeze_sha256"],
             "signal frozen rule mismatch")
    _require(signal["status"] == "signal_preview_only" and type(signal["orders_sent"]) is int
             and signal["orders_sent"] == 0 and type(signal["jev_calls"]) is int and signal["jev_calls"] == 0,
             "signal is not unpaid paper observation")
    _require(type(signal["funding_boundary_reconciled"]) is bool, "invalid funding boundary flag")
    _require(set(signal["source_code_sha256"]) == SIGNAL_CODE,
             "incomplete signal source code manifest")
    _require(all(config["code_sha256"].get(name) == sha
                 for name, sha in signal["source_code_sha256"].items()), "signal code mismatch")
    market = signal["market_observation"]
    _chain_record(market, market["previous_sha256"], -1)
    _require(market["server_time_ms"] == now and market["status"] == "market_observation_only"
             and type(market["orders_sent"]) is int and market["orders_sent"] == 0
             and market["paper_positions"] is None and market["paper_equity"] is None,
             "market observation mode or timestamp mismatch")


def _ranges(hours):
    result = []
    for hour in sorted(hours):
        if result and hour == result[-1]["last_hour_ms"] + HOUR_MS:
            result[-1]["last_hour_ms"] = hour
            result[-1]["count"] += 1
        else:
            result.append({"first_hour_ms": hour, "last_hour_ms": hour, "count": 1})
    return result


def _coverage(records, config):
    first, last = config["first_entry_ms"], records[-1]["server_time_ms"]
    slots = list(range(first, last // HOUR_MS * HOUR_MS + 1, HOUR_MS)) if last >= first else []
    closed = {hour for hour in slots if last >= hour + 300_000}
    processed = {row["last_processed_hour_ms"] for row in records if row["status"] == "processed_hour"}
    captured = {row["server_time_ms"] // HOUR_MS * HOUR_MS for row in records
                if row["server_time_ms"] >= first}
    missing = closed - processed
    days = {}
    for hour in slots:
        day = _utc(hour)[:10]
        row = days.setdefault(day, {"utc_date": day, "scheduled_hours_in_scope": 0,
                                    "closed_windows": 0, "processed_hours": 0, "missed_closed_hours": 0})
        row["scheduled_hours_in_scope"] += 1
        row["closed_windows"] += int(hour in closed)
        row["processed_hours"] += int(hour in processed)
        row["missed_closed_hours"] += int(hour in missing)
    return {"coverage_start_ms": first, "coverage_through_observation_ms": last,
            "scheduled_hours_in_scope": len(slots), "closed_hour_windows": len(closed),
            "processed_hour_count": len(processed), "missed_closed_hour_count": len(missing),
            "missed_closed_hour_ranges": _ranges(missing),
            "closed_hours_without_any_capture": len(closed - captured),
            "pending_window_hours": sorted(set(slots) - closed - processed),
            "days_with_missed_hours": sum(row["missed_closed_hours"] > 0 for row in days.values()),
            "complete_utc_days": sum(row["closed_windows"] == row["processed_hours"] == 24
                                     for row in days.values()),
            "days": list(days.values()),
            "method": "Windows before first entry are excluded; open windows are pending, not missing. No gap is filled."}


def _account_metrics(account):
    history, events = account["history"], account["events"]
    fills = [event for event in events if event["type"] == "paper_fill"]
    peak, drawdown = account["initial_equity"], 0.0
    for row in history:
        peak = max(peak, row["equity"])
        drawdown = max(drawdown, 1 - row["equity"] / peak)
    observed_duration = exposed_duration = 0.0
    intervals = 0
    for prior, current in zip(history, history[1:]):
        elapsed = current["timestamp_ms"] - prior["timestamp_ms"]
        if (current["timestamp_ms"] // HOUR_MS - prior["timestamp_ms"] // HOUR_MS == 1
                and elapsed <= 65 * 60_000):
            intervals += 1
            observed_duration += elapsed / HOUR_MS
            if prior["gross_notional"] > 0:
                exposed_duration += elapsed / HOUR_MS
    return {"performance_state": "paper_trades_observed" if fills else "pending_first_trade",
            "initial_equity": account["initial_equity"], "equity": account["equity"],
            "net_total_return": account["equity"] / account["initial_equity"] - 1,
            "cumulative_price_pnl": account["cumulative_price_pnl"], "funding_pnl": account["funding_pnl"],
            "fees": account["fees"], "fill_count": len(fills),
            "rebalance_fill_tick_count": len({event["timestamp_ms"] for event in fills
                                               if event["reason"] == "explicit_targets"}),
            "rebalance_evaluation_tick_count": sum(row["targets_provided"] for row in history),
            "stop_tick_count": len({event["timestamp_ms"] for event in events
                                    if event["type"] == "portfolio_trailing"}),
            "processed_observation_count": len(history),
            "exposed_observation_count": sum(row["gross_notional"] > 0 for row in history),
            "complete_adjacent_hour_intervals": intervals,
            "observed_duration_hours": observed_duration, "exposed_duration_hours": exposed_duration,
            "max_observed_drawdown": drawdown,
            "drawdown_method": "Post-cost processed equity marks including initial equity; intrahour drawdown is unknown.",
            "duration_method": "Only adjacent processed calendar hours, at most 65 minutes apart; exposure uses prior positions. First mark, gaps and pending intervals add no duration.",
            "open_positions": account["positions"],
            "first_fill_ms": min((event["timestamp_ms"] for event in fills), default=None),
            "last_account_mark_ms": account["last_ms"]}


def audit_records(records, snapshots):
    """Replay already-loaded records; disk provenance is additionally checked by report()."""
    _require(bool(records) and len(records) == len(snapshots), "missing ledger records or snapshots")
    config = records[0]["config"]
    first_ms = records[0]["server_time_ms"]
    _require(type(config["activated_ms"]) is int and config["activated_ms"] == first_ms,
             "activation timestamp mismatch")
    _require(type(config["first_entry_ms"]) is int and config["first_entry_ms"] == next_weekly_entry(first_ms),
             "first entry schedule mismatch")
    _require(config["orders_enabled"] is False and _same(config["variants"], {"reference": None, "trailing4": .04})
             and _same(config["initial_paper_usdt_per_account"], 10_000), "unexpected paper configuration")
    _require(set(config["code_sha256"]) == BASE_CODE | SIGNAL_CODE, "incomplete frozen code manifest")
    previous, previous_ms, accounts, last_hour = ZERO, -1, None, None
    for index, (record, signal) in enumerate(zip(records, snapshots)):
        _chain_record(record, previous, previous_ms)
        _require(_same(record["config"], config), "configuration changed within ledger")
        _require(type(record["orders_sent"]) is int and record["orders_sent"] == 0
                 and record["continuous_service_running"] is False, "unexpected paper execution flags")
        _signal(record, signal, config)
        now, error = record["server_time_ms"], None
        if index == 0:
            accounts = {name: initialize(now, config["initial_paper_usdt_per_account"], distance)
                        for name, distance in config["variants"].items()}
            status = "initialized_flat"
        else:
            timing = schedule(now, config["first_entry_ms"], last_hour)
            status = "outside_scheduled_window"
            if timing["due"]:
                status = "processed_hour"
                if not signal["funding_boundary_reconciled"]:
                    status, error = "blocked_accounting", "funding boundary not reconciled"
                else:
                    tick = {"server_time_ms": now, "accepted_quotes": signal["market_observation"]["accepted_quotes"],
                            "funding": signal["funding"]}
                    targets = signal["target_weights"] if timing["rebalance"] else None
                    try:
                        changed = {name: advance(account, tick, targets) for name, account in accounts.items()}
                    except ValueError as exc:
                        status, error = "blocked_accounting", str(exc)
                    else:
                        accounts, last_hour = changed, timing["hour_ms"]
        _require(record["status"] == status and record["error"] == error, "tick status or error differs from replay")
        _require(_same(record["last_processed_hour_ms"], last_hour), "processed hour differs from replay")
        _require(_same(record["accounts"], accounts), "account state differs from deterministic replay")
        previous, previous_ms = record["record_sha256"], now
    result = {"schema_version": 1, "mode": "paper", "orders_sent": 0, "jev_calls": 0,
              "ledger_head_sha256": previous, "ledger_head_time_ms": previous_ms,
              "ledger_head_utc": _utc(previous_ms), "capture_count": len(records),
              "status_counts": dict(Counter(row["status"] for row in records)),
              "first_entry_ms": config["first_entry_ms"], "first_entry_utc": _utc(config["first_entry_ms"]),
              "rule": config["rule"], "freeze_sha256": config["freeze_sha256"],
              "accounts": {name: _account_metrics(account) for name, account in accounts.items()},
              "coverage": _coverage(records, config),
              "verification": "Deterministic replay of the same frozen accounting; file provenance requires report().",
              "limits": ["Pre-entry cash is not evidence of trading consistency.",
                         "Hashes and replay do not independently validate market truth or model correctness.",
                         "Raw input hashes are checked; features and target weights are not independently rederived from those inputs.",
                         "Paper fills are assumptions, not executed orders; there is no terminal liquidation.",
                         "No annualization, Sharpe ratio, significance or readiness claim is made."]}
    result["processed_hour_count"] = result["coverage"]["processed_hour_count"]
    result["performance_state"] = ("pending_first_trade" if all(
        row["performance_state"] == "pending_first_trade" for row in result["accounts"].values())
        else "paper_trades_observed")
    return result


def _bounded(base, name, depth):
    _require(isinstance(name, str) and bool(name) and "\\" not in name and "\0" not in name,
             "invalid bounded file path")
    relative = PurePosixPath(name)
    _require(not relative.is_absolute() and not PureWindowsPath(name).is_absolute()
             and not PureWindowsPath(name).drive and len(relative.parts) == depth
             and all(part not in (".", "..") for part in relative.parts), "path outside allowed directory")
    target = (base / name).resolve()
    _require(target.is_relative_to(base.resolve()), "path outside allowed directory")
    return target


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(entries, base, depth):
    _require(isinstance(entries, list) and bool(entries), "missing raw source manifest")
    seen = set()
    for source in entries:
        path = _bounded(base, source["file"], depth)
        _require(path not in seen, "duplicate raw source file")
        seen.add(path)
        _require(_sha(path) == source["sha256"], "raw source hash mismatch")
    return len(entries)


def report(series="forward_paper_v2", *, project_root=ROOT, results_root=RESULTS):
    """Read and audit a stable ledger; never acquire data, alter state, or create locks."""
    _require(isinstance(series, str) and re.fullmatch(r"[a-z0-9_]+", series) is not None,
             "invalid explicit paper series name")
    project_root, results_root = Path(project_root), Path(results_root)
    root = _bounded(results_root, series, 1)
    lock, path = root / "tick.lock", root / "ledger.jsonl"
    _require(not lock.exists(), "paper tick in progress; retry after tick.lock clears")
    before_stat, before = path.stat(), path.read_bytes()
    _require(bool(before) and before.endswith(b"\n"), "ledger is empty or has an incomplete final line")
    records = read_chain(path)
    _require(bool(records), "ledger is empty")
    freeze_path = project_root / FREEZE_FILE
    freeze_bytes = freeze_path.read_bytes()
    freeze = json.loads(freeze_bytes.decode("utf-8"))
    freeze_sha = hashlib.sha256(freeze_bytes).hexdigest()
    config = records[0]["config"]
    _require(config["freeze_sha256"] == freeze_sha and config["rule"] == freeze["rule"],
             "current strategy freeze differs from paper series")
    code_root = project_root / "src/jev_trader"
    manifests = [config["code_sha256"], freeze["source_code_sha256"]]
    snapshots, raw_count = [], 0
    for record in records:
        saved = _bounded(root, record["signal_file"], 1)
        payload = saved.read_bytes()
        _require(hashlib.sha256(payload).hexdigest() == record["signal_file_sha256"],
                 "signal file hash mismatch")
        signal = json.loads(payload.decode("utf-8"))
        raw_count += _manifest(signal["sources"], results_root / "forward_signals", 2)
        _require(all(source["file"].startswith("raw/") for source in signal["market_observation"]["sources"]),
                 "market source path outside raw directory")
        raw_count += _manifest(signal["market_observation"]["sources"], results_root / "forward_observer", 3)
        manifests.append(signal["market_observation"]["source_code_sha256"])
        snapshots.append(signal)
    for manifest in manifests:
        _require(isinstance(manifest, dict) and bool(manifest), "missing source code manifest")
        for name, expected in manifest.items():
            _require(_sha(_bounded(code_root, name, 1)) == expected, "frozen source code hash mismatch: " + name)
    result = audit_records(records, snapshots)
    after, after_stat = path.read_bytes(), path.stat()
    _require(not lock.exists() and before == after and before_stat.st_size == after_stat.st_size
             and before_stat.st_mtime_ns == after_stat.st_mtime_ns
             and before_stat.st_ino == after_stat.st_ino,
             "ledger changed or paper tick started during report; retry")
    created_ms = time.time_ns() // 1_000_000
    result.update({"series": series, "ledger_file_sha256": hashlib.sha256(before).hexdigest(),
                   "report_created_ms": created_ms, "report_created_utc": _utc(created_ms),
                   "latest_observation_age_ms": created_ms - result["ledger_head_time_ms"],
                   "report_source_sha256": _sha(Path(__file__)),
                   "raw_source_references_verified": raw_count,
                   "verification": "Stable complete ledger; signal/raw/frozen-code hashes checked; every account transition reproduced with frozen accounting."})
    result["limits"].append("Coverage ends at the latest ledger observation; this report does not verify watcher liveness.")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series", default="forward_paper_v2", help="Existing paper series; report never modifies it")
    args = parser.parse_args()
    try:
        result = report(args.series)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, "Paper report rejected: " + str(exc) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
