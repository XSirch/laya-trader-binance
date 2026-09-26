"""Frozen multifactor adherence rules for an offline, whole-basket experiment.

JEV scores the five explicit criteria in one request. Only this local policy
accepts a leg's scores and chooses a uniform basket multiplier. This module has
no network, order, position-management, or fallback-to-numeric execution path.
"""

from collections.abc import Mapping
import math


ECONOMIC_FIELDS = (
    "momentum7", "momentum30", "momentum90", "reversal1", "reversal7", "carry30",
    "volatility", "taker_flow20", "beta60", "time_series_ensemble",
)
TECHNICAL_FIELDS = tuple(sorted(
    [f"technical.trend.distance_sma_pct.{n}" for n in (10, 20, 50, 100, 200)]
    + [f"technical.trend.distance_ema_pct.{n}" for n in (12, 26, 50, 200)]
    + [f"technical.trend.{name}" for name in
       ("sma50_slope_5bars_pct", "adx14", "plus_di14", "minus_di14")]
    + [f"technical.momentum.return_pct.{n}" for n in (1, 7, 30, 90)]
    + [f"technical.momentum.{name}" for name in
       ("rsi14", "macd_pct", "macd_histogram_pct", "stochastic_k14")]
    + [f"technical.volatility.{name}" for name in
       ("atr14_pct", "realized20_per_bar_pct", "bollinger_position",
        "bollinger_width_pct", "drawdown_from_high60_pct")]
    + [f"technical.participation.{name}" for name in
       ("relative_volume20", "volume_zscore20", "obv_change20_over_volume",
        "taker_buy_fraction20", "distance_vwap20_pct", "quote_volume", "trade_count")]
    + [f"technical.structure.{name}" for name in
       ("distance_prior_high20_pct", "distance_prior_low20_pct", "close_position_in_bar")]
    + [f"technical.structure.fibonacci.{period}.{name}"
       for period in (60, 180) for name in ("high_after_low", "retracement_fraction")]
    + [f"technical.structure.fibonacci.{period}.distance_to_level_pct.{ratio}"
       for period in (60, 180) for ratio in (.236, .382, .5, .618, .786)]
))
FEATURE_FIELDS = ECONOMIC_FIELDS + TECHNICAL_FIELDS
CRITERION_NAMES = ("trend", "timing", "participation", "structure", "risk")
UNITS = {
    "economic_returns": "momentum7/30/90 and reversal1/7 are fractions: 0.01 means 1%",
    "volatility": "economic daily volatility is a fraction: 0.05 means 5%",
    "carry30": "annualized past funding carry fraction, not a forecast; -0.05 means -5% per year",
    "taker_flow20": "taker buy volume fraction minus 0.5",
    "technical_pct": "all technical field names containing pct are percent: 1.0 means 1%",
    "fractions": "retracement_fraction, taker_buy_fraction20, close_position_in_bar and bollinger_position use fraction units",
    "oscillators": "RSI, stochastic K, ADX and DI use the 0-100 indicator scale",
    "other_ratios": "beta60, time_series_ensemble, relative_volume20, volume_zscore20 and obv_change20_over_volume are dimensionless",
    "high_after_low": "0=false, 1=true; describes observed extrema order only",
    "liquidity": "quote_volume20 and technical.participation.quote_volume are quote-currency units; trade_count is a count",
    "timeframe": "completed daily candles; horizon_days=7; no future labels supplied",
}

_PREFIX = (
    "Score only adherence to the exact observed-number criterion below, in [0,1]: "
    "1 means the complete criterion is met, 0 means it is not met. Do not predict "
    "price, profit, or trade success; do not choose any trade action. All indicator "
    "values are flat keys in state.market, so market['technical.trend.distance_sma_pct.200'] "
    "is a single flat-key lookup. Let d=state.position_direction (+1 long, -1 short). "
    "Use the given rounded values, inclusive bounds where shown, and state.units. "
    "All sixty indicators are supplied together for this single observed state. "
)
CRITERIA = {
    "trend": (
        "At least 3 of these 5 must hold: "
        "d*market['technical.trend.distance_sma_pct.200']>0; "
        "d*market['technical.trend.distance_ema_pct.50']>0; "
        "d*market['technical.trend.sma50_slope_5bars_pct']>0; "
        "d*(market['technical.trend.plus_di14']-market['technical.trend.minus_di14'])>0; "
        "d*market['time_series_ensemble']>0."
    ),
    "timing": (
        "At least 3 of these 5 must hold: "
        "d*market['technical.momentum.macd_histogram_pct']>=0; "
        "d*market['momentum7']>0; d*market['momentum30']>0; "
        "-10<=d*(market['technical.momentum.rsi14']-50)<=20; "
        "-30<=d*(market['technical.momentum.stochastic_k14']-50)<=35."
    ),
    "participation": (
        "market['technical.participation.relative_volume20']>=0.8 AND at least 2 of "
        "these 3 must hold: d*market['technical.participation.obv_change20_over_volume']>0; "
        "d*(market['technical.participation.taker_buy_fraction20']-0.5)>=0; "
        "d*market['technical.participation.distance_vwap20_pct']>=0."
    ),
    "structure": (
        "At least one of A, B or C must hold. A: the side-specific 60-bar Fibonacci "
        "condition AND d*(market['technical.structure.close_position_in_bar']-0.5)>=0. "
        "For d=+1 the Fibonacci condition is "
        "market['technical.structure.fibonacci.60.high_after_low']==1 AND "
        "0.236<=market['technical.structure.fibonacci.60.retracement_fraction']<=0.618. "
        "For d=-1 it is market['technical.structure.fibonacci.60.high_after_low']==0 AND "
        "0.236<=1-market['technical.structure.fibonacci.60.retracement_fraction']<=0.618. "
        "B: market['technical.participation.relative_volume20']>=1.2 AND "
        "(for d=+1, 0<=market['technical.structure.distance_prior_high20_pct']<=2; "
        "for d=-1, -2<=market['technical.structure.distance_prior_low20_pct']<=0). "
        "C: d*market['technical.trend.sma50_slope_5bars_pct']>0 AND "
        "(for d=+1, -1<=market['technical.trend.distance_sma_pct.50']<=2; "
        "for d=-1, -2<=market['technical.trend.distance_sma_pct.50']<=1)."
    ),
    "risk": (
        "ALL 5 must hold: market['volatility']<=0.05; "
        "market['technical.volatility.atr14_pct']<=6; "
        "abs(market['technical.momentum.return_pct.1'])<=8; "
        "state.quote_volume20>=10000000; d*market['carry30']>=-0.05. "
        "The volatility and annualized historical carry thresholds are FRACTIONS; "
        "ATR and the one-day technical return thresholds are PERCENT. carry30 "
        "describes past funding, not future expected carry."
    ),
}
QUESTIONS = {name: {"type": "noul", "instructions": _PREFIX + criterion}
             for name, criterion in CRITERIA.items()}


def _number(value, name, *, allow_bool=False):
    if (not isinstance(value, (int, float)) or
            (isinstance(value, bool) and not allow_bool) or not math.isfinite(value)):
        raise ValueError(f"invalid finite numeric value: {name}")
    return float(value)


def market_state(row, direction, fields):
    """Transmit exactly the complete known schema, without symbol/date/outcomes."""
    if not isinstance(row, Mapping):
        raise ValueError("market row must be a mapping")
    if not isinstance(fields, tuple) or fields != FEATURE_FIELDS:
        raise ValueError("expected the complete ordered 60-field feature_bundle schema")
    d = _number(direction, "position_direction")
    if d not in (-1, 1):
        raise ValueError("position_direction must be +1 or -1")
    missing = set(fields).union({"quote_volume20"}) - row.keys()
    if missing:
        raise ValueError(f"missing market inputs: {sorted(missing)}")
    values = {field: round(_number(row[field], field, allow_bool=True), 8)
              for field in fields}
    for period in (60, 180):
        if values[f"technical.structure.fibonacci.{period}.high_after_low"] not in (0, 1):
            raise ValueError("Fibonacci extrema-order flags must be zero or one")
    return {"market": values, "position_direction": d,
            "quote_volume20": round(_number(row["quote_volume20"], "quote_volume20"), 8),
            "horizon_days": 7, "units": dict(UNITS)}


def numeric_adherence(state):
    """Deterministic reference over precisely the state sent to JEV, not fallback."""
    if (not isinstance(state, Mapping) or
            set(state) != {"market", "position_direction", "quote_volume20", "horizon_days", "units"} or
            state["horizon_days"] != 7 or state["units"] != UNITS or
            not isinstance(state["market"], Mapping) or set(state["market"]) != set(FEATURE_FIELDS)):
        raise ValueError("invalid complete policy state")
    checked = market_state({**state["market"], "quote_volume20": state["quote_volume20"]},
                           state["position_direction"], FEATURE_FIELDS)
    if checked != state:
        raise ValueError("policy state must use the transmitted eight-decimal values")
    m, d = checked["market"], checked["position_direction"]
    trend = sum((d * m["technical.trend.distance_sma_pct.200"] > 0,
                 d * m["technical.trend.distance_ema_pct.50"] > 0,
                 d * m["technical.trend.sma50_slope_5bars_pct"] > 0,
                 d * (m["technical.trend.plus_di14"] - m["technical.trend.minus_di14"]) > 0,
                 d * m["time_series_ensemble"] > 0)) >= 3
    timing = sum((d * m["technical.momentum.macd_histogram_pct"] >= 0,
                  d * m["momentum7"] > 0, d * m["momentum30"] > 0,
                  -10 <= d * (m["technical.momentum.rsi14"] - 50) <= 20,
                  -30 <= d * (m["technical.momentum.stochastic_k14"] - 50) <= 35)) >= 3
    participation = m["technical.participation.relative_volume20"] >= .8 and sum((
        d * m["technical.participation.obv_change20_over_volume"] > 0,
        d * (m["technical.participation.taker_buy_fraction20"] - .5) >= 0,
        d * m["technical.participation.distance_vwap20_pct"] >= 0)) >= 2
    retracement = m["technical.structure.fibonacci.60.retracement_fraction"]
    fib = (m["technical.structure.fibonacci.60.high_after_low"] == (1 if d == 1 else 0)
           and .236 <= (retracement if d == 1 else 1 - retracement) <= .618
           and d * (m["technical.structure.close_position_in_bar"] - .5) >= 0)
    breakout = m["technical.participation.relative_volume20"] >= 1.2 and (
        0 <= m["technical.structure.distance_prior_high20_pct"] <= 2 if d == 1 else
        -2 <= m["technical.structure.distance_prior_low20_pct"] <= 0)
    average_pullback = d * m["technical.trend.sma50_slope_5bars_pct"] > 0 and (
        -1 <= m["technical.trend.distance_sma_pct.50"] <= 2 if d == 1 else
        -2 <= m["technical.trend.distance_sma_pct.50"] <= 1)
    risk = (m["volatility"] <= .05 and m["technical.volatility.atr14_pct"] <= 6
            and abs(m["technical.momentum.return_pct.1"]) <= 8
            and checked["quote_volume20"] >= 10_000_000 and d * m["carry30"] >= -.05)
    return dict(zip(CRITERION_NAMES, map(float, (trend, timing, participation,
                                               fib or breakout or average_pullback, risk))))


def script_accept(adherence):
    """Only the local script applies score thresholds; invalid scores abort."""
    if not isinstance(adherence, Mapping) or set(adherence) != set(CRITERION_NAMES):
        raise ValueError("exactly the five adherence scores are required")
    scores = {name: _number(adherence[name], name) for name in CRITERION_NAMES}
    if any(not 0 <= score <= 1 for score in scores.values()):
        raise ValueError("adherence scores must be in [0,1]")
    return scores["risk"] >= .75 and sum(scores[name] >= .65 for name in CRITERION_NAMES[:-1]) >= 2


def filter_scale(base_weights, adherence_by_symbol, active_scale):
    """Return a UNIFORM basket scale and gross-weighted accepted fraction.

    BTC and every other nonzero leg are counted identically. Rejected legs remain
    in an accepted basket: the caller multiplies EVERY base weight by the same
    returned scale, preserving all relative hedge proportions. Scale 4 permits
    gross exposure up to 2 only in the separate offline experiment.
    """
    scale = _number(active_scale, "active_scale")
    if scale not in (1, 4):
        raise ValueError("offline active_scale must be 1 or 4")
    if not isinstance(base_weights, Mapping) or not isinstance(adherence_by_symbol, Mapping):
        raise ValueError("weights and scores must be mappings")
    weights = {symbol: _number(weight, f"weight:{symbol}") for symbol, weight in base_weights.items()}
    accepted = {symbol: script_accept(scores) for symbol, scores in adherence_by_symbol.items()}
    gross = math.fsum(abs(weight) for weight in weights.values())
    if gross > .5 + 1e-12:
        raise ValueError("base basket exceeds the frozen 0.5 gross cap")
    if not gross:
        return 0.0, 0.0
    if any(weight and symbol not in accepted for symbol, weight in weights.items()):
        raise ValueError("missing adherence for a nonzero basket leg; no numeric fallback")
    fraction = math.fsum(abs(weight) for symbol, weight in weights.items()
                         if weight and accepted[symbol]) / gross
    return (scale if fraction >= .60 else 0.0), fraction
