"""Daily event replay using the preserved hourly accounting engine.

The date key selects a midnight funding event, while its information cutoff is
01:00 and execution is 02:00. Publication by 01:00 is an assumption, not proof.
"""

from .binance_data import HOUR_MS
from .broad_research import DAY_MS
from .scheduled_execution import evaluate as scheduled_evaluate


def evaluate(hourly, funding, states, rule, start, end, side_cost, *,
             exact_funding_marks=None, target_policy=None, settlement_bounds=None,
             trailing=None):
    for symbol, rows in states.items():
        for day, row in rows.items():
            if type(day) is not int or day % DAY_MS:
                raise ValueError("event state key must be UTC midnight")
            decision = day + HOUR_MS
            if row.get("latest_observed_close_ms") != decision:
                raise ValueError("event inputs must close at the 01:00 decision")
            event = row.get("event_timestamp_ms")
            if type(event) is not int or not day <= event < day + 60_000:
                raise ValueError("midnight funding event required before decision")
            for field, expected in (("decision_ms", decision), ("execution_ms", day + 2*HOUR_MS),
                                    ("signal_day_ms", day)):
                if field in row and row[field] != expected:
                    raise ValueError("inconsistent event state " + field)
    result = scheduled_evaluate(
        hourly, funding, states, rule, start, end, side_cost, delay_hours=2,
        exact_funding_marks=exact_funding_marks, target_policy=target_policy,
        settlement_bounds=settlement_bounds, trailing=trailing, cadence="daily")
    for record in result["execution_audit"]:
        day = record["latest_input_close_ms"]
        if record["execution_ms"] != day + 2*HOUR_MS:
            raise ValueError("unexpected event execution hour")
        record.update(signal_day_ms=day, latest_input_close_ms=day + HOUR_MS,
                      decision_ms=day + HOUR_MS, historical_point_in_time_verified=False)
    return result
