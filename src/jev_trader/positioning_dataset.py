"""Verify a complete positioning cache offline and summarize data quality.

This audit proves byte integrity and agreement with the acquisition plan. It
does not establish when historical values were first available to traders.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from .metrics_fetch import _validated_record, fetch
from .positioning_metrics import METRIC_FIELDS


def canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _offline_reader(url: str, maximum_bytes: int) -> bytes:
    raise ValueError("network is disabled during positioning dataset verification")


def _identity(row: dict, cohort: set[str], days: set[str]) -> tuple[str, str]:
    if not isinstance(row, dict):
        raise ValueError("plan entries must be objects")
    symbol, day = row.get("symbol"), row.get("day")
    if not isinstance(symbol, str) or symbol not in cohort or not isinstance(day, str) or day not in days:
        raise ValueError("plan identity is outside its cohort or fixed calendar")
    return symbol, day


def _validate_plan(plan: dict) -> list[dict]:
    if not isinstance(plan, dict) or not isinstance(plan.get("config"), dict):
        raise ValueError("invalid acquisition plan")
    if (plan.get("historical_point_in_time_verified") is not False
            or plan["config"].get("historical_point_in_time_verified") is not False):
        raise ValueError("archive plan cannot assert historical point-in-time availability")
    cohort = plan.get("cohort")
    if (not isinstance(cohort, list) or not cohort
            or any(not isinstance(symbol, str) for symbol in cohort)
            or len(set(cohort)) != len(cohort)):
        raise ValueError("invalid or duplicate acquisition cohort")
    try:
        first = date.fromisoformat(plan["config"]["first_friday"])
        last = date.fromisoformat(plan["config"]["last_friday"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid acquisition calendar") from exc
    if first > last or first.weekday() != 4 or last.weekday() != 4:
        raise ValueError("acquisition calendar must run from Friday to Friday")
    count = (last - first).days // 7 + 1
    if type(plan.get("expected_fridays_per_symbol")) is not int or plan["expected_fridays_per_symbol"] != count:
        raise ValueError("acquisition calendar count differs from plan")
    days = {(first + timedelta(days=7 * index)).isoformat() for index in range(count)}
    expected = {(symbol, day) for symbol in cohort for day in days}
    seen = set()
    jobs = []
    for category in ("jobs", "missing_pairs", "post_settlement_exclusions"):
        records = plan.get(category)
        if not isinstance(records, list):
            raise ValueError(f"plan {category} must be a list")
        for row in records:
            identity = _identity(row, set(cohort), days)
            if identity in seen:
                raise ValueError("duplicate or overlapping identity in acquisition plan")
            seen.add(identity)
            if category == "jobs":
                jobs.append(_validated_record(row))
    if seen != expected:
        raise ValueError("acquisition plan does not account for its complete cohort calendar")
    return sorted(jobs, key=lambda row: (row["symbol"], row["day"]))


def _paths(cache: Path, job: dict) -> dict[str, Path]:
    basename = job["zip"]["key"].rsplit("/", 1)[1]
    directory = cache / job["symbol"]
    paths = {"record": directory / (basename + ".record.json"),
             "zip": directory / basename, "checksum": directory / (basename + ".CHECKSUM")}
    for path in paths.values():
        if path.is_symlink() or not path.resolve().is_relative_to(cache):
            raise ValueError("dataset file escapes cache or is a symbolic link")
    return paths


def _empty_counts() -> dict:
    return {"records": 0, "usable_snapshots": 0, "unavailable_snapshots": 0,
            "zip_bytes": 0, "checksum_bytes": 0, "raw_rows": 0, "unique_rows": 0,
            "identical_duplicate_rows": 0, "missing_slots": 0, "expected_slots": 0,
            "minimum_unique_rows": None, "minimum_daily_coverage_pct": None,
            "observed_slot_coverage_pct": None,
            "minimum_field_valid_counts": {field: None for field in METRIC_FIELDS},
            "minimum_field_positive_counts": {field: None for field in METRIC_FIELDS},
            "field_zero_counts": {field: 0 for field in METRIC_FIELDS},
            "unavailable_reason_counts": {}}


def _minimum(old, value):
    return value if old is None else min(old, value)


def _add(counts: dict, result: dict) -> None:
    quality = result["quality"]
    state = result["snapshot"]
    counts["records"] += 1
    counts["usable_snapshots"] += int(state["available"])
    counts["unavailable_snapshots"] += int(not state["available"])
    for kind in ("zip", "checksum"):
        counts[kind + "_bytes"] += result[kind]["bytes"]
    for field in ("raw_rows", "unique_rows", "missing_slots", "expected_slots"):
        counts[field] += quality[field]
    counts["identical_duplicate_rows"] += quality["duplicate_rows"]
    counts["minimum_unique_rows"] = _minimum(counts["minimum_unique_rows"], quality["unique_rows"])
    coverage = 100 * quality["unique_rows"] / quality["expected_slots"]
    counts["minimum_daily_coverage_pct"] = _minimum(counts["minimum_daily_coverage_pct"], coverage)
    counts["observed_slot_coverage_pct"] = 100 * counts["unique_rows"] / counts["expected_slots"]
    for field in METRIC_FIELDS:
        for source, target in (("field_valid_counts", "minimum_field_valid_counts"),
                               ("field_positive_counts", "minimum_field_positive_counts")):
            counts[target][field] = _minimum(counts[target][field], quality[source][field])
        counts["field_zero_counts"][field] += quality["field_zero_counts"][field]
    for reason in state["reasons"]:
        counts["unavailable_reason_counts"][reason] = counts["unavailable_reason_counts"].get(reason, 0) + 1


def load_verified(plan: dict, cache: Path) -> tuple[dict, dict]:
    """Return ``snapshots[symbol][day]`` and a deterministic offline audit.

    Every planned record and both source files must exist before verification
    starts. Extra records and orphan source files are rejected. Existing bytes
    are hashed before and after the frozen fetcher's offline revalidation.
    """
    jobs = _validate_plan(plan)
    cache = Path(cache).resolve()
    plan_path = cache / "acquisition_plan.json"
    if not plan_path.is_file() or plan_path.is_symlink():
        raise ValueError("preserved acquisition_plan.json is required")
    raw_plan = plan_path.read_bytes()
    if json.loads(raw_plan.decode("utf-8")) != plan:
        raise ValueError("supplied plan differs from preserved acquisition plan")
    paths = {(job["symbol"], job["day"]): _paths(cache, job) for job in jobs}
    expected_files = {path for triple in paths.values() for path in triple.values()}
    missing = sorted(str(path.relative_to(cache)) for path in expected_files if not path.is_file())
    if missing:
        raise ValueError(f"incomplete positioning cache: {len(missing)} required files missing; first={missing[0]}")
    expected_records = {triple["record"] for triple in paths.values()}
    actual_records = set(cache.rglob("*.record.json"))
    if actual_records != expected_records:
        raise ValueError("unexpected record files outside the acquisition plan")
    source_files = {path for path in cache.glob("*/*")
                    if path.is_file() and (path.name.endswith(".zip") or path.name.endswith(".zip.CHECKSUM"))}
    if source_files != expected_files - expected_records:
        raise ValueError("unexpected or orphan source files outside the acquisition plan")
    initial_hashes = {path: _sha(path) for path in sorted(expected_files)}
    initial_plan_hash = hashlib.sha256(raw_plan).hexdigest()
    snapshots = {symbol: {} for symbol in sorted(plan["cohort"])}
    totals = _empty_counts()
    by_symbol = {symbol: _empty_counts() for symbol in sorted(plan["cohort"])}
    by_year, by_symbol_year = {}, {symbol: {} for symbol in sorted(plan["cohort"])}
    unavailable, manifest, modified = [], [], []
    modified_after_day = 0
    for job in jobs:
        symbol, day = job["symbol"], job["day"]
        triple = paths[(symbol, day)]
        result = fetch(job, cache, reader=_offline_reader)
        if (result.get("cache_hit") is not True or result.get("symbol") != symbol
                or result.get("day") != day or result.get("catalogue") != job
                or Path(result.get("record_path", "")).resolve() != triple["record"].resolve()):
            raise ValueError("verified record identity differs from acquisition plan")
        state = result["snapshot"]
        if (state.get("symbol") != symbol or state.get("day") != day
                or type(state.get("available")) is not bool or state.get("quality") != result["quality"]
                or state.get("original_publication_time_known") is not False):
            raise ValueError("verified snapshot identity or provenance differs from plan")
        row = {"symbol": symbol, "day": day, "available": state["available"], "files": {}}
        for kind, path in triple.items():
            digest = _sha(path)
            if digest != initial_hashes[path]:
                raise ValueError("existing source or record bytes changed during verification")
            row["files"][kind] = {"path": path.relative_to(cache).as_posix(), "sha256": digest,
                                   "bytes": path.stat().st_size}
            if kind != "record":
                if (result[kind]["sha256"] != digest or result[kind]["bytes"] != path.stat().st_size
                        or Path(result[kind]["path"]).resolve() != path.resolve()):
                    raise ValueError("verified source provenance differs from cached bytes")
                row["files"][kind]["last_modified"] = job[kind]["last_modified"]
                modified.append(datetime.fromisoformat(job[kind]["last_modified"].replace("Z", "+00:00"))
                                .astimezone(timezone.utc))
        row["record_first_observed_utc"] = result["first_observed_utc"]
        modified_after_day += int(any(datetime.fromisoformat(job[kind]["last_modified"].replace("Z", "+00:00"))
                                      .astimezone(timezone.utc).date()
                                      > date.fromisoformat(day) for kind in ("zip", "checksum")))
        manifest.append(row)
        snapshots[symbol][day] = state
        year = day[:4]
        groups = (totals, by_symbol[symbol], by_year.setdefault(year, _empty_counts()),
                  by_symbol_year[symbol].setdefault(year, _empty_counts()))
        for group in groups:
            _add(group, result)
        if not state["available"]:
            unavailable.append({"symbol": symbol, "day": day, "reasons": state["reasons"],
                                "quality": result["quality"]})
    if _sha(plan_path) != initial_plan_hash:
        raise ValueError("acquisition plan bytes changed during verification")
    # Detect modification of an earlier record while subsequent records were read.
    if any(_sha(path) != digest for path, digest in initial_hashes.items()):
        raise ValueError("existing source or record bytes changed before audit completion")
    final_sources = {path for path in cache.glob("*/*")
                     if path.is_file() and (path.name.endswith(".zip") or path.name.endswith(".zip.CHECKSUM"))}
    if set(cache.rglob("*.record.json")) != expected_records or final_sources != source_files:
        raise ValueError("dataset file inventory changed during verification")
    audit = {"schema_version": 1, "plan_sha256": initial_plan_hash,
             "plan_canonical_sha256": hashlib.sha256(canonical_bytes(plan)).hexdigest(),
             "total_records": len(jobs), "usable_snapshots": totals["usable_snapshots"],
             "unavailable_snapshots": totals["unavailable_snapshots"], "all_planned_records_verified": True,
             "catalog_missing_pairs": len(plan["missing_pairs"]),
             "post_settlement_exclusions": len(plan["post_settlement_exclusions"]),
             "totals": totals, "by_symbol": by_symbol, "by_year": by_year,
             "by_symbol_year": by_symbol_year, "unavailable_details": unavailable,
             "manifest": manifest, "manifest_sha256": hashlib.sha256(canonical_bytes(manifest)).hexdigest(),
             "source_last_modified_min_utc": min(modified).isoformat() if modified else None,
             "source_last_modified_max_utc": max(modified).isoformat() if modified else None,
             "records_with_any_last_modified_after_archive_day": modified_after_day,
             "historical_point_in_time_verified": False, "network_requests": 0,
             "existing_files_modified": False,
             "unchanged_file_scope": "Acquisition plan and all planned records, ZIPs and checksums.",
             "limitation": "Archive integrity and catalogue agreement do not establish original historical publication or availability."}
    return snapshots, audit
