"""Fixed causal histogram-tree forecasts on the complete raw feature bundle.

Weekly labels are gross execution-hour price returns demeaned across the whole
signal-time eligible cross-section. Funding and trading costs are deliberately
outside the label; the portfolio policy must apply its separate cost hurdle.
"""

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math


HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS
WEEK_MS = 7 * DAY_MS
FIRST_LABEL_MS = 1_640_995_200_000  # 2022-01-01T00:00:00Z
MIN_TRAINING_WEEKS = 52
FEATURE_COUNT = 60
ESTIMATOR_PARAMETERS = {
    "loss": "squared_error", "learning_rate": .05, "max_iter": 100,
    "max_leaf_nodes": 7, "max_depth": 3, "min_samples_leaf": 40,
    "l2_regularization": 10, "max_bins": 64, "early_stopping": False,
    "categorical_features": None, "random_state": 548,
}


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def _finite(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


def _utc_ms(value, name):
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an explicit UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"invalid {name}") from error
    if parsed.utcoffset() != timedelta(0) or parsed.microsecond % 1000:
        raise ValueError(f"{name} must be UTC with millisecond precision")
    return int(parsed.timestamp() * 1000)


def _lifecycle(events):
    output, seen = [], set()
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("lifecycle events must be mappings")
        symbol = event.get("symbol")
        if (not isinstance(symbol, str) or not symbol.isascii() or not symbol.isalnum()
                or symbol.upper() != symbol or symbol in seen):
            raise ValueError("invalid or duplicate lifecycle symbol")
        published = _utc_ms(event.get("published_utc"), "published_utc")
        restricted = _utc_ms(event.get("new_positions_stop_utc"), "new_positions_stop_utc")
        settled = (_utc_ms(event["automatic_settlement_utc"], "automatic_settlement_utc")
                   if "automatic_settlement_utc" in event else None)
        if published > restricted or (settled is not None and restricted > settled):
            raise ValueError("lifecycle timestamps must follow publication, restriction, settlement")
        output.append((symbol, published, restricted))
        seen.add(symbol)
    return tuple(sorted(output))


def _validate_fields(fields):
    fields = tuple(fields)
    if (len(fields) != FEATURE_COUNT or len(set(fields)) != FEATURE_COUNT
            or any(not isinstance(field, str) or not field for field in fields)):
        raise ValueError("exactly 60 unique named raw fields required")
    forbidden = {"symbol", "asset", "asset_id", "date", "time", "timestamp",
                 "prediction", "raw_prediction", "target"}
    if any(field.lower().split(".")[-1] in forbidden or field.lower().endswith("_ms")
           for field in fields):
        raise ValueError("identity, time, target, and prediction fields cannot be model inputs")
    return fields


def _states_at(states, cutoff, fields, events):
    excluded = {symbol for symbol, published, restricted in events
                if published <= cutoff + HOUR_MS and restricted <= cutoff + HOUR_MS}
    selected = {}
    for symbol in sorted(states):
        if cutoff not in states[symbol]:
            continue
        row = states[symbol][cutoff]
        observed = row.get("latest_observed_close_ms")
        if isinstance(observed, bool) or not isinstance(observed, int) or observed != cutoff:
            raise ValueError("state latest observed close must equal its forecast cutoff")
        if any(field not in row or not _finite(row[field]) for field in fields):
            raise ValueError(f"all 60 raw fields must be finite: {symbol} {cutoff}")
        if any(name not in row or not _finite(row[name])
               for name in ("quote_volume20", "volatility")):
            raise ValueError("finite volume and volatility required for eligibility")
        if (symbol not in excluded and row["quote_volume20"] >= 10_000_000
                and .005 <= row["volatility"] <= .15):
            selected[symbol] = row
    return selected


def _week_label(prices, current, cutoff, fields):
    start, end = cutoff + HOUR_MS, cutoff + HOUR_MS + WEEK_MS
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
            elif timestamp in (start, end) and (
                    not _finite(getattr(bar, "trades", None)) or bar.trades <= 0):
                failure = {"symbol": symbol, "hour_ms": timestamp, "reason": "untradable_endpoint"}
            if failure is not None:
                failures.append(failure)
                break
        if failure is None:
            value = lookup[end].open / lookup[start].open - 1
            if not math.isfinite(value):
                failures.append({"symbol": symbol, "hour_ms": end, "reason": "nonfinite_return"})
            else:
                returns[symbol] = value
    if failures:
        return None, {"signal_ms": cutoff, "label_start_ms": start, "label_end_ms": end,
                      "eligible_symbols": sorted(current), "failures": failures,
                      "reason": "Incomplete eligible cross-section; entire week excluded."}
    mean = math.fsum(returns.values()) / len(returns)
    return {"signal_ms": cutoff, "label_start_ms": start, "label_end_ms": end,
            "vectors": {symbol: [float(current[symbol][field]) for field in fields]
                        for symbol in sorted(current)},
            "targets": {symbol: returns[symbol] - mean for symbol in sorted(current)}}, None


def _runtime(estimator_factory):
    """Keep sklearn and numpy imports outside module import and synthetic tests."""
    if estimator_factory is not None:
        return estimator_factory, nullcontext, lambda rows: rows, {"injected_estimator": True}
    import numpy as np
    import sklearn
    from sklearn.ensemble import HistGradientBoostingRegressor
    from threadpoolctl import threadpool_limits

    return (HistGradientBoostingRegressor, lambda: threadpool_limits(limits=1),
            lambda rows: np.asarray(rows, dtype=np.float64),
            {"injected_estimator": False, "numpy_version": np.__version__,
             "sklearn_version": sklearn.__version__})


def build_forecasts(hourly, states, fields, lifecycle_events, *, estimator_factory=None):
    """Return frozen monthly fits and strictly causal weekly predictions.

    ``estimator_factory`` is solely a synthetic-test seam. Production calls use
    the fixed sklearn estimator. All fitting and prediction runs with one
    native thread. No model is fit until 52 whole cross-section labels have
    ended strictly before the current Monday midnight information cutoff.
    """
    fields, events = _validate_fields(fields), _lifecycle(lifecycle_events)
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
    current_by_date = {t: _states_at(states, t, fields, events) for t in dates}
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
        week, failure = _week_label(prices, current, cutoff, fields)
        if failure is not None:
            unavailable.append(failure)
        else:
            weeks.append(week)

    factory, thread_limit, array, runtime = _runtime(estimator_factory)
    signals = {symbol: {} for symbol in sorted(states)}
    fits, prediction_audits = [], []
    model, fit_month, fit_cutoff = None, None, None
    for cutoff in dates:
        current = current_by_date[cutoff]
        known = [week for week in weeks if week["label_end_ms"] < cutoff]
        if len(current) < 8 or len(known) < MIN_TRAINING_WEEKS:
            continue
        calendar = datetime.fromtimestamp(cutoff / 1000, timezone.utc)
        month = (calendar.year, calendar.month)
        if model is None or month != fit_month:
            count = sum(len(week["targets"]) for week in known)
            training = []
            for week in known:
                weight = count / (len(known) * len(week["targets"]))
                for symbol in sorted(week["targets"]):
                    training.append({"signal_ms": week["signal_ms"],
                                     "label_end_ms": week["label_end_ms"], "symbol": symbol,
                                     "features": week["vectors"][symbol],
                                     "target": week["targets"][symbol], "sample_weight": weight})
            model = factory(**ESTIMATOR_PARAMETERS)
            with thread_limit():
                model.fit(array([row["features"] for row in training]),
                          array([row["target"] for row in training]),
                          sample_weight=array([row["sample_weight"] for row in training]))
            fit_month, fit_cutoff = month, cutoff
            fits.append({"fit_cutoff_ms": cutoff, "first_training_signal_ms": known[0]["signal_ms"],
                         "last_training_signal_ms": known[-1]["signal_ms"],
                         "latest_label_end_ms": known[-1]["label_end_ms"],
                         "training_weeks": len(known), "training_samples": count,
                         "training_signal_dates_ms": [week["signal_ms"] for week in known],
                         "training_input_sha256": _hash(training), "fields": list(fields),
                         "estimator_parameters": dict(ESTIMATOR_PARAMETERS)})
        symbols = sorted(current)
        vectors = [[float(current[symbol][field]) for field in fields] for symbol in symbols]
        with thread_limit():
            raw = [float(value) for value in model.predict(array(vectors))]
        if len(raw) != len(symbols) or any(not math.isfinite(value) for value in raw):
            raise ValueError("estimator returned malformed or nonfinite predictions")
        center = math.fsum(raw) / len(raw)
        prediction_rows = []
        for symbol, value in zip(symbols, raw):
            prediction = value - center
            if not math.isfinite(prediction):
                raise ValueError("centered prediction is nonfinite")
            signals[symbol][cutoff] = {**current[symbol], "prediction": prediction,
                                       "raw_prediction": value}
            prediction_rows.append({"symbol": symbol, "raw_prediction": value,
                                    "prediction": prediction})
        prediction_audits.append({"signal_ms": cutoff, "fit_cutoff_ms": fit_cutoff,
                                  "prediction_assets": len(symbols),
                                  "prediction_input_sha256": _hash({"fields": fields,
                                                                    "symbols": symbols,
                                                                    "vectors": vectors}),
                                  "predictions_sha256": _hash(prediction_rows)})

    # This pass runs only after predictions are fixed. Realized evaluation labels
    # never enter current predictions or refit scheduling.
    errors = []
    for week in weeks:
        for symbol in sorted(week["targets"]):
            cutoff = week["signal_ms"]
            if cutoff in signals[symbol]:
                errors.append({"signal_ms": cutoff, "label_end_ms": week["label_end_ms"],
                               "symbol": symbol, "prediction": signals[symbol][cutoff]["prediction"],
                               "actual": week["targets"][symbol]})
    design = {"model": "HistGradientBoostingRegressor", "parameters": dict(ESTIMATOR_PARAMETERS),
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
              "prediction_audits_sha256": _hash(prediction_audits), **runtime}
    return {"signals": signals, "fit_audits": fits, "prediction_audits": prediction_audits,
            "prediction_errors": errors, "unavailable_label_weeks": unavailable, "design": design}
