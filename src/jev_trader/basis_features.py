"""Causal hourly basis context, preserving all spot and perp technical fields."""

from bisect import bisect_right
from collections import Counter
import hashlib
import json
import math
from statistics import median, pstdev

from .binance_data import HOUR_MS
from .market_state import states as technical_states

WINDOW = 30 * 24


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _technical(rows):
    """Reset recursive indicators after every missing hour, without imputation."""
    result, segment = {}, []
    for timestamp in sorted(rows):
        if segment and timestamp != segment[-1].open_ms + HOUR_MS:
            result.update((bar.open_ms, state) for bar, state in zip(segment, technical_states(segment))
                          if state is not None)
            segment = []
        segment.append(rows[timestamp])
    if segment:
        result.update((bar.open_ms, state) for bar, state in zip(segment, technical_states(segment))
                      if state is not None)
    return result


def build_states(market):
    """At execution t, newest candle closes at t-H; funding is older still.

    Funding publication one hour after its timestamp is an assumption, not
    proven point-in-time availability. No future prices determine eligibility.
    """
    result, audit, digest = {}, {}, hashlib.sha256()
    for symbol in sorted(market["spot"]):
        spot, future, mark = (market[kind][symbol] for kind in ("spot", "futures", "mark"))
        ts, tf = _technical(spot), _technical(future)
        events = market["funding"][symbol]
        times = [e.timestamp_ms for e in events]
        if any(b <= a for a, b in zip(times, times[1:])):
            raise ValueError("funding history must strictly increase")
        output, reasons, chain = {}, Counter(), []
        for timestamp in sorted(set(spot) & set(future)):
            if chain and timestamp != chain[-1] + HOUR_MS:
                chain = []
            chain.append(timestamp)
            if len(chain) > WINDOW + 1:
                chain.pop(0)
            if len(chain) < WINDOW + 1 or timestamp not in ts or timestamp not in tf:
                reasons["consecutive_history_warmup"] += 1
                continue
            if timestamp not in mark:
                reasons["missing_completed_mark"] += 1
                continue
            cutoff = timestamp + HOUR_MS
            available = cutoff - HOUR_MS
            first = bisect_right(times, available - WINDOW * HOUR_MS)
            last = bisect_right(times, available)
            history = events[first:last]
            if (len(history) < 84 or not history or times[last-1] < available-9*HOUR_MS
                    or history[-1].timestamp_ms-history[0].timestamp_ms < 27*24*HOUR_MS):
                reasons["funding_history_warmup_or_stale"] += 1
                continue
            if any(e.interval_hours != 8 or not math.isfinite(e.rate) for e in history):
                raise ValueError("basis protocol assumes observed past eight-hour funding")
            past_basis = [future[t].close/spot[t].close-1 for t in chain[:-1]]
            volumes = {}
            for name, rows in (("spot", spot), ("futures", future)):
                values = [rows[t].quote_volume for t in chain[-24:]]
                volumes[name] = sum(values) if all(v is not None for v in values) else None
            row = {
                "symbol": symbol, "execution_ms": cutoff+HOUR_MS,
                "latest_observed_close_ms": cutoff, "funding_available_through_ms": available,
                "historical_point_in_time_verified": False,
                "spot_close": spot[timestamp].close, "future_close": future[timestamp].close,
                "basis_fraction": future[timestamp].close/spot[timestamp].close-1,
                "mark_basis_fraction": mark[timestamp].close/spot[timestamp].close-1,
                "basis_previous720_median": median(past_basis),
                "basis_previous720_std": pstdev(past_basis),
                "funding_past30_mean_rate": sum(e.rate for e in history)/len(history),
                "funding_past30_min_rate": min(e.rate for e in history),
                "funding_latest_rate": history[-1].rate,
                "funding_latest_ms": history[-1].timestamp_ms,
                "funding_past30_count": len(history),
                "quote_volume24": volumes,
                "spot_hourly": ts[timestamp], "futures_hourly": tf[timestamp],
                "technical_period_unit": "hourly_bars",
            }
            row["context_sha256"] = hashlib.sha256(canonical(row)).hexdigest()
            output[row["execution_ms"]] = row
            digest.update(canonical(row)+b"\n")
        result[symbol] = output
        audit[symbol] = {"state_count": len(output), "excluded_counts": dict(reasons),
                         "first_execution_ms": min(output) if output else None,
                         "last_execution_ms": max(output) if output else None}
    return result, {"symbols": audit, "state_sha256": digest.hexdigest(),
                    "context": "All market_state technical fields for both legs; all periods are hours.",
                    "unavailable": ["synchronized executable quotes", "historical publication times",
                                    "historical margin tiers", "financing rates", "SOL positioning cohort"]}
