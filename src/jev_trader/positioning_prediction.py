"""Paired fixed trees on a shared positioning-eligible retrospective universe.

The original sixty-field control and sixty-eight-field augmentation share every
label, observation identity, sample weight, and fit schedule. Current archive
versions do not establish historical availability or point-in-time correctness.
"""

from datetime import datetime, timezone
import math

from .positioning_features import FEATURES
from .tree_prediction import (
    DAY_MS, ESTIMATOR_PARAMETERS, FIRST_LABEL_MS, HOUR_MS, MIN_TRAINING_WEEKS,
    WEEK_MS, _hash, _lifecycle, _runtime, _states_at, _validate_fields, _week_label,
)


def _fields(base_fields):
    base = _validate_fields(base_fields)
    if set(base) & set(FEATURES):
        raise ValueError("base sixty fields cannot include positioning augmentation")
    augmented = base + FEATURES
    if len(augmented) != 68 or len(set(augmented)) != 68 or augmented[60:] != FEATURES:
        raise ValueError("exactly the original sixty plus eight fixed positioning fields required")
    return base, augmented


def build_forecasts(hourly, states_augmented, base_fields60, lifecycle_events, *, estimator_factory=None):
    """Fit the frozen estimator twice using one shared label and eligibility pass.

    The injected estimator seam is for synthetic tests only. Production fitting
    uses the same dependency/runtime and native thread limit as the frozen tree
    experiment. Archive revision risk is separate from strict label chronology.
    """
    base, augmented = _fields(base_fields60)
    events = _lifecycle(lifecycle_events)
    states = states_augmented
    if not isinstance(states, dict) or any(not isinstance(symbol, str) for symbol in states):
        raise ValueError("states must map named symbols to timestamped rows")
    all_dates = {cutoff for rows in states.values() for cutoff in rows}
    if any(isinstance(t, bool) or not isinstance(t, int) or t % DAY_MS for t in all_dates):
        raise ValueError("state cutoffs must be integer UTC midnight timestamps")
    dates = sorted(t for t in all_dates if t >= FIRST_LABEL_MS
                   and datetime.fromtimestamp(t / 1000, timezone.utc).weekday() == 0)
    prices = hourly.get("klines")
    if not isinstance(prices, dict):
        raise ValueError("hourly klines mapping required")
    current_by_date = {t: _states_at(states, t, augmented, events) for t in dates}
    weeks, unavailable = [], []
    for cutoff in dates:
        current = current_by_date[cutoff]
        if len(current) < 8:
            unavailable.append({"signal_ms": cutoff,
                                "label_start_ms": cutoff + HOUR_MS,
                                "label_end_ms": cutoff + HOUR_MS + WEEK_MS,
                                "eligible_symbols": sorted(current),
                                "reason": "Fewer than eight signal-time eligible assets."})
            continue
        week, failure = _week_label(prices, current, cutoff, augmented)
        if failure is not None:
            unavailable.append(failure)
        else:
            weeks.append(week)

    factory, thread_limit, array, runtime = _runtime(estimator_factory)
    fields_by_variant = {"control60": base, "augmented68": augmented}
    output = {name: {"signals": {symbol: {} for symbol in sorted(states)},
                     "fit_audits": [], "prediction_audits": [], "prediction_errors": []}
              for name in fields_by_variant}
    models, fit_month, fit_cutoff = {}, None, None
    matching_fits, matching_predictions = [], []
    for cutoff in dates:
        current = current_by_date[cutoff]
        known = [week for week in weeks if week["label_end_ms"] < cutoff]
        if len(current) < 8 or len(known) < MIN_TRAINING_WEEKS:
            continue
        calendar = datetime.fromtimestamp(cutoff / 1000, timezone.utc)
        month = (calendar.year, calendar.month)
        if not models or month != fit_month:
            count = sum(len(week["targets"]) for week in known)
            shared_training = []
            for week in known:
                weight = count / (len(known) * len(week["targets"]))
                for symbol in sorted(week["targets"]):
                    shared_training.append({"signal_ms": week["signal_ms"],
                                            "label_end_ms": week["label_end_ms"], "symbol": symbol,
                                            "features": week["vectors"][symbol],
                                            "target": week["targets"][symbol], "sample_weight": weight})
            shared_rows = [{key: value for key, value in row.items() if key != "features"}
                           for row in shared_training]
            matching_fits.append({"fit_cutoff_ms": cutoff,
                                  "training_weeks": len(known), "training_samples": count,
                                  "training_identity_label_weight_sha256": _hash(shared_rows),
                                  "training_signal_dates_ms": [week["signal_ms"] for week in known],
                                  "latest_label_end_ms": known[-1]["label_end_ms"]})
            for name, fields in fields_by_variant.items():
                training = [{**row, "features": row["features"][:len(fields)]} for row in shared_training]
                model = factory(**ESTIMATOR_PARAMETERS)
                with thread_limit():
                    model.fit(array([row["features"] for row in training]),
                              array([row["target"] for row in training]),
                              sample_weight=array([row["sample_weight"] for row in training]))
                models[name] = model
                output[name]["fit_audits"].append({
                    "fit_cutoff_ms": cutoff, "first_training_signal_ms": known[0]["signal_ms"],
                    "last_training_signal_ms": known[-1]["signal_ms"],
                    "latest_label_end_ms": known[-1]["label_end_ms"],
                    "training_weeks": len(known), "training_samples": count,
                    "training_signal_dates_ms": [week["signal_ms"] for week in known],
                    "training_input_sha256": _hash(training), "fields": list(fields),
                    "estimator_parameters": dict(ESTIMATOR_PARAMETERS)})
            fit_month, fit_cutoff = month, cutoff
        symbols = sorted(current)
        matching_predictions.append({"signal_ms": cutoff, "fit_cutoff_ms": fit_cutoff,
                                     "eligible_symbols": symbols,
                                     "prediction_assets": len(symbols),
                                     "prediction_identity_sha256": _hash({"signal_ms": cutoff,
                                                                          "symbols": symbols})})
        for name, fields in fields_by_variant.items():
            vectors = [[float(current[symbol][field]) for field in fields] for symbol in symbols]
            with thread_limit():
                raw = [float(value) for value in models[name].predict(array(vectors))]
            if len(raw) != len(symbols) or any(not math.isfinite(value) for value in raw):
                raise ValueError("estimator returned malformed or nonfinite predictions")
            center = math.fsum(raw) / len(raw)
            prediction_rows = []
            for symbol, value in zip(symbols, raw):
                prediction = value - center
                if not math.isfinite(prediction):
                    raise ValueError("centered prediction is nonfinite")
                output[name]["signals"][symbol][cutoff] = {
                    **current[symbol], "prediction": prediction, "raw_prediction": value}
                prediction_rows.append({"symbol": symbol, "raw_prediction": value, "prediction": prediction})
            output[name]["prediction_audits"].append({
                "signal_ms": cutoff, "fit_cutoff_ms": fit_cutoff, "prediction_assets": len(symbols),
                "prediction_input_sha256": _hash({"fields": fields, "symbols": symbols, "vectors": vectors}),
                "predictions_sha256": _hash(prediction_rows)})

    # Future outcomes enter evaluation only after both streams are fixed.
    shared_error_rows = []
    for week in weeks:
        for symbol in sorted(week["targets"]):
            cutoff = week["signal_ms"]
            if cutoff in output["control60"]["signals"][symbol]:
                common = {"signal_ms": cutoff, "label_end_ms": week["label_end_ms"],
                          "symbol": symbol, "actual": week["targets"][symbol]}
                shared_error_rows.append(common)
                for name in fields_by_variant:
                    output[name]["prediction_errors"].append({
                        **common, "prediction": output[name]["signals"][symbol][cutoff]["prediction"]})
    for name, fields in fields_by_variant.items():
        output[name]["unavailable_label_weeks"] = unavailable
        output[name]["design"] = {
            "model": "HistGradientBoostingRegressor", "parameters": dict(ESTIMATOR_PARAMETERS),
            "fields": list(fields), "raw_feature_count": len(fields),
            "first_label_ms": FIRST_LABEL_MS, "minimum_completed_training_weeks": MIN_TRAINING_WEEKS,
            "training": "Expanding; labels end strictly before forecast cutoff; monthly refits.",
            "sample_weight": "sample_count / (training_week_count * assets_in_week)",
            "label": "Monday 01:00 to following Monday 01:00 gross price return minus eligible cross-section mean.",
            "label_funding_included": False, "label_costs_included": False,
            "prediction_centering": "Current eligible cross-section mean removed.",
            "interior_zero_trade_hours_allowed": True,
            "all_hourly_open_prices_required_positive": True,
            "native_thread_limit": 1, "hyperparameter_search": False,
            "prediction_audits_sha256": _hash(output[name]["prediction_audits"]), **runtime}
    shared_labels = [{key: value for key, value in week.items() if key != "vectors"} for week in weeks]
    output["matching_audit"] = {
        "base_fields": list(base), "augmented_fields": list(augmented),
        "label_weeks": len(weeks), "label_samples": sum(len(week["targets"]) for week in weeks),
        "shared_label_identity_sha256": _hash(shared_labels),
        "shared_evaluation_identity_actual_sha256": _hash(shared_error_rows),
        "training_audits": matching_fits, "prediction_audits": matching_predictions,
        "training_audits_sha256": _hash(matching_fits),
        "prediction_audits_sha256": _hash(matching_predictions),
        "historical_point_in_time_verified": False,
        "scope": "Same positioning-eligible assets/dates for both models; no comparison to the unfiltered original universe.",
    }
    return output
