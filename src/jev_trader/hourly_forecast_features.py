"""Hourly absolute BTC forecasting inputs, derived from frozen causal context."""

import hashlib
import math
from datetime import datetime, timezone

from .basis_features import build_states as basis_states, canonical

SYMBOL = "BTCUSDT"
ECONOMIC = ("basis_fraction", "mark_basis_fraction", "basis_previous720_median", "basis_previous720_std",
            "funding_past30_mean_rate", "funding_past30_min_rate", "funding_latest_rate", "funding_past30_count")


def _flatten(value, prefix, output):
    if isinstance(value, dict):
        for key, child in sorted(value.items()):
            _flatten(child, prefix+"."+key, output)
    elif value is None:
        output[prefix] = None
    elif isinstance(value, (int, float)) and math.isfinite(value):
        output[prefix] = float(value)
    else:
        raise ValueError("invalid numeric technical field " + prefix)


def flatten_contexts(contexts):
    """No nominal prices/timestamps enter the vector; every technical leaf does."""
    result, fields, digest = {}, None, hashlib.sha256()
    for execution, context in sorted(contexts.items()):
        values = {key: context[key] for key in ECONOMIC}
        for leg in ("spot", "futures"):
            _flatten(context[leg+"_hourly"], leg, values)
            values[leg+".quote_volume24"] = context["quote_volume24"][leg]
        cutoff = context["latest_observed_close_ms"]
        time = datetime.fromtimestamp(cutoff/1000, timezone.utc)
        for name, angle in (("hour", 2*math.pi*time.hour/24), ("weekday", 2*math.pi*time.weekday()/7)):
            values[name+"_sin"], values[name+"_cos"] = math.sin(angle), math.cos(angle)
        current = tuple(sorted(values))
        if fields is None:
            fields = current
        elif fields != current:
            raise ValueError("hourly feature schema changed across observations")
        for key, value in values.items():
            if value is not None and not math.isfinite(value):
                raise ValueError("nonfinite feature " + key)
        row = {**values, "latest_observed_close_ms": cutoff, "execution_ms": execution,
               "context_sha256": context["context_sha256"], "historical_point_in_time_verified": False}
        result[execution] = row
        digest.update(canonical(row)+b"\n")
    if fields is None:
        raise ValueError("no eligible hourly feature contexts")
    return result, fields, digest.hexdigest()


def build_states(market):
    btc = {kind: {SYMBOL: by_symbol[SYMBOL]} for kind, by_symbol in market.items()}
    contexts, audit = basis_states(btc)
    states, fields, digest = flatten_contexts(contexts[SYMBOL])
    return states, fields, {"basis_context_audit": audit, "state_sha256": digest,
                           "fields": list(fields), "field_count": len(fields), "state_count": len(states),
                           "first_execution_ms": min(states), "last_execution_ms": max(states),
                           "numeric_missing_policy": "None in stored data; training-only matrix transformation",
                           "period_unit": "hourly bars", "historical_point_in_time_verified": False}
