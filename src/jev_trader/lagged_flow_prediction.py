"""Pooled eight-hour spot forecasts with causally lagged cross-asset flow."""

from bisect import bisect_left
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math

from .basis_features import build_states as build_contexts, canonical
from .binance_data import HOUR_MS
from .hourly_forecast_features import flatten_contexts
from .hourly_forecast_prediction import ESTIMATOR_PARAMETERS
from .tree_prediction import _finite, _hash, _runtime

SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
LEADERS = ("BTCUSDT", "ETHUSDT")
LAGS = (1, 2, 3, 6)
HORIZON_HOURS = 8
INTERVAL_HOURS = 8
TRAINING_WINDOW_MS = 365 * 24 * HOUR_MS
MIN_TRAINING_ROWS = 4_000
MODELS = ("rolling_mean", "own_hgb", "leader_hgb")


def _lag_values(spot, end_open_ms, lag):
    """Return an n-hour close return and n-hour taker volume imbalance."""
    first = end_open_ms - (lag - 1) * HOUR_MS
    end_bar = spot.get(end_open_ms)
    prior = spot.get(end_open_ms - lag * HOUR_MS)
    bars = [spot.get(first + i * HOUR_MS) for i in range(lag)]
    if end_bar is None or prior is None or any(bar is None for bar in bars):
        return None, None
    if (any(not _finite(getattr(bar, "close", None)) or bar.close <= 0 for bar in (end_bar, prior))
            or any(not _finite(getattr(bar, "volume", None)) or bar.volume <= 0
                   or not _finite(getattr(bar, "taker_buy_base", None))
                   or bar.taker_buy_base < 0 or bar.taker_buy_base > bar.volume for bar in bars)):
        return None, None
    imbalance = 2 * math.fsum(bar.taker_buy_base for bar in bars) / math.fsum(bar.volume for bar in bars) - 1
    return end_bar.close / prior.close - 1, imbalance


def build_panel(market):
    """Flatten each asset's causal context and add fixed 1/2/3/6-hour lags."""
    if not isinstance(market, dict) or set(market.get("spot", {})) != set(SYMBOLS):
        raise ValueError("market must contain exactly the four frozen spot symbols")
    contexts, context_audit = build_contexts(market)
    fields = None
    panel = {}
    state_hashes = {}
    for symbol in SYMBOLS:
        base, current_fields, _ = flatten_contexts(contexts[symbol])
        if fields is None:
            fields = current_fields
        elif fields != current_fields:
            raise ValueError("base feature schema differs by asset")
        spot = market["spot"][symbol]
        for execution_ms, row in sorted(base.items()):
            if execution_ms % (INTERVAL_HOURS * HOUR_MS):
                continue
            end_open = execution_ms - 2 * HOUR_MS
            values = {name: row[name] for name in fields}
            for lag in LAGS:
                own_return, own_flow = _lag_values(spot, end_open, lag)
                values[f"own.return_{lag}h"] = own_return
                values[f"own.flow_imbalance_{lag}h"] = own_flow
            for leader in LEADERS:
                for lag in LAGS:
                    if leader == symbol:
                        ret, flow = None, None
                    else:
                        ret, flow = _lag_values(market["spot"][leader], end_open, lag)
                    values[f"leader.{leader}.return_{lag}h"] = ret
                    values[f"leader.{leader}.flow_imbalance_{lag}h"] = flow
            for asset in SYMBOLS:
                values[f"asset.is_{asset}"] = float(asset == symbol)
            if any(value is not None and not _finite(value) for value in values.values()):
                raise ValueError("feature panel contains a nonfinite value")
            feature_names = tuple(sorted(values))
            if "field_names" not in state_hashes:
                state_hashes["field_names"] = feature_names
            elif state_hashes["field_names"] != feature_names:
                raise ValueError("lag feature schema differs by asset")
            ordered = [None if values[name] is None else float(values[name]) for name in feature_names]
            observed_close = execution_ms - HOUR_MS
            identity = {"execution_ms": execution_ms, "symbol": symbol,
                        "latest_observed_close_ms": observed_close,
                        "base_context_sha256": row["context_sha256"], "features": ordered}
            key = (execution_ms, symbol)
            panel[key] = {**identity, "context_sha256": _hash(identity)}
    feature_names = state_hashes.pop("field_names", None)
    if not panel or feature_names is None:
        raise ValueError("no eligible pooled events")
    digest = hashlib.sha256()
    for key in sorted(panel):
        digest.update(canonical(panel[key]) + b"\n")
    return panel, feature_names, {"basis_context_audit": context_audit,
        "panel_sha256": digest.hexdigest(), "fields": list(feature_names),
        "field_count": len(feature_names), "event_count": len(panel),
        "symbols": list(SYMBOLS), "leaders": list(LEADERS),
        "first_execution_ms": min(key[0] for key in panel),
        "last_execution_ms": max(key[0] for key in panel),
        "historical_point_in_time_verified": False}


def _valid_price_bar(bar, timestamp):
    if bar is None or getattr(bar, "open_ms", None) != timestamp:
        return False
    values = [getattr(bar, name, None) for name in ("open", "high", "low", "close")]
    if any(not _finite(value) or value <= 0 for value in values):
        return False
    opening, high, low, close = values
    return 0 < low <= min(opening, close) <= max(opening, close) <= high


def labels_for(panel, spot_by_symbol):
    """Create open-to-open labels only when the full held path is observed."""
    labels, unavailable = {}, []
    for execution_ms, symbol in sorted(panel):
        spot = spot_by_symbol[symbol]
        end_ms = execution_ms + HORIZON_HOURS * HOUR_MS
        failure = None
        for timestamp in range(execution_ms, end_ms + HOUR_MS, HOUR_MS):
            bar = spot.get(timestamp)
            if not _valid_price_bar(bar, timestamp):
                failure = {"failure_hour_ms": timestamp, "reason": "missing_or_invalid_held_ohlc"}
                break
        entry, exit_bar = spot.get(execution_ms), spot.get(end_ms)
        if failure is None:
            for bar, timestamp in ((entry, execution_ms), (exit_bar, end_ms)):
                trades, volume = getattr(bar, "trades", None), getattr(bar, "volume", None)
                if (isinstance(trades, bool) or not isinstance(trades, int) or trades <= 0
                        or not _finite(volume) or volume <= 0):
                    failure = {"failure_hour_ms": timestamp, "reason": "unverified_entry_or_exit_liquidity"}
                    break
        if failure is not None:
            unavailable.append({"execution_ms": execution_ms, "symbol": symbol, **failure})
            continue
        actual = exit_bar.open / entry.open - 1
        if not _finite(actual):
            unavailable.append({"execution_ms": execution_ms, "symbol": symbol,
                                "failure_hour_ms": end_ms, "reason": "nonfinite_open_return"})
            continue
        available = end_ms + HOUR_MS
        labels[(execution_ms, symbol)] = {"execution_ms": execution_ms, "symbol": symbol,
            "label_start_ms": execution_ms, "label_end_ms": end_ms,
            "available_ms": available, "true_return": actual, "sample_weight": 1.0,
            "outcome_sha256": _hash({"entry_open": entry.open, "exit_open": exit_bar.open,
                                      "end_ms": end_ms, "available_ms": available})}
    return labels, unavailable


def _matrix(vectors, array, all_missing):
    return array([[0.0 if i in all_missing else math.nan if value is None else value
                   for i, value in enumerate(vector)] for vector in vectors])


def build_forecasts(panel, fields, spot_by_symbol, progress=None):
    """Fit matched own-only and leader models at causal monthly cutoffs."""
    fields = tuple(fields)
    if not fields or any(not isinstance(name, str) or not name for name in fields) or len(set(fields)) != len(fields):
        raise ValueError("feature fields must be unique names")
    if progress is not None and not callable(progress):
        raise ValueError("progress must be callable or None")
    forbidden = {"symbol", "asset", "date", "time", "timestamp", "target", "label", "true_return"}
    if any(name.lower().split(".")[-1] in forbidden or name.lower().endswith("_ms") for name in fields):
        raise ValueError("identity, time and label fields cannot be model inputs")
    for key, row in panel.items():
        if (not isinstance(key, tuple) or len(key) != 2 or key[1] not in SYMBOLS
                or row.get("execution_ms") != key[0] or row.get("symbol") != key[1]
                or row.get("latest_observed_close_ms") != key[0] - HOUR_MS
                or len(row.get("features", ())) != len(fields)
                or any(value is not None and not _finite(value) for value in row["features"])):
            raise ValueError("malformed event feature panel")
    events = sorted(panel)
    labels, unavailable_labels = labels_for(panel, spot_by_symbol)
    labelled = sorted(labels)
    event_times = [key[0] for key in labelled]
    factory, thread_limit, array, runtime = _runtime(None)
    own_indices = [i for i, name in enumerate(fields) if not name.startswith("leader.")]
    leader_indices = list(range(len(fields)))
    if not any(name.startswith("leader.") for name in fields):
        raise ValueError("leader treatment has no cross-asset fields")
    predictions = {model: {} for model in MODELS}
    errors, fits, unavailable = [], [], []
    fitted_month = None
    models, missing = {}, {}
    means_by_symbol = {}
    with thread_limit():
        for execution_ms, symbol in events:
            row = panel[(execution_ms, symbol)]
            cutoff = row["latest_observed_close_ms"]
            left = bisect_left(event_times, cutoff - TRAINING_WINDOW_MS)
            right = bisect_left(event_times, cutoff - (HORIZON_HOURS + 1) * HOUR_MS)
            train_keys = labelled[left:right]
            if len(train_keys) < MIN_TRAINING_ROWS:
                unavailable.append({"execution_ms": execution_ms, "symbol": symbol,
                    "decision_cutoff_ms": cutoff, "completed_training_rows": len(train_keys),
                    "reason": "insufficient_completed_training_rows"})
                continue
            month = datetime.fromtimestamp(cutoff / 1000, timezone.utc).strftime("%Y-%m")
            if fitted_month != month:
                known = [labels[key] for key in train_keys]
                vectors = [panel[key]["features"] for key in train_keys]
                targets = [labels[key]["true_return"] for key in train_keys]
                weights = [1.0] * len(train_keys)
                models, missing = {}, {}
                fit_models = {}
                for name, indices in (("own_hgb", own_indices), ("leader_hgb", leader_indices)):
                    raw = [[vector[i] for i in indices] for vector in vectors]
                    all_missing = frozenset(i for i in range(len(indices))
                        if all(vector[i] is None for vector in raw))
                    effective = _matrix(raw, array, all_missing)
                    model = factory(**ESTIMATOR_PARAMETERS)
                    model.fit(effective, array(targets), sample_weight=array(weights))
                    models[name], missing[name] = model, all_missing
                    effective_for_hash = [[None if not math.isfinite(float(value)) else float(value)
                                           for value in row] for row in effective.tolist()]
                    fit_models[name] = {"all_missing_indices": sorted(all_missing),
                        "feature_indices": indices, "effective_matrix_sha256": _hash(effective_for_hash),
                        "model_sha256": _hash({"name": name, "parameters": ESTIMATOR_PARAMETERS,
                                               "training_keys": train_keys, "targets": targets})}
                means_by_symbol = {}
                for asset in SYMBOLS:
                    values = [labels[key]["true_return"] for key in train_keys if key[1] == asset]
                    if not values:
                        raise ValueError("pooled fit lacks a symbol-specific rolling mean")
                    means_by_symbol[asset] = math.fsum(values) / len(values)
                fit_audit = {"fit_cutoff_ms": cutoff, "first_forecast_execution_ms": execution_ms,
                    "training_window_start_ms": cutoff - TRAINING_WINDOW_MS,
                    "training_samples": len(train_keys),
                    "training_counts_by_symbol": dict(Counter(key[1] for key in train_keys)),
                    "first_training_execution_ms": min(key[0] for key in train_keys),
                    "last_training_execution_ms": max(key[0] for key in train_keys),
                    "latest_label_end_ms": max(labels[key]["label_end_ms"] for key in train_keys),
                    "latest_label_available_ms": max(labels[key]["available_ms"] for key in train_keys),
                    "training_identity_sha256": _hash(known), "training_features_sha256": _hash(vectors),
                    "training_labels_sha256": _hash(targets), "sample_weight": "One per eligible asset event.",
                    "rolling_means_by_symbol": means_by_symbol, "models": fit_models,
                    "estimator_parameters": dict(ESTIMATOR_PARAMETERS), "native_thread_limit": 1,
                    **runtime}
                fit_audit["fit_sha256"] = _hash(fit_audit)
                fits.append(fit_audit)
                fitted_month = month
                if progress is not None:
                    progress({"cutoff_ms": cutoff, "training_samples": len(train_keys),
                              "fit_sha256": fit_audit["fit_sha256"]})
            vector = row["features"]
            for name, value in (("rolling_mean", means_by_symbol[symbol]),):
                predictions[name][(execution_ms, symbol)] = {"prediction": value,
                    "latest_observed_close_ms": cutoff, "context_sha256": row["context_sha256"]}
            for name, indices in (("own_hgb", own_indices), ("leader_hgb", leader_indices)):
                raw = [[vector[i] for i in indices]]
                effective = _matrix(raw, array, missing[name])
                predicted = float(models[name].predict(effective)[0])
                if not _finite(predicted):
                    raise ValueError("nonfinite model prediction")
                predictions[name][(execution_ms, symbol)] = {"prediction": predicted,
                    "latest_observed_close_ms": cutoff, "context_sha256": row["context_sha256"]}
            actual_label = labels.get((execution_ms, symbol))
            if actual_label is not None:
                errors.append({"execution_ms": execution_ms, "symbol": symbol,
                    "available_ms": actual_label["available_ms"], "actual_return": actual_label["true_return"],
                    **{name + "_prediction": predictions[name][(execution_ms, symbol)]["prediction"]
                       for name in MODELS}})
    audits = {name: {"count": len(rows),
        "sha256": _hash([[key[0], key[1], row] for key, row in sorted(rows.items())])}
        for name, rows in predictions.items()}
    return {"predictions": predictions, "prediction_errors": errors, "fits": fits,
        "unavailable_labels": unavailable_labels, "unavailable_predictions": unavailable,
        "label_outcomes": labels, "runtime": runtime, "prediction_audits": audits,
        "design": {"event_count": len(events), "label_count": len(labels),
                   "prediction_error_count": len(errors), "fit_count": len(fits),
                   "unavailable_label_count": len(unavailable_labels),
                   "unavailable_prediction_count": len(unavailable),
                   "historical_point_in_time_verified": False}}


def score_forecasts(errors, start_ms, end_ms):
    selected = [row for row in errors if start_ms <= row["execution_ms"] < end_ms
                and row["available_ms"] <= end_ms]
    if not selected:
        return {"count": 0, "models": {}}
    actual = [row["actual_return"] for row in selected]
    zero_sse = math.fsum(value * value for value in actual)
    results = {}
    for name in MODELS:
        residual = [row[name + "_prediction"] - row["actual_return"] for row in selected]
        sse = math.fsum(value * value for value in residual)
        results[name] = {"mse": sse / len(selected),
            "mae": math.fsum(abs(value) for value in residual) / len(selected),
            "skill_vs_zero": 1 - sse / zero_sse if zero_sse else None,
            "direction_accuracy": sum((row[name + "_prediction"] > 0) == (row["actual_return"] > 0)
                                       for row in selected) / len(selected)}
    return {"count": len(selected), "models": results,
            "leader_hgb_mse_minus_own_hgb_mse": results["leader_hgb"]["mse"] - results["own_hgb"]["mse"]}
