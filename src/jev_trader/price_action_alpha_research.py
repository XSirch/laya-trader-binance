"""Walk-forward research for the frozen independent price-action candidate."""

from __future__ import annotations

from bisect import bisect_left
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from .binance_data import HOUR_MS, load_cached_range
from .price_action_alpha import FEATURES, SYMBOLS, build_events
from .price_action_alpha_execution import replay

CONFIG = {
    "symbols": list(SYMBOLS), "bar_interval": "1h",
    "first_month": "2023-01", "last_month": "2026-08",
    "event": "current low below previous 24-hour low and current close above it",
    "entry_delay_hours_after_signal_close": 1,
    "horizon_hours": 24, "stop_buffer_atr": 0.10, "target_R": 2.0,
    "maximum_stop_distance_atr": 2.0, "event_cooldown_hours": 24,
    "side_costs": [0.0015, 0.003], "allocation_per_asset": 0.25,
    "minimum_training_events": 400,
    "estimator": {"loss": "squared_error", "max_depth": 3,
        "max_iter": 100, "learning_rate": 0.05, "max_leaf_nodes": 7,
        "min_samples_leaf": 40, "l2_regularization": 10.0,
        "max_bins": 64, "random_state": 548, "early_stopping": False},
    "prediction_target": "gross_trade_return_divided_by_R",
    "trade_gate": "predicted_gross_R * risk_fraction > 2 * side_cost",
    "target_net_cagr_pct": 50, "maximum_drawdown_pct": 10,
    "orders_authorized": False, "jev_calls_authorized": False,
}

ROOT = Path.cwd()
DATA_ROOT = ROOT / "data" / "binance" / "spot" / "1h"
INPUTS = ROOT / "results" / "price_action_alpha_inputs.json"
FULL_REPORT = ROOT / "results" / "price_action_alpha_research.json"
SUMMARY = ROOT / "docs" / "price_action_alpha_research_2026-09-27.json"


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha_bytes(payload):
    return hashlib.sha256(payload).hexdigest()


def _sha_file(path):
    return _sha_bytes(path.read_bytes())


def _stamp(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def _context_hash(event):
    return _sha_bytes(_canonical({"symbol": event["symbol"],
        "signal_ms": event["signal_ms"], "entry_ms": event["entry_ms"],
        "features": event["features"], "support24": event["support24"],
        "signal_low": event["signal_low"], "atr": event["atr"]}))


def _fit_and_predict(events):
    events = sorted(events, key=lambda event: (event["entry_ms"], event["symbol"]))
    predictions, errors, fits = [], [], []
    fitted_month = None
    model = None
    train_mean = None
    fit_cutoff = None
    for event in events:
        cutoff = event["entry_ms"]
        month = datetime.fromtimestamp(cutoff / 1000, timezone.utc).strftime("%Y-%m")
        if fitted_month != month:
            train = [row for row in events if row["entry_ms"] < cutoff
                     and row["available_ms"] < cutoff]
            fitted_month = month
            model = None
            train_mean = None
            fit_cutoff = cutoff
            if len(train) >= CONFIG["minimum_training_events"]:
                x_train = np.asarray([[row["features"][name] for name in FEATURES]
                                      for row in train], dtype=np.float64)
                y_train = np.asarray([row["gross_R"] for row in train], dtype=np.float64)
                model = HistGradientBoostingRegressor(**CONFIG["estimator"])
                with threadpool_limits(limits=1):
                    model.fit(x_train, y_train)
                train_mean = float(np.mean(y_train))
                audit = {"fit_month": month, "fit_cutoff_ms": cutoff,
                    "training_events": len(train),
                    "first_training_entry_ms": train[0]["entry_ms"],
                    "last_training_entry_ms": train[-1]["entry_ms"],
                    "latest_label_available_ms": max(row["available_ms"] for row in train),
                    "training_identity_sha256": _sha_bytes(_canonical([
                        [row["entry_ms"], row["symbol"], row["available_ms"]] for row in train])),
                    "training_features_sha256": _sha_bytes(_canonical([
                        [row["features"][name] for name in FEATURES] for row in train])),
                    "training_targets_sha256": _sha_bytes(_canonical(y_train.tolist())),
                    "estimator": dict(CONFIG["estimator"])}
                audit["model_sha256"] = _sha_bytes(_canonical(audit))
                fits.append(audit)
            else:
                fits.append({"fit_month": month, "fit_cutoff_ms": cutoff,
                    "training_events": len(train), "status": "below_minimum_training_events"})

        if model is None:
            continue
        vector = np.asarray([[event["features"][name] for name in FEATURES]], dtype=np.float64)
        with threadpool_limits(limits=1):
            prediction = float(model.predict(vector)[0])
        if not math.isfinite(prediction):
            raise ValueError("nonfinite price-action regression prediction")
        row = {"entry_ms": cutoff, "symbol": event["symbol"],
            "signal_ms": event["signal_ms"], "context_sha256": _context_hash(event),
            "predicted_gross_R": prediction, "training_mean_gross_R": train_mean,
            "actual_gross_R": event["gross_R"], "available_ms": event["available_ms"],
            "risk_fraction": event["risk_fraction"], "outcome_reason": event["reason"],
            "fit_cutoff_ms": fit_cutoff}
        predictions.append(row)
        errors.append(row)
    return predictions, errors, fits


def _forecast_scores(rows):
    result = {}
    periods = {"all": lambda row: True,
        "2024": lambda row: _stamp(row["entry_ms"]).startswith("2024-"),
        "2025": lambda row: _stamp(row["entry_ms"]).startswith("2025-"),
        "2026_jan_aug": lambda row: _stamp(row["entry_ms"]).startswith("2026-")}
    for period, predicate in periods.items():
        subset = [row for row in rows if predicate(row)]
        if not subset:
            result[period] = {"count": 0}
            continue
        actual = [row["actual_gross_R"] for row in subset]
        pred = [row["predicted_gross_R"] for row in subset]
        mean = [row["training_mean_gross_R"] for row in subset]
        mse = lambda a, b: math.fsum((x - y) ** 2 for x, y in zip(a, b)) / len(a)
        model_mse = mse(actual, pred)
        mean_mse = mse(actual, mean)
        zero_mse = mse(actual, [0.0] * len(actual))
        result[period] = {"count": len(subset),
            "mae_gross_R": math.fsum(abs(a - p) for a, p in zip(actual, pred)) / len(actual),
            "mse_gross_R": model_mse,
            "skill_vs_training_mean": (1 - model_mse / mean_mse if mean_mse > 0 else None),
            "skill_vs_zero": (1 - model_mse / zero_mse if zero_mse > 0 else None),
            "direction_accuracy": math.fsum((a > 0) == (p > 0) for a, p in zip(actual, pred)) / len(actual)}
    return result


def _compact(scenario):
    metrics = {key: value for key, value in scenario.items()
        if key not in {"daily_equity", "hourly_equity", "actions", "trades",
                       "execution_assumptions"}}
    return metrics


def run(progress=True):
    started = time.monotonic()
    market, selected_archives = load_cached_range(
        list(SYMBOLS), CONFIG["first_month"], CONFIG["last_month"], DATA_ROOT)
    if len(selected_archives) != len(SYMBOLS) * 44:
        raise ValueError("cached first-party archive coverage is incomplete")
    events, excluded = build_events(market)
    if len(events) <= CONFIG["minimum_training_events"]:
        raise ValueError("too few valid sweep/reclaim events for the frozen minimum")

    predictions, errors, fits = _fit_and_predict(events)
    if not predictions:
        raise ValueError("no walk-forward predictions met the frozen training minimum")
    prediction_map = {(row["entry_ms"], row["symbol"]): row for row in predictions}
    common = set.intersection(*(set(bar.open_ms for bar in market[symbol]) for symbol in SYMBOLS))
    common = sorted(common)
    latest_gap_after = max((following.open_ms for symbol in SYMBOLS
        for previous, following in zip(market[symbol], market[symbol][1:])
        if following.open_ms - previous.open_ms > HOUR_MS), default=0)
    continuous_starts = [timestamp for timestamp in common if timestamp > latest_gap_after]
    if not continuous_starts:
        raise ValueError("no common continuous spot path remains after the last data gap")
    start_ms = max(min(row["entry_ms"] for row in predictions), continuous_starts[0])
    end_ms = common[-1]
    expected_marks = set(range(start_ms, end_ms + 1, HOUR_MS))
    for symbol in SYMBOLS:
        available_marks = {bar.open_ms for bar in market[symbol] if start_ms <= bar.open_ms <= end_ms}
        if available_marks != expected_marks:
            raise ValueError("portfolio replay interval is not a complete common hourly path")
    eligible = [event for event in events if start_ms <= event["entry_ms"] <= end_ms - 24 * HOUR_MS]
    event_by_id = {(event["entry_ms"], event["symbol"]): event for event in eligible}
    predictions = [row for row in predictions if (row["entry_ms"], row["symbol"]) in event_by_id]
    prediction_map = {(row["entry_ms"], row["symbol"]): row for row in predictions}
    if not predictions:
        raise ValueError("no complete scored event remains inside the replay period")
    start_ms = min(row["entry_ms"] for row in predictions)
    forecast = _forecast_scores(predictions)

    scenarios = []
    models = ("ml_gated", "all_sweeps", "buy_hold", "cash")
    for mode in models:
        for cost in CONFIG["side_costs"]:
            row = replay(market, eligible, prediction_map if mode == "ml_gated" else {},
                start_ms=start_ms, end_ms=end_ms, side_cost=cost, mode=mode)
            row["meets_static_50_10_gate"] = (
                row["descriptive_annualized_cagr_pct"] >= CONFIG["target_net_cagr_pct"]
                and row["adverse_intrahour_drawdown_bound_pct"] <= CONFIG["maximum_drawdown_pct"])
            scenarios.append(row)
            if progress:
                print({key: row.get(key) for key in ("mode", "side_cost", "return_pct",
                    "descriptive_annualized_cagr_pct", "max_drawdown_pct",
                    "adverse_intrahour_drawdown_bound_pct", "entries", "event_count")}, flush=True)

    data_identity = [{key: archive[key] for key in ("symbol", "month", "sha256", "bytes", "rows", "gaps")
                      if key in archive} for archive in selected_archives]
    code_files = ["src/jev_trader/price_action_alpha.py",
        "src/jev_trader/price_action_alpha_execution.py",
        "src/jev_trader/price_action_alpha_research.py",
        "docs/price_action_alpha_protocol_2026-09-27.md"]
    source_hashes = {name: _sha_file(ROOT / name) for name in code_files}
    inputs = {"config": CONFIG, "features": list(FEATURES),
        "selected_archive_count": len(selected_archives), "archive_identity": data_identity,
        "archive_identity_sha256": _sha_bytes(_canonical(data_identity)),
        "event_count": len(events), "event_exclusions": excluded,
        "event_identity_sha256": _sha_bytes(_canonical([
            {"entry_ms": event["entry_ms"], "symbol": event["symbol"],
             "context_sha256": _context_hash(event)} for event in events])),
        "label_identity_sha256": _sha_bytes(_canonical([
            [event["entry_ms"], event["symbol"], event["available_ms"], event["gross_R"]]
            for event in events])),
        "common_timestamp_count": len(common), "replay_start_ms": start_ms,
        "replay_end_ms": end_ms, "source_hashes": source_hashes,
        "python": platform.python_version(), "numpy": np.__version__,
        "scikit_learn": sklearn.__version__}
    INPUTS.parent.mkdir(parents=True, exist_ok=True)
    INPUTS.write_bytes(_canonical(inputs))
    inputs_hash = _sha_file(INPUTS)
    full = {"created_utc": datetime.now(timezone.utc).isoformat(),
        "config": CONFIG, "decision": "retrospective event-specific experiment only; no consistency claim",
        "event_design": {"event_count": len(events), "excluded": excluded,
            "feature_names": list(FEATURES), "feature_count": len(FEATURES),
            "outcome_count": len(events), "fit_count": len(fits),
            "prediction_count": len(predictions),
            "prediction_training_availability_verified": True,
            "historical_point_in_time_verified": False,
            "first_prediction_ms": start_ms, "last_prediction_ms": max(row["entry_ms"] for row in predictions)},
        "forecast_scores": forecast, "fits": fits, "predictions": predictions,
        "scenarios": scenarios, "inputs": inputs, "inputs_file_sha256": inputs_hash,
        "elapsed_seconds": time.monotonic() - started,
        "selected_winner": None, "goal_achieved": False, "deployable": False,
        "orders_sent": 0, "jev_calls": 0,
        "limits": ["The historical files were already inspected in this project; this is not an untouched holdout.",
            "The product vendor does not publish GainzAlgo V2 Alpha rules; this is a separate implementation.",
            "Hourly OHLC and assumed costs do not establish actual orders, spreads, latency, or fills.",
            "The four assets are correlated and one event is not an independent market regime."]}
    FULL_REPORT.parent.mkdir(parents=True, exist_ok=True)
    FULL_REPORT.write_text(json.dumps(full, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    full_hash = _sha_file(FULL_REPORT)
    summary = {key: value for key, value in full.items()
        if key not in {"predictions", "fits", "scenarios", "inputs"}}
    summary.update({"full_report_sha256": full_hash,
        "scenario_count": len(scenarios),
        "scenarios": [_compact(row) for row in scenarios],
        "inputs": {key: value for key, value in inputs.items()
                   if key not in {"archive_identity"}}})
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2,
        sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    if progress:
        print("events", len(events), "predictions", len(predictions), "fits", len(fits), flush=True)
        print("input_sha256", inputs_hash, "full_report_sha256", full_hash, flush=True)
        print("Completed", len(scenarios), "price-action scenarios.", flush=True)
    return summary


if __name__ == "__main__":
    run()
