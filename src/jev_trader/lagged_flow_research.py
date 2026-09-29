"""Frozen walk-forward study of lagged BTC/ETH information for spot returns."""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import itertools
import json
import os
import platform
import re
import subprocess
import time

from .basis_data import load
from .basis_features import canonical
from .basis_research import sha, timestamp, write_new_or_equal
from .binance_data import HOUR_MS
from .cli import ROOT, RESULTS
from .hourly_forecast_research import RUNTIME
from .hourly_forecast_prediction import ESTIMATOR_PARAMETERS
from .lagged_flow_prediction import (build_panel, build_forecasts, MODELS, SYMBOLS,
                                     TRAINING_WINDOW_MS, MIN_TRAINING_ROWS, INTERVAL_HOURS)
from .lagged_flow_execution import evaluate, ExecutionUnavailable

CONFIG = {
    "schema_version": 1,
    "symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"],
    "leader_symbols": ["BTCUSDT", "ETHUSDT"],
    "feature_lags_hours": [1, 2, 3, 6],
    "models": ["rolling_mean", "own_hgb", "leader_hgb", "always", "buy_hold"],
    "side_costs": [0.0015, 0.003],
    "allocation_per_asset": 0.25,
    "decision_interval_hours": 8,
    "target_horizon_hours": 8,
    "execution_delay_hours": 1,
    "training_window_days": 365,
    "minimum_training_rows": 4000,
    "refit": "first_eligible_event_monthly_cutoff",
    "development": ["2024-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"],
    "later": ["2025-01-01T00:00:00+00:00", "2026-08-31T16:00:00+00:00"],
    "target_net_cagr_pct": 50,
    "maximum_drawdown_pct": 10,
    "historical_point_in_time_verified": False,
}
PROTOCOL = ROOT / "docs/lagged_flow_protocol_2026-09-27.md"
INPUTS = RESULTS / "lagged_flow_inputs.json"
REPORT = RESULTS / "lagged_flow_research.json"
SUMMARY = ROOT / "docs/lagged_flow_research_2026-09-27.json"
CODE = ("lagged_flow_prediction.py", "lagged_flow_execution.py", "lagged_flow_research.py",
        "basis_data.py", "basis_features.py", "basis_research.py", "binance_data.py",
        "hourly_forecast_features.py", "hourly_forecast_prediction.py",
        "hourly_forecast_research.py", "tree_prediction.py", "derivatives_data.py", "market_state.py")
LARGE = {"hourly_equity", "daily_equity", "action_decisions"}


def anchors():
    blocks = re.findall(r"```json\s*\n(.*?)\n```", PROTOCOL.read_text(encoding="utf-8"), re.DOTALL)
    if len(blocks) != 1 or json.loads(blocks[0]) != CONFIG:
        raise ValueError("lagged-flow protocol/configuration mismatch")
    if TRAINING_WINDOW_MS != 365 * 24 * HOUR_MS or MIN_TRAINING_ROWS != 4000 or INTERVAL_HOURS != 8:
        raise ValueError("lagged-flow training schedule mismatch")
    runtime = {name: importlib.metadata.version(name) for name in RUNTIME}
    if runtime != RUNTIME:
        raise ValueError("lagged-flow study requires pinned tree runtime")
    files = [PROTOCOL, ROOT / "docs/cross_asset_sources_2026-09-26.md",
        ROOT / "docs/strategy_research_sources_2026-09-27.md",
        ROOT / "docs/barrier_payoff_research_2026-09-27.md",
        ROOT / "docs/basis_data_inventory_2026-09-26.md",
        ROOT / "requirements-tree.lock", ROOT / "pyproject.toml"]
    files += [ROOT / "src/jev_trader" / name for name in CODE]
    files += sorted((ROOT / "tests").glob("test_lagged_flow_*.py"))
    return {"files_sha256": {str(path.relative_to(ROOT)).replace("\\", "/"): sha(path) for path in files},
        "runtime": runtime, "python": platform.python_version(),
        "estimator_parameters": ESTIMATOR_PARAMETERS}


def prepare():
    frozen = anchors()
    market, data_audit = load()
    if data_audit.get("network_requests") != 0 or data_audit.get("cache_writes") != 0:
        raise ValueError("lagged-flow preparation must be offline and read-only")
    print("Verified local inventory; building the four-asset 8-hour panel.", flush=True)
    panel, fields, feature_audit = build_panel(market)
    inputs = {"anchors": frozen, "config": CONFIG, "data": data_audit,
              "features": feature_audit, "fields": list(fields)}
    if anchors() != frozen:
        raise ValueError("lagged-flow sources changed during preparation")
    write_new_or_equal(INPUTS, inputs)
    return market["spot"], panel, fields, inputs


def calendar_year_returns(monthly):
    grouped = defaultdict(list)
    for month, value in sorted(monthly.items()):
        grouped[month[:4]].append(value)
    return {year: 100 * (__import__("math").prod(1 + value / 100 for value in values) - 1)
            for year, values in grouped.items()}


def scenario(spot, event_symbols, forecasts, model, cost, period):
    start, end = map(timestamp, CONFIG[period])
    mode = model
    signals = forecasts["predictions"][model] if model in MODELS else {}
    row = {"model": model, "side_cost": cost, "period": period, "mode": mode}
    try:
        metrics = evaluate(spot, event_symbols, signals, start_ms=start, end_ms=end,
                           side_cost=cost, mode=mode)
    except ExecutionUnavailable as error:
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


def compact(row):
    result = {key: value for key, value in row.items() if key != "metrics"}
    if row["metrics"] is None:
        result["metrics"] = None
        return result
    result["metrics"] = {key: value for key, value in row["metrics"].items() if key not in LARGE}
    result["event_counts"] = {key: len(row["metrics"][key]) for key in sorted(LARGE) if key in row["metrics"]}
    result["series_sha256"] = {key: hashlib.sha256(canonical(row["metrics"][key])).hexdigest()
                                for key in sorted(LARGE) if key in row["metrics"]}
    return result


def serializable_forecasts(forecasts):
    """Keep composite event identity as explicit fields in the JSON report."""
    result = dict(forecasts)
    result["predictions"] = {
        name: [{"execution_ms": key[0], "symbol": key[1], **value}
               for key, value in sorted(rows.items())]
        for name, rows in forecasts["predictions"].items()}
    result["label_outcomes"] = [
        {"execution_ms": key[0], "symbol": key[1], **value}
        for key, value in sorted(forecasts["label_outcomes"].items())]
    return result


def run(prepare_only=False):
    RESULTS.mkdir(exist_ok=True)
    lock = RESULTS / "lagged_flow_research.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(descriptor)
    try:
        started = time.perf_counter()
        if not prepare_only and (not INPUTS.exists() or REPORT.exists() or SUMMARY.exists()):
            raise ValueError("freeze lagged-flow inputs first and preserve any existing result")
        spot, panel, fields, inputs = prepare()
        event_symbols = defaultdict(set)
        for execution_ms, symbol in panel:
            event_symbols[execution_ms].add(symbol)
        print("Frozen panel events:", len(panel), "fields:", len(fields), flush=True)
        if prepare_only:
            return inputs
        forecasts = build_forecasts( panel, fields, spot,
            progress=lambda row: print("Monthly fit:", row, flush=True))
        periods = {"development": CONFIG["development"], "later": CONFIG["later"],
            "year2025": ["2025-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"],
            "year2026": ["2026-01-01T00:00:00+00:00", CONFIG["later"][1]]}
        scores = {key: forecasts_score(forecasts["prediction_errors"], *map(timestamp, dates))
                  for key, dates in periods.items()}
        rows = [scenario(spot, event_symbols, forecasts, model, cost, period)
            for model, cost, period in itertools.product(CONFIG["models"], CONFIG["side_costs"],
                                                          ("development", "later"))]
        if anchors() != inputs["anchors"]:
            raise ValueError("lagged-flow sources changed during experiment")
        later = [row for row in rows if row["period"] == "later"]
        selected = [row for row in later if row["model"] == "leader_hgb"]
        annual_positive = all(
            all(value > 0 for year, value in row["metrics"]["calendar_year_returns"].items()
                if year in ("2025", "2026")) and set(row["metrics"]["calendar_year_returns"]) >= {"2025", "2026"}
            for row in selected if row["status"] == "complete")
        goal = (len(selected) == 2 and all(row["status"] == "complete" and row["meets_adverse_target"]
                for row in selected) and annual_positive)
        report = {"created_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": time.perf_counter() - started,
            "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "inputs": inputs, "inputs_file_sha256": sha(INPUTS),
            "forecasts": serializable_forecasts(forecasts),
            "forecast_scores": scores, "scenarios": rows, "goal_achieved": goal,
            "deployable": False, "selected_winner": None, "orders_sent": 0,
            "new_market_downloads": 0, "jev_calls": 0,
            "limits": ["All history in this project has been examined; results remain retrospective.",
                "OHLC prices and assumed proportional fees do not prove fills or account-specific costs.",
                "The four assets and their hourly outcomes are correlated, not independent observations.",
                "Funding publication timing and availability in historical features remain unverified.",
                "Hourly extrema form a conservative bound, not an observed intrabar path."]}
        write_new_or_equal(REPORT, report)
        summary = {key: value for key, value in report.items() if key not in ("forecasts", "scenarios")}
        summary["forecasts"] = {key: value for key, value in forecasts.items()
            if key not in ("predictions", "prediction_errors", "label_outcomes", "unavailable_labels", "unavailable_predictions")}
        summary["forecasts"].update(
            prediction_counts={name: len(values) for name, values in forecasts["predictions"].items()},
            prediction_audits=forecasts["prediction_audits"],
            prediction_error_count=len(forecasts["prediction_errors"]),
            label_count=len(forecasts["label_outcomes"]),
            unavailable_label_count=len(forecasts["unavailable_labels"]),
            unavailable_prediction_count=len(forecasts["unavailable_predictions"]))
        summary.update(full_report_sha256=sha(REPORT), scenarios=[compact(row) for row in rows])
        write_new_or_equal(SUMMARY, summary)
        print("Completed", len(rows), "scenarios; target gate:", goal, flush=True)
        return summary
    finally:
        lock.unlink()


def forecasts_score(errors, start, end):
    from .lagged_flow_prediction import score_forecasts
    return score_forecasts(errors, start, end)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    run(parser.parse_args().prepare_only)
