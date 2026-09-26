"""Matched daily trees forecasting 24-hour BTC-hedged pair price returns.

Only already completed daily groups enter training. Future missing prices can
exclude a training group, but never the current causal prediction universe.
"""

from collections.abc import Mapping
from datetime import datetime, timezone
import math

from .funding_event_policy import DAY_MS, HOUR_MS, eligible_states
from .positioning_features import FEATURES as POSITIONING_FIELDS
from .tree_policy import _events
from .tree_prediction import ESTIMATOR_PARAMETERS, _finite, _hash, _runtime


MIN_TRAINING_DAYS = 365


def _fields(control_fields, event_fields):
    control, event = tuple(control_fields), tuple(event_fields)
    combined = control + event
    if (len(control) != 75 or len(event) != 5 or len(set(combined)) != 80
            or any(not isinstance(field, str) or not field for field in combined)):
        raise ValueError("exactly 75 control fields and five additional event fields required")
    forbidden = {"symbol", "asset", "asset_id", "date", "time", "timestamp", "prediction", "raw_prediction", "target"}
    if any(field.lower().split(".")[-1] in forbidden or field.lower().endswith("_ms") for field in combined):
        raise ValueError("identity, time, target and prediction fields cannot be model inputs")
    if not set(POSITIONING_FIELDS).issubset(control):
        raise ValueError("control fields must retain all eight positioning features")
    return control, combined


def _validate_states(states, fields):
    if not isinstance(states, dict) or any(not isinstance(symbol, str) for symbol in states):
        raise ValueError("states must map named symbols to timestamped event rows")
    dates = set()
    for symbol, rows in states.items():
        if not isinstance(rows, Mapping):
            raise ValueError("each symbol must map days to event rows")
        for day, row in rows.items():
            if isinstance(day, bool) or not isinstance(day, int) or day % DAY_MS:
                raise ValueError("state keys must be integer UTC midnight timestamps")
            if not isinstance(row, Mapping) or row.get("latest_observed_close_ms") != day + HOUR_MS:
                raise ValueError("state decision must equal its day plus one hour")
            for field in fields:
                if field not in row or not (_finite(row[field]) or row[field] is None and field in POSITIONING_FIELDS):
                    raise ValueError(f"invalid event model input: {symbol}.{field}")
            dates.add(day)
    return sorted(dates)


def _daily_label(prices, current, day, fields):
    decision, start, end = day + HOUR_MS, day + 2 * HOUR_MS, day + 26 * HOUR_MS
    failures, returns = [], {}
    for symbol in sorted(current):
        lookup = prices.get(symbol, {})
        failure = None
        for timestamp in range(start, end + HOUR_MS, HOUR_MS):
            bar = lookup.get(timestamp)
            if bar is None:
                failure = {"symbol": symbol, "hour_ms": timestamp, "reason": "missing_hour"}
            elif (getattr(bar, "open_ms", None) != timestamp
                  or not _finite(getattr(bar, "open", None)) or bar.open <= 0):
                failure = {"symbol": symbol, "hour_ms": timestamp, "reason": "invalid_hour_price"}
            elif timestamp in (start, end) and (not _finite(getattr(bar, "trades", None)) or bar.trades <= 0):
                failure = {"symbol": symbol, "hour_ms": timestamp, "reason": "untradable_endpoint"}
            if failure:
                failures.append(failure)
                break
        if failure is None:
            value = lookup[end].open / lookup[start].open - 1
            if not math.isfinite(value):
                failures.append({"symbol": symbol, "hour_ms": end, "reason": "nonfinite_return"})
            else:
                returns[symbol] = value
    identity = {"day_ms": day, "signal_ms": decision, "label_start_ms": start, "label_end_ms": end}
    if failures:
        return None, {**identity, "eligible_symbols": sorted(current), "failures": failures,
                      "reason": "Incomplete eligible cross-section; entire day excluded."}
    targets, betas = {}, {}
    for symbol in sorted(current):
        if symbol == "BTCUSDT":
            continue
        beta = current[symbol]["beta60"] / current["BTCUSDT"]["beta60"]
        denominator = 1 + abs(beta)
        target = returns[symbol] / denominator - (beta / denominator) * returns["BTCUSDT"]
        if not math.isfinite(target):
            return None, {**identity, "eligible_symbols": sorted(current),
                          "failures": [{"symbol": symbol, "hour_ms": end, "reason": "nonfinite_pair_return"}],
                          "reason": "Incomplete eligible cross-section; entire day excluded."}
        targets[symbol], betas[symbol] = target, beta
    return {**identity, "eligible_symbols": sorted(current), "targets": targets, "betas": betas,
            "vectors": {symbol: [None if current[symbol][field] is None else float(current[symbol][field])
                                  for field in fields] for symbol in targets}}, None


def _model_matrix(rows, array):
    return array([[math.nan if value is None else value for value in row] for row in rows])


def _constant_missing_vectors(vectors, indices):
    """Apply only the mask learned from this model's completed training sample."""
    return [[0.0 if index in indices else value for index, value in enumerate(row)] for row in vectors]


def build_forecasts(hourly, states, control_fields, event_fields, lifecycle_events, estimator_factory=None, *, progress=None):
    """Return matched 75/80-field forecasts and common identity/label audits."""
    control, augmented = _fields(control_fields, event_fields)
    if progress is not None and not callable(progress):
        raise ValueError("progress must be callable or None")
    dates = _validate_states(states, augmented)
    events = _events(lifecycle_events)
    prices = hourly.get("klines") if isinstance(hourly, Mapping) else None
    if not isinstance(prices, Mapping):
        raise ValueError("hourly klines mapping required")
    current_by_date, eligibility_audits, groups, unavailable = {}, [], [], []
    for day in dates:
        current, audit = eligible_states({s: rows[day] for s, rows in states.items() if day in rows}, events)
        current_by_date[day] = current
        eligibility_audits.append({"day_ms": day, **audit})
        if not current:
            unavailable.append({"day_ms": day, "signal_ms": day + HOUR_MS,
                                "label_start_ms": day + 2 * HOUR_MS, "label_end_ms": day + 26 * HOUR_MS,
                                "eligible_symbols": audit["eligible_symbols"], "reason": audit["reason"]})
            continue
        label, failure = _daily_label(prices, current, day, augmented)
        if failure:
            unavailable.append(failure)
        else:
            groups.append(label)
    factory, thread_limit, array, runtime = _runtime(estimator_factory)
    fields_by_model = {"control75": control, "augmented80": augmented}
    output = {name: {"signals": {symbol: {} for symbol in sorted(states)}, "fit_audits": [],
                     "prediction_audits": [], "prediction_errors": []} for name in fields_by_model}
    models, transforms, fit_month, fit_cutoff = {}, {}, None, None
    matched_fits, matched_predictions = [], []
    for day in dates:
        decision = day + HOUR_MS
        current = current_by_date[day]
        known = [group for group in groups if group["label_end_ms"] < decision]
        if not current or len(known) < MIN_TRAINING_DAYS:
            continue
        calendar = datetime.fromtimestamp(decision / 1000, timezone.utc)
        month = (calendar.year, calendar.month)
        if not models or month != fit_month:
            count = sum(len(group["targets"]) for group in known)
            training = []
            for group in known:
                weight = count / (len(known) * len(group["targets"]))
                for symbol in sorted(group["targets"]):
                    training.append({"day_ms": group["day_ms"], "signal_ms": group["signal_ms"],
                                     "label_end_ms": group["label_end_ms"], "symbol": symbol,
                                     "features": group["vectors"][symbol], "target": group["targets"][symbol],
                                     "sample_weight": weight})
            common = [{key: value for key, value in row.items() if key != "features"} for row in training]
            shared = {"fit_cutoff_ms": decision, "training_days": len(known), "training_samples": count,
                      "training_signal_dates_ms": [group["signal_ms"] for group in known],
                      "latest_label_end_ms": known[-1]["label_end_ms"],
                      "training_identity_label_weight_sha256": _hash(common)}
            matched_fits.append(shared)
            for name, fields in fields_by_model.items():
                rows = [{**row, "features": row["features"][:len(fields)]} for row in training]
                raw_vectors = [row["features"] for row in rows]
                missing_indices = frozenset(index for index in range(len(fields))
                                            if all(row[index] is None for row in raw_vectors))
                missing_fields = [field for index, field in enumerate(fields) if index in missing_indices]
                transform = {"fields": list(fields), "all_missing_training_fields": missing_fields,
                             "constant_value": 0.0,
                             "other_missing_values": "Preserve null in audits; encode NaN only in model matrices.",
                             "scope": "Training-only mask; retained unchanged until next monthly fit."}
                effective_vectors = _constant_missing_vectors(raw_vectors, missing_indices)
                effective_rows = [{**row, "features": vector} for row, vector in zip(rows, effective_vectors)]
                model = factory(**ESTIMATOR_PARAMETERS)
                with thread_limit():
                    model.fit(_model_matrix(effective_vectors, array),
                              array([row["target"] for row in rows]),
                              sample_weight=array([row["sample_weight"] for row in rows]))
                models[name] = model
                transforms[name] = {"indices": missing_indices, "audit": transform, "sha256": _hash(transform)}
                output[name]["fit_audits"].append({**shared, "first_training_signal_ms": known[0]["signal_ms"],
                    "last_training_signal_ms": known[-1]["signal_ms"], "fields": list(fields),
                    "training_input_sha256": _hash(rows), "transformed_training_input_sha256": _hash(effective_rows),
                    "all_missing_training_fields": missing_fields, "feature_transform": transform,
                    "feature_transform_sha256": transforms[name]["sha256"],
                    "estimator_parameters": dict(ESTIMATOR_PARAMETERS)})
            fit_month, fit_cutoff = month, decision
            if progress is not None:
                progress({"fit_cutoff_ms": decision, "training_days": len(known), "training_samples": count})
        symbols = sorted(symbol for symbol in current if symbol != "BTCUSDT")
        common_prediction = {"day_ms": day, "signal_ms": decision, "fit_cutoff_ms": fit_cutoff,
                             "eligible_symbols": sorted(current), "predicted_symbols": symbols,
                             "prediction_identity_sha256": _hash({"signal_ms": decision, "symbols": symbols})}
        matched_predictions.append(common_prediction)
        for name, fields in fields_by_model.items():
            vectors = [[None if current[symbol][field] is None else float(current[symbol][field])
                        for field in fields] for symbol in symbols]
            transform = transforms[name]
            effective_vectors = _constant_missing_vectors(vectors, transform["indices"])
            with thread_limit():
                raw = [float(value) for value in models[name].predict(_model_matrix(effective_vectors, array))]
            if len(raw) != len(symbols) or any(not math.isfinite(value) for value in raw):
                raise ValueError("estimator returned malformed or nonfinite predictions")
            prediction_rows = []
            for symbol, value in zip(symbols, raw):
                output[name]["signals"][symbol][day] = {**current[symbol], "prediction": value, "raw_prediction": value}
                prediction_rows.append({"symbol": symbol, "prediction": value})
            output[name]["signals"]["BTCUSDT"][day] = {**current["BTCUSDT"], "prediction": 0.0, "raw_prediction": 0.0}
            output[name]["prediction_audits"].append({
                **common_prediction, "prediction_assets": len(symbols),
                "prediction_input_sha256": _hash({"fields": fields, "symbols": symbols, "vectors": vectors}),
                "transformed_prediction_input_sha256": _hash({"fields": fields, "symbols": symbols,
                                                               "vectors": effective_vectors}),
                "all_missing_training_fields": transform["audit"]["all_missing_training_fields"],
                "feature_transform_sha256": transform["sha256"],
                "predictions_sha256": _hash(prediction_rows)})
    evaluation = []
    for group in groups:
        day = group["day_ms"]
        for symbol, actual in sorted(group["targets"].items()):
            if day in output["control75"]["signals"][symbol]:
                common = {"day_ms": day, "signal_ms": group["signal_ms"],
                          "label_end_ms": group["label_end_ms"], "symbol": symbol, "actual": actual}
                evaluation.append(common)
                for name in fields_by_model:
                    output[name]["prediction_errors"].append({**common,
                        "prediction": output[name]["signals"][symbol][day]["prediction"]})
    for name, fields in fields_by_model.items():
        output[name]["unavailable_label_days"] = unavailable
        output[name]["design"] = {
            "model": "HistGradientBoostingRegressor", "parameters": dict(ESTIMATOR_PARAMETERS),
            "fields": list(fields), "raw_feature_count": len(fields),
            "minimum_completed_training_days": MIN_TRAINING_DAYS,
            "training": "Expanding; labels end strictly before UTC 01:00 decision; first eligible monthly refit.",
            "sample_weight": "sample_count / (training_day_count * non_btc_assets_in_day)",
            "label": "(asset 02:00-to-next-day-02:00 price return - beta_ratio * BTC return) / (1 + abs(beta_ratio))",
            "prediction_centering": "None; BTC synthetic hedge prediction is zero.",
            "label_funding_included": False, "label_costs_included": False,
            "nullable_fields": list(POSITIONING_FIELDS),
            "null_model_encoding": "Training-all-null columns fixed at zero through next refit; other nulls become NaN only in model matrices.",
            "native_thread_limit": 1, "hyperparameter_search": False,
            "historical_point_in_time_verified": False, **runtime}
    shared_labels = [{key: value for key, value in group.items() if key != "vectors"} for group in groups]
    output["matching_audit"] = {
        "control_fields": list(control), "augmented_fields": list(augmented),
        "label_days": len(groups), "label_samples": sum(len(group["targets"]) for group in groups),
        "shared_label_identity_sha256": _hash(shared_labels),
        "shared_evaluation_identity_actual_sha256": _hash(evaluation),
        "training_audits": matched_fits, "prediction_audits": matched_predictions,
        "eligibility_audits": eligibility_audits,
        "training_audits_sha256": _hash(matched_fits), "prediction_audits_sha256": _hash(matched_predictions),
        "historical_point_in_time_verified": False,
    }
    return output
