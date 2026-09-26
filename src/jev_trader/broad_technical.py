"""Full available daily technical bundle for the preregistered second family."""

import math

from .broad_prediction import FIELDS, run
from .broad_research import DAY_MS, features
from .market_state import states as technical_states


def flatten(value, prefix="technical"):
    if isinstance(value, dict):
        output = {}
        for key, item in sorted(value.items()):
            output.update(flatten(item, f"{prefix}.{key}"))
        return output
    if value is None:
        return {prefix: None}
    if not isinstance(value, (int, float, bool)) or not math.isfinite(value):
        raise ValueError(f"invalid technical input: {prefix}")
    return {prefix: float(value)}


def feature_bundle(data):
    economic = features(data)
    output, unavailable, schema = {}, {}, None
    for symbol, bars in data["klines"].items():
        output[symbol], unavailable[symbol] = {}, 0
        for index, technical in enumerate(technical_states(bars)):
            cutoff = bars[index].open_ms + DAY_MS
            if technical is None or cutoff not in economic[symbol]:
                continue
            row = flatten(technical)
            keys = tuple(sorted(row))
            if schema is None:
                schema = keys
            elif keys != schema:
                raise ValueError("technical field schema changed between observations")
            if any(v is None for v in row.values()):
                unavailable[symbol] += 1
                continue
            output[symbol][cutoff] = {**economic[symbol][cutoff], **row}
    if schema is None:
        raise ValueError("no technical observations")
    fields = FIELDS + schema
    quality = {"economic_fields": len(FIELDS), "technical_fields": len(schema),
               "observations_with_missing_inputs_excluded": unavailable,
               "included_observations": {s: len(rows) for s, rows in output.items()},
               "timeframe": "completed daily candles only"}
    return output, fields, quality


if __name__ == "__main__":
    run(feature_bundle, "technical")
