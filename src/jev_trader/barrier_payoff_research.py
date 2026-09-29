"""Offline, frozen stop/target/timeout payoff experiment for paid BTC spot."""

import argparse
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
from .cli import ROOT, RESULTS
from .hourly_forecast_features import build_states
from .hourly_forecast_research import calendar_year_returns, score_forecasts, RUNTIME, CODE as HOURLY_CODE
from .barrier_payoff_prediction import build_forecasts, MAX_HOURS, MIN_TRAINING_ROWS, TRAINING_WINDOW_MS
from .barrier_payoff_execution import evaluate, ExecutionUnavailable
from .hourly_forecast_prediction import ESTIMATOR_PARAMETERS, HOUR_MS

CONFIG = {
    "schema_version": 1, "symbol": "BTCUSDT",
    "periods": {"development": ["2023-01-01T00:00:00+00:00", "2024-01-01T00:00:00+00:00"],
                "later": ["2024-01-01T00:00:00+00:00", "2026-08-31T23:00:00+00:00"]},
    "models": ["rolling_mean", "hgb", "always", "buy_hold"],
    "side_costs": [.0012, .0024], "allocations": [.5, 1.],
    "stop_atr": 1, "target_atr": 2, "max_hours": 8, "execution_delay_hours": 1,
    "rolling_training_days": 365, "minimum_training_rows": 4320,
    "refit": "first_eligible_monthly_cutoff", "target_net_cagr_pct": 50,
    "maximum_drawdown_pct": 10, "historical_point_in_time_verified": False,
}
PROTOCOL = ROOT/"docs/barrier_payoff_protocol_2026-09-26.md"
INPUTS = RESULTS/"barrier_payoff_inputs.json"
REPORT = RESULTS/"barrier_payoff_research.json"
LARGE = {"trade_events", "stop_events", "hourly_equity", "daily_equity", "wallet_snapshots",
         "action_decisions", "valuation_points", "decision_trace"}


def anchors():
    blocks = re.findall(r"```json\s*\n(.*?)\n```", PROTOCOL.read_text(encoding="utf-8"), re.DOTALL)
    if len(blocks) != 1 or json.loads(blocks[0]) != CONFIG:
        raise ValueError("barrier protocol/configuration mismatch")
    if MAX_HOURS != 8 or MIN_TRAINING_ROWS != 4320 or TRAINING_WINDOW_MS != 365*24*HOUR_MS:
        raise ValueError("barrier predictor configuration mismatch")
    runtime = {key: importlib.metadata.version(key) for key in RUNTIME}
    if runtime != RUNTIME:
        raise ValueError("barrier study requires pinned tree runtime")
    files = [PROTOCOL, ROOT/"docs/barrier_payoff_sources_2026-09-26.md",
             ROOT/"docs/cross_asset_sources_2026-09-26.md", ROOT/"docs/basis_data_inventory_2026-09-26.md",
             ROOT/"requirements-tree.lock", ROOT/"pyproject.toml"]
    code = set(HOURLY_CODE) | {"barrier_payoff_prediction.py", "barrier_payoff_execution.py", "barrier_payoff_research.py"}
    files += [ROOT/"src/jev_trader"/name for name in sorted(code)]
    files += sorted((ROOT/"tests").glob("test_barrier_payoff_*.py"))
    return {"files_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in files},
            "runtime": runtime, "python": platform.python_version(), "estimator_parameters": ESTIMATOR_PARAMETERS}


def prepare():
    frozen = anchors()
    market, data_audit = load()
    print("Verified inventory; building unchanged 114-field BTC context.", flush=True)
    states, fields, features = build_states(market)
    if features["state_sha256"] != "1c4a3ec01be0efab8daea6a52fd2b87928d5ea20d7cd4371751ee284cb56a902":
        raise ValueError("barrier inputs differ from the previously frozen BTC context")
    inputs = {"anchors": frozen, "config": CONFIG, "data": data_audit, "features": features}
    if anchors() != frozen:
        raise ValueError("barrier sources changed during preparation")
    write_new_or_equal(INPUTS, inputs)
    return market["spot"][CONFIG["symbol"]], states, fields, inputs


def scenario(spot, states, forecasts, model, cost, allocation, period):
    start, end = map(timestamp, CONFIG["periods"][period])
    mode = model if model in ("always", "buy_hold") else "forecast"
    signals = forecasts["models"][model if mode == "forecast" else "rolling_mean"]["signals"]
    row = {"model": model, "mode": mode, "side_cost": cost, "allocation": allocation, "period": period}
    try:
        metrics = evaluate(spot, signals, states, start_ms=start, end_ms=end,
                           side_cost=cost, allocation=allocation, mode=mode)
    except ExecutionUnavailable as error:
        row.update(status="invalid_execution", metrics=None, error=str(error),
                   meets_nominal_target=False, meets_target_and_adverse_bound=False)
    else:
        metrics["calendar_year_returns"] = calendar_year_returns(metrics["monthly_returns_pct"])
        years = (end-start)/(365.25*24*HOUR_MS)
        cagr = 100*((1+metrics["return_pct"]/100)**(1/years)-1)
        nominal = cagr >= 50 and metrics["max_drawdown_pct"] <= 10
        row.update(status="complete", metrics=metrics, net_cagr_pct=cagr,
                   meets_nominal_target=nominal,
                   meets_target_and_adverse_bound=nominal and metrics["adverse_intrahour_drawdown_bound_pct"] <= 10)
    print({k: row.get(k) for k in ("model", "allocation", "side_cost", "period", "status", "net_cagr_pct")}, flush=True)
    return row


def compact(row):
    result = {k: v for k, v in row.items() if k != "metrics"}
    if row["metrics"] is None:
        return {**result, "metrics": None}
    result["metrics"] = {k: v for k, v in row["metrics"].items() if k not in LARGE}
    result["event_counts"] = {k: len(row["metrics"][k]) for k in sorted(LARGE) if k in row["metrics"]}
    result["series_sha256"] = {k: hashlib.sha256(canonical(row["metrics"][k])).hexdigest()
                               for k in sorted(LARGE) if k in row["metrics"]}
    return result


def run(prepare_only=False):
    RESULTS.mkdir(exist_ok=True)
    lock = RESULTS/"barrier_payoff_research.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(descriptor)
    try:
        started = time.perf_counter()
        if not prepare_only and (not INPUTS.exists() or REPORT.exists()):
            raise ValueError("freeze barrier inputs first and preserve any existing result")
        spot, states, fields, inputs = prepare()
        print("Frozen states:", len(states), "fields:", len(fields), flush=True)
        if prepare_only:
            return inputs
        forecasts = build_forecasts(spot, states, fields, progress=lambda r: print("Monthly fit:", r, flush=True))
        for model in forecasts["models"].values():
            model["signal_sha256"] = hashlib.sha256(canonical(model["signals"])).hexdigest()
        periods = {**CONFIG["periods"], "year2024": ["2024-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"],
                   "year2025": ["2025-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"],
                   "year2026": ["2026-01-01T00:00:00+00:00", CONFIG["periods"]["later"][1]]}
        scores = {key: score_forecasts(forecasts["prediction_errors"], *map(timestamp, dates))
                  for key, dates in periods.items()}
        rows = [scenario(spot, states, forecasts, model, cost, allocation, period)
                for model, cost, allocation, period in itertools.product(CONFIG["models"], CONFIG["side_costs"],
                                                                        CONFIG["allocations"], CONFIG["periods"])]
        if anchors() != inputs["anchors"]:
            raise ValueError("barrier sources changed during experiment")
        report = {"created_utc": datetime.now(timezone.utc).isoformat(), "elapsed_seconds": time.perf_counter()-started,
            "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "inputs": inputs, "inputs_file_sha256": sha(INPUTS), "forecasts": forecasts,
            "forecast_scores": scores, "scenarios": rows, "goal_achieved": False, "deployable": False,
            "selected_winner": None, "jev_calls": 0, "orders_sent": 0, "new_market_downloads": 0,
            "limits": ["Reused history is not untouched confirmation.",
                "OHLC first-touch ordering and stop/limit fills are assumptions; exact intrabar execution time is unknown.",
                "The full-bar adverse bound can include prices after the assumed intrabar fill.",
                "Potential training episodes overlap; they are not independent trades.",
                "A payoff forecast is neither a probability nor a guaranteed execution profit.",
                "Publication timing, executable quotes, individual fees and capacity remain unverified.",
                "ATR-sized barriers do not guarantee a total portfolio drawdown ceiling."]}
        write_new_or_equal(REPORT, report)
        summary = {k: v for k, v in report.items() if k not in ("forecasts", "scenarios")}
        summary["forecasts"] = {k: v for k, v in forecasts.items() if k not in
            ("models", "prediction_errors", "label_outcomes", "unavailable_labels", "unavailable_predictions")}
        summary["forecasts"].update(model_counts={name: {"signals": len(m["signals"]),
            "prediction_audits": len(m["prediction_audits"]), "signal_sha256": m["signal_sha256"]}
            for name, m in forecasts["models"].items()}, label_count=len(forecasts["label_outcomes"]),
            prediction_error_count=len(forecasts["prediction_errors"]), unavailable_label_count=len(forecasts["unavailable_labels"]),
            unavailable_prediction_count=len(forecasts["unavailable_predictions"]))
        summary.update(full_report_sha256=sha(REPORT), scenarios=[compact(r) for r in rows])
        write_new_or_equal(ROOT/"docs/barrier_payoff_research_2026-09-26.json", summary)
        print("Completed", len(rows), "scenarios; nominal targets:", sum(r["meets_nominal_target"] for r in rows), flush=True)
        return summary
    finally:
        lock.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    run(parser.parse_args().prepare_only)
