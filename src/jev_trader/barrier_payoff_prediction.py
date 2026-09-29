"""Causal forecasts of the gross payoff of a fixed stop/target/timeout policy.

Event labels can finish out of entry order. Availability is therefore processed
by completion time, while the rolling training window is indexed by entry time.
"""

from bisect import bisect_left, insort
from datetime import datetime, timezone
import math

from .barrier_payoff_execution import episode
from .hourly_forecast_prediction import (
    _validate, _effective, _matrix, ESTIMATOR_PARAMETERS, HOUR_MS,
    TRAINING_WINDOW_MS, MIN_TRAINING_ROWS,
)
from .tree_prediction import _finite, _hash, _runtime

ATR_FIELD = "spot.volatility.atr14_pct"
MAX_HOURS = 8


def _atr(row):
    value = row.get(ATR_FIELD)
    if value is None:
        return None
    if not _finite(value) or not 0 < value < 100:
        raise ValueError("ATR percent must be finite, positive and below 100")
    return value / 100


def labels_for(spot, states):
    labels, unavailable = {}, []
    for execution, state in sorted(states.items()):
        atr = _atr(state)
        if atr is None:
            unavailable.append({"execution_ms": execution, "reason": "missing_observed_atr"})
            continue
        outcome = episode(spot, execution, atr, max_hours=MAX_HOURS)
        if outcome["status"] == "unavailable":
            unavailable.append({"execution_ms": execution, **outcome})
            continue
        if outcome["status"] != "complete":
            raise ValueError("unknown barrier episode status")
        available = outcome["available_ms"]
        exit_bar = outcome["exit_bar_open_ms"]
        if (not isinstance(available, int) or isinstance(available, bool)
                or available <= execution or available > execution + (MAX_HOURS+1)*HOUR_MS
                or available % HOUR_MS or not isinstance(exit_bar, int) or isinstance(exit_bar, bool)
                or exit_bar < execution or available != exit_bar + HOUR_MS
                or outcome["exit_phase"] not in ("open", "intrabar")
                or not _finite(outcome["gross_return"])):
            raise ValueError("malformed barrier episode label")
        labels[execution] = {
            "execution_ms": execution, "label_start_ms": execution,
            "label_end_ms": available, "available_ms": available,
            "true_return": outcome["gross_return"], "sample_weight": 1.,
            "exit_bar_open_ms": outcome["exit_bar_open_ms"], "exit_phase": outcome["exit_phase"],
            "outcome_sha256": _hash(outcome), "outcome": outcome,
        }
    return labels, unavailable


def build_forecasts(spot, states, fields, progress=None):
    if progress is not None and not callable(progress):
        raise ValueError("progress must be callable or None")
    fields, current = _validate(states, fields)
    if ATR_FIELD not in fields:
        raise ValueError("observed ATR must be included in feature fields")
    atrs = {t: _atr(states[t]) for t in current}
    labels, unavailable_labels = labels_for(spot, states)
    # Sorting by entry is insufficient: a newer event can hit its stop first.
    queue = sorted(labels.values(), key=lambda r: (r["available_ms"], r["execution_ms"]))
    completed, cursor = [], 0
    factory, thread_limit, array, runtime = _runtime(None)
    models = {name: {"signals": {}, "prediction_audits": []} for name in ("rolling_mean", "hgb")}
    fits, unavailable_predictions = [], []
    model, fit, fit_month, mean = None, None, None, None
    missing_indices = frozenset()
    with thread_limit():
        for execution, state in sorted(current.items()):
            cutoff = state["latest_observed_close_ms"]
            lower = cutoff - TRAINING_WINDOW_MS
            while cursor < len(queue) and queue[cursor]["available_ms"] < cutoff:
                label = queue[cursor]
                if label["execution_ms"] >= lower:
                    insort(completed, label["execution_ms"])
                cursor += 1
            del completed[:bisect_left(completed, lower)]
            if atrs[execution] is None or len(completed) < MIN_TRAINING_ROWS:
                unavailable_predictions.append({"execution_ms": execution, "decision_cutoff_ms": cutoff,
                    "completed_training_rows": len(completed),
                    "reason": "missing_observed_atr" if atrs[execution] is None else "insufficient_completed_training_rows"})
                continue
            time = datetime.fromtimestamp(cutoff/1000, timezone.utc)
            month = (time.year, time.month)
            if model is None or month != fit_month:
                known = [labels[t] for t in completed]
                raw = [current[t]["features"] for t in completed]
                targets = [r["true_return"] for r in known]
                weights = [1.] * len(known)
                missing_indices = frozenset(i for i in range(len(fields)) if all(v[i] is None for v in raw))
                missing_fields = [f for i, f in enumerate(fields) if i in missing_indices]
                effective = [_effective(v, missing_indices) for v in raw]
                transform = {"all_missing_training_fields": missing_fields, "constant_value": 0.,
                             "scope": "Fixed from completed training rows until the next monthly fit."}
                identities = [{k: r[k] for k in ("execution_ms", "available_ms", "outcome_sha256",
                              "true_return", "sample_weight")} | {
                              "context_sha256": current[r["execution_ms"]]["context_sha256"]} for r in known]
                model = factory(**ESTIMATOR_PARAMETERS)
                model.fit(_matrix(effective, array), array(targets), sample_weight=array(weights))
                mean = math.fsum(targets)/len(targets)
                fit = {
                    "fit_cutoff_ms": cutoff, "first_forecast_execution_ms": execution,
                    "training_window_start_ms": lower, "training_samples": len(known),
                    "training_execution_dates_ms": list(completed),
                    "first_training_execution_ms": completed[0], "last_training_execution_ms": completed[-1],
                    "latest_label_available_ms": max(r["available_ms"] for r in known),
                    "training_identity_label_weight_sha256": _hash(identities),
                    "raw_training_matrix_sha256": _hash({"fields": fields, "vectors": raw}),
                    "effective_training_matrix_sha256": _hash({"fields": fields, "vectors": effective}),
                    "training_labels_sha256": _hash(targets), "training_weights_sha256": _hash(weights),
                    "fields": list(fields), "all_missing_training_fields": missing_fields,
                    "training_missing_counts": {f: sum(v[i] is None for v in raw) for i, f in enumerate(fields)},
                    "feature_transform": transform, "feature_transform_sha256": _hash(transform),
                    "rolling_mean": mean, "estimator_parameters": dict(ESTIMATOR_PARAMETERS),
                    "native_thread_limit": 1, "sample_weight": "One per completed potential entry event.", **runtime,
                }
                fit["fit_sha256"] = _hash(fit)
                fits.append(fit)
                fit_month = month
                if progress:
                    progress({"fit_cutoff_ms": cutoff, "training_samples": len(known), "fit_sha256": fit["fit_sha256"]})
            effective = _effective(state["features"], missing_indices)
            predicted = [float(v) for v in model.predict(_matrix([effective], array))]
            if len(predicted) != 1 or not math.isfinite(predicted[0]):
                raise ValueError("estimator returned malformed or nonfinite prediction")
            identity = {"execution_ms": execution, "decision_cutoff_ms": cutoff,
                        "context_sha256": state["context_sha256"], "fields": fields}
            common = {"execution_ms": execution, "decision_cutoff_ms": cutoff,
                "fit_cutoff_ms": fit["fit_cutoff_ms"], "fit_sha256": fit["fit_sha256"],
                "context_sha256": state["context_sha256"],
                "prediction_input_sha256": _hash({**identity, "vector": state["features"]}),
                "effective_prediction_input_sha256": _hash({**identity, "vector": effective}),
                "feature_transform_sha256": fit["feature_transform_sha256"]}
            for name, value in (("rolling_mean", mean), ("hgb", predicted[0])):
                signal = {"prediction": value, "latest_observed_close_ms": cutoff,
                          "context_sha256": state["context_sha256"]}
                models[name]["signals"][execution] = signal
                models[name]["prediction_audits"].append({**common,
                    "prediction_sha256": _hash({"model": name, "execution_ms": execution,
                                                "fit_sha256": fit["fit_sha256"], **signal})})
    errors = [{"execution_ms": t, "label_start_ms": t, "label_end_ms": r["available_ms"],
               "available_ms": r["available_ms"], "actual_return": r["true_return"],
               "rolling_mean_prediction": models["rolling_mean"]["signals"][t]["prediction"],
               "hgb_prediction": models["hgb"]["signals"][t]["prediction"]}
              for t, r in sorted(labels.items()) if t in models["rolling_mean"]["signals"]]
    return {"models": models, "fit_audits": fits, "prediction_errors": errors,
        "label_outcomes": labels, "unavailable_labels": unavailable_labels,
        "unavailable_predictions": unavailable_predictions,
        "shared_label_identity_sha256": _hash(labels), "paired_evaluation_sha256": _hash(errors),
        "fit_audits_sha256": _hash(fits),
        "design": {"models": ["rolling_mean", "hgb"], "fields": list(fields),
            "label": "Gross entry-to-exit return under the same fixed barriers used by the executor.",
            "atr": "Known ATR14_pct / 100, applied to execution open; stop1ATR target2ATR.",
            "max_hours": MAX_HOURS, "label_availability": "Exit candle close, including open exits.",
            "label_end_ms_meaning": "Observation availability, not a claimed exact intrabar fill time.",
            "decision_cutoff": "execution - 1h", "training_availability_comparison": "strictly less than cutoff",
            "training_window_ms": TRAINING_WINDOW_MS, "minimum_completed_training_rows": MIN_TRAINING_ROWS,
            "training_window_lower_boundary": "Label entry >= cutoff - training_window_ms",
            "availability_order": "Completion-time queue; training identity sorted by entry.",
            "refit": "First eligible cutoff of each UTC month; hold estimator between fits.",
            "sample_weight": "Equal events; overlapping potential trades are not independent observations.",
            "label_costs_included": False, "prediction_centering": False,
            "raw_prediction_clipped": False, "policy_upper_cap": "min(raw_prediction, 2*known_atr_fraction)",
            "current_forecast_requires_future_label": False,
            "estimator_parameters": dict(ESTIMATOR_PARAMETERS), "native_thread_limit": 1,
            "hyperparameter_search": False, "historical_point_in_time_verified": False, **runtime}}
