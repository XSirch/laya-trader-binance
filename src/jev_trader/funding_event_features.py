"""Causal daily post-funding inputs; no labels, decisions or market-data I/O.

Funding publication by 01:00 UTC and current archive versions are retrospective
assumptions, not evidence of historical point-in-time availability.
"""

from bisect import bisect_left
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import math

from .positioning_features import FEATURES as POSITIONING_FIELDS


HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS
FIRST_DAY_MS = 1_640_995_200_000
MIN_HISTORY_EVENTS = 450
AVAILABILITY_FIELD = "positioning.available"
INTRADAY_FIELDS = (
    "intraday.return1h", "intraday.return8h", "intraday.return24h",
    "intraday.realized_vol24h", "intraday.taker_flow24h", "intraday.basis_close",
)
EVENT_FIELDS = (
    "event.funding_rate", "event.rank180", "event.change_previous",
    "event.minus_mean30", "event.previous_interval_hours",
)


def _finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _timestamp(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _funding(rows):
    """Validate timestamps/rates without trusting interval_hours from any source."""
    result = []
    for row in rows:
        timestamp, rate = getattr(row, "timestamp_ms", None), getattr(row, "rate", None)
        if not _timestamp(timestamp) or not _finite(rate) or abs(rate) > .1:
            raise ValueError("funding requires an integer timestamp and a finite rate within ten percent")
        result.append((timestamp, float(rate)))
    result.sort()
    if any(a[0] == b[0] for a, b in zip(result, result[1:])):
        raise ValueError("duplicate funding timestamp")
    return result, [row[0] for row in result]


def _bar_valid(bar, timestamp, volume=False):
    if bar is None or getattr(bar, "open_ms", None) != timestamp:
        return False
    values = [getattr(bar, name, None) for name in ("open", "high", "low", "close")]
    if not all(_finite(value) and value > 0 for value in values):
        return False
    opening, high, low, close = values
    if not low <= min(opening, close) <= max(opening, close) <= high:
        return False
    if volume:
        total, taker = getattr(bar, "volume", None), getattr(bar, "taker_buy_base", None)
        if not _finite(total) or not _finite(taker) or not 0 <= taker <= total:
            return False
    return True


def _intraday(hourly, symbol, day):
    lookup = hourly.get("klines", {}).get(symbol, {})
    bars = []
    for timestamp in range(day - 23 * HOUR_MS, day + HOUR_MS, HOUR_MS):
        bar = lookup.get(timestamp)
        if bar is None:
            return None, {"reason": "missing_intraday_hour", "hour_ms": timestamp}
        if not _bar_valid(bar, timestamp, volume=True):
            return None, {"reason": "invalid_intraday_hour", "hour_ms": timestamp}
        bars.append(bar)
    mark = hourly.get("markPriceKlines", {}).get(symbol, {}).get(day)
    if not _bar_valid(mark, day):
        return None, {"reason": "missing_or_invalid_mark_close", "hour_ms": day}
    total = math.fsum(bar.volume for bar in bars)
    if not math.isfinite(total) or total <= 0:
        return None, {"reason": "nonpositive_intraday_volume"}
    logs = [math.log(bar.close) - math.log(bar.open) for bar in bars]
    average = math.fsum(logs) / 24
    values = (
        bars[-1].close / bars[-1].open - 1,
        bars[-1].close / bars[-8].open - 1,
        bars[-1].close / bars[0].open - 1,
        math.sqrt(math.fsum((value - average) ** 2 for value in logs) / 24),
        math.fsum(bar.taker_buy_base for bar in bars) / total - .5,
        mark.close / bars[-1].close - 1,
    )
    if not all(math.isfinite(value) for value in values):
        return None, {"reason": "nonfinite_intraday_transform"}
    return dict(zip(INTRADAY_FIELDS, values)), None


def _positioning(states, symbol, day, fields):
    monday = day - datetime.fromtimestamp(day / 1000, timezone.utc).weekday() * DAY_MS
    row = states.get(symbol, {}).get(monday)
    if row is None:
        return {**dict.fromkeys(fields, None), AVAILABILITY_FIELD: 0}, {
            "positioning_week_ms": monday, "positioning_latest_economic_ms": None,
        }
    observed = row.get("positioning_latest_economic_ms")
    if (row.get("latest_observed_close_ms") != monday or not _timestamp(observed)
            or observed >= monday or any(not _finite(row.get(field)) for field in fields)):
        raise ValueError("positioning row must be a finite Monday snapshot with earlier economic observations")
    metadata = {"positioning_week_ms": monday, "positioning_latest_economic_ms": observed}
    if "positioning_source_days" in row:
        metadata["positioning_source_days"] = deepcopy(row["positioning_source_days"])
    return {**{field: row[field] for field in fields}, AVAILABILITY_FIELD: 1}, metadata


def build_states(data, hourly, base_states, base_fields, positioning_states, positioning_fields):
    """Return day-keyed states, 75 control names, five event names and audit.

    Each decision at 01:00 uses the completed daily state plus 24 completed
    hourly candles ending at 01:00. Execution is scheduled for 02:00 elsewhere.
    Missing weekly positioning is represented by eight None values and a zero
    flag; a missing new Monday never inherits an older Monday's snapshot.
    """
    base_fields, positioning_fields = tuple(base_fields), tuple(positioning_fields)
    if (len(base_fields) != 60 or len(set(base_fields)) != 60
            or any(not isinstance(field, str) or not field for field in base_fields)):
        raise ValueError("exactly sixty unique named base fields required")
    if positioning_fields != POSITIONING_FIELDS:
        raise ValueError("the eight fixed positioning fields are required in canonical order")
    control_fields = base_fields + positioning_fields + (AVAILABILITY_FIELD,) + INTRADAY_FIELDS
    if len(set(control_fields + EVENT_FIELDS)) != 80:
        raise ValueError("feature names overlap")
    output = {symbol: {} for symbol in sorted(base_states)}
    excluded, counts = [], Counter()
    ignored_before_start = 0
    for symbol, states in sorted(base_states.items()):
        funding, times = _funding(data.get("fundingRate", {}).get(symbol, ()))
        for day, state in sorted(states.items()):
            if not _timestamp(day) or day % DAY_MS:
                raise ValueError("base state keys must be UTC midnight integer milliseconds")
            if day < FIRST_DAY_MS:
                ignored_before_start += 1
                continue
            if state.get("latest_observed_close_ms") != day:
                raise ValueError("base state observation differs from its completed daily cutoff")
            if any(not _finite(state.get(field)) for field in base_fields):
                raise ValueError("all sixty base fields must remain finite")
            first, last = bisect_left(times, day), bisect_left(times, day + 60_000)
            failure = None
            if last - first != 1:
                failure = {"reason": "missing_midnight_funding" if first == last else "ambiguous_midnight_funding"}
            else:
                event_ms, rate = funding[first]
                history = funding[bisect_left(times, event_ms - 180 * DAY_MS):first]
                recent = funding[bisect_left(times, event_ms - 30 * DAY_MS):first]
                if len(history) < MIN_HISTORY_EVENTS:
                    failure = {"reason": "insufficient_funding_history180", "history_events": len(history)}
                elif not recent:
                    failure = {"reason": "missing_funding_history30"}
            if failure is None:
                intraday, failure = _intraday(hourly, symbol, day)
            if failure is not None:
                excluded.append({"symbol": symbol, "signal_day_ms": day, **failure})
                counts[failure["reason"]] += 1
                continue
            preceding_ms, preceding_rate = funding[first - 1]
            rates = [item[1] for item in history]
            values = (rate, (sum(value < rate for value in rates) + .5 * sum(value == rate for value in rates)) / len(rates),
                      rate - preceding_rate, rate - math.fsum(item[1] for item in recent) / len(recent),
                      (event_ms - preceding_ms) / HOUR_MS)
            positioning, position_metadata = _positioning(positioning_states, symbol, day, positioning_fields)
            output[symbol][day] = {
                **deepcopy(state), **positioning, **intraday, **dict(zip(EVENT_FIELDS, values)),
                **position_metadata, "latest_observed_close_ms": day + HOUR_MS,
                "signal_day_ms": day, "decision_ms": day + HOUR_MS, "execution_ms": day + 2 * HOUR_MS,
                "event_timestamp_ms": event_ms, "historical_point_in_time_verified": False,
            }
    audit = {
        "control_fields": len(control_fields), "event_fields": len(EVENT_FIELDS),
        "included_observations": {symbol: len(rows) for symbol, rows in output.items()},
        "excluded_observations": excluded, "exclusion_counts": dict(sorted(counts.items())),
        "ignored_before_first_day": ignored_before_start,
        "positioning_available_observations": sum(row[AVAILABILITY_FIELD] for rows in output.values() for row in rows.values()),
        "historical_point_in_time_verified": False,
        "specification": {
            "first_day_ms": FIRST_DAY_MS, "decision_hour_utc": 1, "execution_hour_utc": 2,
            "funding_window": "[day, day + 60000ms)", "funding_publication_assumption": "Observed by 01:00 UTC",
            "funding_history": "[event - 180 days, event), at least 450 events; midrank ties",
            "funding_mean": "[event - 30 days, event)", "previous_interval": "Actual timestamp delta; source interval_hours ignored",
            "intraday_window": "24 consecutive hourly candles ending at 01:00 UTC",
            "intraday_returns": "Final close divided by first open for one, eight and twenty-four candles, minus one",
            "intraday_volatility": "Population standard deviation of 24 log(close/open) returns",
            "positioning": "Only the most recent scheduled Monday; missing values None and availability zero",
            "execution_delay": "02:00 nominal UTC; slightly less than two hours after a millisecond-delayed funding event",
        },
        "limits": ["No future funding event, future quote or future trade is consulted for eligibility.",
                   "Current archive versions and assumed publication times do not prove historical availability."],
    }
    return output, control_fields, EVENT_FIELDS, audit
