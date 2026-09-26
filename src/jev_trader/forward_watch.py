"""Bounded local supervisor for public-data paper ticks; no autostart or orders."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .binance_data import HOUR_MS
from .cli import ROOT, RESULTS
from .forward_observer import read_chain

WINDOW_START_MS = 65_000
WINDOW_END_MS = 290_000  # Ten seconds before the paper deadline.


def next_slot(now_ms, last_attempted_hour=None):
    hour = now_ms // HOUR_MS * HOUR_MS
    if hour == last_attempted_hour or now_ms >= hour + WINDOW_END_MS:
        hour += HOUR_MS
    return {"hour_ms": hour, "start_ms": max(now_ms, hour + WINDOW_START_MS),
            "deadline_ms": hour + WINDOW_END_MS}


def classify_tick(previous, current, hour_ms, returncode, preflight=False):
    if not current or previous and current["record_sha256"] == previous["record_sha256"]:
        return "failed_child" if returncode != 0 else "no_new_paper_record"
    if (current["status"] == "processed_hour" and current["last_processed_hour_ms"] == hour_ms
            and current["server_time_ms"] // HOUR_MS * HOUR_MS == hour_ms):
        return "processed_hour" if returncode == 0 else "processed_hour_with_child_error"
    if returncode != 0:
        return "failed_child"
    if current["status"] == "blocked_accounting":
        return "blocked_accounting"
    if preflight:
        return "preflight_observed"
    if current["server_time_ms"] < current["config"]["first_entry_ms"]:
        return "pre_entry_observed"
    return "not_processed"


def latest(series):
    rows = read_chain(RESULTS / series / "ledger.jsonl")
    if not rows:
        raise ValueError("initialize the explicit paper series before starting a watcher")
    row = rows[-1]
    if row["config"]["orders_enabled"] is not False or any(a["live_orders_enabled"] for a in row["accounts"].values()):
        raise ValueError("watcher accepts simulation-only accounts")
    for name, expected in row["config"]["code_sha256"].items():
        source = ROOT / "src/jev_trader" / name
        if source.resolve().parent != (ROOT / "src/jev_trader").resolve():
            raise ValueError("invalid frozen source path")
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError("frozen paper code changed; watcher halted")
    return row


def held(row):
    return any(account["positions"] for account in row["accounts"].values())


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def monitor_child(child, deadline_ms, stop_reason, on_started, on_poll):
    """Never release a spawned child on callback failure or interruption."""
    forced = None
    try:
        on_started(child.pid)
        while child.poll() is None:
            forced = stop_reason()
            if forced is None and time.time_ns() // 1_000_000 >= deadline_ms:
                forced = "child_deadline_exceeded"
            if forced:
                child.kill()
                child.wait(timeout=15)
                break
            on_poll(child.pid)
            time.sleep(1)
        return child.returncode, forced
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=15)


def run(series="forward_paper_v2", hours=72.0):
    if not series or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in series):
        raise ValueError("invalid explicit series")
    if not 0 < hours <= 72:
        raise ValueError("bounded duration must be greater than zero and at most 72 hours")
    initial = latest(series)
    root = RESULTS / series
    stop_path, lock_path = root / "watch.stop", root / "watch.lock"
    if stop_path.exists():
        raise ValueError("stop request exists; refusing to start")
    pid = os.getpid()
    descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(descriptor, str(pid).encode())
    os.close(descriptor)
    start_ms = time.time_ns() // 1_000_000
    start_mono = time.monotonic()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    folder = root / "watch_runs" / run_id
    folder.mkdir(parents=True)
    status_path = root / "watch_status.json"
    source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    state = {"run_id": run_id, "pid": pid, "series": series, "started_ms": start_ms,
             "expires_ms": start_ms + int(hours * HOUR_MS), "max_hours": hours,
             "watcher_source_sha256": source_hash, "initial_paper_record_sha256": initial["record_sha256"],
             "phase": "starting", "child_pid": None, "processed_hours": [], "missed_hours": [],
             "attempts": 0, "orders_enabled": False, "jev_calls_enabled": False,
             "autostart_installed": False, "run_directory": str(folder)}
    active_child = None

    def event(kind, **details):
        with (folder / "events.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps({"local_time_ms": time.time_ns() // 1_000_000, "type": kind, **details}, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def heartbeat(phase, **details):
        state.update(details)
        state["phase"] = phase
        state["heartbeat_ms"] = time.time_ns() // 1_000_000
        atomic_json(status_path, state)

    def stopped():
        if stop_path.exists():
            return "stop_requested"
        if time.monotonic() - start_mono >= hours * 3600:
            return "expired"
        if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != source_hash:
            return "watcher_source_changed"
        wall_elapsed = time.time_ns() / 1_000_000 - start_ms
        if abs(wall_elapsed - (time.monotonic() - start_mono) * 1000) > 5000:
            return "local_clock_jump"
        return None

    def execute(hour_ms, deadline_ms, preflight=False):
        nonlocal active_child
        before = latest(series)
        if (root / "tick.lock").exists() or (RESULTS / "forward_observer/capture.lock").exists():
            return "existing_child_lock"
        state["attempts"] += 1
        prefix = f"{state['attempts']:04d}"
        args = [sys.executable, "-m", "jev_trader.forward_paper", "--series", series]
        with (folder / (prefix + ".stdout.log")).open("wb") as out, (folder / (prefix + ".stderr.log")).open("wb") as err:
            if (reason := stopped()) or time.time_ns() // 1_000_000 >= deadline_ms:
                return "forced_stop:" + (reason or "deadline_before_start")
            child = active_child = subprocess.Popen(args, cwd=ROOT, stdout=out, stderr=err,
                                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            def started(child_pid):
                heartbeat("acquiring", child_pid=child_pid, attempted_hour_ms=hour_ms)
                event("child_started", child_pid=child_pid, args=args, deadline_ms=deadline_ms, preflight=preflight)
            _, forced = monitor_child(child, deadline_ms, stopped, started,
                                      lambda child_pid: heartbeat("acquiring", child_pid=child_pid))
            active_child = None
            heartbeat("observed", child_pid=None)
            if forced:
                event("child_forcibly_stopped", reason=forced, returncode=child.returncode,
                      locks_preserved=True, ledger_requires_review=True)
                return "forced_stop:" + forced
        after = latest(series)
        outcome = classify_tick(before, after, hour_ms, child.returncode, preflight)
        state["last_paper_record_sha256"] = after["record_sha256"]
        state["last_paper_status"] = after["status"]
        state["last_paper_error"] = after.get("error")
        event("child_finished", outcome=outcome, returncode=child.returncode,
              paper_record_sha256=after["record_sha256"], paper_status=after["status"], paper_error=after.get("error"))
        return outcome

    try:
        heartbeat("starting")
        event("watch_started", **state)
        # A first real acquisition establishes that the current environment can
        # execute the frozen pipeline; it is not counted as a scheduled hour.
        now_ms = time.time_ns() // 1_000_000
        slot = next_slot(now_ms)
        deadline = min(now_ms + 120_000, slot["deadline_ms"])
        outcome = execute(now_ms // HOUR_MS * HOUR_MS, deadline, preflight=True)
        state["preflight_outcome"] = outcome
        if outcome.startswith("forced_stop:") or outcome == "existing_child_lock":
            raise RuntimeError(outcome)
        processed_outcomes = ("processed_hour", "processed_hour_with_child_error")
        last_hour = now_ms // HOUR_MS * HOUR_MS if outcome in processed_outcomes else None
        if last_hour is not None:
            state["processed_hours"].append(last_hour)
        pending_slot = None
        while not (reason := stopped()):
            now_ms = time.time_ns() // 1_000_000
            if pending_slot is None:
                pending_slot = next_slot(now_ms, last_hour)
            slot = pending_slot
            if now_ms >= slot["deadline_ms"]:
                state["missed_hours"].append(slot["hour_ms"])
                event("window_elapsed_without_processing", hour_ms=slot["hour_ms"])
                if held(latest(series)):
                    raise RuntimeError("missed_hour_with_open_positions; observation continuity requires review")
                last_hour, pending_slot = slot["hour_ms"], None
                continue
            heartbeat("waiting", next_window_start_ms=slot["start_ms"], next_window_deadline_ms=slot["deadline_ms"])
            if now_ms < slot["start_ms"]:
                time.sleep(min(15, (slot["start_ms"] - now_ms) / 1000))
                continue
            outcome = execute(slot["hour_ms"], min(slot["deadline_ms"], now_ms + 120_000))
            if outcome.startswith("forced_stop:") or outcome == "existing_child_lock":
                raise RuntimeError(outcome)
            if outcome in (*processed_outcomes, "pre_entry_observed"):
                if outcome in processed_outcomes:
                    state["processed_hours"].append(slot["hour_ms"])
                last_hour, pending_slot = slot["hour_ms"], None
                continue
            if time.time_ns() // 1_000_000 + 45_000 < slot["deadline_ms"]:
                heartbeat("retry_wait", last_outcome=outcome)
                time.sleep(15)
                continue
            state["missed_hours"].append(slot["hour_ms"])
            event("hour_not_processed", hour_ms=slot["hour_ms"], outcome=outcome)
            if held(latest(series)):
                raise RuntimeError("missed_hour_with_open_positions; observation continuity requires review")
            last_hour, pending_slot = slot["hour_ms"], None
        heartbeat(reason, child_pid=None)
        event("watch_ended", reason=reason)
    except BaseException as exc:
        heartbeat("halted", error=str(exc), child_pid=active_child.pid if active_child and active_child.poll() is None else None)
        event("watch_halted", error=str(exc))
        raise
    finally:
        # A stale lock belongs to a failed supervisor and needs explicit review.
        # Only this live owner's normal exit removes its own singleton lock.
        if active_child is not None and active_child.poll() is None:
            active_child.kill()
            active_child.wait(timeout=15)
        if lock_path.exists() and lock_path.read_text() == str(pid):
            lock_path.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--series", default="forward_paper_v2")
    parser.add_argument("--hours", type=float, default=72)
    args = parser.parse_args()
    run(args.series, args.hours)
