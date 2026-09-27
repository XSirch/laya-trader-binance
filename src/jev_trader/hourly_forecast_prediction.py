"""Paired causal forecasts of the absolute next-hour BTC spot price return.

The information cutoff precedes execution by one full hour. A label is usable
only after both execution candles have closed, strictly before that cutoff.
Future candle quality affects labels, never current forecast eligibility.
"""

from bisect import bisect_left
from collections.abc import Mapping
from datetime import datetime, timezone
import math

from .tree_prediction import _finite, _hash, _runtime


HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS
TRAINING_WINDOW_MS = 365 * DAY_MS
MIN_TRAINING_ROWS = 4_320
ESTIMATOR_PARAMETERS = {
    "loss": "squared_error", "learning_rate": .05, "max_iter": 100,
    "max_leaf_nodes": 7, "max_depth": 3, "min_samples_leaf": 40,
    "l2_regularization": 10, "max_bins": 64, "early_stopping": False,
    "categorical_features": None, "random_state": 548,
}


def _validate(states, fields):
    fields = tuple(fields)
    forbidden = {"symbol", "asset", "asset_id", "date", "time", "timestamp",
                 "prediction", "raw_prediction", "target", "context_sha256",
                 "true_return", "actual_return", "label", "actual",
                 "historical_point_in_time_verified"}
    if (not fields or any(not isinstance(field, str) or not field for field in fields)
            or len(set(fields)) != len(fields)):
        raise ValueError("fields must contain unique nonempty names")
    if any(field.lower().split(".")[-1] in forbidden
           or field.lower().endswith("_ms") for field in fields):
        raise ValueError("identity, time, label and prediction fields cannot be model inputs")
    if not isinstance(states, Mapping):
        raise ValueError("states must map execution timestamps to feature rows")
    validated = {}
    for execution, row in states.items():
        if (isinstance(execution, bool) or not isinstance(execution, int)
                or execution < HOUR_MS or execution % HOUR_MS):
            raise ValueError("execution timestamps must be integer UTC hours with nonnegative cutoffs")
        if not isinstance(row, Mapping):
            raise ValueError("each state must be a feature mapping")
        if "execution_ms" in row and (isinstance(row["execution_ms"], bool)
                or not isinstance(row["execution_ms"], int) or row["execution_ms"] != execution):
            raise ValueError("state execution_ms must match its timestamp key")
        observed = row.get("latest_observed_close_ms")
        if (isinstance(observed, bool) or not isinstance(observed, int)
                or observed != execution - HOUR_MS):
            raise ValueError("latest observed close must equal execution minus one hour")
        context = row.get("context_sha256")
        if (not isinstance(context, str) or len(context) != 64
                or any(character not in "0123456789abcdef" for character in context)):
            raise ValueError("context_sha256 must be a lowercase SHA256 digest")
        vector = []
        for field in fields:
            if field not in row or not (row[field] is None or _finite(row[field])):
                raise ValueError(f"model field must be finite or None: {field}")
            vector.append(None if row[field] is None else float(row[field]))
        validated[execution] = {
            "execution_ms": execution, "latest_observed_close_ms": observed,
            "context_sha256": context, "features": vector,
        }
    return fields, validated


def _bar_failure(bar, timestamp):
    if bar is None:
        return "missing_candle"
    if getattr(bar, "open_ms", None) != timestamp:
        return "misaligned_candle"
    values = [getattr(bar, name, None) for name in ("open", "high", "low", "close")]
    if any(not _finite(value) or value <= 0 for value in values):
        return "incomplete_or_invalid_ohlc"
    opened, high, low, closed = values
    if low > min(opened, closed) or high < max(opened, closed) or low > high:
        return "inconsistent_ohlc"
    trades = getattr(bar, "trades", None)
    if (isinstance(trades, bool) or not isinstance(trades, int) or trades <= 0
            or not _finite(getattr(bar, "volume", None)) or bar.volume <= 0):
        return "unverified_execution_liquidity"
    quote_volume = getattr(bar, "quote_volume", None)
    if quote_volume is not None and (not _finite(quote_volume) or quote_volume <= 0):
        return "unverified_execution_liquidity"
    return None


def _label(spot_bars, execution):
    end = execution + HOUR_MS
    identity = {"execution_ms": execution, "label_start_ms": execution,
                "label_end_ms": end, "available_ms": end + HOUR_MS}
    for timestamp in (execution, end):
        failure = _bar_failure(spot_bars.get(timestamp), timestamp)
        if failure is not None:
            return None, {**identity, "failure_hour_ms": timestamp, "reason": failure}
    value = float(spot_bars[end].open / spot_bars[execution].open - 1)
    if not math.isfinite(value):
        return None, {**identity, "failure_hour_ms": end, "reason": "nonfinite_return"}
    return {**identity, "true_return": value, "sample_weight": 1.0}, None


def _effective(vector, missing_indices):
    return [0.0 if index in missing_indices else value for index, value in enumerate(vector)]


def _matrix(vectors, array):
    return array([[math.nan if value is None else value for value in row] for row in vectors])


def build_forecasts(spot_bars, states, fields, progress=None):
    """Return monthly rolling fits, matched forecasts and retrospective errors.

    A fit uses equal-weight completed labels whose execution timestamps lie in
    [cutoff - 365 days, cutoff), with availability strictly before the cutoff.
    Each eligible UTC month is fitted once, at its first eligible state cutoff.
    Missing training columns become zero until the next refit; other missing
    values remain null in audit inputs and become NaN only inside sklearn.
    """
    if not isinstance(spot_bars, Mapping):
        raise ValueError("spot_bars must map hour timestamps to complete bars")
    if progress is not None and not callable(progress):
        raise ValueError("progress must be callable or None")
    fields, current = _validate(states, fields)
    dates = sorted(current)
    labels, unavailable_labels = [], []
    for execution in dates:
        label, failure = _label(spot_bars, execution)
        if failure is not None:
            unavailable_labels.append(failure)
        else:
            labels.append(label)
    label_dates = [label["execution_ms"] for label in labels]
    factory, thread_limit, array, runtime = _runtime(None)
    models = {name: {"signals": {}, "prediction_audits": []} for name in ("rolling_mean", "hgb")}
    fits, unavailable_predictions = [], []
    model, fit_month, fit = None, None, None
    missing_indices = frozenset()
    mean = None
    with thread_limit():
        for execution in dates:
            state = current[execution]
            cutoff = state["latest_observed_close_ms"]
            left = bisect_left(label_dates, cutoff - TRAINING_WINDOW_MS)
            # label.available_ms = label.execution_ms + two complete hours.
            right = bisect_left(label_dates, cutoff - 2 * HOUR_MS)
            count = right - left
            if count < MIN_TRAINING_ROWS:
                unavailable_predictions.append({"execution_ms": execution, "decision_cutoff_ms": cutoff,
                    "completed_training_rows": count, "reason": "insufficient_completed_training_rows"})
                continue
            calendar = datetime.fromtimestamp(cutoff / 1000, timezone.utc)
            month = (calendar.year, calendar.month)
            if model is None or month != fit_month:
                known = labels[left:right]
                raw_vectors = [current[row["execution_ms"]]["features"] for row in known]
                targets = [row["true_return"] for row in known]
                weights = [row["sample_weight"] for row in known]
                missing_indices = frozenset(index for index in range(len(fields))
                    if all(vector[index] is None for vector in raw_vectors))
                missing_fields = [field for index, field in enumerate(fields) if index in missing_indices]
                effective_vectors = [_effective(vector, missing_indices) for vector in raw_vectors]
                training_rows = [{**label, "latest_observed_close_ms": current[label["execution_ms"]]["latest_observed_close_ms"],
                                  "context_sha256": current[label["execution_ms"]]["context_sha256"]}
                                 for label in known]
                transform = {"all_missing_training_fields": missing_fields, "constant_value": 0.0,
                             "scope": "Fixed from completed training rows until the next monthly fit."}
                model = factory(**ESTIMATOR_PARAMETERS)
                model.fit(_matrix(effective_vectors, array), array(targets), sample_weight=array(weights))
                mean = math.fsum(targets) / len(targets)
                fit = {
                    "fit_cutoff_ms": cutoff, "first_forecast_execution_ms": execution,
                    "training_window_start_ms": cutoff - TRAINING_WINDOW_MS,
                    "training_samples": count, "training_execution_dates_ms": label_dates[left:right],
                    "first_training_execution_ms": known[0]["execution_ms"],
                    "last_training_execution_ms": known[-1]["execution_ms"],
                    "latest_label_end_ms": known[-1]["label_end_ms"],
                    "latest_label_available_ms": known[-1]["available_ms"],
                    "training_identity_label_weight_sha256": _hash(training_rows),
                    "raw_training_matrix_sha256": _hash({"fields": fields, "vectors": raw_vectors}),
                    "effective_training_matrix_sha256": _hash({"fields": fields, "vectors": effective_vectors}),
                    "training_labels_sha256": _hash(targets), "training_weights_sha256": _hash(weights),
                    "fields": list(fields), "all_missing_training_fields": missing_fields,
                    "training_missing_counts": {field: sum(vector[index] is None for vector in raw_vectors)
                                                for index, field in enumerate(fields)},
                    "feature_transform": transform, "feature_transform_sha256": _hash(transform),
                    "rolling_mean": mean, "sample_weight": "One per completed hourly label.",
                    "estimator_parameters": dict(ESTIMATOR_PARAMETERS), "native_thread_limit": 1,
                    **runtime,
                }
                fit["fit_sha256"] = _hash(fit)
                fits.append(fit)
                fit_month = month
                if progress is not None:
                    progress({"fit_cutoff_ms": cutoff, "training_samples": count, "fit_sha256": fit["fit_sha256"]})
            effective = _effective(state["features"], missing_indices)
            predicted = [float(value) for value in model.predict(_matrix([effective], array))]
            if len(predicted) != 1 or not math.isfinite(predicted[0]):
                raise ValueError("estimator returned malformed or nonfinite prediction")
            identity = {"execution_ms": execution, "decision_cutoff_ms": cutoff,
                        "context_sha256": state["context_sha256"], "fields": fields}
            common = {
                "execution_ms": execution, "decision_cutoff_ms": cutoff,
                "fit_cutoff_ms": fit["fit_cutoff_ms"], "fit_sha256": fit["fit_sha256"],
                "context_sha256": state["context_sha256"],
                "prediction_input_sha256": _hash({**identity, "vector": state["features"]}),
                "effective_prediction_input_sha256": _hash({**identity, "vector": effective}),
                "feature_transform_sha256": fit["feature_transform_sha256"],
            }
            for name, value in (("rolling_mean", mean), ("hgb", predicted[0])):
                signal = {"prediction": value, "latest_observed_close_ms": cutoff,
                          "context_sha256": state["context_sha256"]}
                models[name]["signals"][execution] = signal
                models[name]["prediction_audits"].append({**common,
                    "prediction_sha256": _hash({"model": name, "execution_ms": execution,
                                                "fit_sha256": fit["fit_sha256"], **signal})})
    # Evaluation is deliberately constructed only after both signal maps exist.
    errors = [{"execution_ms": label["execution_ms"], "label_start_ms": label["label_start_ms"],
               "label_end_ms": label["label_end_ms"], "available_ms": label["available_ms"],
               "actual_return": label["true_return"],
               "rolling_mean_prediction": models["rolling_mean"]["signals"][label["execution_ms"]]["prediction"],
               "hgb_prediction": models["hgb"]["signals"][label["execution_ms"]]["prediction"]}
              for label in labels if label["execution_ms"] in models["rolling_mean"]["signals"]]
    design = {
        "models": ["rolling_mean", "hgb"], "fields": list(fields),
        "label": "spot_open[execution + 1h] / spot_open[execution] - 1",
        "label_availability": "execution + 2h, after the exit candle completes",
        "decision_cutoff": "execution - 1h", "training_availability_comparison": "strictly less than cutoff",
        "training_window_ms": TRAINING_WINDOW_MS, "minimum_completed_training_rows": MIN_TRAINING_ROWS,
        "training_window_lower_boundary": "Label execution >= cutoff - training_window_ms",
        "refit": "First eligible cutoff in each UTC calendar month; no intra-month refit.",
        "prediction_eligibility": "Current feature row and enough past completed labels; no future candle check.",
        "insufficient_training_rows": "No forecast; an existing model is not used until eligibility returns.",
        "null_encoding": "Raw null retained in audits; training-all-null columns zero until refit; other nulls become NaN.",
        "label_costs_included": False, "label_funding_included": False,
        "prediction_centering": False, "sample_weight": "Equal hourly rows, weight 1.0.",
        "estimator_parameters": dict(ESTIMATOR_PARAMETERS), "native_thread_limit": 1,
        "hyperparameter_search": False, "historical_point_in_time_verified": False, **runtime,
    }
    return {
        "models": models, "fit_audits": fits, "prediction_errors": errors,
        "unavailable_labels": unavailable_labels, "unavailable_predictions": unavailable_predictions,
        "shared_label_identity_sha256": _hash(labels), "paired_evaluation_sha256": _hash(errors),
        "fit_audits_sha256": _hash(fits), "design": design,
    }
