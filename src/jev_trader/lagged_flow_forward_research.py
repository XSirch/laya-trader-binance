"""Forward holdout of frozen lag-only spot models on verified September data."""

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import itertools
import json
import os
import platform
import subprocess
import time
import urllib.error
import urllib.request
import zipfile

from .basis_data import _merge, load
from .basis_features import canonical
from .basis_research import sha, timestamp, write_new_or_equal
from .binance_data import HOUR_MS, _expected_hash, parse_archive
from .cli import ROOT, RESULTS
from .hourly_forecast_research import RUNTIME
from .lagged_flow_ablation_prediction import MODELS, build_ablation_forecasts, build_panel
from .lagged_flow_ablation_research import calendar_year_returns, compact, score_forecasts
from .lagged_flow_execution import evaluate, ExecutionUnavailable
from .lagged_flow_prediction import INTERVAL_HOURS, LAGS, _hash, _lag_values

BASE_SUMMARY = ROOT / "docs/lagged_flow_ablation_research_2026-09-27.json"
BASE_REPORT = RESULTS / "lagged_flow_ablation_research.json"
AB_PROTOCOL = ROOT / "docs/lagged_flow_ablation_protocol_2026-09-27.md"
AB_REPORT = ROOT / "docs/lagged_flow_ablation_research_2026-09-27.md"
PROTOCOL = ROOT / "docs/lagged_flow_forward_protocol_2026-09-27.md"
INPUTS = RESULTS / "lagged_flow_forward_inputs.json"
REPORT = RESULTS / "lagged_flow_forward_research.json"
SUMMARY = ROOT / "docs/lagged_flow_forward_research_2026-09-27.json"
ARCHIVE_ROOT = RESULTS / "lagged_flow_forward_data" / "spot_daily"
ARCHIVE_MANIFEST = RESULTS / "lagged_flow_forward_data" / "spot_daily_manifest.json"
FORWARD_CODE = ROOT / "src/jev_trader/lagged_flow_forward_research.py"
BASE = "https://data.binance.vision/data/spot/daily/klines"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
FIRST_DAY, LAST_DAY = "2026-09-01", "2026-09-26"
START_TEXT, END_TEXT = "2026-09-01T00:00:00+00:00", "2026-09-26T16:00:00+00:00"
PERIOD = {"forward_holdout": [START_TEXT, END_TEXT]}
CONFIG = {"schema_version": 1,
    "base_summary": "docs/lagged_flow_ablation_research_2026-09-27.json",
    "symbols": list(SYMBOLS), "daily_archives": [FIRST_DAY, LAST_DAY],
    "execution_period_utc": [START_TEXT, END_TEXT],
    "decision_interval_hours": 8, "target_horizon_hours": 8,
    "execution_delay_hours": 1,
    "models": ["own_lag_hgb", "leader_lag_hgb", "combined_lag_hgb"],
    "side_costs": [0.0015, 0.003], "allocation_per_asset": 0.25,
    "target_net_cagr_pct": 50, "maximum_drawdown_pct": 10,
    "acceptance_gate_for_25_day_window": False, "orders_authorized": False}


def anchors():
    import re
    blocks = re.findall(r"```json\s*\n(.*?)\n```", PROTOCOL.read_text(encoding="utf-8"), re.DOTALL)
    if len(blocks) != 1 or json.loads(blocks[0]) != CONFIG:
        raise ValueError("forward-holdout protocol/configuration mismatch")
    ablation = json.loads(BASE_SUMMARY.read_text(encoding="utf-8"))
    ab_module = __import__("jev_trader.lagged_flow_ablation_research", fromlist=["anchors"])
    if ablation["inputs"]["anchors"] != ab_module.anchors():
        raise ValueError("lag-ablation source anchors changed")
    if sha(BASE_REPORT) != ablation["full_report_sha256"]:
        raise ValueError("lag-ablation report hash changed")
    runtime = {name: importlib.metadata.version(name) for name in RUNTIME}
    if runtime != RUNTIME:
        raise ValueError("forward holdout requires the pinned tree runtime")
    files = [PROTOCOL, AB_PROTOCOL, AB_REPORT, BASE_SUMMARY, BASE_REPORT,
        ROOT / "docs/lagged_flow_ablation_research_2026-09-27.json",
        ROOT / "docs/lagged_flow_research_2026-09-27.md",
        ROOT / "src/jev_trader/lagged_flow_ablation_prediction.py",
        ROOT / "src/jev_trader/lagged_flow_ablation_research.py", FORWARD_CODE]
    return {"files_sha256": {str(path.relative_to(ROOT)).replace("\\", "/"): sha(path)
            for path in files}, "runtime": runtime, "python": platform.python_version(),
        "base_ablation_sha256": ablation["full_report_sha256"]}


def _url(symbol, day):
    date = datetime.strptime(day, "%Y-%m-%d")
    basename = f"{symbol}-1h-{date:%Y-%m-%d}.zip"
    return f"{BASE}/{symbol}/1h/{basename}"


def _request(url):
    request = urllib.request.Request(url, headers={"User-Agent": "jev-lagged-flow-forward-study/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Binance daily archive unavailable: {url} ({exc.code})") from exc


def _fetch_one(symbol, day):
    url = _url(symbol, day)
    basename = f"{symbol}-1h-{day}.zip"
    target = ARCHIVE_ROOT / symbol / basename
    checksum_path = target.with_suffix(".zip.CHECKSUM")
    target.parent.mkdir(parents=True, exist_ok=True)
    requests, downloaded = 0, False
    if checksum_path.exists():
        checksum = checksum_path.read_bytes()
    else:
        checksum = _request(url + ".CHECKSUM")
        requests += 1
        checksum_path.write_bytes(checksum)
    expected = _expected_hash(checksum)
    if target.exists():
        payload = target.read_bytes()
        if hashlib.sha256(payload).hexdigest() != expected:
            raise ValueError(f"cached forward ZIP checksum mismatch: {target}")
    else:
        payload = _request(url)
        requests += 1
        actual = hashlib.sha256(payload).hexdigest()
        if actual != expected:
            raise ValueError(f"forward ZIP checksum mismatch: {url}")
        with zipfile.ZipFile(__import__("io").BytesIO(payload)) as archive:
            if archive.testzip() is not None:
                raise ValueError(f"forward ZIP CRC mismatch: {url}")
        temporary = target.with_suffix(".zip.part")
        temporary.write_bytes(payload)
        temporary.replace(target)
        downloaded = True
    bars = parse_archive(target)
    day_ms = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    expected_times = list(range(day_ms, day_ms + 24 * HOUR_MS, HOUR_MS))
    actual_times = [bar.open_ms for bar in bars]
    if actual_times != expected_times:
        raise ValueError(f"forward daily archive is incomplete or misaligned: {symbol} {day}")
    return {"symbol": symbol, "day": day, "url": url, "checksum_url": url + ".CHECKSUM",
        "sha256": expected, "bytes": len(payload),
        "path": str(target.relative_to(ROOT)).replace("\\", "/"),
        "rows": len(bars), "first_open_ms": actual_times[0], "last_open_ms": actual_times[-1],
        "network_requests": requests, "downloaded_now": downloaded}


def archive_manifest():
    expected = [(symbol, day) for symbol in SYMBOLS for day in
        [f"2026-09-{number:02d}" for number in range(1, 27)]]
    if ARCHIVE_MANIFEST.exists():
        manifest = json.loads(ARCHIVE_MANIFEST.read_text(encoding="utf-8"))
        records = manifest.get("files", [])
        if [(row.get("symbol"), row.get("day")) for row in records] != sorted(expected):
            raise ValueError("forward daily archive manifest does not match frozen universe/dates")
        for row in records:
            path = ROOT / row["path"]
            if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
                raise ValueError(f"forward daily archive changed: {row['path']}")
            if len(parse_archive(path)) != 24:
                raise ValueError(f"forward daily archive row count changed: {row['path']}")
        return manifest

    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_fetch_one, symbol, day): (symbol, day) for symbol, day in expected}
        for index, future in enumerate(as_completed(futures), start=1):
            row = future.result()
            results.append(row)
            print(f"forward archives {index}/{len(expected)} {row['symbol']} {row['day']}", flush=True)
    results.sort(key=lambda row: (row["symbol"], row["day"]))
    manifest = {"schema_version": 1, "acquired_utc": datetime.now(timezone.utc).isoformat(),
        "files": results, "file_count": len(results), "rows": sum(row["rows"] for row in results),
        "network_requests": sum(row["network_requests"] for row in results),
        "new_zip_downloads": sum(row["downloaded_now"] for row in results)}
    ARCHIVE_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with ARCHIVE_MANIFEST.open("xb") as handle:
        handle.write(canonical(manifest) + b"\n")
    return manifest


def prepare():
    frozen = anchors()
    market, historical_audit = load()
    if historical_audit.get("network_requests") != 0 or historical_audit.get("cache_writes") != 0:
        raise ValueError("historical input must remain offline and read-only")
    for symbol in SYMBOLS:
        if max(market["spot"][symbol]) != 1788217200000:
            raise ValueError("historical spot baseline no longer ends on 2026-08-31 23:00 UTC")
    manifest = archive_manifest()
    daily_coverage = {}
    by_symbol = defaultdict(list)
    for row in manifest["files"]:
        bars = parse_archive(ROOT / row["path"])
        by_symbol[row["symbol"]].extend(bars)
    for symbol in SYMBOLS:
        bars = sorted(by_symbol[symbol], key=lambda bar: bar.open_ms)
        expected = list(range(timestamp(FIRST_DAY + "T00:00:00+00:00"),
            timestamp(LAST_DAY + "T00:00:00+00:00") + 24 * HOUR_MS, HOUR_MS))
        if [bar.open_ms for bar in bars] != expected:
            raise ValueError(f"daily holdout has a gap, duplicate, or wrong date for {symbol}")
        if bars[0].open_ms <= max(market["spot"][symbol]):
            raise ValueError(f"forward archive overlaps historical cache for {symbol}")
        _merge(market["spot"][symbol], bars)
        daily_coverage[symbol] = {"rows": len(bars), "first_open_ms": bars[0].open_ms,
            "last_open_ms": bars[-1].open_ms,
            "sha256": hashlib.sha256(canonical([[bar.open_ms, bar.open, bar.high, bar.low,
                bar.close, bar.volume, bar.quote_volume, bar.trades, bar.taker_buy_base]
                for bar in bars])).hexdigest()}
    if anchors() != frozen:
        raise ValueError("forward-holdout sources changed during data acquisition")
    print("Building historical context and spot-only forward events through 2026-09-26.", flush=True)
    panel, fields, feature_audit = build_panel(market)
    historical_event_count = len(panel)
    first = timestamp(FIRST_DAY + "T00:00:00+00:00")
    last_open = timestamp(LAST_DAY + "T00:00:00+00:00") + 23 * HOUR_MS
    forward_count = overlap_count = 0
    for execution_ms in range(first, last_open + 1, INTERVAL_HOURS * HOUR_MS):
        for symbol in SYMBOLS:
            spot = market["spot"][symbol]
            end_open = execution_ms - 2 * HOUR_MS
            values = {name: None for name in fields}
            for lag in LAGS:
                own_return, own_flow = _lag_values(spot, end_open, lag)
                values[f"own.return_{lag}h"] = own_return
                values[f"own.flow_imbalance_{lag}h"] = own_flow
            for leader in ("BTCUSDT", "ETHUSDT"):
                for lag in LAGS:
                    if leader == symbol:
                        ret, flow = None, None
                    else:
                        ret, flow = _lag_values(market["spot"][leader], end_open, lag)
                    values[f"leader.{leader}.return_{lag}h"] = ret
                    values[f"leader.{leader}.flow_imbalance_{lag}h"] = flow
            for asset in SYMBOLS:
                values[f"asset.is_{asset}"] = float(asset == symbol)
            ordered = [values[name] for name in fields]
            identity = {"execution_ms": execution_ms, "symbol": symbol,
                "latest_observed_close_ms": execution_ms - HOUR_MS,
                "base_context_sha256": "spot_only_forward_lags_v1", "features": ordered}
            key = (execution_ms, symbol)
            if key in panel:
                existing = panel[key]["features"]
                lag_indices = [index for index, name in enumerate(fields)
                    if name.startswith("own.return_") or name.startswith("own.flow_imbalance_")
                    or name.startswith("leader.") or name.startswith("asset.is_")]
                if any(existing[index] != ordered[index] for index in lag_indices):
                    raise ValueError("overlapping cached and forward spot lag features differ")
                overlap_count += 1
                continue
            panel[key] = {"execution_ms": execution_ms, "symbol": symbol,
                "latest_observed_close_ms": execution_ms - HOUR_MS,
                "features": ordered, "context_sha256": _hash(identity)}
            forward_count += 1
    panel_digest = hashlib.sha256()
    for key in sorted(panel):
        panel_digest.update(canonical(panel[key]) + b"\n")
    feature_audit.update(event_count=len(panel), panel_sha256=panel_digest.hexdigest(),
        first_execution_ms=min(key[0] for key in panel),
        last_execution_ms=max(key[0] for key in panel),
        historical_event_count=historical_event_count,
        forward_calendar_event_count=forward_count + overlap_count,
        forward_event_count=forward_count, forward_base_overlap_count=overlap_count,
        forward_feature_policy="Only spot return/flow lags and fixed asset IDs are populated; other fields are missing and excluded from the three ablation models.")
    inputs = {"anchors": frozen, "config": CONFIG, "historical_cache": historical_audit,
        "forward_archive_manifest": manifest, "forward_spot_coverage": daily_coverage,
        "features": feature_audit, "fields": list(fields)}
    write_new_or_equal(INPUTS, inputs)
    return market["spot"], panel, fields, inputs


def scenario(spot, event_symbols, forecasts, model, cost, start, end):
    execution_mode = model if model in {"always", "buy_hold"} else "leader_hgb"
    signals = forecasts["predictions"].get(model, {})
    row = {"model": model, "execution_mode": execution_mode,
        "side_cost": cost, "period": "forward_holdout"}
    try:
        metrics = evaluate(spot, event_symbols, signals, start_ms=start, end_ms=end,
            side_cost=cost, mode=execution_mode)
    except ExecutionUnavailable as error:
        row.update(status="invalid_execution", execution_error=str(error), metrics=None)
    else:
        metrics["calendar_year_returns"] = calendar_year_returns(metrics["monthly_returns_pct"])
        years = (end - start) / (365.25 * 24 * HOUR_MS)
        cagr = 100 * (metrics["terminal_equity"] ** (1 / years) - 1)
        row.update(status="complete", metrics=metrics, cumulative_return_pct=metrics["return_pct"],
            descriptive_annualized_cagr_pct=cagr,
            meets_static_50_10_gate=False)
    print({key: row.get(key) for key in ("model", "side_cost", "period", "status",
        "cumulative_return_pct", "descriptive_annualized_cagr_pct")}, flush=True)
    return row


def serializable_forecasts(forecasts):
    result = dict(forecasts)
    result["predictions"] = {name: [{"execution_ms": key[0], "symbol": key[1], **value}
        for key, value in sorted(rows.items())] for name, rows in forecasts["predictions"].items()}
    result["label_outcomes"] = [{"execution_ms": key[0], "symbol": key[1], **value}
        for key, value in sorted(forecasts["label_outcomes"].items())]
    return result


def run(prepare_only=False):
    RESULTS.mkdir(exist_ok=True)
    lock = RESULTS / "lagged_flow_forward_research.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(descriptor)
    try:
        started = time.perf_counter()
        if not prepare_only and (not INPUTS.exists() or REPORT.exists() or SUMMARY.exists()):
            raise ValueError("freeze forward-holdout data first; preserve prior outputs")
        spot, panel, fields, inputs = prepare()
        event_symbols = defaultdict(set)
        for execution_ms, symbol in panel:
            event_symbols[execution_ms].add(symbol)
        print("Forward panel events:", len(panel), "fields:", len(fields), flush=True)
        if prepare_only:
            return inputs
        forecasts = build_ablation_forecasts(panel, fields, spot,
            progress=lambda row: print("Monthly fit:", row, flush=True))
        start, end = map(timestamp, PERIOD["forward_holdout"])
        scores = {"forward_holdout": score_forecasts(forecasts["prediction_errors"],
            start, end + HOUR_MS)}
        all_models = (*MODELS, "always", "buy_hold")
        rows = [scenario(spot, event_symbols, forecasts, model, cost, start, end)
            for model, cost in itertools.product(all_models, CONFIG["side_costs"])]
        if anchors() != inputs["anchors"]:
            raise ValueError("forward-holdout sources changed during replay")
        complete = all(row["status"] == "complete" for row in rows)
        report = {"created_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": time.perf_counter() - started,
            "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"],
                cwd=ROOT, text=True).strip(),
            "inputs": inputs, "inputs_file_sha256": sha(INPUTS),
            "forecasts": serializable_forecasts(forecasts), "forecast_scores": scores,
            "scenarios": rows, "goal_achieved": False, "deployable": False,
            "selected_winner": None, "orders_sent": 0,
            "jev_calls": 0,
            "new_market_downloads": inputs["forward_archive_manifest"]["new_zip_downloads"],
            "forward_archive_network_requests": inputs["forward_archive_manifest"]["network_requests"],
            "all_scenarios_complete": complete,
            "decision": "short forward holdout only; no annual consistency claim or acceptance gate",
            "limits": ["A 25-day forward window is too short to establish annual consistency.",
                "Historical feature timing remains unverified; candles and archive publication can be revised.",
                "OHLC opens and assumed costs do not establish real fills, spreads, or account fees.",
                "The four asset outcomes are correlated; no orders are authorized."]}
        write_new_or_equal(REPORT, report)
        summary = {key: value for key, value in report.items()
            if key not in ("forecasts", "scenarios")}
        summary["forecasts"] = {key: value for key, value in forecasts.items()
            if key not in ("predictions", "prediction_errors", "label_outcomes",
                "unavailable_labels", "unavailable_predictions")}
        summary["forecasts"].update(
            prediction_counts={name: len(values) for name, values in forecasts["predictions"].items()},
            prediction_error_count=len(forecasts["prediction_errors"]),
            label_count=len(forecasts["label_outcomes"]),
            unavailable_label_count=len(forecasts["unavailable_labels"]),
            unavailable_prediction_count=len(forecasts["unavailable_predictions"]))
        summary.update(full_report_sha256=sha(REPORT), scenarios=[compact(row) for row in rows])
        write_new_or_equal(SUMMARY, summary)
        print("Completed", len(rows), "forward scenarios.", flush=True)
        return summary
    finally:
        lock.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    run(parser.parse_args().prepare_only)
