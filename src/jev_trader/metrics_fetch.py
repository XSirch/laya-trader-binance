"""Bounded, resumable acquisition of public Binance positioning archives.

``fetch`` raises ValueError for untrusted metadata, corrupt or changed cache,
and invalid archive content; RuntimeError for a busy record or exhausted
transport retries. Invalid content is retained under ``quarantine`` without
replacing any previously verified record. Nothing is extracted from a ZIP.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from .positioning_metrics import parse_metrics, snapshot

ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "https://data.binance.vision/"
ZIP_LIMIT = 2 * 1024 * 1024
CHECKSUM_LIMIT = 4096
ATTEMPTS = 3
Reader = Callable[[str, int], bytes]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, stream, code, message, headers, new_url):
        raise ValueError("archive redirect is not allowed")


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _validated_record(record: dict) -> dict:
    if not isinstance(record, dict):
        raise ValueError("catalogue record must be an object")
    symbol, day = record.get("symbol"), record.get("day")
    if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z0-9]{2,30}", symbol):
        raise ValueError("invalid catalogue symbol")
    if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("invalid catalogue day")
    date.fromisoformat(day)
    key = f"data/futures/um/daily/metrics/{symbol}/{symbol}-metrics-{day}.zip"
    result = {"symbol": symbol, "day": day}
    for kind, expected, limit in (("zip", key, ZIP_LIMIT),
                                  ("checksum", key + ".CHECKSUM", CHECKSUM_LIMIT)):
        item = record.get(kind)
        if not isinstance(item, dict) or item.get("key") != expected:
            raise ValueError(f"invalid {kind} catalogue key")
        size = item.get("size")
        if type(size) is not int or not 0 < size <= limit:
            raise ValueError(f"invalid or oversized {kind} catalogue size")
        modified, etag = item.get("last_modified"), item.get("etag")
        if not isinstance(modified, str) or not modified or len(modified) > 100:
            raise ValueError(f"invalid {kind} last_modified")
        try:
            stamp = datetime.fromisoformat(modified.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"invalid {kind} last_modified") from exc
        if stamp.utcoffset() is None:
            raise ValueError(f"timezone missing from {kind} last_modified")
        if (not isinstance(etag, str) or not etag or len(etag) > 200
                or any(ord(character) < 32 or ord(character) > 126 for character in etag)):
            raise ValueError(f"invalid {kind} etag")
        result[kind] = {"key": expected, "size": size,
                        "last_modified": modified, "etag": etag}
    return result


def _read_url(url: str, limit: int, etag: str) -> bytes:
    """Bound bytes before allocation; bind default reads to the listed version."""
    quoted_etag = etag if etag.startswith('"') else f'"{etag}"'
    request = urllib.request.Request(url, headers={
        "User-Agent": "jev-binance-research/0.1", "If-Match": quoted_etag})
    with urllib.request.build_opener(_NoRedirect()).open(request, timeout=30) as response:
        if response.geturl() != url:
            raise ValueError("archive redirect is not allowed")
        response_etag = response.headers.get("ETag")
        if response_etag is not None and response_etag.strip('"') != etag.strip('"'):
            raise ValueError("downloaded version does not match catalogue etag")
        declared = response.headers.get("Content-Length")
        if declared is not None and (not declared.isdigit() or int(declared) > limit):
            raise ValueError("oversized or invalid archive Content-Length")
        payload = response.read(limit + 1)
    if len(payload) > limit:
        raise ValueError("archive response exceeds byte limit")
    return payload


def _download(item: dict, limit: int, reader: Reader | None,
              sleeper: Callable[[float], None]) -> bytes:
    url = BASE_URL + item["key"]
    for attempt in range(ATTEMPTS):
        try:
            payload = (reader(url, limit) if reader is not None
                       else _read_url(url, limit, item["etag"]))
            if not isinstance(payload, bytes):
                raise ValueError("archive reader must return bytes")
            if len(payload) > limit:
                raise ValueError("archive response exceeds byte limit")
            return payload
        except urllib.error.HTTPError as exc:
            transient = exc.code == 429 or 500 <= exc.code <= 599
            if not transient or attempt == ATTEMPTS - 1:
                raise RuntimeError(f"archive HTTP {exc.code}: {url}") from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            if attempt == ATTEMPTS - 1:
                raise RuntimeError(f"archive transport failed after {ATTEMPTS} attempts: {url}") from exc
        sleeper(float(2 ** attempt))
    raise AssertionError("unreachable retry state")


def _safe_path(root: Path, path: Path) -> Path:
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError("cache path escapes root or is a symbolic link")
    return path


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=path.name + ".", suffix=".part",
                                         dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _checksum(payload: bytes, filename: str) -> str:
    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("checksum is not ASCII") from exc
    match = re.fullmatch(r"([0-9a-fA-F]{64})[ \t]+\*?([^\r\n]+)[\r\n]*", text)
    if match is None or match[2] != filename:
        raise ValueError("checksum must identify exactly the expected ZIP basename")
    return match[1].lower()


def _cached_bytes(path: Path, limit: int) -> bytes:
    if path.stat().st_size > limit:
        raise ValueError(f"oversized cached file: {path.name}")
    with path.open("rb") as stream:
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise ValueError(f"oversized cached file: {path.name}")
    return payload


def _quarantine(root: Path, catalogue: dict, payloads: dict[str, bytes], error: Exception) -> None:
    directory = _safe_path(root, root / "quarantine" / catalogue["symbol"])
    directory.mkdir(parents=True, exist_ok=True)
    evidence = {"catalogue": catalogue, "error": str(error), "payloads": {}}
    basename = f"{catalogue['symbol']}-metrics-{catalogue['day']}"
    for kind, payload in payloads.items():
        name = f"{basename}.{_sha(payload)}.{kind}"
        target = _safe_path(root, directory / name)
        if not target.exists():
            _atomic_write(target, payload)
        evidence["payloads"][kind] = {"path": str(target), "bytes": len(payload), "sha256": _sha(payload)}
    raw = _json_bytes(evidence)
    target = _safe_path(root, directory / f"{basename}.{_sha(raw)}.failure.json")
    if not target.exists():
        _atomic_write(target, raw)


def fetch(record: dict, root: Path = ROOT / "data/binance/positioning", *,
          reader: Reader | None = None,
          sleeper: Callable[[float], None] = time.sleep) -> dict:
    """Acquire one catalogue pair, or verify its cached bytes without a request.

    Injected readers take ``(url, maximum_bytes)`` and return bytes. Per-file
    retries are bounded to three attempts with 1s/2s backoff. A complete cache
    retains its first observation timestamp and refuses catalogue changes.
    """
    catalogue = _validated_record(record)
    root = Path(root).resolve()
    directory = _safe_path(root, root / catalogue["symbol"])
    directory.mkdir(parents=True, exist_ok=True)
    basename = Path(catalogue["zip"]["key"]).name
    paths = {"zip": _safe_path(root, directory / basename),
             "checksum": _safe_path(root, directory / (basename + ".CHECKSUM"))}
    record_path = _safe_path(root, directory / (basename + ".record.json"))
    lock = _safe_path(root, directory / (basename + ".lock"))
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError(f"archive fetch already locked: {basename}") from exc
    os.close(descriptor)
    payloads: dict[str, bytes] = {}
    try:
        existing = None
        fingerprint = _sha(_json_bytes(catalogue))
        if record_path.exists():
            existing = json.loads(_cached_bytes(record_path, 1024 * 1024).decode("utf-8"))
            if (not isinstance(existing, dict) or existing.get("catalogue") != catalogue
                    or existing.get("catalogue_sha256") != fingerprint):
                raise ValueError("catalogue version changed; verified record will not be overwritten")
            if (existing.get("schema_version") != 1 or existing.get("symbol") != catalogue["symbol"]
                    or existing.get("day") != catalogue["day"]
                    or any(not isinstance(existing.get(kind), dict) for kind in ("zip", "checksum"))
                    or not isinstance(existing.get("first_observed_utc"), str)):
                raise ValueError("invalid verified cache record")
            try:
                observation = datetime.fromisoformat(existing["first_observed_utc"])
            except ValueError as exc:
                raise ValueError("invalid cache observation timestamp") from exc
            if observation.utcoffset() is None:
                raise ValueError("cache observation timestamp has no timezone")
        cache_hit = all(path.exists() for path in paths.values()) and existing is not None
        for kind, limit in (("checksum", CHECKSUM_LIMIT), ("zip", ZIP_LIMIT)):
            path = paths[kind]
            payload = (_cached_bytes(path, limit) if path.exists()
                       else _download(catalogue[kind], limit, reader, sleeper))
            payloads[kind] = payload
            if len(payload) != catalogue[kind]["size"]:
                raise ValueError(f"{kind} byte count differs from catalogue")
            if existing is not None:
                expected = existing.get(kind, {})
                if (expected.get("sha256") != _sha(payload) or expected.get("bytes") != len(payload)
                        or expected.get("url") != BASE_URL + catalogue[kind]["key"]):
                    raise ValueError(f"cached {kind} no longer matches verified record")
        if _sha(payloads["zip"]) != _checksum(payloads["checksum"], basename):
            raise ValueError("ZIP SHA256 does not match the first-party checksum")
        parsed = parse_metrics(payloads["zip"], catalogue["symbol"], catalogue["day"])
        state = snapshot(parsed)
        result = {"schema_version": 1, "symbol": catalogue["symbol"], "day": catalogue["day"],
                  "catalogue": catalogue, "catalogue_sha256": fingerprint,
                  "first_observed_utc": (existing["first_observed_utc"] if existing is not None
                                         else datetime.now(timezone.utc).isoformat()),
                  "quality": parsed["quality"], "snapshot": state}
        for kind in ("zip", "checksum"):
            result[kind] = {"path": str(paths[kind]), "url": BASE_URL + catalogue[kind]["key"],
                            "bytes": len(payloads[kind]), "sha256": _sha(payloads[kind]),
                            "current_version_metadata": catalogue[kind]}
        if existing is not None and existing != result:
            raise ValueError("cached parse or provenance differs from verified record")
        for kind in ("checksum", "zip"):
            if not paths[kind].exists():
                _atomic_write(paths[kind], payloads[kind])
        if existing is None:
            _atomic_write(record_path, _json_bytes(result))
        return {**result, "record_path": str(record_path), "cache_hit": cache_hit}
    except (ValueError, zipfile.BadZipFile, UnicodeError) as exc:
        _quarantine(root, catalogue, payloads, exc)
        raise ValueError(str(exc)) from exc
    finally:
        lock.unlink(missing_ok=True)
