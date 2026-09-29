"""Walk-forward HGB ablations for short own and leader return/flow lags."""

from bisect import bisect_left
from collections import Counter
from datetime import datetime, timezone
import math

from .binance_data import HOUR_MS
from .hourly_forecast_prediction import ESTIMATOR_PARAMETERS
from .lagged_flow_prediction import (HORIZON_HOURS, INTERVAL_HOURS, MIN_TRAINING_ROWS,
    SYMBOLS, TRAINING_WINDOW_MS, _finite, _hash, _matrix, build_panel, labels_for)
from .tree_prediction import _runtime

ASSET_FIELDS = tuple(f"asset.is_{symbol}" for symbol in SYMBOLS)
MODELS = ("own_lag_hgb", "leader_lag_hgb", "combined_lag_hgb")


def feature_groups(fields):
    fields = tuple(fields)
    own = [i for i, name in enumerate(fields)
           if name.startswith("own.return_") or name.startswith("own.flow_imbalance_")]
    leader = [i for i, name in enumerate(fields)
              if name.startswith("leader.") and
              (".return_" in name or ".flow_imbalance_" in name)]
    asset = [fields.index(name) for name in ASSET_FIELDS if name in fields]
    if len(own) != 8 or len(leader) != 16 or len(asset) != len(SYMBOLS):
        raise ValueError("short-lag feature schema differs from frozen protocol")
    return {"own_lag_hgb": own + asset,
            "leader_lag_hgb": leader + asset,
            "combined_lag_hgb": own + leader + asset}


def build_ablation_forecasts(panel, fields, spot_by_symbol, progress=None):
    """Fit the three fixed feature groups at identical causal cutoffs."""
    fields = tuple(fields)
    groups = feature_groups(fields)
    events = sorted(panel)
    labels, unavailable_labels = labels_for(panel, spot_by_symbol)
    labelled = sorted(labels)
    event_times = [key[0] for key in labelled]
    factory, thread_limit, array, runtime = _runtime(None)
    predictions = {name: {} for name in MODELS}
    errors, fits, unavailable = [], [], []
    fitted_month = None
    models, missing = {}, {}

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
                targets = [labels[key]["true_return"] for key in train_keys]
                vectors = [panel[key]["features"] for key in train_keys]
                models, missing, model_audits = {}, {}, {}
                for name, indices in groups.items():
                    raw = [[vector[i] for i in indices] for vector in vectors]
                    all_missing = frozenset(index for index in range(len(indices))
                        if all(vector[index] is None for vector in raw))
                    effective = _matrix(raw, array, all_missing)
                    model = factory(**ESTIMATOR_PARAMETERS)
                    model.fit(effective, array(targets), sample_weight=array([1.0] * len(targets)))
                    models[name], missing[name] = model, all_missing
                    effective_for_hash = [[None if not math.isfinite(float(value)) else float(value)
                                           for value in vector] for vector in effective.tolist()]
                    model_audits[name] = {"feature_indices": indices,
                        "all_missing_indices": sorted(all_missing),
                        "effective_matrix_sha256": _hash(effective_for_hash),
                        "model_sha256": _hash({"name": name,
                            "parameters": ESTIMATOR_PARAMETERS, "training_keys": train_keys,
                            "targets": targets})}
                fit_audit = {"fit_cutoff_ms": cutoff,
                    "first_forecast_execution_ms": execution_ms,
                    "training_window_start_ms": cutoff - TRAINING_WINDOW_MS,
                    "training_samples": len(train_keys),
                    "training_counts_by_symbol": dict(Counter(key[1] for key in train_keys)),
                    "first_training_execution_ms": min(key[0] for key in train_keys),
                    "last_training_execution_ms": max(key[0] for key in train_keys),
                    "latest_label_end_ms": max(labels[key]["label_end_ms"] for key in train_keys),
                    "latest_label_available_ms": max(labels[key]["available_ms"] for key in train_keys),
                    "training_identity_sha256": _hash([labels[key] for key in train_keys]),
                    "training_features_sha256": _hash(vectors),
                    "training_labels_sha256": _hash(targets),
                    "sample_weight": "One per eligible asset event.",
                    "feature_indices": groups, "models": model_audits,
                    "estimator_parameters": dict(ESTIMATOR_PARAMETERS),
                    "native_thread_limit": 1, **runtime}
                fit_audit["fit_sha256"] = _hash(fit_audit)
                fits.append(fit_audit)
                fitted_month = month
                if progress is not None:
                    progress({"cutoff_ms": cutoff, "training_samples": len(train_keys),
                              "fit_sha256": fit_audit["fit_sha256"]})

            vector = row["features"]
            prediction_row = {}
            for name, indices in groups.items():
                raw = [[vector[i] for i in indices]]
                effective = _matrix(raw, array, missing[name])
                value = float(models[name].predict(effective)[0])
                if not _finite(value):
                    raise ValueError("nonfinite lag-ablation prediction")
                prediction_row[name] = {"prediction": value,
                    "latest_observed_close_ms": cutoff,
                    "context_sha256": row["context_sha256"]}
                predictions[name][(execution_ms, symbol)] = prediction_row[name]

            label = labels.get((execution_ms, symbol))
            if label is not None:
                errors.append({"execution_ms": execution_ms, "symbol": symbol,
                    "available_ms": label["available_ms"], "actual_return": label["true_return"],
                    **{name + "_prediction": prediction_row[name]["prediction"]
                       for name in MODELS}})

    audits = {name: {"count": len(rows),
        "sha256": _hash([[key[0], key[1], value] for key, value in sorted(rows.items())])}
        for name, rows in predictions.items()}
    return {"predictions": predictions, "prediction_errors": errors,
        "fits": fits, "unavailable_labels": unavailable_labels,
        "unavailable_predictions": unavailable, "label_outcomes": labels,
        "runtime": runtime, "prediction_audits": audits,
        "design": {"event_count": len(events), "label_count": len(labels),
            "prediction_error_count": len(errors), "fit_count": len(fits),
            "unavailable_label_count": len(unavailable_labels),
            "unavailable_prediction_count": len(unavailable),
            "historical_point_in_time_verified": False}}
