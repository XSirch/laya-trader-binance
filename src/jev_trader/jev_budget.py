"""One-request adherence scoring with a cumulative, persistent USD budget.

Every POST first reserves USD 0.01. Unknown charges retain that reservation and
are never retried automatically. A provider charge above the reservation is
recorded at its actual value and stops further spending; this reservation is a
conservative allowance, not a provider-enforced maximum price.

Pinned-model pricing assumption checked by the caller on 2026-09-26: Jev 1.13
accepts at most 32,768 input tokens at USD 0.042 per million input tokens, with
free output. A full input context therefore costs USD 0.001376256; the USD 0.01
reservation exceeds seven times that amount. Requests additionally cap the
entire JSON body at 24,000 UTF-8 bytes. Pricing changes or unexpected charges
still require review, and any unresolved reservation stops new paid work even
after the client is reopened.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import threading
import time
import urllib.request
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .jev import ENDPOINT, MODEL

RESERVATION_USD = Decimal("0.01")
MAX_BUDGET_USD = Decimal("2")
MAX_REQUEST_BYTES = 24_000
MAX_INPUT_TOKENS = 32_768
_ZERO_HASH = "0" * 64
_COMPLETE_FIELDS = {"key", "status", "charged_or_reserved_usd", "adherence",
                    "usage", "request_id", "model", "latency_seconds", "request_bytes"}
_RESERVED_FIELDS = {"key", "status", "charged_or_reserved_usd"}
_CHARGED_INVALID_FIELDS = _RESERVED_FIELDS | {"usage", "request_bytes"}
_ENVELOPE_FIELDS = {"sequence", "previous_sha256", "record_sha256", "prior_sha256"}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _decimal(value, *, stored=False):
    allowed = (int, float, Decimal, str) if stored else (int, float, Decimal)
    if isinstance(value, bool) or not isinstance(value, allowed):
        raise ValueError("cost must be a finite nonnegative number")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid decimal cost") from exc
    if not number.is_finite() or number < 0:
        raise ValueError("cost must be a finite nonnegative number")
    return number


def _integer(value, name, *, minimum=0, maximum=None):
    if (isinstance(value, bool) or not isinstance(value, int) or value < minimum
            or (maximum is not None and value > maximum)):
        raise ValueError(f"invalid {name}")
    return value


def _number(value, name, *, maximum=None):
    if (isinstance(value, bool) or not isinstance(value, (int, float, Decimal))
            or not math.isfinite(value) or value < 0
            or (maximum is not None and value > maximum)):
        raise ValueError(f"invalid {name}")
    return float(value)


def _hash_string(value):
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


def _names(values):
    if (not isinstance(values, list) or not values
            or any(not isinstance(v, str) or not v for v in values)
            or len(set(values)) != len(values) or values != sorted(values)):
        raise ValueError("invalid question names")
    return values


def _validate_complete(row, *, stored):
    cost = _decimal(row["charged_or_reserved_usd"], stored=stored)
    usage = row["usage"]
    if not isinstance(usage, dict) or set(usage) != {"cost", "input_tokens", "output_tokens"}:
        raise ValueError("invalid usage shape")
    if cost != _decimal(usage["cost"], stored=stored):
        raise ValueError("recorded cost differs from usage cost")
    for field in ("input_tokens", "output_tokens"):
        _integer(usage[field], field,
                 maximum=MAX_INPUT_TOKENS if field == "input_tokens" else None)
    adherence = row["adherence"]
    if (not isinstance(adherence, dict) or not adherence
            or any(not isinstance(k, str) or not k for k in adherence)):
        raise ValueError("invalid adherence shape")
    for value in adherence.values():
        _number(value, "adherence", maximum=1)
    model = row["model"]
    if not isinstance(model, str) or not (model == MODEL or model.startswith(MODEL + "-")):
        raise ValueError("unexpected returned model")
    if not isinstance(row["request_id"], str) or not 0 < len(row["request_id"]) <= 512:
        raise ValueError("invalid request ID")
    _number(row["latency_seconds"], "latency")
    _integer(row["request_bytes"], "request size", minimum=1, maximum=MAX_REQUEST_BYTES)
    return cost


def _read_rows(data, *, decimal_numbers=False):
    if not data:
        return []
    if not data.endswith(b"\n"):
        raise ValueError("truncated ledger: final newline missing")
    rows = []
    for line in data.decode("utf-8", errors="strict").splitlines():
        if not line.strip():
            raise ValueError("blank ledger row")
        kwargs = {"parse_float": Decimal} if decimal_numbers else {}
        row = json.loads(line, object_pairs_hook=_unique_object, **kwargs)
        if not isinstance(row, dict):
            raise ValueError("ledger row must be an object")
        rows.append(row)
    return rows


def _legacy_ledger(data):
    latest = {}
    for row in _read_rows(data, decimal_numbers=True):
        key, status = row.get("key"), row.get("status")
        if not _hash_string(key) or status not in ("reserved", "complete"):
            raise ValueError("invalid prior ledger key or status")
        if status == "reserved":
            if set(row) != _RESERVED_FIELDS or key in latest:
                raise ValueError("invalid or duplicate prior reservation")
            if _decimal(row["charged_or_reserved_usd"]) != RESERVATION_USD:
                raise ValueError("invalid prior reservation amount")
        else:
            if (set(row) != _COMPLETE_FIELDS or key not in latest
                    or latest[key]["status"] != "reserved"):
                raise ValueError("invalid prior completion transition")
            _validate_complete(row, stored=False)
        latest[key] = row
    return latest


def _json_state(value):
    if isinstance(value, dict):
        if any(not isinstance(k, str) for k in value):
            raise ValueError("state object keys must be strings")
        for item in value.values():
            _json_state(item)
    elif isinstance(value, list):
        for item in value:
            _json_state(item)
    elif value is None or isinstance(value, (str, bool, int)):
        return
    elif isinstance(value, float) and math.isfinite(value):
        return
    else:
        raise ValueError("state must contain finite JSON values")


def _post(request, timeout_seconds):
    # Intentionally one call, without automatic retry even after HTTP errors.
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"),
                          object_pairs_hook=_unique_object, parse_float=Decimal)


def decision_key(state, questions, model=MODEL):
    """Offline cache key for the exact model/questions/state request body."""
    _json_state(state)
    _json_state(questions)
    return _sha(_canonical({"model": model, "questions": questions, "state": state}))


class BudgetedJevClient:
    """Context-managed cache. The caller must await its submitted worker tasks.

    ``spent`` includes the required legacy ledger and latest new-cache records.
    All questions and state fields are sent in a single POST per distinct state.
    Returns adherence scores only; deciding exposure belongs to the caller.
    """

    def __init__(self, *, path: Path, prior_path: Path, questions: dict,
                 api_key: str | None = None, budget_usd=MAX_BUDGET_USD,
                 transport=None, timeout_seconds=45, max_in_flight=4):
        self.path, self.prior_path = Path(path), Path(prior_path)
        if self.path.resolve() == self.prior_path.resolve():
            raise ValueError("new and prior ledgers must be distinct")
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.budget_usd = _decimal(budget_usd, stored=True)
        if self.budget_usd > MAX_BUDGET_USD:
            raise ValueError("budget exceeds USD 2 authorization")
        _integer(max_in_flight, "max in flight", minimum=1, maximum=4)
        if _number(timeout_seconds, "timeout", maximum=90) == 0:
            raise ValueError("timeout must be positive")
        if not isinstance(questions, dict) or not questions:
            raise ValueError("questions must be a nonempty object")
        for name, question in questions.items():
            if (not isinstance(name, str) or not name or not isinstance(question, dict)
                    or set(question) != {"type", "instructions"}
                    or question["type"] != "noul"
                    or not isinstance(question["instructions"], str)
                    or not question["instructions"].strip()):
                raise ValueError("questions must request only numeric adherence")
        self._questions = copy.deepcopy(questions)
        self._api_key = api_key
        self._transport = transport or _post
        self._timeout = timeout_seconds
        self._condition = threading.Condition(threading.RLock())
        self._slots = threading.Semaphore(max_in_flight)
        self._latest = {}
        self._prior_latest = {}
        self._active = 0
        self._entered = self._closing = self._stopped = self._used = False
        self._lock_bytes = None
        self._cache_bytes = b""
        self._last_hash = _ZERO_HASH
        self._sequence = 0

    def __enter__(self):
        if self._used:
            raise RuntimeError("client context cannot be reused; construct a new client")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        token = _canonical({"owner": uuid.uuid4().hex, "pid": os.getpid()}) + b"\n"
        fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        self._used = True
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(token)
                stream.flush()
                os.fsync(stream.fileno())
            self._lock_bytes = token
            self._prior_bytes = self.prior_path.read_bytes()
            self.prior_sha256 = _sha(self._prior_bytes)
            self._prior_latest = _legacy_ledger(self._prior_bytes)
            self._cache_bytes = self.path.read_bytes() if self.path.exists() else b""
            self._load_cache()
            self._stopped = any(
                row["status"] == "reserved"
                or _decimal(row["charged_or_reserved_usd"], stored=True) > RESERVATION_USD
                for row in (*self._prior_latest.values(), *self._latest.values()))
            self._entered = True
            return self
        except BaseException:
            self._release_lock()
            raise

    def _release_lock(self):
        if self._lock_bytes is not None:
            if not self.lock_path.exists() or self.lock_path.read_bytes() != self._lock_bytes:
                raise RuntimeError("cache lock ownership changed; lock preserved")
            self.lock_path.unlink()
            self._lock_bytes = None

    def __exit__(self, exc_type, exc, traceback):
        with self._condition:
            self._closing = True
            while self._active:
                self._condition.wait()
            self._entered = False
            self._release_lock()
        return False

    def _load_cache(self):
        for row in _read_rows(self._cache_bytes):
            if not _ENVELOPE_FIELDS <= set(row):
                raise ValueError("cache hash envelope missing")
            digest = row["record_sha256"]
            unsigned = {k: v for k, v in row.items() if k != "record_sha256"}
            if (not _hash_string(digest) or _sha(_canonical(unsigned)) != digest
                    or row["previous_sha256"] != self._last_hash
                    or _integer(row["sequence"], "sequence", minimum=1) != self._sequence + 1
                    or row["prior_sha256"] != self.prior_sha256):
                raise ValueError("cache chain or prior ledger fingerprint mismatch")
            record = {k: v for k, v in row.items() if k not in _ENVELOPE_FIELDS}
            self._validate_transition(record)
            self._latest[record["key"]] = record
            self._sequence, self._last_hash = row["sequence"], digest

    def _validate_transition(self, row):
        key, status = row.get("key"), row.get("status")
        if not _hash_string(key) or status not in ("reserved", "complete", "charged_invalid"):
            raise ValueError("invalid cache key or status")
        if status == "reserved":
            expected = _RESERVED_FIELDS | {"question_names", "request_bytes"}
            if set(row) != expected or key in self._latest:
                raise ValueError("invalid or duplicate cache reservation")
            _names(row["question_names"])
            _integer(row["request_bytes"], "request size", minimum=1, maximum=MAX_REQUEST_BYTES)
            if _decimal(row["charged_or_reserved_usd"], stored=True) != RESERVATION_USD:
                raise ValueError("invalid cache reservation amount")
        elif status == "complete":
            previous = self._latest.get(key)
            if set(row) != _COMPLETE_FIELDS or not previous or previous["status"] != "reserved":
                raise ValueError("invalid cache completion transition")
            _validate_complete(row, stored=True)
            if (sorted(row["adherence"]) != previous["question_names"]
                    or row["request_bytes"] != previous["request_bytes"]):
                raise ValueError("completion differs from reserved request")
        else:
            previous = self._latest.get(key)
            if (set(row) != _CHARGED_INVALID_FIELDS or not previous
                    or previous["status"] != "reserved"
                    or row["request_bytes"] != previous["request_bytes"]
                    or not isinstance(row["usage"], dict) or set(row["usage"]) != {"cost"}):
                raise ValueError("invalid known-charge transition")
            cost = _decimal(row["charged_or_reserved_usd"], stored=True)
            if cost <= RESERVATION_USD or cost != _decimal(row["usage"]["cost"], stored=True):
                raise ValueError("invalid known excess charge")

    def _check_files(self):
        if self.prior_path.read_bytes() != self._prior_bytes:
            self._stopped = True
            raise RuntimeError("prior cost ledger changed; spending stopped")
        current = self.path.read_bytes() if self.path.exists() else b""
        if current != self._cache_bytes:
            self._stopped = True
            raise RuntimeError("cache changed outside this client; spending stopped")
        if not self.lock_path.exists() or self.lock_path.read_bytes() != self._lock_bytes:
            self._stopped = True
            raise RuntimeError("cache lock ownership changed; spending stopped")

    def _write(self, record):
        self._check_files()
        self._validate_transition(record)
        row = dict(record, sequence=self._sequence + 1,
                   previous_sha256=self._last_hash, prior_sha256=self.prior_sha256)
        row["record_sha256"] = _sha(_canonical(row))
        data = _canonical(row) + b"\n"
        with self.path.open("ab") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        self._cache_bytes += data
        self._sequence, self._last_hash = row["sequence"], row["record_sha256"]
        self._latest[record["key"]] = copy.deepcopy(record)

    @property
    def questions(self):
        return copy.deepcopy(self._questions)

    @property
    def prior_spent(self):
        with self._condition:
            return sum((_decimal(r["charged_or_reserved_usd"], stored=True)
                        for r in self._prior_latest.values()), Decimal(0))

    @property
    def spent(self):
        with self._condition:
            return self.prior_spent + sum((_decimal(r["charged_or_reserved_usd"], stored=True)
                                          for r in self._latest.values()), Decimal(0))

    @property
    def cached(self):
        with self._condition:
            return copy.deepcopy({k: r for k, r in self._latest.items() if r["status"] == "complete"})

    def _body(self, state):
        if not isinstance(state, dict):
            raise ValueError("state must be one market-record object")
        _json_state(state)
        body = _canonical({"model": MODEL, "questions": self._questions, "state": state})
        if len(body) > MAX_REQUEST_BYTES:
            raise ValueError("request exceeds bounded input size")
        return body

    def key(self, state):
        return _sha(self._body(state))

    def decide(self, state):
        body = self._body(state)
        key = _sha(body)
        with self._condition:
            if not self._entered or self._closing:
                raise RuntimeError("use client inside an active context")
            self._active += 1
        try:
            with self._slots:
                return self._decide(key, body)
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify_all()

    def _decide(self, key, body):
        with self._condition:
            self._check_files()
            previous = self._latest.get(key)
            if previous and previous["status"] == "complete":
                return copy.deepcopy(previous)
            if previous:
                raise RuntimeError("incomplete request requires charge review; automatic retry refused")
            prior = self._prior_latest.get(key)
            if prior:
                if prior["status"] != "complete":
                    raise RuntimeError("prior incomplete request requires charge review; automatic retry refused")
                # A matching request can be reused across ledgers without a new charge.
                reused = copy.deepcopy(prior)
                reused["charged_or_reserved_usd"] = str(_decimal(prior["charged_or_reserved_usd"]))
                reused["usage"]["cost"] = reused["charged_or_reserved_usd"]
                reused["adherence"] = {k: float(v) for k, v in prior["adherence"].items()}
                reused["latency_seconds"] = float(prior["latency_seconds"])
                return reused
            if self._stopped:
                raise RuntimeError("client stopped after uncertain or excessive charge")
            if not self._api_key:
                raise RuntimeError("cached decision absent; paid replay not enabled")
            if self.spent + RESERVATION_USD > self.budget_usd:
                raise RuntimeError("authorized cumulative API budget exhausted")
            self._write({"key": key, "status": "reserved",
                         "charged_or_reserved_usd": str(RESERVATION_USD),
                         "question_names": sorted(self._questions), "request_bytes": len(body)})
        started = time.perf_counter()
        payload = None
        try:
            request = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
                "Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"})
            payload = self._transport(request, self._timeout)
            latency = time.perf_counter() - started
            record = self._response(payload, key, len(body), latency)
            with self._condition:
                self._write(record)
                if _decimal(record["charged_or_reserved_usd"], stored=True) > RESERVATION_USD:
                    self._stopped = True
                    raise RuntimeError("actual API charge exceeds reserve; recorded and spending stopped")
            return copy.deepcopy(record)
        except BaseException:
            with self._condition:
                self._stopped = True
                self._retain_known_excess(payload, key, len(body))
            raise

    def _retain_known_excess(self, payload, key, request_bytes):
        """Malformed scores cannot hide a known charge exceeding its reserve."""
        if (self._latest[key]["status"] != "reserved" or not isinstance(payload, dict)
                or not isinstance(payload.get("usage"), dict)):
            return
        try:
            cost = _decimal(payload["usage"].get("cost"))
        except ValueError:
            return
        if cost > RESERVATION_USD:
            self._write({"key": key, "status": "charged_invalid",
                         "charged_or_reserved_usd": str(cost), "usage": {"cost": str(cost)},
                         "request_bytes": request_bytes})

    def _response(self, payload, key, request_bytes, latency):
        if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict):
            raise ValueError("missing adherence answers; reserved charge retained")
        answers = payload["answers"]
        if set(answers) != set(self._questions):
            raise ValueError("criterion answer IDs differ; reserved charge retained")
        adherence = {}
        for name, answer in answers.items():
            if not isinstance(answer, dict) or set(answer) != {"type", "noul"} or answer["type"] != "noul":
                raise ValueError("invalid criterion answer; reserved charge retained")
            adherence[name] = _number(answer["noul"], "adherence", maximum=1)
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            raise ValueError("missing usage; reserved charge retained")
        cost = _decimal(usage.get("cost"))
        safe_usage = {"cost": str(cost)}
        for field in ("input_tokens", "output_tokens"):
            safe_usage[field] = _integer(usage.get(field), field)
        row = {"key": key, "status": "complete", "charged_or_reserved_usd": str(cost),
               "adherence": adherence, "usage": safe_usage, "request_id": payload.get("id"),
               "model": payload.get("model"), "latency_seconds": latency,
               "request_bytes": request_bytes}
        _validate_complete(row, stored=True)
        return row
