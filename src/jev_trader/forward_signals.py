"""Current completed-candle feature snapshots for a fixed paper candidate."""

import hashlib
import json
import math
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from .binance_data import Bar, HOUR_MS, _read_url
from .broad_data import load as load_daily
from .broad_extension import extend
from .broad_research import DAY_MS, target_weights
from .broad_technical import feature_bundle
from .cli import ROOT, RESULTS
from .derivatives_data import Funding
from .forward_observer import API, capture, digest


def feature_cutoff(server_ms):
    return (server_ms - HOUR_MS) // DAY_MS * DAY_MS


def merge_closed_bars(existing, rows, cutoff):
    if not existing or cutoff % DAY_MS or existing[-1].open_ms >= cutoff:
        raise ValueError("invalid daily seed or cutoff")
    lookup = {b.open_ms: b for b in existing}
    expected = set(range(existing[-1].open_ms, cutoff, DAY_MS))
    observed = set()
    for row in rows:
        opening, close_ms = int(row[0]), int(row[6])
        if opening % DAY_MS or close_ms != opening + DAY_MS - 1:
            raise ValueError("invalid daily REST timestamps")
        if close_ms >= cutoff:
            continue  # A developing candle cannot enter any feature.
        if opening not in expected or opening in observed:
            raise ValueError("unexpected or duplicated completed REST day")
        observed.add(opening)
        bar = Bar(opening, *map(float, row[1:6]), float(row[7]), int(row[8]), float(row[9]))
        if (not all(math.isfinite(v) for v in (bar.open, bar.high, bar.low, bar.close, bar.volume,
                                              bar.quote_volume, bar.taker_buy_base))
                or not 0 < bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
                or bar.volume <= 0 or bar.quote_volume <= 0 or bar.trades <= 0
                or not 0 <= bar.taker_buy_base <= bar.volume):
            raise ValueError("invalid completed daily candle")
        if opening in lookup:
            fields = ("open", "high", "low", "close", "volume", "quote_volume", "trades", "taker_buy_base")
            if any(not math.isclose(getattr(bar, k), getattr(lookup[opening], k), rel_tol=1e-8, abs_tol=1e-8) for k in fields):
                raise ValueError("completed candle overlap changed")
        else:
            lookup[opening] = bar
    if observed != expected:
        raise ValueError("incomplete completed daily calendar")
    return [lookup[t] for t in sorted(lookup)]


def merge_funding(existing, rows, symbol, observed_ms):
    if not existing:
        raise ValueError("funding seed required")
    lookup = {r.timestamp_ms: r for r in existing}
    last = existing[-1].timestamp_ms
    prior_interval = existing[-1].interval_hours
    events, seen = [], set()
    for row in rows:
        try:
            timestamp, rate, mark = int(row["fundingTime"]), float(row["fundingRate"]), float(row["markPrice"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid funding numeric fields") from exc
        if (row["symbol"] != symbol or timestamp in seen or timestamp < last or timestamp > observed_ms
                or not 0 <= timestamp % HOUR_MS < 60_000 or not math.isfinite(rate) or abs(rate) > .1
                or not math.isfinite(mark) or mark <= 0 or row.get("rateType", "Regular") != "Regular"):
            raise ValueError("invalid or unsupported observed funding")
        seen.add(timestamp)
        if timestamp in lookup:
            if not math.isclose(rate, lookup[timestamp].rate, rel_tol=0, abs_tol=1e-12):
                raise ValueError("funding overlap changed")
            predecessor = max((t for t in lookup if t < timestamp), default=None)
            if predecessor is None or timestamp // HOUR_MS - predecessor // HOUR_MS != lookup[timestamp].interval_hours:
                raise ValueError("funding predecessor or overlap interval unresolved")
        else:
            interval = timestamp // HOUR_MS - last // HOUR_MS
            if not 1 <= interval <= prior_interval:
                raise ValueError("unresolved funding interval or missing settlement")
            lookup[timestamp] = Funding(timestamp, interval, rate)
            prior_interval = interval
        last = timestamp
        events.append({"symbol": symbol, "timestamp_ms": timestamp, "rate": rate, "mark_price": mark})
    missing_due_event = (observed_ms % HOUR_MS >= 60_000
                         and observed_ms // HOUR_MS - last // HOUR_MS >= prior_interval)
    if (not seen or existing[-1].timestamp_ms not in seen
            or observed_ms - last > prior_interval * HOUR_MS + 60_000 or missing_due_event):
        raise ValueError("funding overlap absent or tail stale")
    return [lookup[t] for t in sorted(lookup)], events


def build_snapshot():
    freeze_path = ROOT / "docs/broad_candidate_freeze_2026-09-26.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    for name, expected in freeze["source_code_sha256"].items():
        if hashlib.sha256((ROOT / "src/jev_trader" / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"fixed strategy source changed: {name}")
    data, archive_sources, cohort = load_daily()
    # These hourly lookups support extension validation; daily feature history
    # already has publisher-verified archive provenance from load_daily().
    empty_hourly = {kind: {s: {} for s in data["klines"]} for kind in ("klines", "markPriceKlines")}
    seed_sources, _, _ = extend(data, empty_hourly)
    root = RESULTS / "forward_signals"
    folder = root / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8])
    folder.mkdir(parents=True)

    def request(endpoint, params, label):
        if endpoint not in ("time", "exchangeInfo", "klines", "fundingRate"):
            raise ValueError("only public observation endpoints allowed")
        url = API + endpoint + ("?" + urlencode(params) if params else "")
        started = time.time_ns() // 1_000_000
        payload = _read_url(url)
        received = time.time_ns() // 1_000_000
        rows = json.loads(payload)
        path = folder / (label + ".json")
        path.write_bytes(payload)
        if isinstance(rows, list) and "limit" in params and len(rows) >= params["limit"]:
            raise ValueError("potentially truncated response; pagination required")
        return rows, {"url": url, "file": str(path.relative_to(root)).replace("\\", "/"),
                      "sha256": hashlib.sha256(payload).hexdigest(), "request_started_ms": started, "received_ms": received}

    clock, clock_source = request("time", {}, "clock")
    observed_ms = int(clock["serverTime"])
    if not clock_source["request_started_ms"] - 5000 <= observed_ms <= clock_source["received_ms"] + 5000:
        raise ValueError("server/local clock mismatch")
    cutoff = feature_cutoff(observed_ms)
    exchange, exchange_source = request("exchangeInfo", {}, "exchange")
    info = {r["symbol"]: r for r in exchange["symbols"]}
    active = [s for s in cohort["selected"] if s in info and info[s]["status"] == "TRADING"
              and info[s]["contractType"] == "PERPETUAL" and info[s]["quoteAsset"] == "USDT"]
    sources = [clock_source, exchange_source]
    responses = {}
    jobs = []
    for s in active:
        jobs.append(("klines", s, {"symbol": s, "interval": "1d", "startTime": data["klines"][s][-1].open_ms,
                                  "endTime": observed_ms, "limit": 1500}))
        jobs.append(("fundingRate", s, {"symbol": s, "startTime": data["fundingRate"][s][-1].timestamp_ms,
                                       "endTime": observed_ms, "limit": 1000}))
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending = {pool.submit(request, endpoint, params, endpoint + "_" + s): (endpoint, s)
                   for endpoint, s, params in jobs}
        for future in as_completed(pending):
            response, source = future.result()
            responses[pending[future]] = response
            sources.append(source)
    funding = []
    for s in active:
        data["klines"][s] = merge_closed_bars(data["klines"][s], responses["klines", s], cutoff)
        data["fundingRate"][s], events = merge_funding(data["fundingRate"][s], responses["fundingRate", s], s, observed_ms)
        funding.extend(events)
    states, fields, quality = feature_bundle(data)
    latest = {s: states[s][cutoff] for s in active if cutoff in states[s]}
    if set(latest) != set(active):
        raise ValueError("current tradable contract missing complete feature bundle")
    if any(row["latest_observed_close_ms"] != cutoff for row in latest.values()):
        raise ValueError("inconsistent feature cutoff")
    quotes = capture()
    if feature_cutoff(quotes["server_time_ms"]) != cutoff:
        raise ValueError("feature availability boundary changed during acquisition; rebuild")
    if set(quotes["accepted_quotes"]) != set(active) or quotes["rejected_quotes"]:
        raise ValueError("contract availability or quote validity changed during acquisition")
    targets = target_weights(latest, freeze["rule"])
    if set(targets) - set(quotes["accepted_quotes"]):
        raise ValueError("target lacks a fresh quote")
    now = datetime.fromtimestamp(quotes["server_time_ms"] / 1000, timezone.utc)
    result = {"created_utc": datetime.now(timezone.utc).isoformat(), "server_time_ms": quotes["server_time_ms"],
              "feature_cutoff_ms": cutoff, "funding_observed_through_ms": observed_ms,
              "funding_boundary_reconciled": observed_ms // HOUR_MS == quotes["server_time_ms"] // HOUR_MS
                  and observed_ms % HOUR_MS >= 60_000,
              "field_names": fields, "feature_quality": quality, "features": latest, "target_weights": targets,
              "weekly_window_open": now.weekday() == 0 and now.hour == 1 and now.minute < 5,
              "sources": sorted(sources, key=lambda r: r["file"]),
              "funding": sorted(funding, key=lambda r: (r["timestamp_ms"], r["symbol"])),
              "market_observation": quotes, "fixed_rule": freeze["rule"],
              "freeze_sha256": hashlib.sha256(freeze_path.read_bytes()).hexdigest(),
              "archive_sources_sha256": digest([{k: v for k, v in r.items() if k != "path"} for r in archive_sources]),
              "seed_sources_sha256": digest([{k: v for k, v in r.items() if k != "path"} for r in seed_sources]),
              "source_code_sha256": {name: hashlib.sha256((ROOT / "src/jev_trader" / name).read_bytes()).hexdigest()
                                     for name in ("forward_signals.py", "broad_technical.py", "broad_prediction.py",
                                                  "broad_research.py", "market_state.py", "strategies.py", "broad_data.py",
                                                  "broad_extension.py", "binance_data.py", "derivatives_data.py")},
              "status": "signal_preview_only", "orders_sent": 0, "jev_calls": 0,
              "limits": ["No paper positions or simulated fills created by this command.",
                         "All 60 advertised fields retained; fixed strategy uses its declared factor inputs.",
                         "Funding boundary flag assumes validated settlement timestamps occur within the first minute of an hour.",
                         "Weekly schedule flag is not proof that a timely decision was made or executed."]}
    result["snapshot_sha256"] = digest(result)
    (folder / "signal.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"snapshot": str(folder / "signal.json"), "cutoff": cutoff, "fields": len(fields),
                      "symbols": len(latest), "target_gross": sum(abs(w) for w in targets.values()),
                      "weekly_window_open": result["weekly_window_open"], "hash": result["snapshot_sha256"]}, indent=2))
    return result


if __name__ == "__main__":
    build_snapshot()
