"""Fixed eight-field augmentation from lagged weekly positioning snapshots.

Archive versions are observed now; this transformation does not establish
historical publication or eliminate revision bias with an arbitrary lag.
"""

from datetime import datetime, timedelta, timezone
import math


DAY_MS = 86_400_000
FEATURES = (
    "positioning.log_oi_value_to_volume20",
    "positioning.oi_quantity_change1w",
    "positioning.oi_quantity_change4w",
    "positioning.log_top_account_ratio",
    "positioning.log_top_position_ratio",
    "positioning.log_global_account_ratio",
    "positioning.top_position_minus_account",
    "positioning.top_account_minus_global",
)


def _snapshot(snapshots, symbol, day):
    record = snapshots.get(symbol, {}).get(day)
    if record is None:
        return None, "missing_snapshot"
    row = record.get("snapshot", record)
    if row.get("symbol") != symbol or row.get("day") != day:
        raise ValueError("positioning snapshot identity differs from requested symbol/day")
    if not row.get("available", False):
        return None, "snapshot_quality_unavailable"
    expected_end = int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()*1000) + DAY_MS - 300_000
    if row.get("last_observed_timestamp_ms") != expected_end:
        raise ValueError("positioning snapshot final timestamp differs from designated day")
    if row.get("timezone_assumption") != "UTC":
        raise ValueError("positioning snapshot requires documented UTC assumption")
    return row, None


def _positive(values, name):
    value = values.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("positioning feature requires positive finite " + name)
    return value


def augment(states, fields, snapshots):
    """Return eligible Monday states, 68 named fields and missingness audit."""
    fields = tuple(fields)
    if len(fields) != 60 or len(set(fields)) != 60 or set(fields) & set(FEATURES):
        raise ValueError("positioning augmentation requires the original sixty unique fields")
    output = {symbol: {} for symbol in sorted(states)}
    missing = []
    for symbol, rows in sorted(states.items()):
        for cutoff, state in sorted(rows.items()):
            if isinstance(cutoff, bool) or not isinstance(cutoff, int) or cutoff % DAY_MS:
                raise ValueError("state cutoff must be UTC midnight milliseconds")
            day = datetime.fromtimestamp(cutoff/1000, timezone.utc)
            if day.weekday() != 0:
                continue
            if state.get("latest_observed_close_ms") != cutoff:
                raise ValueError("state observation must equal cutoff")
            if any(isinstance(state.get(f), bool) or not isinstance(state.get(f), (int, float))
                   or not math.isfinite(state[f]) for f in fields):
                raise ValueError("original sixty features must remain finite")
            friday = day - timedelta(days=3)
            days = [(friday-timedelta(weeks=lag)).strftime("%Y-%m-%d") for lag in (0, 1, 4)]
            observed, failures = [], []
            for source_day in days:
                snapshot, reason = _snapshot(snapshots, symbol, source_day)
                if reason:
                    failures.append({"day": source_day, "reason": reason})
                observed.append(snapshot)
            if failures:
                missing.append({"symbol": symbol, "cutoff_ms": cutoff, "failures": failures})
                continue
            current, prior, older = (row["values"] for row in observed)
            oi = _positive(current, "sum_open_interest")
            oi1 = _positive(prior, "sum_open_interest")
            oi4 = _positive(older, "sum_open_interest")
            oi_value = _positive(current, "sum_open_interest_value")
            volume = _positive(state, "quote_volume20")
            account = math.log(_positive(current, "count_toptrader_long_short_ratio"))
            position = math.log(_positive(current, "sum_toptrader_long_short_ratio"))
            global_account = math.log(_positive(current, "count_long_short_ratio"))
            # Difference of logs avoids overflow from otherwise finite ratios.
            values = (math.log(oi_value)-math.log(volume), math.log(oi)-math.log(oi1),
                      math.log(oi)-math.log(oi4), account, position, global_account,
                      position-account, account-global_account)
            if not all(math.isfinite(value) for value in values):
                raise ValueError("nonfinite positioning transform")
            output[symbol][cutoff] = {**state, **dict(zip(FEATURES, values)),
                                      "positioning_source_days": days,
                                      "positioning_latest_economic_ms": observed[0]["last_observed_timestamp_ms"],
                                      "historical_point_in_time_verified": False}
    return output, fields + FEATURES, {
        "original_fields": 60, "additional_fields": 8,
        "included_observations": {symbol: len(rows) for symbol, rows in output.items()},
        "unavailable_observations": missing,
        "snapshot_lag": "Monday cutoff uses prior Friday plus one/four-week earlier Fridays.",
        "historical_point_in_time_verified": False,
        "limits": ["Current archive versions can contain revisions not observed historically.",
                   "UTC interpretation and publication before decision are explicit retrospective assumptions."]}
