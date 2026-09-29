from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from jev_trader import futures_flow_absorption_research as common  # noqa: E402

SERIES = "cross_sectional_momentum_20260927"
PROTOCOL = ROOT / "docs" / "cross_sectional_momentum_protocol_2026-09-27.md"
OUTPUT_DIR = ROOT / "results" / SERIES
OUTPUT_JSON = OUTPUT_DIR / "research.json"
OUTPUT_TRADES = OUTPUT_DIR / "signal_trades.csv"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
SIGNAL_INTERVAL = 15
MOMENTUM_HORIZON = 60
MIN_GAP_PCT = 0.75
HOLD_MINUTES = 60
COOLDOWN_MS = 30 * 60_000
PAIR_ALLOCATION = 0.25
SIDE_COSTS = {"base": 0.0010, "stress": 0.0015}
MIN_TRAIN = 400
MIN_SCREEN = 30
MIN_CONFIRM = 100
THRESHOLDS = tuple(round(value, 2) for value in np.arange(0.55, 0.901, 0.05))
FEATURE_NAMES = (
    "leader_return_5m_pct", "leader_return_15m_pct", "leader_return_60m_pct",
    "leader_return_240m_pct", "leader_return_1440m_pct",
    "laggard_return_5m_pct", "laggard_return_15m_pct", "laggard_return_60m_pct",
    "laggard_return_240m_pct", "laggard_return_1440m_pct",
    "cross_section_mean_return_60m_pct", "cross_section_std_return_60m_pct",
    "cross_section_mean_return_240m_pct", "cross_section_std_return_240m_pct",
    "momentum_gap_over_dispersion_60m", "leader_realized_volatility_60m_pct",
    "laggard_realized_volatility_60m_pct", "leader_relative_volume_5m",
    "laggard_relative_volume_5m", "leader_taker_imbalance_5m",
    "laggard_taker_imbalance_5m", "funding_rate_leader_minus_laggard",
)


def _leg_return(entry_long: float, entry_short: float,
                exit_long: float, exit_short: float) -> float:
    return 0.5 * ((exit_long / entry_long - 1.0) - (exit_short / entry_short - 1.0))


def _funding_sum_for(funding: dict[str, tuple[np.ndarray, np.ndarray]], symbol: str,
                     start_ms: int, end_ms: int) -> float:
    times, rates = funding[symbol]
    return common._funding_sum(times, rates, start_ms, end_ms)


def _funding_rate_at(funding: dict[str, tuple[np.ndarray, np.ndarray]],
                     symbol: str, at_ms: int) -> float:
    times, rates = funding[symbol]
    index = int(np.searchsorted(times, at_ms, side="right")) - 1
    return 0.0 if index < 0 else float(rates[index])


def _simulate(long_symbol: str, short_symbol: str, bars_long: np.ndarray,
              bars_short: np.ndarray, signal_index: int,
              funding: dict[str, tuple[np.ndarray, np.ndarray]]) -> dict:
    entry_index = signal_index + 1
    exit_index = entry_index + HOLD_MINUTES
    entry_long = float(bars_long[entry_index]["o"])
    entry_short = float(bars_short[entry_index]["o"])
    entry_ms = int(bars_long[entry_index]["t"])
    path = []
    for current in range(entry_index, exit_index):
        bar_long, bar_short = bars_long[current], bars_short[current]
        adverse_long = float(bar_long["l"])
        adverse_short = float(bar_short["h"])
        mark_gross = _leg_return(entry_long, entry_short, adverse_long, adverse_short)
        mark_ms = int(bar_long["t"]) + 59_999
        mark_funding = 0.5 * (
            _funding_sum_for(funding, short_symbol, entry_ms, mark_ms)
            - _funding_sum_for(funding, long_symbol, entry_ms, mark_ms)
        )
        path.append({
            "timestamp": mark_ms,
            "base_return_pct": 100 * (mark_gross - SIDE_COSTS["base"] + mark_funding),
            "stress_return_pct": 100 * (mark_gross - SIDE_COSTS["stress"] + mark_funding),
        })

    exit_long = float(bars_long[exit_index]["o"])
    exit_short = float(bars_short[exit_index]["o"])
    exit_ms = int(bars_long[exit_index]["t"])
    funding_return = 0.5 * (
        _funding_sum_for(funding, short_symbol, entry_ms, exit_ms)
        - _funding_sum_for(funding, long_symbol, entry_ms, exit_ms)
    )
    gross = _leg_return(entry_long, entry_short, exit_long, exit_short)
    result = {
        "entry_ms": entry_ms, "exit_ms": exit_ms, "entry_index": entry_index,
        "exit_index": exit_index, "entry_price_long": entry_long,
        "entry_price_short": entry_short, "exit_price_long": exit_long,
        "exit_price_short": exit_short, "gross_return_pct": 100 * gross,
        "funding_return_pct": 100 * funding_return,
    }
    for label, side_cost in SIDE_COSTS.items():
        net = 100 * (gross - 2 * side_cost + funding_return)
        result[f"net_return_{label}_pct"] = net
    path.append({"timestamp": exit_ms,
                 "base_return_pct": result["net_return_base_pct"],
                 "stress_return_pct": result["net_return_stress_pct"]})
    result["path"] = path
    return result


def _return(close: np.ndarray, index: int, horizon: int) -> float:
    return math.log(float(close[index]) / float(close[index - horizon]))


def _realized_vol(close: np.ndarray, index: int, horizon: int = 60) -> float:
    values = np.log(close[index - horizon:index + 1].astype(np.float64, copy=False))
    return float(np.std(np.diff(values)))


def _features(index: int, long_symbol: str, short_symbol: str,
              close_by_symbol: dict[str, np.ndarray],
              bars_by_symbol: dict[str, np.ndarray],
              compact_features: dict[str, np.ndarray],
              funding: dict[str, tuple[np.ndarray, np.ndarray]]) -> list[float]:
    horizons = (5, 15, 60, 240, 1440)
    long_returns = [_return(close_by_symbol[long_symbol], index, h) for h in horizons]
    short_returns = [_return(close_by_symbol[short_symbol], index, h) for h in horizons]
    all_returns_60 = [_return(close_by_symbol[s], index, 60) for s in SYMBOLS]
    all_returns_240 = [_return(close_by_symbol[s], index, 240) for s in SYMBOLS]
    dispersion_60 = float(np.std(all_returns_60))
    long_vol = _realized_vol(close_by_symbol[long_symbol], index)
    short_vol = _realized_vol(close_by_symbol[short_symbol], index)
    long_compact = compact_features[long_symbol][index]
    short_compact = compact_features[short_symbol][index]
    funding_ms = int(bars_by_symbol[long_symbol][index]["t"]) + 60_000
    funding_diff = (_funding_rate_at(funding, long_symbol, funding_ms)
                    - _funding_rate_at(funding, short_symbol, funding_ms))
    return [
        *(100 * x for x in long_returns), *(100 * x for x in short_returns),
        100 * float(np.mean(all_returns_60)), 100 * dispersion_60,
        100 * float(np.mean(all_returns_240)), 100 * float(np.std(all_returns_240)),
        (long_returns[2] - short_returns[2]) / max(dispersion_60, 1e-8),
        100 * long_vol, 100 * short_vol,
        float(long_compact[0]), float(short_compact[0]),
        float(long_compact[1]), float(short_compact[1]), funding_diff,
    ]


def _build_events(bars_by_symbol: dict[str, np.ndarray],
                  compact_features: dict[str, np.ndarray],
                  funding: dict[str, tuple[np.ndarray, np.ndarray]]) -> list[dict]:
    close_by_symbol = {
        symbol: bars_by_symbol[symbol]["c"].astype(np.float64, copy=False)
        for symbol in SYMBOLS
    }
    times = bars_by_symbol[SYMBOLS[0]]["t"]
    n = len(times)
    events = []
    start_index = 1440
    stop_index = n - HOLD_MINUTES - 2
    for index in range(start_index, stop_index):
        if (int(times[index]) // 60_000) % SIGNAL_INTERVAL:
            continue
        returns = {symbol: _return(close_by_symbol[symbol], index, MOMENTUM_HORIZON)
                   for symbol in SYMBOLS}
        ordered = sorted(SYMBOLS, key=lambda s: (-returns[s], SYMBOLS.index(s)))
        long_symbol, short_symbol = ordered[0], ordered[-1]
        gap_pct = 100 * (returns[long_symbol] - returns[short_symbol])
        if (returns[long_symbol] <= 0 or returns[short_symbol] >= 0
                or gap_pct < MIN_GAP_PCT):
            continue
        outcome = _simulate(long_symbol, short_symbol,
                            bars_by_symbol[long_symbol], bars_by_symbol[short_symbol],
                            index, funding)
        feature = _features(index, long_symbol, short_symbol, close_by_symbol,
                            bars_by_symbol, compact_features, funding)
        if not np.isfinite(feature).all():
            continue
        events.append({
            "long_symbol": long_symbol, "short_symbol": short_symbol,
            "pair": f"LONG {long_symbol}/SHORT {short_symbol}",
            "signal_index": index, "signal_ms": int(times[index]) + 60_000,
            "momentum_gap_pct": gap_pct, "feature_vector": feature, **outcome,
        })
    return events


def _decluster(events: list[dict]) -> list[dict]:
    selected = []
    next_allowed: dict[str, int] = {}
    for row in sorted(events, key=lambda item: (item["entry_ms"], item["pair"])):
        long_symbol, short_symbol = row["long_symbol"], row["short_symbol"]
        start = row["entry_ms"]
        if start < next_allowed.get(long_symbol, 0) or start < next_allowed.get(short_symbol, 0):
            continue
        selected.append(row)
        until = start + HOLD_MINUTES * 60_000
        next_allowed[long_symbol] = until
        next_allowed[short_symbol] = until
    return selected


def _choose(events: list[dict], threshold: float) -> list[dict]:
    selected = []
    next_allowed: dict[str, int] = {}
    for row in sorted(events, key=lambda item: (item["entry_ms"], item["pair"])):
        if row.get("probability_win", 0.0) < threshold:
            continue
        long_symbol, short_symbol = row["long_symbol"], row["short_symbol"]
        start = row["entry_ms"]
        if start < next_allowed.get(long_symbol, 0) or start < next_allowed.get(short_symbol, 0):
            continue
        selected.append(row)
        until = row["exit_ms"] + COOLDOWN_MS
        next_allowed[long_symbol] = until
        next_allowed[short_symbol] = until
    return selected


def _metrics(trades: list[dict], cost_label: str) -> dict:
    values = [float(row[f"net_return_{cost_label}_pct"]) for row in trades]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    win_rate = len(wins) / len(values) if values else None
    mean_win = math.fsum(wins) / len(wins) if wins else None
    mean_loss = math.fsum(losses) / len(losses) if losses else None
    payoff = mean_win / abs(mean_loss) if mean_win is not None and mean_loss is not None else None
    deltas: dict[int, float] = {}
    for row in trades:
        previous = 0.0
        for point in row["path"]:
            current = float(point[f"{cost_label}_return_pct"])
            timestamp = int(point["timestamp"])
            deltas[timestamp] = deltas.get(timestamp, 0.0) + PAIR_ALLOCATION * (current - previous)
            previous = current
    equity, peak, max_dd = 100.0, 100.0, 0.0
    for timestamp in sorted(deltas):
        equity += deltas[timestamp]
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, 100 * (peak - equity) / peak)
    ev = math.fsum(values) / len(values) if values else None
    checks = {
        "at_least_30_closed_trades": len(values) >= MIN_SCREEN,
        "win_rate_at_least_70_pct": win_rate is not None and win_rate >= 0.70,
        "net_payoff_at_least_1_to_1": payoff is not None and payoff >= 1.0,
        "net_ev_above_1_2_pct": ev is not None and ev > 1.2,
        "max_drawdown_at_most_10_pct": max_dd <= 10.0,
    }
    return {
        "closed_trades": len(values), "wins": len(wins), "losses": len(losses),
        "win_rate_pct": None if win_rate is None else 100 * win_rate,
        "net_payoff_ratio": payoff,
        "ev_net_pct_per_trade_on_combined_gross_notional": ev,
        "portfolio_return_pct_non_compounded_25pct_allocation": equity - 100,
        "max_adverse_drawdown_pct": max_dd, "gate_checks": checks,
        "passes_all_gates": all(checks.values()),
    }


def _period(events: list[dict], name: str) -> list[dict]:
    start, end = common._period_bounds(name)
    return [row for row in events if start <= row["entry_ms"] < end and row["exit_ms"] < end]


def _write_csv(records: list[tuple[str, dict]]) -> None:
    fields = ["period", "pair", "entry_ms", "exit_ms", "momentum_gap_pct",
              "entry_price_long", "entry_price_short", "exit_price_long", "exit_price_short",
              "gross_return_pct", "funding_return_pct", "net_return_base_pct",
              "net_return_stress_pct", "probability_win"]
    with OUTPUT_TRADES.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for label, row in records:
            writer.writerow({"period": label, **{key: row.get(key) for key in fields if key != "period"}})


def run() -> dict:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    bars_by_symbol, funding, archive_manifest, funding_manifest = {}, {}, {}, {}
    for symbol in SYMBOLS:
        bars, bar_rows = common.load_symbol_bars(symbol)
        ft, fr, funding_rows = common.load_funding(symbol)
        bars_by_symbol[symbol] = bars
        funding[symbol] = (ft, fr)
        for row in bar_rows:
            archive_manifest[(symbol, row["month"])] = row
        for row in funding_rows:
            funding_manifest[(symbol, row["month"])] = row
    reference_times = bars_by_symbol[SYMBOLS[0]]["t"]
    if any(not np.array_equal(reference_times, bars_by_symbol[s]["t"]) for s in SYMBOLS[1:]):
        raise ValueError("the four 1m series do not share identical timestamps")
    compact_features = {
        symbol: common.build_features(bars_by_symbol[symbol])[0][:, [3, 1]].astype(np.float32)
        for symbol in SYMBOLS
    }
    print("building 15-minute leader/laggard events", flush=True)
    events = _build_events(bars_by_symbol, compact_features, funding)
    train = _decluster(_period(events, "train"))
    validation = _period(events, "validation")
    confirmation = _period(events, "confirmation")
    static_validation = _choose(validation, 0.0)
    static_confirmation = _choose(confirmation, 0.0)
    source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    protocol_hash = hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()
    report = {
        "schema_version": 1, "series": SERIES,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "decision": "insufficient_training_events", "deployable": False,
        "full_goal_validated": False, "source_sha256": source_hash,
        "protocol_sha256": protocol_hash, "universe": list(SYMBOLS),
        "timeframe": "USD-M Futures 1m; signal every 15m", "first_month": common.FIRST_MONTH,
        "last_month": common.LAST_MONTH, "candidate_events": len(events),
        "training_events_after_asset_aware_declustering": len(train),
        "validation_events": len(validation), "confirmation_events": len(confirmation),
        "feature_names": list(FEATURE_NAMES),
        "model": {"name": "HistGradientBoostingClassifier", "early_stopping": False,
                  "l2_regularization": 10.0, "learning_rate": 0.05, "max_iter": 100,
                  "max_leaf_nodes": 7, "min_samples_leaf": 40, "random_state": 661,
                  "label": "net positive PnL at base cost", "fitted": False},
        "fixed_rule": {"ranking_horizon_minutes": MOMENTUM_HORIZON,
                       "minimum_gap_pct": MIN_GAP_PCT,
                       "leader_positive_and_laggard_negative": True,
                       "signal_interval_minutes": SIGNAL_INTERVAL,
                       "hold_minutes": HOLD_MINUTES,
                       "gross_notional_allocation": PAIR_ALLOCATION,
                       "side_cost_per_order_per_leg": SIDE_COSTS,
                       "round_trip_cost_on_combined_gross_notional": {
                           label: 2 * rate for label, rate in SIDE_COSTS.items()},
                       "funding_included": True, "leverage": 1.0, "live_orders_enabled": False},
        "threshold_candidates": list(THRESHOLDS), "minimum_validation_trades": MIN_CONFIRM,
        "archive_count": len(archive_manifest), "input_archives": list(archive_manifest.values()),
        "funding_archive_count": len(funding_manifest),
        "funding_archives": list(funding_manifest.values()),
        "orders_sent": 0, "jev_calls": 0,
        "unfiltered_signal_diagnostic": {
            "validation": {label: _metrics(static_validation, label) for label in SIDE_COSTS},
            "confirmation_diagnostic": {label: _metrics(static_confirmation, label)
                                        for label in SIDE_COSTS},
        },
    }
    if len(train) < MIN_TRAIN or len({row["net_return_base_pct"] > 0 for row in train}) < 2:
        OUTPUT_JSON.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n",
                               encoding="utf-8")
        _write_csv([("validation", row) for row in static_validation]
                   + [("confirmation_diagnostic", row) for row in static_confirmation])
        return report

    from sklearn.ensemble import HistGradientBoostingClassifier

    x_train = np.asarray([row["feature_vector"] for row in train], dtype=np.float64)
    y_train = np.asarray([row["net_return_base_pct"] > 0 for row in train], dtype=np.int8)
    model = HistGradientBoostingClassifier(
        early_stopping=False, l2_regularization=10.0, learning_rate=0.05,
        max_iter=100, max_leaf_nodes=7, min_samples_leaf=40, random_state=661)
    model.fit(x_train, y_train)
    report["model"]["fitted"] = True
    report["model"]["training_wins"] = int(np.sum(y_train))
    for rows in (validation, confirmation):
        if rows:
            probabilities = model.predict_proba(
                np.asarray([row["feature_vector"] for row in rows], dtype=np.float64))[:, 1]
            for row, probability in zip(rows, probabilities):
                row["probability_win"] = float(probability)

    threshold_results = []
    for threshold in THRESHOLDS:
        selected = _choose(validation, threshold)
        by_cost = {label: _metrics(selected, label) for label in SIDE_COSTS}
        threshold_results.append({
            "threshold": threshold, "trades": len(selected), "by_cost": by_cost,
            "passes_all_gates_both_costs": all(x["passes_all_gates"] for x in by_cost.values()),
        })
    preliminary = [row for row in threshold_results
                   if row["passes_all_gates_both_costs"] and row["trades"] >= MIN_CONFIRM]
    selected_gate = max(
        preliminary,
        key=lambda row: min(x["ev_net_pct_per_trade_on_combined_gross_notional"]
                            for x in row["by_cost"].values()), default=None)
    confirm_report = None
    selected_validation, selected_confirmation = [], []
    if selected_gate is not None:
        threshold = selected_gate["threshold"]
        selected_validation = _choose(validation, threshold)
        selected_confirmation = _choose(confirmation, threshold)
        confirm_metrics = {label: _metrics(selected_confirmation, label) for label in SIDE_COSTS}
        enough = len(selected_confirmation) >= MIN_CONFIRM
        passes = all(x["passes_all_gates"] for x in confirm_metrics.values())
        confirm_report = {"threshold_frozen_from_2025": threshold,
                          "trades": len(selected_confirmation),
                          "at_least_100_trades": enough,
                          "passes_all_gates_both_costs": passes, "by_cost": confirm_metrics}
        report["full_goal_validated"] = enough and passes
    decision = ("validation_gates_passed_confirmation_pending" if selected_gate
                else "no_threshold_passed_validation")
    report.update({"decision": decision, "validation_thresholds": threshold_results,
                   "selected_threshold": None if selected_gate is None else selected_gate["threshold"],
                   "selected_validation": selected_gate, "confirmation": confirm_report,
                   "full_goal_historical_sample_passed": report["full_goal_validated"]})
    OUTPUT_JSON.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n",
                           encoding="utf-8")
    if selected_gate:
        _write_csv([("validation", row) for row in selected_validation]
                   + [("confirmation", row) for row in selected_confirmation])
    else:
        _write_csv([("validation", row) for row in static_validation]
                   + [("confirmation_diagnostic", row) for row in static_confirmation])
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    result = run()
    print(f"{result['decision']}: candidates={result['candidate_events']}; "
          f"train={result['training_events_after_asset_aware_declustering']}; "
          f"validation={result['validation_events']}; confirmation={result['confirmation_events']}; "
          f"threshold={result.get('selected_threshold')}")


if __name__ == "__main__":
    main()
