from __future__ import annotations

import argparse
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

SERIES = "cross_asset_spread_20260927"
PROTOCOL = ROOT / "docs" / "cross_asset_spread_protocol_2026-09-27.md"
OUTPUT_DIR = ROOT / "results" / SERIES
OUTPUT_JSON = OUTPUT_DIR / "research.json"
OUTPUT_STATIC_TRADES = OUTPUT_DIR / "static_signal_trades.csv"
OUTPUT_SELECTED_TRADES = OUTPUT_DIR / "selected_trades.csv"
PAIRS = (("BTCUSDT", "ETHUSDT"), ("BTCUSDT", "BNBUSDT"), ("BTCUSDT", "SOLUSDT"),
         ("ETHUSDT", "BNBUSDT"), ("ETHUSDT", "SOLUSDT"), ("BNBUSDT", "SOLUSDT"))
WINDOW = 1440
ENTRY_Z = 2.5
TARGET_Z = 0.5
STOP_Z = 3.5
MAX_HOLD = 60
COOLDOWN_MS = 30 * 60_000
PAIR_ALLOCATION = 0.25
MIN_TRAIN = 400
MIN_SCREEN = 30
MIN_CONFIRM = 100
THRESHOLDS = tuple(round(value, 2) for value in np.arange(0.55, 0.901, 0.05))
SIDE_COSTS = {"base": 0.0010, "stress": 0.0015}
FEATURE_NAMES = (
    "zscore", "zscore_change_1m", "zscore_change_5m", "zscore_change_15m",
    "spread_change_1m_pct", "spread_change_5m_pct", "spread_change_15m_pct",
    "spread_change_60m_pct", "spread_return_volatility_60m_pct", "spread_sigma_24h_pct",
    "asset_return_correlation_60m", "asset_a_return_5m_pct", "asset_b_return_5m_pct",
    "relative_volume_a", "relative_volume_b", "taker_imbalance_a", "taker_imbalance_b",
    "asset_a_return_60m_pct", "asset_b_return_60m_pct",
)


def _prior_mean_std(values: np.ndarray, window: int) -> tuple[np.ndarray, np.ndarray]:
    values = values.astype(np.float64, copy=False)
    prefix = np.concatenate(([0.0], np.cumsum(values, dtype=np.float64)))
    prefix_sq = np.concatenate(([0.0], np.cumsum(values * values, dtype=np.float64)))
    mean = np.full(len(values), np.nan, dtype=np.float64)
    std = np.full(len(values), np.nan, dtype=np.float64)
    if len(values) <= window:
        return mean, std
    total = prefix[window:len(values)] - prefix[:len(values) - window]
    total_sq = prefix_sq[window:len(values)] - prefix_sq[:len(values) - window]
    mean[window:] = total / window
    variance = np.maximum(0.0, total_sq / window - (total / window) ** 2)
    std[window:] = np.sqrt(variance)
    return mean, std


def _leg_return(direction: int, entry_a: float, entry_b: float,
                exit_a: float, exit_b: float) -> float:
    return 0.5 * (
        direction * (exit_a / entry_a - 1.0)
        - direction * (exit_b / entry_b - 1.0)
    )


def _funding_contribution(direction: int, funding_a: float, funding_b: float) -> float:
    # Equal notional legs: funding is paid by longs and received by shorts.
    return -0.5 * direction * (funding_a - funding_b)


def _funding_pair(funding: dict[str, tuple[np.ndarray, np.ndarray]], asset_a: str,
                  asset_b: str, direction: int, start_ms: int, end_ms: int) -> float:
    times_a, rates_a = funding[asset_a]
    times_b, rates_b = funding[asset_b]
    return _funding_contribution(
        direction,
        common._funding_sum(times_a, rates_a, start_ms, end_ms),
        common._funding_sum(times_b, rates_b, start_ms, end_ms),
    )


def _simulate_spread(asset_a: str, asset_b: str, bars_a: np.ndarray, bars_b: np.ndarray,
                     index: int, direction: int, mean: float, sigma: float,
                     funding: dict[str, tuple[np.ndarray, np.ndarray]]) -> dict | None:
    entry_index = index + 1
    entry_a = float(bars_a[entry_index]["o"])
    entry_b = float(bars_b[entry_index]["o"])
    entry_spread = math.log(entry_a / entry_b)
    entry_z = (entry_spread - mean) / sigma
    target_level = mean + (TARGET_Z * sigma if direction < 0 else -TARGET_Z * sigma)
    stop_level = mean + (STOP_Z * sigma if direction < 0 else -STOP_Z * sigma)

    # Skip a gap that has already reached the target or passed the stop before entry.
    if direction < 0 and not TARGET_Z < entry_z < STOP_Z:
        return None
    if direction > 0 and not -STOP_Z < entry_z < -TARGET_Z:
        return None

    # Observe a threshold at a completed close, then execute at the next open.
    end_index = min(entry_index + MAX_HOLD, len(bars_a) - 1)
    exit_index = end_index
    exit_a = float(bars_a[exit_index]["o"])
    exit_b = float(bars_b[exit_index]["o"])
    exit_spread = math.log(exit_a / exit_b)
    reason = "time"
    path = []
    entry_ms = int(bars_a[entry_index]["t"])

    for current in range(entry_index, end_index):
        bar_a, bar_b = bars_a[current], bars_b[current]
        close_spread = math.log(float(bar_a["c"]) / float(bar_b["c"]))
        adverse_a = float(bar_a["l"] if direction > 0 else bar_a["h"])
        adverse_b = float(bar_b["h"] if direction > 0 else bar_b["l"])
        mark_time = int(bar_a["t"]) + 59_999
        mark_funding = _funding_pair(funding, asset_a, asset_b, direction, entry_ms, mark_time)
        mark_gross = _leg_return(direction, entry_a, entry_b, adverse_a, adverse_b)
        path.append({
            "timestamp": mark_time,
            "base_return_pct": 100 * (mark_gross - SIDE_COSTS["base"] + mark_funding),
            "stress_return_pct": 100 * (mark_gross - SIDE_COSTS["stress"] + mark_funding),
        })
        if direction < 0:
            stop_hit = close_spread >= stop_level
            target_hit = close_spread <= target_level
            if stop_hit:
                exit_index = current + 1
                exit_a = float(bars_a[exit_index]["o"])
                exit_b = float(bars_b[exit_index]["o"])
                exit_spread = math.log(exit_a / exit_b)
                reason = "stop"
                break
            if target_hit:
                exit_index = current + 1
                exit_a = float(bars_a[exit_index]["o"])
                exit_b = float(bars_b[exit_index]["o"])
                exit_spread = math.log(exit_a / exit_b)
                reason = "target"
                break
        else:
            stop_hit = close_spread <= stop_level
            target_hit = close_spread >= target_level
            if stop_hit:
                exit_index = current + 1
                exit_a = float(bars_a[exit_index]["o"])
                exit_b = float(bars_b[exit_index]["o"])
                exit_spread = math.log(exit_a / exit_b)
                reason = "stop"
                break
            if target_hit:
                exit_index = current + 1
                exit_a = float(bars_a[exit_index]["o"])
                exit_b = float(bars_b[exit_index]["o"])
                exit_spread = math.log(exit_a / exit_b)
                reason = "target"
                break

    exit_ms = int(bars_a[exit_index]["t"])
    funding_return = _funding_pair(funding, asset_a, asset_b, direction, entry_ms, exit_ms)
    gross_return = _leg_return(direction, entry_a, entry_b, exit_a, exit_b)
    outcome = {
        "exit_index": int(exit_index), "exit_ms": exit_ms, "exit_spread": exit_spread,
        "entry_price_a": entry_a, "entry_price_b": entry_b,
        "exit_price_a": exit_a, "exit_price_b": exit_b,
        "reason": reason, "gross_return_pct": 100 * gross_return,
        "funding_return_pct": 100 * funding_return,
    }
    for label, side_cost in SIDE_COSTS.items():
        outcome[f"net_return_{label}_pct"] = 100 * (gross_return - 2 * side_cost + funding_return)
    exit_path = {
        "timestamp": exit_ms,
        "base_return_pct": outcome["net_return_base_pct"],
        "stress_return_pct": outcome["net_return_stress_pct"],
    }
    if path and path[-1]["timestamp"] == exit_ms:
        path[-1] = exit_path
    else:
        path.append(exit_path)
    return outcome | {"path": path}


def _build_pair_events(asset_a: str, asset_b: str, bars_a: np.ndarray, bars_b: np.ndarray,
                       features_a: np.ndarray, features_b: np.ndarray,
                       funding: dict[str, tuple[np.ndarray, np.ndarray]]) -> list[dict]:
    close_a = bars_a["c"].astype(np.float64, copy=False)
    close_b = bars_b["c"].astype(np.float64, copy=False)
    spread = np.log(close_a / close_b)
    mean, sigma = _prior_mean_std(spread, WINDOW)
    z = (spread - mean) / sigma
    n = len(spread)
    logret_a = np.zeros(n, dtype=np.float64)
    logret_b = np.zeros(n, dtype=np.float64)
    logret_a[1:] = np.log(close_a[1:] / close_a[:-1])
    logret_b[1:] = np.log(close_b[1:] / close_b[:-1])
    imbalance_a = features_a[:, 0]
    imbalance_b = features_b[:, 0]
    relvol_a = features_a[:, 1]
    relvol_b = features_b[:, 1]
    events = []
    start_index = WINDOW + 60
    end_index = n - MAX_HOLD - 1
    for index in range(start_index, end_index):
        if not (math.isfinite(float(z[index])) and math.isfinite(float(z[index - 1]))
                and sigma[index] > 0 and np.isfinite(features_a[index]).all()
                and np.isfinite(features_b[index]).all()):
            continue
        if z[index] >= ENTRY_Z and z[index - 1] < ENTRY_Z:
            direction = -1
        elif z[index] <= -ENTRY_Z and z[index - 1] > -ENTRY_Z:
            direction = 1
        else:
            continue
        outcome = _simulate_spread(asset_a, asset_b, bars_a, bars_b, index,
                                   direction, float(mean[index]), float(sigma[index]), funding)
        if outcome is None:
            continue
        feature = np.concatenate((
            np.asarray([
                z[index], z[index] - z[index - 1], z[index] - z[index - 5],
                z[index] - z[index - 15], 100 * (spread[index] - spread[index - 1]),
                100 * (spread[index] - spread[index - 5]),
                100 * (spread[index] - spread[index - 15]),
                100 * (spread[index] - spread[index - 60]),
                100 * np.std(np.diff(spread[index - 60:index + 1])), 100 * sigma[index],
                np.corrcoef(logret_a[index - 60:index], logret_b[index - 60:index])[0, 1],
                100 * (close_a[index] / close_a[index - 5] - 1),
                100 * (close_b[index] / close_b[index - 5] - 1),
                relvol_a[index], relvol_b[index], imbalance_a[index], imbalance_b[index],
                100 * (close_a[index] / close_a[index - 60] - 1),
                100 * (close_b[index] / close_b[index - 60] - 1),
            ], dtype=np.float64),
        ))
        if not np.isfinite(feature).all():
            continue
        events.append({
            "asset_a": asset_a, "asset_b": asset_b, "pair": f"{asset_a}/{asset_b}",
            "signal_index": index, "entry_index": index + 1,
            "entry_ms": int(bars_a[index + 1]["t"]),
            "signal_close_ms": int(bars_a[index]["t"]) + 60_000,
            "direction": direction, "entry_spread": math.log(
                float(bars_a[index + 1]["o"]) / float(bars_b[index + 1]["o"])),
            "signal_zscore": float(z[index]), "mean_spread": float(mean[index]),
            "spread_sigma": float(sigma[index]), "target_level": float(
                mean[index] + (TARGET_Z * sigma[index] if direction < 0 else -TARGET_Z * sigma[index])),
            "stop_level": float(
                mean[index] + (STOP_Z * sigma[index] if direction < 0 else -STOP_Z * sigma[index])),
            "feature_vector": feature.tolist(), **outcome,
        })
    return events


def _decluster_training(events: list[dict]) -> list[dict]:
    chosen = []
    next_available: dict[str, int] = {}
    for row in sorted(events, key=lambda item: (item["entry_ms"], item["pair"])):
        start = row["entry_ms"]
        if start < next_available.get(row["asset_a"], 0) or start < next_available.get(row["asset_b"], 0):
            continue
        chosen.append(row)
        until = start + MAX_HOLD * 60_000
        next_available[row["asset_a"]] = until
        next_available[row["asset_b"]] = until
    return chosen


def _choose_trades(events: list[dict], threshold: float) -> list[dict]:
    chosen = []
    next_available: dict[str, int] = {}
    for row in sorted(events, key=lambda item: (item["entry_ms"], item["pair"])):
        if row.get("probability_win", 0.0) < threshold:
            continue
        start = row["entry_ms"]
        if start < next_available.get(row["asset_a"], 0) or start < next_available.get(row["asset_b"], 0):
            continue
        chosen.append(row)
        until = row["exit_ms"] + COOLDOWN_MS
        next_available[row["asset_a"]] = until
        next_available[row["asset_b"]] = until
    return chosen


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
    equity, peak, max_drawdown = 100.0, 100.0, 0.0
    for timestamp in sorted(deltas):
        equity += deltas[timestamp]
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, 100 * (peak - equity) / peak)
    ev = math.fsum(values) / len(values) if values else None
    checks = {
        "at_least_30_closed_trades": len(values) >= MIN_SCREEN,
        "win_rate_at_least_70_pct": win_rate is not None and win_rate >= 0.70,
        "net_payoff_at_least_1_to_1": payoff is not None and payoff >= 1.0,
        "net_ev_above_1_2_pct": ev is not None and ev > 1.2,
        "max_drawdown_at_most_10_pct": max_drawdown <= 10.0,
    }
    return {
        "closed_trades": len(values), "wins": len(wins), "losses": len(losses),
        "win_rate_pct": None if win_rate is None else 100 * win_rate,
        "net_payoff_ratio": payoff,
        "ev_net_pct_per_trade_on_combined_gross_notional": ev,
        "portfolio_return_pct_non_compounded_25pct_spread_allocation": equity - 100,
        "max_adverse_drawdown_pct": max_drawdown,
        "gate_checks": checks, "passes_all_gates": all(checks.values()),
    }


def _score_period(events: list[dict], name: str) -> list[dict]:
    start, end = common._period_bounds(name)
    return [row for row in events if start <= row["entry_ms"] < end and row["exit_ms"] < end]


def _csv(path: Path, records: list[tuple[str, dict]]) -> None:
    import csv

    fields = ["period", "pair", "asset_a", "asset_b", "entry_ms", "exit_ms", "direction",
              "signal_zscore", "entry_spread", "exit_spread", "entry_price_a", "entry_price_b",
              "exit_price_a", "exit_price_b", "target_level", "stop_level",
              "reason", "gross_return_pct", "funding_return_pct", "net_return_base_pct",
              "net_return_stress_pct", "probability_win"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for period, row in records:
            writer.writerow({"period": period, **{key: row.get(key) for key in fields if key != "period"}})


def run(skip_download: bool = False) -> dict:
    del skip_download
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    bars_by_symbol: dict[str, np.ndarray] = {}
    funding_by_symbol: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    funding = {}
    monthly_manifest: dict[tuple[str, str], dict] = {}
    funding_manifest: dict[tuple[str, str], dict] = {}
    for symbol in common.SYMBOLS:
        bars, month_rows = common.load_symbol_bars(symbol)
        ft, fr, funding_rows = common.load_funding(symbol)
        bars_by_symbol[symbol] = bars
        funding_by_symbol[symbol] = (ft, fr)
        funding[symbol] = (ft, fr)
        for row in month_rows:
            monthly_manifest[(symbol, row["month"])] = row
        for row in funding_rows:
            funding_manifest[(symbol, row["month"])] = row
    reference_times = bars_by_symbol[common.SYMBOLS[0]]["t"]
    if any(not np.array_equal(reference_times, bars_by_symbol[symbol]["t"])
           for symbol in common.SYMBOLS[1:]):
        raise ValueError("the four one-minute pair series do not share identical timestamps")

    print("building causal pair features and event trades", flush=True)
    features_by_symbol = {
        symbol: common.build_features(bars_by_symbol[symbol])[0][:, [1, 3]].astype(np.float32)
        for symbol in common.SYMBOLS
    }
    all_events = []
    for asset_a, asset_b in PAIRS:
        rows = _build_pair_events(
            asset_a, asset_b, bars_by_symbol[asset_a], bars_by_symbol[asset_b],
            features_by_symbol[asset_a], features_by_symbol[asset_b], funding)
        all_events.extend(rows)
        print(f"{asset_a}/{asset_b}: events={len(rows)}", flush=True)

    train_events = _decluster_training(_score_period(all_events, "train"))
    validation_events = _score_period(all_events, "validation")
    confirmation_events = _score_period(all_events, "confirmation")
    static_validation = _choose_trades(validation_events, 0.0)
    static_confirmation = _choose_trades(confirmation_events, 0.0)
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
    except ImportError as exc:
        raise RuntimeError("install the project tree-research extra to run the frozen ML model") from exc

    protocol_hash = hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()
    source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report = {
        "schema_version": 1, "series": SERIES,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "decision": "insufficient_training_events", "deployable": False,
        "full_goal_validated": False, "source_sha256": source_hash,
        "protocol_sha256": protocol_hash, "pairs": [f"{a}/{b}" for a, b in PAIRS],
        "timeframe": "USD-M Futures 1m", "first_month": common.FIRST_MONTH,
        "last_month": common.LAST_MONTH,
        "events_by_pair": {f"{a}/{b}": sum(row["pair"] == f"{a}/{b}" for row in all_events)
                            for a, b in PAIRS},
        "training_events_after_asset_aware_60m_declustering": len(train_events),
        "minimum_training_events": MIN_TRAIN,
        "validation_events": len(validation_events),
        "confirmation_events": len(confirmation_events),
        "feature_names": list(FEATURE_NAMES),
        "model": {"name": "HistGradientBoostingClassifier", "early_stopping": False,
                  "l2_regularization": 10.0, "learning_rate": 0.05, "max_iter": 100,
                  "max_leaf_nodes": 7, "min_samples_leaf": 40, "random_state": 548,
                  "label": "positive net PnL at base cost", "fitted": False},
        "target_and_execution": {"entry_z_abs": ENTRY_Z, "target_abs_z": TARGET_Z,
                                  "stop_abs_z": STOP_Z, "rolling_window_minutes": WINDOW,
                                  "max_hold_minutes": MAX_HOLD, "cooldown_minutes_per_asset": 30,
                                  "gross_notional_allocation_per_spread": PAIR_ALLOCATION,
                                  "legs_each_half_notional": True, "leverage": 1.0,
                                  "side_costs_per_leg": SIDE_COSTS,
                                  "combined_round_trip_costs": {
                                      label: 2 * value for label, value in SIDE_COSTS.items()},
                                  "funding_included": True, "stop_first": True,
                                  "live_orders_enabled": False},
        "threshold_candidates": list(THRESHOLDS),
        "validation_sample_minimum": MIN_SCREEN,
        "validation_minimum_trades_for_confirmation": MIN_CONFIRM,
        "archive_count": len(monthly_manifest),
        "input_archives": list(monthly_manifest.values()),
        "funding_archive_count": len(funding_manifest),
        "funding_archives": list(funding_manifest.values()),
        "orders_sent": 0, "jev_calls": 0,
        "unfiltered_signal_diagnostic": {
            "validation": {label: _metrics(static_validation, label) for label in SIDE_COSTS},
            "confirmation_diagnostic": {label: _metrics(static_confirmation, label)
                                        for label in SIDE_COSTS},
        },
    }
    if len(train_events) < MIN_TRAIN or len({row["net_return_base_pct"] > 0 for row in train_events}) < 2:
        report["decision"] = "insufficient_training_events"
        OUTPUT_JSON.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n",
                               encoding="utf-8")
        _csv(OUTPUT_STATIC_TRADES,
             [("validation", row) for row in static_validation]
             + [("confirmation_diagnostic", row) for row in static_confirmation])
        return report

    x_train = np.asarray([row["feature_vector"] for row in train_events], dtype=np.float64)
    y_train = np.asarray([row["net_return_base_pct"] > 0 for row in train_events], dtype=np.int8)
    model = HistGradientBoostingClassifier(
        early_stopping=False, l2_regularization=10.0, learning_rate=0.05,
        max_iter=100, max_leaf_nodes=7, min_samples_leaf=40, random_state=548,
    )
    model.fit(x_train, y_train)
    report["model"]["fitted"] = True
    report["model"]["training_wins"] = int(np.sum(y_train))
    for rows in (validation_events, confirmation_events):
        if rows:
            probabilities = model.predict_proba(
                np.asarray([row["feature_vector"] for row in rows], dtype=np.float64))[:, 1]
            for row, probability in zip(rows, probabilities):
                row["probability_win"] = float(probability)

    validation_thresholds = []
    for threshold in THRESHOLDS:
        selected = _choose_trades(validation_events, threshold)
        by_cost = {label: _metrics(selected, label) for label in SIDE_COSTS}
        validation_thresholds.append({
            "threshold": threshold, "trades": len(selected), "by_cost": by_cost,
            "passes_all_gates_both_costs": all(row["passes_all_gates"] for row in by_cost.values()),
        })
    preliminary = [row for row in validation_thresholds if row["passes_all_gates_both_costs"]]
    eligible = [row for row in preliminary if row["trades"] >= MIN_CONFIRM]
    selected_gate = max(
        eligible,
        key=lambda row: min(metric["ev_net_pct_per_trade_on_combined_gross_notional"]
                            for metric in row["by_cost"].values()), default=None)
    confirmation = None
    selected_validation, selected_confirmation = [], []
    if selected_gate is not None:
        threshold = selected_gate["threshold"]
        selected_validation = _choose_trades(validation_events, threshold)
        selected_confirmation = _choose_trades(confirmation_events, threshold)
        confirm_metrics = {label: _metrics(selected_confirmation, label) for label in SIDE_COSTS}
        passes = all(row["passes_all_gates"] for row in confirm_metrics.values())
        enough = len(selected_confirmation) >= MIN_CONFIRM
        confirmation = {"threshold_frozen_from_2025": threshold,
                        "trades": len(selected_confirmation),
                        "at_least_100_trades": enough,
                        "passes_all_gates_both_costs": passes,
                        "by_cost": confirm_metrics}
        report["full_goal_validated"] = enough and passes
    if selected_gate is not None:
        decision = "validation_gates_passed_confirmation_pending"
    elif preliminary:
        decision = "screen_passed_but_fewer_than_100_validation_trades"
    else:
        decision = "no_threshold_passed_validation"
    report.update({"decision": decision, "validation_thresholds": validation_thresholds,
                   "validation_preliminary_pass_count": len(preliminary),
                   "selected_threshold": None if selected_gate is None else selected_gate["threshold"],
                   "selected_validation": selected_gate, "confirmation": confirmation,
                   "full_goal_historical_sample_passed": report["full_goal_validated"]})
    OUTPUT_JSON.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n",
                           encoding="utf-8")
    if selected_gate is not None:
        _csv(OUTPUT_SELECTED_TRADES,
             [("validation", row) for row in selected_validation]
             + [("confirmation", row) for row in selected_confirmation])
    else:
        _csv(OUTPUT_STATIC_TRADES,
             [("validation", row) for row in static_validation]
             + [("confirmation_diagnostic", row) for row in static_confirmation])
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-download", action="store_true",
                        help="reuse local checksum-verified archives")
    report = run(skip_download=parser.parse_args().skip_download)
    print(f"{report['decision']}: train={report['training_events_after_asset_aware_60m_declustering']}; "
          f"validation={report['validation_events']}; confirmation={report['confirmation_events']}; "
          f"threshold={report.get('selected_threshold')}")


if __name__ == "__main__":
    main()
