"""Prospective, paper-only C18 collector for Binance USD-M perpetuals."""

from __future__ import annotations

import hashlib
import json
import math
import os
import pickle
import sqlite3
import sys
import time
import uuid
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import sklearn

from . import lowvol_hgb_account as account
from . import lowvol_hgb_freeze as freeze
from .binance_data import Bar, _read_url, utc_ms
from .broad_data import CACHE
from .broad_prediction import FIELDS
from .broad_research import DAY_MS, features, sign, target_weights
from .cli import ROOT
from .derivatives_data import Funding
from .forward_observer import validate_quote
from .forward_signals import feature_cutoff, merge_closed_bars, merge_funding


OUTPUT = ROOT / "research/results/cycle18_lowvol_hgb_forward"
PAPER = OUTPUT / "paper"
DATABASE = PAPER / "paper.sqlite3"
CONFIG_PATH = PAPER / "config.json"
REPORT_PATH = PAPER / "latest_report.json"
MODEL_PATH = OUTPUT / "model/model.pkl"
TRAINING_PATH = OUTPUT / "model_training.json"
PROTOCOL_PATH = ROOT / "research/docs/CICLO18_META_FILTRO_HGB_BAIXA_VOLATILIDADE_FORWARD_PROTOCOLO_2026-09-29.md"
API = "https://fapi.binance.com/fapi/v1/"
ALLOWED_ENDPOINTS = {"time", "exchangeInfo", "klines", "fundingRate", "ticker/bookTicker"}
ZERO_SHA256 = "0" * 64
INITIAL_EQUITY = 10_000.0
SEED_DAILY_DAYS = 240
SEED_FUNDING_DAYS = 45
KEEP_FUNDING_DAYS = 45
FIRST_DECISION_MS = utc_ms("2026-10-05T01:00:00Z")
WEEK_MS = 7 * DAY_MS
OBSERVATION_INTERVAL_MS = 15 * 60_000
BOOTSTRAP_REPLICATES = 2_000
EXPECTED_TRAINING_METADATA_SHA256 = "55f315df0cb78b49b3b3d820eb43535938dce18112bc23caaaaa95064ad446dd"
EXPECTED_MODEL_SHA256 = "13c1b2dbd59a56d29ed172a5abb390159da0b6528989993b02641c1e7f9ad606"
EXPECTED_PROTOCOL_SHA256 = "8cf48c4b423ffd91026e69fbf19fc68f5da05ce4de37803bfe87181bff7778b4"

CODE_FILES = (
    "lowvol_hgb_paper.py",
    "lowvol_hgb_account.py",
    "lowvol_hgb_freeze.py",
    "forward_signals.py",
    "forward_observer.py",
    "broad_research.py",
    "broad_prediction.py",
    "market_state.py",
    "binance_data.py",
    "derivatives_data.py",
)


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json_exclusive(path: Path, value: dict) -> bytes:
    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return raw


def _atomic_json(path: Path, value: dict) -> None:
    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    temporary = path.with_name(path.name + ".part-" + uuid.uuid4().hex)
    with temporary.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


@contextmanager
def _exclusive_paper_tick_lock(path: Path | None = None):
    """Serialize local C18 ticks; overlapping scheduled/manual runs skip."""
    PAPER.mkdir(parents=True, exist_ok=True)
    lock_path = path or (PAPER / ".paper_tick.lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    backend = None
    try:
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"0")
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt

            backend = msvcrt
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                acquired = True
            except OSError:
                acquired = False
        else:
            import fcntl

            backend = fcntl
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                acquired = False
        yield acquired
    finally:
        if acquired:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.name == "nt":
                backend.locking(descriptor, backend.LK_UNLCK, 1)
            else:
                backend.flock(descriptor, backend.LOCK_UN)
        os.close(descriptor)


@contextmanager
def _exclusive_paper_tick_lock(path: Path | None = None):
    """Serialize local C18 ticks; overlapping scheduled/manual runs skip."""
    PAPER.mkdir(parents=True, exist_ok=True)
    lock_path = path or (PAPER / ".paper_tick.lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    backend = None
    try:
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"0")
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt

            backend = msvcrt
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                acquired = True
            except OSError:
                acquired = False
        else:
            import fcntl

            backend = fcntl
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                acquired = False
        yield acquired
    finally:
        if acquired:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.name == "nt":
                backend.locking(descriptor, backend.LK_UNLCK, 1)
            else:
                backend.flock(descriptor, backend.LOCK_UN)
        os.close(descriptor)


def _connect() -> sqlite3.Connection:
    PAPER.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE, timeout=30, isolation_level=None)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS daily_klines (
            symbol TEXT NOT NULL,
            open_ms INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (symbol, open_ms)
        );
        CREATE TABLE IF NOT EXISTS funding_events (
            symbol TEXT NOT NULL,
            timestamp_ms INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (symbol, timestamp_ms)
        );
        CREATE TABLE IF NOT EXISTS records (
            sequence INTEGER PRIMARY KEY,
            payload_json TEXT NOT NULL,
            record_sha256 TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS account_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            base_json TEXT NOT NULL,
            stress_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS equity_points (
            sequence INTEGER PRIMARY KEY REFERENCES records(sequence),
            timestamp_ms INTEGER NOT NULL,
            base_equity REAL NOT NULL,
            stress_equity REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS decision_attempts (
            feature_cutoff_ms INTEGER PRIMARY KEY,
            attempted_server_ms INTEGER NOT NULL,
            reservation_record_sha256 TEXT,
            completed_record_sha256 TEXT
        );
    """)
    return connection


def _training_metadata() -> dict:
    if _sha_file(TRAINING_PATH) != EXPECTED_TRAINING_METADATA_SHA256:
        raise ValueError("C18 frozen model metadata hash mismatch")
    metadata = json.loads(TRAINING_PATH.read_text(encoding="utf-8"))
    if (metadata.get("experiment_id") != "C18-lowvol-hgb-forward-static-2026-09-29"
            or metadata.get("orders_enabled") is not False
            or metadata.get("real_orders_sent") is not False
            or metadata.get("prospective_scores_computed") is not False
            or metadata.get("forward_market_observations_collected") is not False
            or metadata.get("model", {}).get("gpu_training_performed") is not False
            or metadata.get("model", {}).get("prediction_threshold") != 0.70
            or metadata.get("scikit_learn_version") != sklearn.__version__
            or metadata.get("model_sha256") != EXPECTED_MODEL_SHA256
            or _sha_file(PROTOCOL_PATH) != EXPECTED_PROTOCOL_SHA256
            or metadata.get("features") != [*FIELDS, "direction"]
            or metadata.get("training", {}).get("mature_episode_count") != 105
            or metadata.get("training", {}).get("class_counts") != {"0": 44, "1": 61}):
        raise ValueError("C18 frozen model metadata is not the registered paper-only model")
    if _sha_file(MODEL_PATH) != metadata.get("model_sha256"):
        raise ValueError("C18 frozen model hash mismatch")
    for relative, expected in metadata["input_sha256"].items():
        if _sha_file(ROOT / relative) != expected:
            raise ValueError(f"C18 historical training input changed: {relative}")
    if _sha_file(PROTOCOL_PATH) != metadata["input_sha256"][
            "research/docs/CICLO18_META_FILTRO_HGB_BAIXA_VOLATILIDADE_FORWARD_PROTOCOLO_2026-09-29.md"]:
        raise ValueError("C18 protocol changed after the frozen model fit")
    return metadata


def _make_config(metadata: dict) -> dict:
    cohort = json.loads((CACHE / "cohort.json").read_text(encoding="utf-8"))["selected"]
    if _sha_file(CACHE / "cohort.json") != metadata["input_sha256"]["data/binance/broad/cohort.json"]:
        raise ValueError("C18 fixed cohort differs from the frozen training input")
    code_hashes = {name: _sha_file(ROOT / "src/jev_trader" / name) for name in CODE_FILES}
    return {
        "schema_version": 1,
        "experiment_id": metadata["experiment_id"],
        "market": "Binance USD-M perpetuals",
        "cohort": cohort,
        "cohort_sha256": metadata["input_sha256"]["data/binance/broad/cohort.json"],
        "protocol_sha256": _sha_file(PROTOCOL_PATH),
        "training_metadata_sha256": _sha_file(TRAINING_PATH),
        "model_sha256": metadata["model_sha256"],
        "training_archive_manifest_sha256": metadata["source_archive_manifest_sha256"],
        "training_input_sha256": metadata["input_sha256"],
        "base_rule": "low_volatility30_betahedged",
        "model_type": "HistGradientBoostingClassifier",
        "model_features": [*FIELDS, "direction"],
        "prediction_threshold": 0.70,
        "score_is_calibrated_probability": False,
        "entry_exit_abstention": {
            "entry": "new base-rule direction only when static HGB win score is at least 0.70",
            "hold": "existing position continues only while base-rule direction remains unchanged",
            "exit": "close or reverse on the next valid weekly rebalance when base direction changes or disappears",
            "abstain": "outside the five-minute UTC window, incomplete/stale inputs, unavailable quotes/funding, or fewer than both long and short accepted sides",
            "sizing": "equally distribute 25 percent gross per side; cash unless both sides exist",
        },
        "model_compute": "CPU",
        "first_decision_utc": "2026-10-05T01:00:00Z",
        "weekly_decision_window_utc": "Monday 01:00:00 through 01:04:59",
        "costs": {
            "base_fee_per_side": account.BASE_FEE_RATE,
            "base_slippage_per_side": account.BASE_SLIPPAGE,
            "stress_fee_per_side": account.STRESS_FEE_RATE,
            "stress_slippage_per_side": account.STRESS_SLIPPAGE,
        },
        "maximum_gross_exposure": account.MAX_GROSS,
        "initial_paper_equity_usd": INITIAL_EQUITY,
        "orders_enabled": False,
        "code_sha256": code_hashes,
    }


def _verify_chain(connection: sqlite3.Connection, *, full: bool = True) -> dict | None:
    count, maximum = connection.execute("SELECT COUNT(*),COALESCE(MAX(sequence),0) FROM records").fetchone()
    if not count:
        return None
    if count != maximum:
        raise ValueError("C18 paper record sequence has a gap")
    if full:
        rows = connection.execute(
            "SELECT sequence,payload_json,record_sha256 FROM records ORDER BY sequence").fetchall()
    else:
        rows = connection.execute(
            "SELECT sequence,payload_json,record_sha256 FROM records ORDER BY sequence DESC LIMIT 2").fetchall()
        rows.reverse()
    previous = ZERO_SHA256 if rows[0][0] == 1 else None
    expected_sequence = rows[0][0]
    last = None
    for sequence, payload_json, record_sha256 in rows:
        payload = json.loads(payload_json)
        if (sequence != expected_sequence or payload.get("sequence") != sequence
                or (previous is not None and payload.get("previous_sha256") != previous)
                or _digest(payload) != record_sha256):
            raise ValueError("C18 paper record hash chain is invalid")
        previous = record_sha256
        expected_sequence += 1
        last = payload
    if last and last.get("base_state_sha256"):
        stored = connection.execute("SELECT base_json, stress_json FROM account_state WHERE id=1").fetchone()
        if stored is None or _digest(json.loads(stored[0])) != last["base_state_sha256"]:
            raise ValueError("C18 base account state does not match the hash-chain head")
        if _digest(json.loads(stored[1])) != last["stress_state_sha256"]:
            raise ValueError("C18 stress account state does not match the hash-chain head")
    return last


def _verify_public_receipts(connection: sqlite3.Connection, *, full: bool = True) -> None:
    root = PAPER.resolve()
    query = ("SELECT payload_json FROM records ORDER BY sequence" if full else
             "SELECT payload_json FROM records ORDER BY sequence DESC LIMIT 1")
    for payload_json, in connection.execute(query):
        payload = json.loads(payload_json)
        for receipt in payload.get("public_request_receipts", []):
            path = (PAPER / receipt["file"]).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise ValueError("C18 public response receipt points outside its paper archive or is missing")
            if _sha_file(path) != receipt["sha256"]:
                raise ValueError("C18 public response payload no longer matches its registered hash")


def _append_record(connection: sqlite3.Connection, body: dict, *, base_state: dict | None = None,
                   stress_state: dict | None = None, equity_point: bool = False) -> dict:
    last_row = connection.execute(
        "SELECT sequence, record_sha256, payload_json FROM records ORDER BY sequence DESC LIMIT 1").fetchone()
    sequence = (last_row[0] + 1) if last_row else 1
    previous = last_row[1] if last_row else ZERO_SHA256
    prior_time = json.loads(last_row[2]).get("server_time_ms") if last_row else None
    if (prior_time is not None and body.get("server_time_ms") is not None
            and body["server_time_ms"] <= prior_time):
        raise ValueError("C18 paper record server timestamps are not strictly increasing")
    payload = {**body, "sequence": sequence, "previous_sha256": previous}
    if base_state is not None or stress_state is not None:
        if base_state is None or stress_state is None:
            raise ValueError("both C18 account states must advance together")
        payload["base_state_sha256"] = _digest(base_state)
        payload["stress_state_sha256"] = _digest(stress_state)
    record_sha256 = _digest(payload)
    encoded = _json(payload)
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute("INSERT INTO records(sequence,payload_json,record_sha256) VALUES(?,?,?)",
                           (sequence, encoded, record_sha256))
        if base_state is not None:
            connection.execute(
                "INSERT INTO account_state(id,base_json,stress_json) VALUES(1,?,?) "
                "ON CONFLICT(id) DO UPDATE SET base_json=excluded.base_json,stress_json=excluded.stress_json",
                (_json(base_state), _json(stress_state)))
        if equity_point:
            connection.execute("INSERT INTO equity_points VALUES(?,?,?,?)",
                               (sequence, body["server_time_ms"], base_state["equity"], stress_state["equity"]))
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    return {**payload, "record_sha256": record_sha256}


def _config_without_code_hash(config: dict) -> dict:
    return {key: value for key, value in config.items() if key != "code_sha256"}


def _ensure_runtime_code_amendment(connection: sqlite3.Connection, stored_config: dict,
                                   expected_config: dict, config_sha256: str) -> str | None:
    stored_code = stored_config.get("code_sha256")
    current_code = expected_config["code_sha256"]
    if stored_code == current_code:
        connection.execute(
            "INSERT INTO metadata(key,value) VALUES('runtime_code_sha256',?) "
            "ON CONFLICT(key) DO NOTHING", (_json(current_code),))
        amendment_row = connection.execute(
            "SELECT value FROM metadata WHERE key='runtime_code_amendment_record_sha256'"
        ).fetchone()
        return json.loads(amendment_row[0]) if amendment_row else None

    row = connection.execute("SELECT value FROM metadata WHERE key='runtime_code_sha256'").fetchone()
    previous_code = json.loads(row[0]) if row else stored_code
    if previous_code == current_code:
        amendment_row = connection.execute(
            "SELECT value FROM metadata WHERE key='runtime_code_amendment_record_sha256'"
        ).fetchone()
        return json.loads(amendment_row[0]) if amendment_row else None
    amendment_row = connection.execute(
        "SELECT payload_json FROM records ORDER BY sequence DESC LIMIT 1").fetchone()
    last_record = json.loads(amendment_row[0]) if amendment_row else {}
    if (not row and last_record.get("kind") == "code_amendment"
            and last_record.get("code_sha256") == current_code):
        connection.execute("INSERT INTO metadata(key,value) VALUES('runtime_code_sha256',?)",
                           (_json(current_code),))
        connection.execute(
            "INSERT INTO metadata(key,value) VALUES('runtime_code_amendment_record_sha256',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (_json(last_record.get("record_sha256")),),
        )
        return last_record.get("record_sha256")

    effective_config = {**expected_config}
    effective_raw = (json.dumps(effective_config, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    state_row = connection.execute("SELECT base_json,stress_json FROM account_state WHERE id=1").fetchone()
    base_state = json.loads(state_row[0]) if state_row else None
    stress_state = json.loads(state_row[1]) if state_row else None
    saved = _append_record(
        connection,
        {
            "kind": "code_amendment",
            "status": "operational_correction_without_economic_change",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "registered_config_sha256": config_sha256,
            "effective_config_sha256": hashlib.sha256(effective_raw).hexdigest(),
            "previous_code_sha256": previous_code,
            "code_sha256": current_code,
            "economic_config_unchanged": True,
            "model_sha256": expected_config["model_sha256"],
            "prediction_threshold": expected_config["prediction_threshold"],
            "orders_enabled": False,
            "real_orders_sent": False,
        },
        base_state=base_state,
        stress_state=stress_state,
    )
    connection.execute(
        "INSERT INTO metadata(key,value) VALUES('runtime_code_sha256',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (_json(current_code),))
    connection.execute(
        "INSERT INTO metadata(key,value) VALUES('runtime_code_amendment_record_sha256',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (_json(saved["record_sha256"]),),
    )
    return saved["record_sha256"]


def _blocked(connection: sqlite3.Connection, body: dict, base_state: dict,
             stress_state: dict) -> dict:
    saved = _append_record(connection, body, base_state=base_state, stress_state=stress_state)
    result = {
        **body,
        "record_sha256": saved["record_sha256"],
        "orders_sent": False,
        "operational_status": _operational_status(
            base_state, int(body.get("server_time_ms", base_state["last_ms"])),
            status="blocked", blocking_reason=body.get("status", "blocked_observation"),
        ),
    }
    _atomic_json(REPORT_PATH, result)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return result


def _reserve_weekly_decision(connection: sqlite3.Connection, *, feature_cutoff_ms: int,
                             attempted_server_ms: int, base_state: dict,
                             stress_state: dict) -> tuple[bool, str | None]:
    connection.execute("BEGIN IMMEDIATE")
    try:
        cursor = connection.execute(
            "INSERT OR IGNORE INTO decision_attempts(feature_cutoff_ms,attempted_server_ms) VALUES(?,?)",
            (feature_cutoff_ms, attempted_server_ms),
        )
        reserved = cursor.rowcount == 1
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    if not reserved:
        return False, None
    record = _append_record(
        connection,
        {
            "kind": "weekly_decision_reservation",
            "status": "inference_reserved_once_for_frozen_weekly_cutoff",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "feature_cutoff_ms": feature_cutoff_ms,
            "attempted_server_ms": attempted_server_ms,
            "orders_enabled": False,
        },
        base_state=base_state,
        stress_state=stress_state,
    )
    connection.execute(
        "UPDATE decision_attempts SET reservation_record_sha256=? WHERE feature_cutoff_ms=?",
        (record["record_sha256"], feature_cutoff_ms),
    )
    return True, record["record_sha256"]


def _next_weekly_decision_utc(server_ms: int) -> str:
    current = datetime.fromtimestamp(server_ms / 1000, timezone.utc)
    days_ahead = (0 - current.weekday()) % 7
    candidate = (current + timedelta(days=days_ahead)).replace(hour=1, minute=0, second=0, microsecond=0)
    first_decision = datetime.fromtimestamp(FIRST_DECISION_MS / 1000, timezone.utc)
    candidate = max(candidate, first_decision)
    if candidate <= current:
        candidate += timedelta(days=7)
    return candidate.isoformat().replace("+00:00", "Z")


def _operational_status(base_state: dict, server_ms: int, *, status: str,
                        blocking_reason: str | None = None) -> dict:
    positions = []
    for symbol, position in sorted(base_state.get("positions", {}).items()):
        quantity = float(position["quantity"])
        positions.append({
            "symbol": symbol,
            "direction": "long" if quantity > 0 else "short",
            "quantity": quantity,
            "mark_price": float(position["mark_price"]),
        })
    return {
        "status": status,
        "last_observation_server_time_ms": server_ms,
        "last_observation_utc": datetime.fromtimestamp(server_ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z"),
        "last_accounted_server_time_ms": int(base_state["last_ms"]),
        "heartbeat_age_ms_at_write": max(0, server_ms - int(base_state["last_ms"])),
        "observation_interval_ms": OBSERVATION_INTERVAL_MS,
        "next_weekly_decision_utc": _next_weekly_decision_utc(server_ms),
        "open_positions": positions,
        "blocking_reason": blocking_reason,
        "orders_enabled": False,
    }


def _setup(connection: sqlite3.Connection) -> tuple[dict, dict]:
    metadata = _training_metadata()
    expected_config = _make_config(metadata)
    if CONFIG_PATH.exists():
        stored_raw = CONFIG_PATH.read_bytes()
        stored_config = json.loads(stored_raw.decode("utf-8", errors="strict"))
        if _config_without_code_hash(stored_config) != _config_without_code_hash(expected_config):
            raise ValueError("C18 immutable economic paper configuration changed")
    else:
        stored_config = expected_config
        stored_raw = (json.dumps(stored_config, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
        _write_json_exclusive(CONFIG_PATH, expected_config)
    config_sha256 = hashlib.sha256(stored_raw).hexdigest()
    last = _verify_chain(connection, full=False)
    if last is None:
        _append_record(connection, {
            "kind": "registration",
            "status": "frozen_before_C18_forward_inference",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "config_sha256": config_sha256,
            "model_sha256": metadata["model_sha256"],
            "training_metadata_sha256": _sha_file(TRAINING_PATH),
            "protocol_sha256": _sha_file(PROTOCOL_PATH),
            "code_sha256": stored_config["code_sha256"],
            "input_sha256": metadata["input_sha256"],
            "orders_enabled": False,
            "real_orders_sent": False,
        })
        last = _verify_chain(connection, full=False)
    registration = connection.execute("SELECT payload_json FROM records WHERE sequence=1").fetchone()
    if not registration:
        raise ValueError("C18 paper ledger has no preregistration record")
    registered = json.loads(registration[0])
    if (registered.get("kind") != "registration"
            or registered.get("config_sha256") != config_sha256
            or registered.get("code_sha256") != stored_config.get("code_sha256")):
        raise ValueError("C18 paper registration does not match its immutable configuration")
    amendment_sha256 = _ensure_runtime_code_amendment(
        connection, stored_config, expected_config, config_sha256,
    )
    _verify_chain(connection, full=False)
    effective_config = {
        **expected_config,
        "registered_config_sha256": config_sha256,
        "effective_config_sha256": hashlib.sha256(
            (json.dumps(expected_config, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
        ).hexdigest(),
        "code_amendment_record_sha256": amendment_sha256,
    }
    return metadata, effective_config


def _verify_config_record(connection: sqlite3.Connection) -> dict:
    if not CONFIG_PATH.exists():
        raise ValueError("C18 frozen paper configuration is missing")
    metadata = _training_metadata()
    expected = _make_config(metadata)
    stored_raw = CONFIG_PATH.read_bytes()
    stored = json.loads(stored_raw.decode("utf-8", errors="strict"))
    if _config_without_code_hash(stored) != _config_without_code_hash(expected):
        raise ValueError("C18 frozen economic paper configuration changed")
    first = connection.execute("SELECT payload_json FROM records WHERE sequence=1").fetchone()
    if first is None:
        raise ValueError("C18 paper ledger has no preregistration record")
    registration = json.loads(first[0])
    if (registration.get("kind") != "registration"
            or registration.get("config_sha256") != hashlib.sha256(stored_raw).hexdigest()
            or registration.get("code_sha256") != stored.get("code_sha256")):
        raise ValueError("C18 paper registration differs from its frozen configuration")
    current_code = registration["code_sha256"]
    for payload_json, in connection.execute("SELECT payload_json FROM records ORDER BY sequence DESC"):
        payload = json.loads(payload_json)
        if payload.get("kind") == "code_amendment":
            current_code = payload.get("code_sha256")
            break
    effective_raw = (json.dumps(expected, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    return {
        "status": "registered" if current_code == expected["code_sha256"] else "pending_append_only_code_amendment",
        "registered_config_sha256": hashlib.sha256(stored_raw).hexdigest(),
        "effective_config_sha256": hashlib.sha256(effective_raw).hexdigest(),
        "registered_code_sha256": current_code,
        "current_code_sha256": expected["code_sha256"],
    }


def _seed_local_data(connection: sqlite3.Connection, active: list[str], server_ms: int) -> dict:
    existing = connection.execute("SELECT COUNT(*) FROM daily_klines").fetchone()[0]
    if existing:
        return {"status": "already_seeded", "daily_rows": existing}
    data, source_manifest_sha256, source_rows = freeze._load_frozen_economic_data()
    if source_manifest_sha256 != freeze.EXPECTED_SOURCE_MANIFEST_SHA256:
        raise ValueError("C18 local historical seed differs from the frozen source manifest")
    cutoff = feature_cutoff(server_ms)
    daily_start = cutoff - SEED_DAILY_DAYS * DAY_MS
    funding_start = cutoff - SEED_FUNDING_DAYS * DAY_MS
    daily_counts, funding_counts = {}, {}
    connection.execute("BEGIN IMMEDIATE")
    try:
        for symbol in active:
            bars = [bar for bar in data["klines"][symbol]
                    if daily_start <= bar.open_ms < cutoff]
            events = [event for event in data["fundingRate"][symbol]
                      if funding_start <= event.timestamp_ms <= server_ms]
            if len(bars) < 201 or any(b.open_ms - a.open_ms != DAY_MS for a, b in zip(bars, bars[1:])):
                raise ValueError(f"C18 historical seed lacks a continuous feature window for {symbol}")
            for bar in bars:
                connection.execute("INSERT INTO daily_klines VALUES(?,?,?)",
                                   (symbol, bar.open_ms, _json(asdict(bar))))
            for event in events:
                payload = {"timestamp_ms": event.timestamp_ms, "interval_hours": event.interval_hours,
                           "rate": event.rate, "mark_price": None}
                connection.execute("INSERT INTO funding_events VALUES(?,?,?)",
                                   (symbol, event.timestamp_ms, _json(payload)))
            daily_counts[symbol] = len(bars)
            funding_counts[symbol] = len(events)
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    return {
        "status": "seeded_from_checksum_pinned_local_archives",
        "seed_cutoff_ms": cutoff,
        "source_archive_manifest_sha256": source_manifest_sha256,
        "source_archive_files_read": source_rows,
        "daily_rows_by_symbol": daily_counts,
        "funding_rate_rows_by_symbol": funding_counts,
        "historical_funding_mark_price_available": False,
        "prospective_funding_mark_prices_required": True,
        "network_calls": False,
        "shared_cache_writes": False,
    }


def _raw_request(endpoint: str, params: dict, label: str, raw_dir: Path) -> tuple[object, dict]:
    if endpoint not in ALLOWED_ENDPOINTS:
        raise ValueError("C18 permits only allowlisted public USD-M GET endpoints")
    url = API + endpoint + ("?" + urlencode(params) if params else "")
    started_ms = time.time_ns() // 1_000_000
    payload = _read_url(url)
    received_ms = time.time_ns() // 1_000_000
    target = raw_dir / (label + ".json")
    with target.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    parsed = json.loads(payload)
    if isinstance(parsed, list) and params.get("limit") and len(parsed) >= params["limit"]:
        raise ValueError(f"C18 response may be truncated; refusing {label}")
    receipt = {
        "url": url,
        "file": str(target.relative_to(PAPER)).replace("\\", "/"),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "request_started_ms": started_ms,
        "received_ms": received_ms,
        "http_success": True,
    }
    return parsed, receipt


def _read_recent_bars(connection: sqlite3.Connection, symbol: str) -> list[Bar]:
    rows = connection.execute(
        "SELECT payload_json FROM daily_klines WHERE symbol=? ORDER BY open_ms DESC LIMIT ?",
        (symbol, SEED_DAILY_DAYS)).fetchall()
    return [Bar(**json.loads(row[0])) for row in reversed(rows)]


def _read_recent_funding(connection: sqlite3.Connection, symbol: str) -> list[Funding]:
    rows = connection.execute(
        "SELECT payload_json FROM funding_events WHERE symbol=? ORDER BY timestamp_ms DESC LIMIT 1200",
        (symbol,)).fetchall()
    values = [json.loads(row[0]) for row in reversed(rows)]
    return [Funding(row["timestamp_ms"], row["interval_hours"], row["rate"]) for row in values]


def _sync_contract_data(connection: sqlite3.Connection, active: list[str], cutoff: int,
                         observed_ms: int, raw_dir: Path) -> tuple[dict, list[dict]]:
    jobs = []
    for symbol in active:
        bars = _read_recent_bars(connection, symbol)
        funding = _read_recent_funding(connection, symbol)
        if not bars or not funding:
            raise ValueError(f"C18 local seed missing for active contract {symbol}")
        jobs.append(("klines", symbol, {"symbol": symbol, "interval": "1d",
                                         "startTime": bars[-1].open_ms, "endTime": observed_ms,
                                         "limit": 1500}))
        jobs.append(("fundingRate", symbol, {"symbol": symbol,
                                             "startTime": funding[-1].timestamp_ms,
                                             "endTime": observed_ms, "limit": 1000}))

    responses, receipts = {}, []
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending = {
            pool.submit(_raw_request, endpoint, params, f"{endpoint}_{symbol}", raw_dir): (endpoint, symbol)
            for endpoint, symbol, params in jobs
        }
        for future in as_completed(pending):
            key = pending[future]
            parsed, receipt = future.result()
            responses[key] = parsed
            receipts.append(receipt)

    merged_bars, funding_inserts = {}, {}
    connection.execute("BEGIN IMMEDIATE")
    try:
        for symbol in active:
            previous_bars = _read_recent_bars(connection, symbol)
            updated_bars = merge_closed_bars(previous_bars, responses["klines", symbol], cutoff)
            merged_bars[symbol] = updated_bars
            previous_funding = _read_recent_funding(connection, symbol)
            updated_funding, observed_events = merge_funding(
                previous_funding, responses["fundingRate", symbol], symbol, observed_ms)
            intervals = {row.timestamp_ms: row.interval_hours for row in updated_funding}
            old_marks = {
                row[0]: json.loads(row[1]).get("mark_price")
                for row in connection.execute(
                    "SELECT timestamp_ms,payload_json FROM funding_events WHERE symbol=?", (symbol,))
            }
            for event in observed_events:
                timestamp = event["timestamp_ms"]
                mark = float(event["mark_price"])
                if timestamp in old_marks:
                    prior_mark = old_marks[timestamp]
                    if prior_mark is not None and not math.isclose(mark, prior_mark, rel_tol=1e-9, abs_tol=1e-8):
                        raise ValueError(f"C18 historical funding mark changed for {symbol} at {timestamp}")
                    continue
                if timestamp not in intervals:
                    raise ValueError(f"C18 funding interval missing for {symbol} at {timestamp}")
                funding_inserts.setdefault(symbol, []).append({
                    "timestamp_ms": timestamp,
                    "interval_hours": intervals[timestamp],
                    "rate": float(event["rate"]),
                    "mark_price": mark,
                })
        for symbol, bars in merged_bars.items():
            for bar in bars:
                connection.execute("INSERT OR IGNORE INTO daily_klines VALUES(?,?,?)",
                                   (symbol, bar.open_ms, _json(asdict(bar))))
        for symbol, events in funding_inserts.items():
            for event in events:
                connection.execute("INSERT INTO funding_events VALUES(?,?,?)",
                                   (symbol, event["timestamp_ms"], _json(event)))
        min_daily = cutoff - SEED_DAILY_DAYS * DAY_MS
        min_funding = observed_ms - KEEP_FUNDING_DAYS * DAY_MS
        connection.execute("DELETE FROM daily_klines WHERE open_ms < ?", (min_daily,))
        connection.execute("DELETE FROM funding_events WHERE timestamp_ms < ?", (min_funding,))
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise

    data = {"klines": {}, "fundingRate": {}}
    for symbol in active:
        data["klines"][symbol] = _read_recent_bars(connection, symbol)
        data["fundingRate"][symbol] = _read_recent_funding(connection, symbol)
    return data, receipts


def _active_contracts(exchange: dict, cohort: list[str]) -> tuple[list[str], dict[str, str]]:
    by_symbol = {row.get("symbol"): row for row in exchange.get("symbols", [])}
    active, unavailable = [], {}
    for symbol in cohort:
        info = by_symbol.get(symbol)
        if info is None:
            unavailable[symbol] = "absent_from_exchange_info"
        elif (info.get("status") == "TRADING" and info.get("contractType") == "PERPETUAL"
              and info.get("quoteAsset") == "USDT"):
            active.append(symbol)
        else:
            unavailable[symbol] = (f"not_current_usdt_perpetual:status={info.get('status')};"
                                   f"type={info.get('contractType')};quote={info.get('quoteAsset')}")
    return active, unavailable


def _load_accounts(connection: sqlite3.Connection, start_ms: int) -> tuple[dict, dict, bool]:
    row = connection.execute("SELECT base_json,stress_json FROM account_state WHERE id=1").fetchone()
    if row is None:
        return (account.initialize(start_ms, INITIAL_EQUITY),
                account.initialize(start_ms, INITIAL_EQUITY), True)
    return json.loads(row[0]), json.loads(row[1]), False


def _funding_for_tick(connection: sqlite3.Connection, after_ms: int, through_ms: int,
                      symbols: set[str]) -> list[dict]:
    rows = []
    for symbol in sorted(symbols):
        for payload_json, in connection.execute(
                "SELECT payload_json FROM funding_events WHERE symbol=? AND timestamp_ms>? "
                "AND timestamp_ms<=? ORDER BY timestamp_ms", (symbol, after_ms, through_ms)):
            item = json.loads(payload_json)
            if item["mark_price"] is None:
                raise ValueError(f"C18 historical funding mark unavailable inside paper interval: {symbol}")
            rows.append({"symbol": symbol, "timestamp_ms": item["timestamp_ms"],
                         "rate": item["rate"], "mark_price": item["mark_price"]})
    return sorted(rows, key=lambda item: (item["timestamp_ms"], item["symbol"]))


def _scheduled(server_ms: int) -> bool:
    if server_ms < FIRST_DECISION_MS:
        return False
    instant = datetime.fromtimestamp(server_ms / 1000, timezone.utc)
    return instant.weekday() == 0 and instant.hour == 1 and instant.minute < 5


def _week_bucket(timestamp_ms: int) -> int:
    # Unix epoch begins on Thursday; offset to the Monday UTC week boundary.
    return (timestamp_ms - 4 * DAY_MS) // WEEK_MS


def _model_predictions(model, states: dict, base_targets: dict) -> dict[str, float]:
    predictions = {}
    class_index = list(model.classes_).index(1)
    for symbol in sorted(base_targets):
        feature_row = states[symbol]
        vector = [float(feature_row[name]) for name in FIELDS] + [float(sign(base_targets[symbol]))]
        if not all(math.isfinite(value) for value in vector):
            raise ValueError(f"C18 model feature is non-finite for {symbol}")
        probability = float(model.predict_proba(np.asarray([vector], dtype=np.float64))[0, class_index])
        if not math.isfinite(probability) or not 0 <= probability <= 1:
            raise ValueError(f"C18 model probability is invalid for {symbol}")
        predictions[symbol] = probability
    return predictions


def _filtered_targets(base_targets: dict, probabilities: dict, features_by_symbol: dict,
                      base_account: dict) -> tuple[dict, dict]:
    candidates = {}
    for symbol, weight in base_targets.items():
        direction = sign(weight)
        position = base_account["positions"].get(symbol)
        continuing = position is not None and sign(position["quantity"]) == direction
        if continuing or probabilities[symbol] >= 0.70:
            candidates[symbol] = direction
    longs = sorted(symbol for symbol, direction in candidates.items() if direction > 0)
    shorts = sorted(symbol for symbol, direction in candidates.items() if direction < 0)
    if not longs or not shorts:
        return {}, {"accepted_long_count": len(longs), "accepted_short_count": len(shorts),
                    "status": "cash_no_both_sides"}
    targets = {symbol: 0.25 / len(longs) for symbol in longs}
    targets.update({symbol: -0.25 / len(shorts) for symbol in shorts})
    beta = math.fsum(weight * features_by_symbol[symbol]["beta60"] for symbol, weight in targets.items())
    diagnostics = {
        "accepted_long_count": len(longs),
        "accepted_short_count": len(shorts),
        "status": "balanced_long_short",
        "gross_weight": math.fsum(abs(weight) for weight in targets.values()),
        "net_weight": math.fsum(targets.values()),
        "beta_residual": beta,
        "accepted_symbols": sorted(targets),
        "accepted_probabilities": {symbol: probabilities[symbol] for symbol in sorted(targets)},
    }
    return targets, diagnostics


def _portfolio_snapshot(snapshot: dict, funding: list[dict]) -> dict:
    return {"server_time_ms": snapshot["server_time_ms"],
            "accepted_quotes": snapshot["accepted_quotes"], "funding": funding}


def _decision_quote_check(snapshot: dict, prefetched_active: set[str], cutoff: int) -> tuple[bool, str | None]:
    if feature_cutoff(snapshot["server_time_ms"]) != cutoff:
        return False, "feature_cutoff_changed_during_collection"
    accepted = set(snapshot["accepted_quotes"])
    active_observed = accepted | set(snapshot["rejected_quotes"])
    if active_observed != prefetched_active or snapshot["rejected_quotes"]:
        return False, "active_contract_or_fresh_quote_set_changed"
    if not _scheduled(snapshot["server_time_ms"]):
        return False, "decision_snapshot_outside_registered_weekly_window"
    return True, None


def _clustered_intervals(trades: list[dict]) -> dict | None:
    if len(trades) < 20:
        return None
    symbols = sorted({row["symbol"] for row in trades})
    weeks = sorted({_week_bucket(row["entry_ms"]) for row in trades})
    symbol_index = {symbol: index for index, symbol in enumerate(symbols)}
    week_index = {week: index for index, week in enumerate(weeks)}
    returns = np.asarray([row["net_return_on_entry_notional"] for row in trades], dtype=np.float64)
    wins = (returns > 0).astype(np.float64)
    si = np.asarray([symbol_index[row["symbol"]] for row in trades], dtype=np.int64)
    wi = np.asarray([week_index[_week_bucket(row["entry_ms"])] for row in trades], dtype=np.int64)
    rng = np.random.default_rng(2026)
    samples = []
    for _ in range(BOOTSTRAP_REPLICATES):
        symbol_counts = np.bincount(rng.integers(0, len(symbols), len(symbols)), minlength=len(symbols))
        week_counts = np.bincount(rng.integers(0, len(weeks), len(weeks)), minlength=len(weeks))
        weights = symbol_counts[si] * week_counts[wi]
        denominator = weights.sum()
        if denominator:
            samples.append(float(np.dot(weights, returns) / denominator))
    if len(samples) < BOOTSTRAP_REPLICATES * 0.9:
        return {"method": "two_way_symbol_week_pigeonhole_bootstrap_percentile",
                "status": "insufficient_nonempty_resamples", "nonempty_resamples": len(samples)}
    low, high = np.quantile(np.asarray(samples), [0.025, 0.975])
    return {"method": "two_way_symbol_week_pigeonhole_bootstrap_percentile",
            "replicates": len(samples), "seed": 2026,
            "ev_pct_95_interval": [100 * float(low), 100 * float(high)],
            "limits": "Exploratory dependence-aware interval; sparse symbols/weeks limit calibration."}


def _metrics(connection: sqlite3.Connection, base: dict, stress: dict) -> dict:
    closed = base["closed_trades"]
    returns = [row["net_return_on_entry_notional"] for row in closed]
    monetary_pnls = [row["net_pnl"] for row in closed]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    gross_wins = math.fsum(value for value in monetary_pnls if value > 0)
    gross_losses = -math.fsum(value for value in monetary_pnls if value < 0)
    payoff = ((math.fsum(wins) / len(wins)) / abs(math.fsum(losses) / len(losses))) if wins and losses else (
        "unbounded" if wins else None)
    profit_factor = (gross_wins / gross_losses if gross_losses else "unbounded" if wins else None)
    profit_factor_gate_passed = (
        gross_losses > 0 and isinstance(profit_factor, (int, float)) and profit_factor >= 1.25
    )
    weeks = {_week_bucket(row["entry_ms"]) for row in closed}
    stress_closed = stress["closed_trades"]
    stress_returns = [row["net_return_on_entry_notional"] for row in stress_closed]
    stress_monetary_pnls = [row["net_pnl"] for row in stress_closed]
    stress_wins = [value for value in stress_returns if value > 0]
    stress_losses = [value for value in stress_returns if value < 0]
    stress_gross_wins = math.fsum(value for value in stress_monetary_pnls if value > 0)
    stress_gross_losses = -math.fsum(value for value in stress_monetary_pnls if value < 0)
    stress_payoff = ((math.fsum(stress_wins) / len(stress_wins))
                     / abs(math.fsum(stress_losses) / len(stress_losses))) if stress_wins and stress_losses else (
                         "unbounded" if stress_wins else None)
    stress_profit_factor = (stress_gross_wins / stress_gross_losses if stress_gross_losses
                            else "unbounded" if stress_wins else None)
    points = connection.execute(
        "SELECT timestamp_ms,base_equity,stress_equity FROM equity_points ORDER BY sequence").fetchall()
    turnover_base = base.get("turnover_notional", 0.0)
    turnover_stress = stress.get("turnover_notional", 0.0)
    base_trades = len(closed)
    unique_ids = {row["trade_id"] for row in closed}
    duplicate_trade_ids = base_trades - len(unique_ids)
    active_decision_gate = (
        len(unique_ids) >= 200 and duplicate_trade_ids == 0 and len(weeks) >= 8
        and (100 * math.fsum(returns) / base_trades) > 1.2
        and (payoff == "unbounded" or (payoff is not None and payoff >= 1.0))
        and profit_factor_gate_passed
        and stress["equity"] > stress["initial_equity"]
    )
    by_symbol = {}
    by_direction = {}
    for trade in closed:
        bucket = by_symbol.setdefault(trade["symbol"], {"episodes": 0, "net_return_sum": 0.0})
        bucket["episodes"] += 1
        bucket["net_return_sum"] += trade["net_return_on_entry_notional"]
        key = "long" if trade["direction"] > 0 else "short"
        side = by_direction.setdefault(key, {"episodes": 0, "net_return_sum": 0.0})
        side["episodes"] += 1
        side["net_return_sum"] += trade["net_return_on_entry_notional"]
    return {
        "complete_unique_episodes": len(unique_ids),
        "duplicate_trade_ids": duplicate_trade_ids,
        "open_episodes": len(base["positions"]),
        "active_entry_weeks": len(weeks),
        "win_rate_pct": 100 * len(wins) / base_trades if base_trades else None,
        "distance_from_70pct_hit_rate_points": abs(100 * len(wins) / base_trades - 70) if base_trades else None,
        "mean_net_ev_pct_per_episode": 100 * math.fsum(returns) / base_trades if base_trades else None,
        "payoff_ratio": payoff,
        "profit_factor": profit_factor,
        "profit_factor_gate_passed": profit_factor_gate_passed,
        "profit_factor_definition": "sum_positive_net_pnl_usd / abs(sum_negative_net_pnl_usd)",
        "stress_complete_episodes": len(stress_closed),
        "stress_win_rate_pct": 100 * len(stress_wins) / len(stress_closed) if stress_closed else None,
        "stress_mean_net_ev_pct_per_episode": 100 * math.fsum(stress_returns) / len(stress_closed) if stress_closed else None,
        "stress_payoff_ratio": stress_payoff,
        "stress_profit_factor": stress_profit_factor,
        "stress_profit_factor_definition": "sum_positive_net_pnl_usd / abs(sum_negative_net_pnl_usd)",
        "base_total_pnl_usd": base["equity"] - base["initial_equity"],
        "stress_total_pnl_usd": stress["equity"] - stress["initial_equity"],
        "base_equity_usd": base["equity"],
        "stress_equity_usd": stress["equity"],
        "base_max_drawdown_pct": 100 * base["max_drawdown"],
        "stress_max_drawdown_pct": 100 * stress["max_drawdown"],
        "base_turnover_usd": turnover_base,
        "stress_turnover_usd": turnover_stress,
        "base_turnover_x_initial_equity": turnover_base / base["initial_equity"],
        "stress_turnover_x_initial_equity": turnover_stress / stress["initial_equity"],
        "base_fees_usd": base["fees"],
        "stress_fees_usd": stress["fees"],
        "base_funding_pnl_usd": base["funding_pnl"],
        "stress_funding_pnl_usd": stress["funding_pnl"],
        "base_episode_concentration": by_symbol,
        "base_direction_concentration": by_direction,
        "clustered_ev_interval": _clustered_intervals(closed),
        "stress_clustered_ev_interval": _clustered_intervals(stress_closed),
        "sample_gate_passed": active_decision_gate and duplicate_trade_ids == 0,
        "equity_points": len(points),
        "real_orders_sent": False,
    }


def _market_capture(raw_dir: Path, label: str) -> dict:
    before, before_receipt = _raw_request("time", {}, f"{label}_server_before", raw_dir)
    start_ms = int(before["serverTime"])
    exchange, exchange_receipt = _raw_request("exchangeInfo", {}, f"{label}_exchange", raw_dir)
    quotes, quotes_receipt = _raw_request("ticker/bookTicker", {}, f"{label}_quotes", raw_dir)
    after, after_receipt = _raw_request("time", {}, f"{label}_server_after", raw_dir)
    server_ms = int(after["serverTime"])
    if not start_ms <= server_ms or server_ms - start_ms > 30_000:
        raise ValueError("C18 quote capture clock interval is invalid or too wide")
    if not after_receipt["request_started_ms"] - 5_000 <= server_ms <= after_receipt["received_ms"] + 5_000:
        raise ValueError("C18 local/server clock mismatch during quote capture")
    active, unavailable = _active_contracts(exchange, json.loads(
        (CACHE / "cohort.json").read_text(encoding="utf-8"))["selected"])
    if not isinstance(quotes, list) or len({row.get("symbol") for row in quotes}) != len(quotes):
        raise ValueError("C18 quote response is not a unique symbol list")
    quote_by_symbol = {row["symbol"]: row for row in quotes}
    accepted, rejected = {}, {}
    for symbol in active:
        try:
            accepted[symbol] = validate_quote(quote_by_symbol[symbol], server_ms)
        except (KeyError, TypeError, ValueError) as exc:
            rejected[symbol] = str(exc)
    body = {
        "server_time_ms": server_ms,
        "capture_start_server_ms": start_ms,
        "sources": [before_receipt, exchange_receipt, quotes_receipt, after_receipt],
        "accepted_quotes": accepted,
        "unavailable_contracts": unavailable,
        "rejected_quotes": rejected,
        "status": "market_observation_only",
        "orders_sent": 0,
        "authenticated_requests": False,
    }
    return {**body, "capture_sha256": _digest(body)}


def tick() -> dict:
    with _exclusive_paper_tick_lock() as acquired:
        if not acquired:
            report = {
                "status": "skipped_overlap",
                "blocking_reason": "another_C18_observation_is_running",
                "observation_interval_ms": OBSERVATION_INTERVAL_MS,
                "orders_enabled": False,
            }
            print(json.dumps(report, sort_keys=True, allow_nan=False))
            return report
        return _tick_once()


def _tick_once() -> dict:
    connection = _connect()
    try:
        metadata, config = _setup(connection)
        _verify_chain(connection, full=False)
        _verify_public_receipts(connection, full=False)
        cohort = config["cohort"]
        raw_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        raw_dir = PAPER / "raw" / raw_id
        raw_dir.mkdir(parents=True, exist_ok=False)
        clock, clock_receipt = _raw_request("time", {}, "server_time", raw_dir)
        prefetch_ms = int(clock["serverTime"])
        if not clock_receipt["request_started_ms"] - 5_000 <= prefetch_ms <= clock_receipt["received_ms"] + 5_000:
            raise ValueError("C18 local/server clock mismatch")
        cutoff = feature_cutoff(prefetch_ms)
        exchange, exchange_receipt = _raw_request("exchangeInfo", {}, "exchange_info", raw_dir)
        active, unavailable = _active_contracts(exchange, cohort)
        if set(active) & set(unavailable):
            raise ValueError("C18 exchange contract classification is inconsistent")
        if "BTCUSDT" not in active:
            raise ValueError("C18 beta-hedged signal suspended because BTCUSDT is not an active USD-M perpetual")

        daily_count = connection.execute("SELECT COUNT(*) FROM daily_klines").fetchone()[0]
        seed = None
        if daily_count == 0:
            seed = _seed_local_data(connection, active, prefetch_ms)
            _append_record(connection, {"kind": "local_seed", "created_utc": datetime.now(timezone.utc).isoformat(),
                                        **seed})

        data, data_receipts = _sync_contract_data(connection, active, cutoff, prefetch_ms, raw_dir)
        base_state, stress_state, _ = _load_accounts(connection, prefetch_ms)
        position_symbols = set(base_state["positions"]) | set(stress_state["positions"])
        if position_symbols - set(active):
            blocked = {"kind": "blocked_observation", "status": "held_contract_unavailable",
                       "created_utc": datetime.now(timezone.utc).isoformat(),
                       "server_time_ms": prefetch_ms, "unavailable_contracts": unavailable,
                       "held_symbols_without_active_contract": sorted(position_symbols - set(active)),
                       "public_request_receipts": [clock_receipt, exchange_receipt, *data_receipts],
                       "orders_sent": False}
            return _blocked(connection, blocked, base_state, stress_state)
        _append_record(connection, {
            "kind": "market_data_sync",
            "status": "public_inputs_acquired_before_decision",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "server_time_ms": prefetch_ms,
            "feature_cutoff_ms": cutoff,
            "active_symbols": active,
            "unavailable_contracts": unavailable,
            "public_request_receipts": [clock_receipt, exchange_receipt, *data_receipts],
            "orders_sent": False,
        }, base_state=base_state, stress_state=stress_state)

        state_features = features(data)
        complete_symbols = sorted(symbol for symbol in active if cutoff in state_features.get(symbol, {}))
        incomplete = sorted(set(active) - set(complete_symbols))
        if incomplete:
            raise ValueError(f"C18 active contract feature history incomplete at frozen cutoff: {incomplete}")
        current_features = {symbol: state_features[symbol][cutoff] for symbol in active}
        if any(row["latest_observed_close_ms"] != cutoff for row in current_features.values()):
            raise ValueError("C18 feature cutoffs differ across the fixed active cohort")

        decision_candidate = _scheduled(prefetch_ms)
        decision_reservation_sha256 = None
        already_attempted = False
        if decision_candidate:
            decision_candidate, decision_reservation_sha256 = _reserve_weekly_decision(
                connection,
                feature_cutoff_ms=cutoff,
                attempted_server_ms=prefetch_ms,
                base_state=base_state,
                stress_state=stress_state,
            )
            already_attempted = not decision_candidate
        predictions, base_targets, target_diagnostics = {}, {}, {"status": "not_scheduled"}
        if already_attempted:
            target_diagnostics = {"status": "weekly_decision_already_attempted"}
        if decision_candidate:
            base_targets = target_weights(current_features, "low_volatility30_betahedged")
            if base_targets:
                with MODEL_PATH.open("rb") as handle:
                    model = pickle.load(handle)
                if (list(model.classes_) != [0, 1]
                        or model.n_features_in_ != len(FIELDS) + 1
                        or type(model).__name__ != "HistGradientBoostingClassifier"):
                    raise ValueError("C18 serialized model structure differs from the frozen training schema")
                predictions = _model_predictions(model, current_features, base_targets)
                proposed_targets, target_diagnostics = _filtered_targets(
                    base_targets, predictions, current_features, base_state)
            else:
                proposed_targets = {}
                target_diagnostics = {"status": "base_rule_cash_or_ineligible", "gross_weight": 0.0,
                                      "net_weight": 0.0, "beta_residual": 0.0}
        else:
            proposed_targets = None

        first_capture = _market_capture(raw_dir, "decision_quote" if decision_candidate else "mark_quote")
        first_cutoff_ok = feature_cutoff(first_capture["server_time_ms"]) == cutoff
        used_capture = first_capture
        decision_status, decision_reason = (
            ("mark_only", "weekly_decision_already_attempted") if already_attempted
            else ("mark_only", None)
        )
        target_to_apply = None
        predictions_recorded = {}
        if decision_candidate:
            decision_ok, decision_reason = _decision_quote_check(first_capture, set(active), cutoff)
            if decision_ok and set(base_targets) - set(first_capture["accepted_quotes"]):
                decision_ok, decision_reason = False, "base_rule_target_quote_missing"
            if decision_ok:
                target_to_apply = proposed_targets
                decision_status = "decision_registered"
                predictions_recorded = predictions
                second_capture = _market_capture(raw_dir, "post_decision_fill_quote")
                used_capture = second_capture
                if (feature_cutoff(second_capture["server_time_ms"]) != cutoff
                        or set(second_capture["accepted_quotes"]) != set(active)
                        or second_capture["rejected_quotes"]
                        or (set(target_to_apply) | position_symbols) - set(second_capture["accepted_quotes"])):
                    decision_status = "decision_abstained_before_fill"
                    decision_reason = "post_decision_fill_quote_or_contract_set_incomplete"
                    target_to_apply = None
                    used_capture = second_capture
            else:
                decision_status = "decision_abstained"
            if not _scheduled(first_capture["server_time_ms"]):
                target_to_apply = None
                decision_status = "decision_missed_window"
        if not first_cutoff_ok:
            target_to_apply = None
            decision_status = "abstained_cutoff_changed"
            decision_reason = "feature_cutoff_changed_during_collection"

        final_time = int(used_capture["server_time_ms"])
        if feature_cutoff(final_time) != cutoff:
            blocked = {"kind": "blocked_observation", "status": "feature_cutoff_changed_during_collection",
                       "created_utc": datetime.now(timezone.utc).isoformat(),
                       "server_time_ms": final_time, "feature_cutoff_ms": cutoff,
                       "quote_snapshots": [first_capture, *([used_capture] if used_capture is not first_capture else [])],
                       "public_request_receipts": [*first_capture["sources"],
                                                    *(used_capture["sources"] if used_capture is not first_capture else [])],
                       "orders_sent": False}
            return _blocked(connection, blocked, base_state, stress_state)

        if (set(base_state["positions"]) | set(stress_state["positions"]) |
                set(target_to_apply or {})) - set(used_capture["accepted_quotes"]):
            blocked = {"kind": "blocked_observation", "status": "required_quote_unavailable",
                       "created_utc": datetime.now(timezone.utc).isoformat(),
                       "server_time_ms": final_time, "unavailable_contracts": used_capture["unavailable_contracts"],
                       "rejected_quotes": used_capture["rejected_quotes"],
                       "quote_snapshots": [first_capture, *([used_capture] if used_capture is not first_capture else [])],
                       "public_request_receipts": [*first_capture["sources"],
                                                    *(used_capture["sources"] if used_capture is not first_capture else [])],
                       "orders_sent": False}
            return _blocked(connection, blocked, base_state, stress_state)

        # Funding is refreshed through the exact quote snapshot time before either simulated account advances.
        held_symbols = sorted(set(base_state["positions"]) | set(stress_state["positions"]))
        _, funding_receipts = _sync_funding_to_quote(connection, held_symbols, final_time, raw_dir)
        account_symbols = set(held_symbols)
        funding_events = _funding_for_tick(connection, base_state["last_ms"], final_time, account_symbols)
        snapshot = _portfolio_snapshot(used_capture, funding_events)
        try:
            base_next = account.advance(base_state, snapshot, target_to_apply,
                                        fee_rate=account.BASE_FEE_RATE, slippage=account.BASE_SLIPPAGE)
            stress_next = account.advance(stress_state, snapshot, target_to_apply,
                                          fee_rate=account.STRESS_FEE_RATE, slippage=account.STRESS_SLIPPAGE)
        except ValueError as exc:
            if "observation gap exceeds 65 minutes" not in str(exc):
                raise
            blocked = {
                "kind": "blocked_observation",
                "status": "observation_gap_exceeded_65_minutes",
                "blocking_reason": str(exc),
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "server_time_ms": final_time,
                "last_accounted_server_time_ms": base_state["last_ms"],
                "open_positions": sorted(base_state["positions"]),
                "orders_sent": False,
                "public_request_receipts": [clock_receipt, exchange_receipt, *data_receipts,
                                             *first_capture["sources"],
                                             *(used_capture["sources"] if used_capture is not first_capture else []),
                                             *funding_receipts],
            }
            return _blocked(connection, blocked, base_state, stress_state)
        if (base_next["last_ms"] != stress_next["last_ms"]
                or base_next["equity"] <= 0 or stress_next["equity"] <= 0):
            raise ValueError("C18 base/stress accounting did not advance consistently")

        exposure = {"gross_weight": 0.0, "net_weight": 0.0, "beta_residual": None}
        if target_to_apply is not None:
            exposure = {
                "gross_weight": math.fsum(abs(value) for value in target_to_apply.values()),
                "net_weight": math.fsum(target_to_apply.values()),
                "beta_residual": (math.fsum(value * current_features[symbol]["beta60"]
                                            for symbol, value in target_to_apply.items())
                                  if target_to_apply else 0.0),
            }
        status = {
            "kind": "paper_tick",
            "status": decision_status,
            "decision_reason": decision_reason,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "server_time_ms": final_time,
            "prefetch_server_time_ms": prefetch_ms,
            "feature_cutoff_ms": cutoff,
            "decision_reservation_sha256": decision_reservation_sha256,
            "registered_config_sha256": config["registered_config_sha256"],
            "effective_config_sha256": config["effective_config_sha256"],
            "code_sha256": config["code_sha256"],
            "code_amendment_record_sha256": config["code_amendment_record_sha256"],
            "active_symbols": active,
            "unavailable_contracts": unavailable,
            "current_features": current_features if decision_candidate else None,
            "base_rule_targets": base_targets,
            "probabilities": predictions_recorded,
            "decision_diagnostics": target_diagnostics,
            "targets": target_to_apply,
            "portfolio_exposure": exposure,
            "quote_snapshot_sha256": used_capture["capture_sha256"],
            "decision_quote_snapshot_sha256": first_capture["capture_sha256"],
            "quote_snapshots": [first_capture, *([used_capture] if used_capture is not first_capture else [])],
            "public_request_receipts": [clock_receipt, exchange_receipt, *data_receipts,
                                         *first_capture["sources"],
                                         *(used_capture["sources"] if used_capture is not first_capture else []),
                                         *funding_receipts],
            "local_seed": seed,
            "feature_archive_source_manifest_sha256": metadata["source_archive_manifest_sha256"],
            "base_events": base_next["events"],
            "stress_events": stress_next["events"],
            "orders_sent": False,
            "authenticated_requests": False,
            "model_refit": False,
        }
        inserted = _append_record(connection, status, base_state=base_next, stress_state=stress_next,
                                  equity_point=True)
        if decision_reservation_sha256:
            connection.execute(
                "UPDATE decision_attempts SET completed_record_sha256=? WHERE feature_cutoff_ms=?",
                (inserted["record_sha256"], cutoff),
            )
        metrics = _metrics(connection, base_next, stress_next)
        report = {"experiment_id": config["experiment_id"], "last_record_sha256": inserted["record_sha256"],
                  "last_status": status["status"], "last_server_time_ms": final_time,
                  "feature_cutoff_ms": cutoff, "sample_metrics": metrics,
                  "operational_status": _operational_status(
                      base_next, final_time,
                      status="observed" if not decision_reason else "decision_abstained",
                      blocking_reason=decision_reason,
                  ),
                  "registered_config_sha256": config["registered_config_sha256"],
                  "effective_config_sha256": config["effective_config_sha256"],
                  "code_sha256": config["code_sha256"],
                  "code_amendment_record_sha256": config["code_amendment_record_sha256"],
                  "candidate_approved": metrics["sample_gate_passed"],
                  "approval_limit": "Paper evidence only; never enables real orders.",
                  "orders_enabled": False}
        _atomic_json(REPORT_PATH, report)
        print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
        return report
    finally:
        connection.close()


def _sync_funding_to_quote(connection: sqlite3.Connection, active: list[str], quote_ms: int,
                           raw_dir: Path) -> tuple[int, list[dict]]:
    receipts, responses = [], {}
    jobs = []
    for symbol in active:
        latest = connection.execute(
            "SELECT MAX(timestamp_ms) FROM funding_events WHERE symbol=?", (symbol,)).fetchone()[0]
        if latest is None:
            raise ValueError(f"C18 prospective funding seed missing for {symbol}")
        jobs.append((symbol, {"symbol": symbol, "startTime": latest, "endTime": quote_ms, "limit": 1000}))
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending = {pool.submit(_raw_request, "fundingRate", params,
                               f"funding_final_{symbol}", raw_dir): symbol for symbol, params in jobs}
        for future in as_completed(pending):
            symbol = pending[future]
            responses[symbol], receipt = future.result()
            receipts.append(receipt)
    connection.execute("BEGIN IMMEDIATE")
    try:
        for symbol in active:
            previous = _read_recent_funding(connection, symbol)
            merged, events = merge_funding(previous, responses[symbol], symbol, quote_ms)
            intervals = {row.timestamp_ms: row.interval_hours for row in merged}
            for event in events:
                timestamp = event["timestamp_ms"]
                prior = connection.execute(
                    "SELECT payload_json FROM funding_events WHERE symbol=? AND timestamp_ms=?",
                    (symbol, timestamp)).fetchone()
                mark = float(event["mark_price"])
                if prior:
                    old = json.loads(prior[0]).get("mark_price")
                    if old is not None and not math.isclose(mark, old, rel_tol=1e-9, abs_tol=1e-8):
                        raise ValueError(f"C18 funding settlement mark changed for {symbol} at {timestamp}")
                    if old is None:
                        payload = {"timestamp_ms": timestamp, "interval_hours": intervals[timestamp],
                                   "rate": float(event["rate"]), "mark_price": mark}
                        connection.execute("UPDATE funding_events SET payload_json=? WHERE symbol=? AND timestamp_ms=?",
                                           (_json(payload), symbol, timestamp))
                    continue
                if timestamp not in intervals:
                    raise ValueError(f"C18 funding interval unresolved for {symbol} at {timestamp}")
                payload = {"timestamp_ms": timestamp, "interval_hours": intervals[timestamp],
                           "rate": float(event["rate"]), "mark_price": mark}
                connection.execute("INSERT INTO funding_events VALUES(?,?,?)",
                                   (symbol, timestamp, _json(payload)))
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    return len(active), receipts


def status() -> dict:
    if not DATABASE.exists():
        return {"status": "not_initialized", "orders_enabled": False}
    connection = sqlite3.connect(DATABASE.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        _verify_chain(connection, full=True)
        config_state = _verify_config_record(connection)
        _verify_public_receipts(connection)
        row = connection.execute("SELECT base_json,stress_json FROM account_state WHERE id=1").fetchone()
        last = connection.execute("SELECT payload_json,record_sha256 FROM records ORDER BY sequence DESC LIMIT 1").fetchone()
        if row is None:
            return {"status": "registered_without_paper_account", "orders_enabled": False}
        base, stress = json.loads(row[0]), json.loads(row[1])
        metrics = _metrics(connection, base, stress)
        last_payload = json.loads(last[0])
        observed_server_ms = int(last_payload.get("server_time_ms", base["last_ms"]))
        operational = _operational_status(
            base,
            observed_server_ms,
            status="blocked" if last_payload.get("kind") == "blocked_observation" else "observed",
            blocking_reason=last_payload.get("blocking_reason", last_payload.get("status")
                             if last_payload.get("kind") == "blocked_observation" else None),
        )
        now_ms = time.time_ns() // 1_000_000
        operational["heartbeat_age_ms"] = max(0, now_ms - observed_server_ms)
        if (base["positions"] and operational["heartbeat_age_ms"] > account.MAX_GAP_MS
                and operational["blocking_reason"] is None):
            operational["status"] = "stale_blocked"
            operational["blocking_reason"] = "last_C18_observation_exceeds_65_minutes_with_open_positions"
        has_decision_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='decision_attempts'"
        ).fetchone()
        pending_decisions = [
            {"feature_cutoff_ms": cutoff, "attempted_server_ms": attempted,
             "reservation_record_sha256": reservation}
            for cutoff, attempted, reservation in connection.execute(
                "SELECT feature_cutoff_ms,attempted_server_ms,reservation_record_sha256 "
                "FROM decision_attempts WHERE completed_record_sha256 IS NULL ORDER BY feature_cutoff_ms"
            )
        ] if has_decision_table else []
        result = {"experiment_id": "C18-lowvol-hgb-forward-static-2026-09-29",
                  "last_record": last_payload, "last_record_sha256": last[1],
                  "sample_metrics": metrics, "candidate_approved": metrics["sample_gate_passed"],
                  "operational_status": operational,
                  "configuration_amendment_status": config_state,
                  "pending_weekly_decision_attempts": pending_decisions,
                  "read_only_snapshot": True,
                  "wal_file_present": Path(str(DATABASE) + "-wal").exists(),
                  "orders_enabled": False}
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
        return result
    finally:
        connection.close()


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "tick"
    if command == "tick":
        tick()
        return 0
    if command == "status":
        status()
        return 0
    print("usage: python -m jev_trader.lowvol_hgb_paper [tick|status]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
