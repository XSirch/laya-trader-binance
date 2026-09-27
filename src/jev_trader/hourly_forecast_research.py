"""Frozen hourly BTC forecast/turnover experiment, using verified offline data."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import itertools
import json
import math
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
from .hourly_forecast_execution import evaluate
from .hourly_forecast_features import build_states
from .hourly_forecast_prediction import (build_forecasts, ESTIMATOR_PARAMETERS, MIN_TRAINING_ROWS,
                                         TRAINING_WINDOW_MS)

CONFIG = {
    "schema_version": 1, "symbol": "BTCUSDT",
    "periods": {"development": ["2023-01-01T00:00:00+00:00", "2024-01-01T00:00:00+00:00"],
                "later": ["2024-01-01T00:00:00+00:00", "2026-08-31T23:00:00+00:00"]},
    "models": ["rolling_mean", "hgb"], "modes": ["sign", "cost_band"],
    "side_costs": [.0012, .0024], "allocations": [.5, 1.], "portfolio_trailing": [None, .04],
    "label_hours": 1, "label_quality_delay_hours": 1, "execution_delay_hours": 1,
    "rolling_training_days": 365, "minimum_training_rows": 4320,
    "refit": "first_eligible_monthly_cutoff", "cost_band_multiple": 2,
    "target_net_cagr_pct": 50, "maximum_drawdown_pct": 10,
    "historical_point_in_time_verified": False,
}
PROTOCOL = ROOT/"docs/hourly_forecast_protocol_2026-09-26.md"
INPUTS = RESULTS/"hourly_forecast_inputs.json"
REPORT = RESULTS/"hourly_forecast_research.json"
CODE = ("hourly_forecast_features.py", "hourly_forecast_prediction.py", "hourly_forecast_execution.py",
        "hourly_forecast_research.py", "basis_data.py", "basis_features.py", "basis_research.py",
        "basis_execution.py", "basis_policy.py", "binance_data.py", "derivatives_data.py",
        "market_state.py", "strategies.py", "cli.py", "tree_prediction.py")
RUNTIME = {"numpy": "2.5.3", "scikit-learn": "1.9.1", "scipy": "1.18.1", "threadpoolctl": "3.7.0"}


def anchors():
    blocks = re.findall(r"```json\s*\n(.*?)\n```", PROTOCOL.read_text(encoding="utf-8"), re.DOTALL)
    if len(blocks) != 1 or json.loads(blocks[0]) != CONFIG:
        raise ValueError("hourly protocol/configuration mismatch")
    if MIN_TRAINING_ROWS != CONFIG["minimum_training_rows"] or TRAINING_WINDOW_MS != 365*24*HOUR_MS:
        raise ValueError("hourly predictor training configuration mismatch")
    runtime = {name: importlib.metadata.version(name) for name in RUNTIME}
    if runtime != RUNTIME:
        raise ValueError("hourly forecast requires pinned tree runtime")
    files = [PROTOCOL, ROOT/"docs/hourly_forecast_sources_2026-09-26.md",
             ROOT/"docs/intrahour_bound_clarification_2026-09-26.md",
             ROOT/"docs/basis_data_inventory_2026-09-26.md", ROOT/"requirements-tree.lock", ROOT/"pyproject.toml"]
    files += [ROOT/"src/jev_trader"/name for name in CODE]
    files += sorted((ROOT/"tests").glob("test_hourly_forecast_*.py"))
    return {"files_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in files},
            "runtime": runtime, "python": platform.python_version(),
            "estimator_parameters": ESTIMATOR_PARAMETERS}


def prepare():
    frozen = anchors()
    market, data_audit = load()
    print("Verified offline inventory; building absolute BTC hourly states.", flush=True)
    states, fields, feature_audit = build_states(market)
    inputs = {"anchors": frozen, "config": CONFIG, "data": data_audit, "features": feature_audit}
    if anchors() != frozen:
        raise ValueError("hourly sources changed during preparation")
    write_new_or_equal(INPUTS, inputs)
    return market["spot"][CONFIG["symbol"]], states, fields, inputs


def score_forecasts(errors, start, end):
    selected = [r for r in errors if start <= r["execution_ms"] < end and r["label_end_ms"] <= end]
    if not selected:
        return {"count": 0, "models": {}}
    actual = [r["actual_return"] for r in selected]
    zero_sse = math.fsum(y*y for y in actual)
    scores = {}
    for name in CONFIG["models"]:
        residuals = [r[name+"_prediction"]-r["actual_return"] for r in selected]
        sse = math.fsum(e*e for e in residuals)
        scores[name] = {"mse": sse/len(selected), "mae": math.fsum(abs(e) for e in residuals)/len(selected),
                        "skill_vs_zero": 1-sse/zero_sse if zero_sse else None,
                        "direction_accuracy": sum((r[name+"_prediction"] > 0) == (r["actual_return"] > 0)
                                                  for r in selected)/len(selected)}
    return {"count": len(selected), "models": scores,
            "hgb_mse_minus_mean_mse": scores["hgb"]["mse"]-scores["rolling_mean"]["mse"],
            "zero_actual_return_count": sum(y == 0 for y in actual)}


def calendar_year_returns(monthly):
    groups = {}
    for month, value in sorted(monthly.items()):
        record = groups.setdefault(month[:4], {"growth": 1., "months": []})
        record["growth"] *= 1+value/100
        record["months"].append(month)
    return {year: {"return_pct": 100*(row["growth"]-1), "months": row["months"],
                   "complete_calendar_year": row["months"] == [f"{year}-{m:02}" for m in range(1, 13)]}
            for year, row in groups.items()}


def scenario(spot, signals, model, mode, cost, allocation, trailing, period):
    start, end = map(timestamp, CONFIG["periods"][period])
    row = {"model": model, "mode": mode, "side_cost": cost, "allocation": allocation,
           "portfolio_trailing": trailing, "period": period}
    try:
        metrics = evaluate(spot, signals, start_ms=start, end_ms=end, side_cost=cost,
                           allocation=allocation, mode=mode, trailing=trailing)
    except ValueError as error:
        if not str(error).startswith(("missing held spot price", "missing execution spot price", "unverified spot execution liquidity",
                                      "negative cash", "nonpositive")):
            raise
        row.update(status="invalid_execution", metrics=None, error=str(error),
                   meets_nominal_target=False, meets_target_and_adverse_bound=False)
    else:
        metrics["calendar_year_returns"] = calendar_year_returns(metrics["monthly_returns_pct"])
        years = (end-start)/(365.25*24*HOUR_MS)
        cagr = 100*((1+metrics["return_pct"]/100)**(1/years)-1)
        nominal = cagr >= 50 and metrics["max_drawdown_pct"] <= 10
        row.update(status="complete", metrics=metrics, net_cagr_pct=cagr, meets_nominal_target=nominal,
                   meets_target_and_adverse_bound=nominal and metrics["adverse_intrahour_drawdown_bound_pct"] <= 10)
    print({k: row.get(k) for k in ("model", "mode", "allocation", "side_cost", "portfolio_trailing",
                                  "period", "status", "net_cagr_pct")}, flush=True)
    return row


def compact_scenario(row):
    output = {k: v for k, v in row.items() if k != "metrics"}
    if row["metrics"] is None:
        output["metrics"] = None
        return output
    large = {"trade_events", "stop_events", "hourly_equity", "daily_equity", "wallet_snapshots", "action_decisions"}
    output["metrics"] = {k: v for k, v in row["metrics"].items() if k not in large}
    output["event_counts"] = {k: len(row["metrics"][k]) for k in sorted(large)}
    output["series_sha256"] = {k: hashlib.sha256(canonical(row["metrics"][k])).hexdigest() for k in sorted(large)}
    return output


def run(prepare_only=False):
    RESULTS.mkdir(exist_ok=True)
    lock = RESULTS/"hourly_forecast_research.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    try:
        started = time.perf_counter()
        if not prepare_only and (not INPUTS.exists() or REPORT.exists()):
            raise ValueError("freeze inputs first and preserve any existing hourly result")
        spot, states, fields, inputs = prepare()
        print("Frozen hourly feature rows:", len(states), "fields:", len(fields), flush=True)
        if prepare_only:
            return inputs
        forecasts = build_forecasts(spot, states, fields, progress=lambda r: print("Monthly fit:", r, flush=True))
        for model in forecasts["models"].values():
            model["signal_sha256"] = hashlib.sha256(canonical(model["signals"])).hexdigest()
        periods = {**CONFIG["periods"], "year2024": ["2024-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"],
                   "year2025": ["2025-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"],
                   "year2026": ["2026-01-01T00:00:00+00:00", CONFIG["periods"]["later"][1]]}
        scores = {name: score_forecasts(forecasts["prediction_errors"], *map(timestamp, dates))
                  for name, dates in periods.items()}
        rows = [scenario(spot, forecasts["models"][model]["signals"], model, mode, cost, allocation, trailing, period)
                for model, mode, cost, allocation, trailing, period in itertools.product(
                    CONFIG["models"], CONFIG["modes"], CONFIG["side_costs"], CONFIG["allocations"],
                    CONFIG["portfolio_trailing"], CONFIG["periods"])]
        rows += [scenario(spot, forecasts["models"]["rolling_mean"]["signals"], "benchmark", "buy_hold",
                          cost, allocation, None, period)
                 for cost, allocation, period in itertools.product(CONFIG["side_costs"], CONFIG["allocations"], CONFIG["periods"])]
        if anchors() != inputs["anchors"]:
            raise ValueError("hourly sources changed during experiment")
        report = {"created_utc": datetime.now(timezone.utc).isoformat(), "elapsed_seconds": time.perf_counter()-started,
                  "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                  "inputs": inputs, "inputs_file_sha256": sha(INPUTS), "forecasts": forecasts,
                  "forecast_scores": scores, "scenarios": rows, "goal_achieved": False, "deployable": False,
                  "selected_winner": None, "jev_calls": 0, "orders_sent": 0, "new_market_downloads": 0,
                  "limits": ["Reused history does not provide untouched confirmation.",
                      "A different target and horizon do not establish an economic edge by themselves.",
                      "Prediction labels are gross one-hour spot returns, not probabilities or full holding-period profits.",
                      "Hourly fills, publication timing and fee/slippage assumptions are unverified for a real account.",
                      "Technical formulas are inherited from frozen basis context; all lookbacks are hourly.",
                      "The adverse intrahour bound permits unknown extreme order and is not an observed price path.",
                      "Trailing cannot guarantee the portfolio drawdown ceiling.",
                      "Funding is a predictor only; this paid spot account neither receives nor pays it."]}
        write_new_or_equal(REPORT, report)
        summary = {k: v for k, v in report.items() if k not in ("forecasts", "scenarios")}
        summary["forecasts"] = {k: v for k, v in forecasts.items() if k not in ("models", "prediction_errors", "unavailable_labels", "unavailable_predictions")}
        summary["forecasts"].update(model_counts={name: {"signals": len(model["signals"]),
            "prediction_audits": len(model["prediction_audits"]), "signal_sha256": model["signal_sha256"]}
            for name, model in forecasts["models"].items()}, prediction_error_count=len(forecasts["prediction_errors"]),
            unavailable_label_count=len(forecasts["unavailable_labels"]), unavailable_prediction_count=len(forecasts["unavailable_predictions"]))
        summary.update(full_report_sha256=sha(REPORT), scenarios=[compact_scenario(row) for row in rows])
        write_new_or_equal(ROOT/"docs/hourly_forecast_research_2026-09-26.json", summary)
        print("Completed", len(rows), "scenarios; nominal targets:", sum(r["meets_nominal_target"] for r in rows), flush=True)
        return summary
    finally:
        lock.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    run(parser.parse_args().prepare_only)
