"""Frozen walk-forward ablation of own and cross-asset short-lag features."""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import itertools
import json
import os
import platform
import subprocess
import time

from .basis_data import load
from .basis_features import canonical
from .basis_research import sha, timestamp, write_new_or_equal
from .binance_data import HOUR_MS
from .cli import ROOT, RESULTS
from .hourly_forecast_prediction import ESTIMATOR_PARAMETERS
from .hourly_forecast_research import RUNTIME
from .lagged_flow_ablation_prediction import (MODELS, build_ablation_forecasts,
    build_panel)
from .lagged_flow_execution import evaluate, ExecutionUnavailable
from .lagged_flow_research import calendar_year_returns, compact

BASE_SUMMARY = ROOT / "docs/lagged_flow_research_2026-09-27.json"
BASE_REPORT = RESULTS / "lagged_flow_research.json"
PROTOCOL = ROOT / "docs/lagged_flow_ablation_protocol_2026-09-27.md"
INPUTS = RESULTS / "lagged_flow_ablation_inputs.json"
REPORT = RESULTS / "lagged_flow_ablation_research.json"
SUMMARY = ROOT / "docs/lagged_flow_ablation_research_2026-09-27.json"
PREDICTION_CODE = ROOT / "src/jev_trader/lagged_flow_ablation_prediction.py"
RESEARCH_CODE = ROOT / "src/jev_trader/lagged_flow_ablation_research.py"
FROM_MODULES = ("rolling_mean", "own_hgb", "leader_hgb")
PERIODS = {"development": ["2024-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"],
    "later": ["2025-01-01T00:00:00+00:00", "2026-08-31T16:00:00+00:00"],
    "year2025": ["2025-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"],
    "year2026": ["2026-01-01T00:00:00+00:00", "2026-08-31T16:00:00+00:00"]}
CONFIG = {"schema_version": 1,
    "base_report": "docs/lagged_flow_research_2026-09-27.json",
    "feature_groups": ["own_lags_plus_asset_ids", "leader_lags_plus_asset_ids",
        "own_and_leader_lags_plus_asset_ids"],
    "symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"],
    "feature_lags_hours": [1, 2, 3, 6], "decision_interval_hours": 8,
    "target_horizon_hours": 8, "execution_delay_hours": 1,
    "training_window_days": 365, "minimum_training_rows": 4000,
    "refit": "first_eligible_event_monthly_cutoff",
    "development": PERIODS["development"], "later": PERIODS["later"],
    "side_costs": [0.0015, 0.003], "allocation_per_asset": 0.25,
    "target_net_cagr_pct": 50, "maximum_drawdown_pct": 10,
    "historical_point_in_time_verified": False, "confirmatory_holdout": False}
LARGE = {"hourly_equity", "daily_equity", "action_decisions"}


def anchors():
    blocks = __import__("re").findall(r"```json\s*\n(.*?)\n```",
        PROTOCOL.read_text(encoding="utf-8"), __import__("re").DOTALL)
    if len(blocks) != 1 or json.loads(blocks[0]) != CONFIG:
        raise ValueError("lagged-flow ablation protocol/configuration mismatch")
    base = json.loads(BASE_SUMMARY.read_text(encoding="utf-8"))
    original_anchors = __import__("jev_trader.lagged_flow_research",
        fromlist=["anchors"]).anchors()
    if base["inputs"]["anchors"] != original_anchors:
        raise ValueError("base lagged-flow source anchors changed")
    if sha(BASE_REPORT) != base["full_report_sha256"]:
        raise ValueError("base lagged-flow full report hash changed")
    runtime = {name: importlib.metadata.version(name) for name in RUNTIME}
    if runtime != RUNTIME:
        raise ValueError("ablation requires the pinned tree runtime")
    files = [PROTOCOL, BASE_SUMMARY, BASE_REPORT, PREDICTION_CODE, RESEARCH_CODE,
        ROOT / "docs/lagged_flow_protocol_2026-09-27.md",
        ROOT / "docs/lagged_flow_research_2026-09-27.md"]
    return {"files_sha256": {str(path.relative_to(ROOT)).replace("\\", "/"): sha(path)
            for path in files}, "base_anchors": original_anchors, "runtime": runtime,
        "python": platform.python_version(), "estimator_parameters": ESTIMATOR_PARAMETERS}


def prepare():
    frozen = anchors()
    market, data_audit = load()
    if data_audit.get("network_requests") != 0 or data_audit.get("cache_writes") != 0:
        raise ValueError("ablation preparation must be offline and read-only")
    print("Verified local inventory; building the four-asset lag-ablation panel.", flush=True)
    panel, fields, feature_audit = build_panel(market)
    inputs = {"anchors": frozen, "config": CONFIG, "data": data_audit,
        "features": feature_audit, "fields": list(fields)}
    if anchors() != frozen:
        raise ValueError("ablation sources changed during preparation")
    write_new_or_equal(INPUTS, inputs)
    return market["spot"], panel, fields, inputs


def score_forecasts(errors, start_ms, end_ms):
    selected = [row for row in errors if start_ms <= row["execution_ms"] < end_ms
                and row["available_ms"] <= end_ms]
    if not selected:
        return {"count": 0, "models": {}}
    actual = [row["actual_return"] for row in selected]
    zero_sse = sum(value * value for value in actual)
    scores = {}
    for name in MODELS:
        residual = [row[name + "_prediction"] - row["actual_return"] for row in selected]
        sse = sum(value * value for value in residual)
        scores[name] = {"mse": sse / len(selected),
            "mae": sum(abs(value) for value in residual) / len(selected),
            "skill_vs_zero": 1 - sse / zero_sse if zero_sse else None,
            "direction_accuracy": sum((row[name + "_prediction"] > 0)
                == (row["actual_return"] > 0) for row in selected) / len(selected)}
    return {"count": len(selected), "models": scores}


def scenario(spot, event_symbols, forecasts, model, cost, period):
    start, end = map(timestamp, PERIODS[period])
    execution_mode = model if model in {"always", "buy_hold"} else "leader_hgb"
    signals = forecasts["predictions"].get(model, {})
    row = {"model": model, "execution_mode": execution_mode,
        "side_cost": cost, "period": period}
    try:
        metrics = evaluate(spot, event_symbols, signals, start_ms=start, end_ms=end,
            side_cost=cost, mode=execution_mode)
    except ExecutionUnavailable:
        row.update(status="invalid_execution", metrics=None,
            meets_nominal_target=False, meets_adverse_target=False)
    else:
        metrics["calendar_year_returns"] = calendar_year_returns(metrics["monthly_returns_pct"])
        years = (end - start) / (365.25 * 24 * HOUR_MS)
        cagr = 100 * (metrics["terminal_equity"] ** (1 / years) - 1)
        nominal = cagr >= 50 and metrics["max_drawdown_pct"] <= 10
        row.update(status="complete", metrics=metrics, net_cagr_pct=cagr,
            meets_nominal_target=nominal,
            meets_adverse_target=nominal and metrics["adverse_intrahour_drawdown_bound_pct"] <= 10)
    print({key: row.get(key) for key in ("model", "side_cost", "period", "status", "net_cagr_pct")}, flush=True)
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
    lock = RESULTS / "lagged_flow_ablation_research.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(descriptor)
    try:
        started = time.perf_counter()
        if not prepare_only and (not INPUTS.exists() or REPORT.exists() or SUMMARY.exists()):
            raise ValueError("freeze ablation inputs first and preserve any existing result")
        spot, panel, fields, inputs = prepare()
        event_symbols = defaultdict(set)
        for execution_ms, symbol in panel:
            event_symbols[execution_ms].add(symbol)
        print("Frozen panel events:", len(panel), "fields:", len(fields), flush=True)
        if prepare_only:
            return inputs
        forecasts = build_ablation_forecasts(panel, fields, spot,
            progress=lambda row: print("Monthly fit:", row, flush=True))
        scores = {name: score_forecasts(forecasts["prediction_errors"],
            *map(timestamp, PERIODS[name])) for name in PERIODS}
        all_models = (*MODELS, "always", "buy_hold")
        rows = [scenario(spot, event_symbols, forecasts, model, cost, period)
            for model, cost, period in itertools.product(all_models,
                CONFIG["side_costs"], ("development", "later"))]
        if anchors() != inputs["anchors"]:
            raise ValueError("ablation sources changed during experiment")
        later = [row for row in rows if row["period"] == "later" and row["model"] in MODELS]
        annual_positive = all(row["status"] == "complete" and
            all(value > 0 for year, value in row["metrics"]["calendar_year_returns"].items()
                if year in ("2025", "2026")) and
            set(row["metrics"]["calendar_year_returns"]) >= {"2025", "2026"}
            for row in later)
        goal = (len(later) == len(MODELS) * 2 and
            all(row["meets_adverse_target"] for row in later) and annual_positive)
        report = {"created_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": time.perf_counter() - started,
            "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"],
                cwd=ROOT, text=True).strip(),
            "inputs": inputs, "inputs_file_sha256": sha(INPUTS),
            "base_report_sha256": sha(BASE_REPORT),
            "forecasts": serializable_forecasts(forecasts), "forecast_scores": scores,
            "scenarios": rows, "goal_achieved": goal, "deployable": False,
            "selected_winner": None, "orders_sent": 0, "new_market_downloads": 0,
            "jev_calls": 0,
            "limits": ["The same project history has already been examined; this ablation is retrospective.",
                "Four assets and their hourly outcomes are correlated, not independent observations.",
                "Historical feature publication timing and account-specific fills remain unverified.",
                "No result is an untouched holdout or authorizes orders."]}
        write_new_or_equal(REPORT, report)
        summary = {key: value for key, value in report.items()
                   if key not in ("forecasts", "scenarios")}
        summary["forecasts"] = {key: value for key, value in forecasts.items()
            if key not in ("predictions", "prediction_errors", "label_outcomes",
                           "unavailable_labels", "unavailable_predictions")}
        summary["forecasts"].update(
            prediction_counts={name: len(values) for name, values in forecasts["predictions"].items()},
            prediction_audits=forecasts["prediction_audits"],
            prediction_error_count=len(forecasts["prediction_errors"]),
            label_count=len(forecasts["label_outcomes"]),
            unavailable_label_count=len(forecasts["unavailable_labels"]),
            unavailable_prediction_count=len(forecasts["unavailable_predictions"]))
        summary.update(full_report_sha256=sha(REPORT),
            scenarios=[compact(row) for row in rows])
        write_new_or_equal(SUMMARY, summary)
        print("Completed", len(rows), "scenarios; target gate:", goal, flush=True)
        return summary
    finally:
        lock.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    run(parser.parse_args().prepare_only)
