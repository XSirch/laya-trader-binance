"""Immutable, resumable metadata inventory of public Binance derivatives metrics."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = ROOT / "data" / "binance" / "metrics_catalog"
S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
DOWNLOAD = "https://data.binance.vision/"
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"


def _prefix(symbol):
    if not re.fullmatch(r"[A-Z0-9]+", symbol):
        raise ValueError("symbol must be uppercase alphanumeric")
    return f"data/futures/um/daily/metrics/{symbol}/"


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def _json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _immutable(path, raw):
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError(f"immutable snapshot differs: {path}")
        return
    with path.open("xb") as handle:
        handle.write(raw)


def parse_page(raw, prefix, marker=""):
    """Validate a ListObjects v1 page and its forward pagination invariant."""
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("DTD/entity declarations are not allowed")
    root = ET.fromstring(raw)
    if root.tag != NS + "ListBucketResult":
        raise ValueError("unexpected S3 listing root")
    if root.findtext(NS + "Prefix") != prefix:
        raise ValueError("listing prefix mismatch")
    if root.findtext(NS + "Marker", default="") != marker:
        raise ValueError("listing marker mismatch")
    truncated = root.findtext(NS + "IsTruncated")
    if truncated not in ("true", "false"):
        raise ValueError("invalid IsTruncated")
    objects, previous = [], marker
    for node in root.findall(NS + "Contents"):
        key = node.findtext(NS + "Key")
        modified = node.findtext(NS + "LastModified")
        etag = node.findtext(NS + "ETag")
        size_text = node.findtext(NS + "Size")
        if not key or not key.startswith(prefix) or key <= previous:
            raise ValueError("invalid, duplicate or unordered key")
        if not size_text or not size_text.isdecimal() or not etag or not modified:
            raise ValueError("missing or invalid object metadata")
        observed = datetime.fromisoformat(modified.replace("Z", "+00:00"))
        if observed.utcoffset() != timedelta(0):
            raise ValueError("LastModified must include UTC")
        objects.append({"key": key, "size": int(size_text), "last_modified": modified, "etag": etag})
        previous = key
    next_marker = root.findtext(NS + "NextMarker") or (objects[-1]["key"] if objects else "")
    if truncated == "true" and (not objects or next_marker <= marker or next_marker < previous):
        raise ValueError("catalog pagination stalled or moved backwards")
    return {"objects": objects, "is_truncated": truncated == "true",
            "next_marker": next_marker if truncated == "true" else None}


def load_catalog(symbol, root=DEFAULT_ROOT, *, fetcher=None):
    """Return key metadata and raw sources; resume only hash-verified cached pages.

    A fresh call can fetch uncached *listings*, never ZIPs or checksums. Completed
    snapshots are deliberately reused rather than silently refreshed.
    """
    prefix = _prefix(symbol)
    target = Path(root) / symbol
    target.mkdir(parents=True, exist_ok=True)
    fetcher = fetcher or _read
    marker, number, objects, sources = "", 0, {}, []
    while True:
        params = {"prefix": prefix, "max-keys": 1000}
        if marker:
            params["marker"] = marker
        url = S3 + "?" + urllib.parse.urlencode(params)
        metadata_path = target / f"page-{number:05d}.json"
        if metadata_path.exists():
            source = json.loads(metadata_path.read_text(encoding="utf-8"))
            if source["url"] != url or source["page"] != number:
                raise ValueError("cached page request mismatch")
            name = source["raw_file"]
            if Path(name).name != name or not re.fullmatch(r"page-\d{5}-[0-9a-f]{64}\.xml", name):
                raise ValueError("invalid raw snapshot filename")
            raw = (target / name).read_bytes()
            if _sha(raw) != source["sha256"] or len(raw) != source["bytes"]:
                raise ValueError("cached raw snapshot hash mismatch")
            retrieved = datetime.fromisoformat(source["retrieved_utc"].replace("Z", "+00:00"))
            if retrieved.utcoffset() != timedelta(0):
                raise ValueError("retrieval timestamp must include UTC")
        else:
            raw = fetcher(url)
            page = parse_page(raw, prefix, marker)
            sha = _sha(raw)
            source = {"page": number, "url": url, "sha256": sha, "bytes": len(raw),
                      "retrieved_utc": datetime.now(timezone.utc).isoformat(),
                      "raw_file": f"page-{number:05d}-{sha}.xml"}
            _immutable(target / source["raw_file"], raw)
            _immutable(metadata_path, _json_bytes(source))
        page = parse_page(raw, prefix, marker)
        for item in page["objects"]:
            if item["key"] in objects:
                raise ValueError("duplicate key across catalog pages")
            objects[item["key"]] = item
        sources.append(source)
        if not page["is_truncated"]:
            break
        marker = page["next_marker"]
        number += 1
    result = {"symbol": symbol, "prefix": prefix, "objects": objects, "raw_sources": sources,
              "complete": True, "historical_publication_verified": False}
    _immutable(target / "catalog.json", _json_bytes(result))
    return result


def calendar(start, end, weekday=None):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last or (weekday is not None and weekday not in range(7)):
        raise ValueError("invalid calendar bounds or weekday")
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    return [day.isoformat() for day in days if weekday is None or day.weekday() == weekday]


def weekly_candidates(catalog, start="2021-12-03", end="2026-09-18"):
    """Return paired Friday ZIP/checksum metadata; no object is downloaded."""
    rows = []
    for day in calendar(start, end, 4):
        key = catalog["prefix"] + f"{catalog['symbol']}-metrics-{day}.zip"
        checksum = key + ".CHECKSUM"
        if key in catalog["objects"] and checksum in catalog["objects"]:
            rows.append({"symbol": catalog["symbol"], "date": day,
                         "zip": {**catalog["objects"][key], "url": DOWNLOAD + key},
                         "checksum": {**catalog["objects"][checksum], "url": DOWNLOAD + checksum}})
    return rows


def coverage(catalog, start, end, *, weekday=None, settlement_date=None):
    days = calendar(start, end, weekday)
    paired, zip_only, checksum_only, absent = [], [], [], []
    total_bytes = 0
    for day in days:
        key = catalog["prefix"] + f"{catalog['symbol']}-metrics-{day}.zip"
        has_zip, has_checksum = key in catalog["objects"], key + ".CHECKSUM" in catalog["objects"]
        if has_zip and has_checksum:
            paired.append(day)
            total_bytes += catalog["objects"][key]["size"]
        elif has_zip:
            zip_only.append(day)
        elif has_checksum:
            checksum_only.append(day)
        else:
            absent.append(day)
    missing = sorted(zip_only + checksum_only + absent)
    post = [day for day in missing if settlement_date and day > settlement_date]
    return {"start": start, "end": end, "weekday": weekday, "expected_days": len(days),
            "paired_days": len(paired), "paired_dates": paired, "paired_zip_bytes": total_bytes,
            "zip_only_dates": zip_only, "checksum_only_dates": checksum_only, "absent_dates": absent,
            "missing_pair_dates": missing, "missing_pair_post_settlement_dates": post,
            "missing_pair_other_dates": [day for day in missing if day not in post],
            "settlement_date": settlement_date,
            "settlement_day_convention": "Only dates strictly after settlement UTC date are post-settlement."}


def compact_report(report, raw):
    """A disclosed projection; complete evidence remains in the ignored data tree."""
    compact = {key: value for key, value in report.items() if key not in ("assets", "weekly_candidates")}
    compact.update(full_report_relative_path="data/binance/metrics_catalog/coverage.json",
                   full_report_sha256=_sha(raw), full_report_bytes=len(raw),
                   projection_omits=["paired_dates", "weekly_candidates"],
                   weekly_candidate_count=len(report["weekly_candidates"]), assets={})
    for symbol, asset in report["assets"].items():
        projected = {key: value for key, value in asset.items() if key not in ("full_calendar", "weekly_fridays")}
        for scope in ("full_calendar", "weekly_fridays"):
            detail = asset[scope]
            projected[scope] = {key: value for key, value in detail.items() if key != "paired_dates"}
            projected[scope]["paired_post_settlement_days"] = sum(
                bool(detail["settlement_date"] and day > detail["settlement_date"])
                for day in detail["paired_dates"])
        compact["assets"][symbol] = projected
    return compact


def run(root=DEFAULT_ROOT, workers=4):
    if workers not in range(1, 5):
        raise ValueError("workers must be between one and four")
    cohort_path = ROOT / "data/binance/broad/cohort.json"
    lifecycle_path = ROOT / "docs/contract_lifecycle_sources_2026-09-26.json"
    cohort = json.loads(cohort_path.read_text(encoding="utf-8"))["selected"]
    events = json.loads(lifecycle_path.read_text(encoding="utf-8"))["events"]
    settlements = {event["symbol"]: event["automatic_settlement_utc"][:10] for event in events}
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(load_catalog, symbol, root): symbol for symbol in cohort}
        for future in as_completed(futures):
            symbol, catalog = futures[future], future.result()
            results[symbol] = catalog
            print(f"catalog {symbol}: {len(catalog['objects'])} objects, {len(catalog['raw_sources'])} pages", flush=True)
    report = {"schema_version": 1, "cohort": cohort, "cohort_sha256": _sha(cohort_path.read_bytes()),
              "lifecycle_sha256": _sha(lifecycle_path.read_bytes()), "listing_endpoint": S3,
              "last_retrieved_utc": max(source["retrieved_utc"] for catalog in results.values()
                                        for source in catalog["raw_sources"]),
              "limitations": ["Object metadata describes current archived versions, not original publication.",
                              "Catalog pairing does not verify checksums or CSV contents.",
                              "No ZIP download, financial replay, authenticated request or trading order."],
              "assets": {}, "weekly_candidates": []}
    for symbol in cohort:
        catalog = results[symbol]
        dated = [key for key in catalog["objects"] if key.endswith(".zip")]
        modified_years = {}
        for item in catalog["objects"].values():
            year = item["last_modified"][:4]
            modified_years[year] = modified_years.get(year, 0) + 1
        report["assets"][symbol] = {
            "object_count": len(catalog["objects"]), "raw_sources": catalog["raw_sources"],
            "catalog_sha256": _sha(_json_bytes(catalog)),
            "first_zip_key": min(dated) if dated else None, "last_zip_key": max(dated) if dated else None,
            "object_last_modified_year_counts": modified_years,
            "full_calendar": coverage(catalog, "2021-12-01", "2026-09-25", settlement_date=settlements.get(symbol)),
            "weekly_fridays": coverage(catalog, "2021-12-03", "2026-09-18", weekday=4,
                                       settlement_date=settlements.get(symbol))}
        report["weekly_candidates"].extend(weekly_candidates(catalog))
    raw = _json_bytes(report)
    _immutable(Path(root) / "coverage.json", raw)
    output = ROOT / "docs/derivatives_metrics_coverage_2026-09-26.json"
    _immutable(output, _json_bytes(compact_report(report, raw)))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--workers", type=int, default=4)
    arguments = parser.parse_args()
    run(arguments.root, arguments.workers)
