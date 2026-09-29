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

SERIES = "minute_ml_buy_idle_sell_20260927"
PROTOCOL = ROOT / "docs" / "minute_ml_buy_idle_sell_protocol_2026-09-27.md"
OUTPUT_DIR = ROOT / "results" / SERIES
OUTPUT_JSON = OUTPUT_DIR / "research.json"
OUTPUT_TRADES = OUTPUT_DIR / "selected_trades.csv"
STOP_DISTANCE = 0.015
TARGET_R = 1.9
MIN_TRAINING_EVENTS = 400
MIN_VALIDATION_TRADES = 100
THRESHOLDS = tuple(round(value, 2) for value in np.arange(0.55, 0.901, 0.05))
SYMBOL_OFFSETS = {"BTCUSDT": 0, "ETHUSDT": 15, "BNBUSDT": 30, "SOLUSDT": 45}
EXTRA_FEATURE_NAMES = ("rsi14_wilder", "macd_hist_pct", "ema200_distance_pct", "fib_position_240m")
LABEL_NAMES = {0: "IDLE", 1: "LONG", 2: "SHORT"}


def _ema(values: np.ndarray, span: int) -> np.ndarray:
    out = np.empty(len(values), dtype=np.float64)
    out[0] = values[0]
    alpha = 2.0 / (span + 1.0)
    for index in range(1, len(values)):
        out[index] = alpha * values[index] + (1.0 - alpha) * out[index - 1]
    return out


def _rsi_wilder(close: np.ndarray, period: int = 14) -> np.ndarray:
    delta = np.diff(close, prepend=close[0])
    gains, losses = np.maximum(delta, 0.0), np.maximum(-delta, 0.0)
    avg_gain = np.full(len(close), np.nan, dtype=np.float64)
    avg_loss = np.full(len(close), np.nan, dtype=np.float64)
    if len(close) <= period:
        return avg_gain
    avg_gain[period] = float(np.mean(gains[1:period + 1]))
    avg_loss[period] = float(np.mean(losses[1:period + 1]))
    for index in range(period + 1, len(close)):
        avg_gain[index] = ((period - 1) * avg_gain[index - 1] + gains[index]) / period
        avg_loss[index] = ((period - 1) * avg_loss[index - 1] + losses[index]) / period
    ratio = np.divide(avg_gain, avg_loss, out=np.full(len(close), np.inf), where=avg_loss > 0)
    rsi = 100.0 - 100.0 / (1.0 + ratio)
    rsi[(avg_loss == 0) & (avg_gain > 0)] = 100.0
    rsi[(avg_loss == 0) & (avg_gain == 0)] = 50.0
    return rsi


def build_features(bars: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    base_features, _ = common.build_features(bars)
    close = bars["c"].astype(np.float64, copy=False)
    high = bars["h"].astype(np.float64, copy=False)
    low = bars["l"].astype(np.float64, copy=False)
    ema200 = _ema(close, 200)
    rsi14 = _rsi_wilder(close)
    macd = _ema(close, 12) - _ema(close, 26)
    macd_hist = macd - _ema(macd, 9)
    high240 = common._rolling_extreme(high, 240, True)
    low240 = common._rolling_extreme(low, 240, False)
    fib_width = high240 - low240
    fib_position = np.divide(close - low240, fib_width,
                             out=np.full(len(close), np.nan), where=fib_width > 0)
    extra = np.column_stack((rsi14,
                             np.divide(macd_hist, close,
                                       out=np.full(len(close), np.nan), where=close > 0),
                             ema200 / close - 1.0,
                             fib_position))
    return np.column_stack((base_features, extra)), extra


def _training_sample(symbol: str, bars: np.ndarray, features: np.ndarray,
                     funding_times: np.ndarray, funding_rates: np.ndarray) -> tuple[list[np.ndarray], list[int], dict[str, int]]:
    train_start, train_end = common._period_bounds("train")
    indices = np.flatnonzero(
        (bars["t"] >= train_start)
        & (bars["t"] + 60_000 < train_end)
        & ((bars["t"] // 60_000) % 60 == SYMBOL_OFFSETS[symbol])
    )
    x_rows: list[np.ndarray] = []
    labels: list[int] = []
    class_counts = {name: 0 for name in LABEL_NAMES.values()}
    end_limit = len(bars) - common.MAX_HOLD_MINUTES - 1
    for index_value in indices:
        index = int(index_value)
        if index < 500 or index >= end_limit or not np.isfinite(features[index]).all():
            continue
        entry_index = index + 1
        entry = float(bars[entry_index]["o"])
        long_stop = entry * (1.0 - STOP_DISTANCE)
        short_stop = entry * (1.0 + STOP_DISTANCE)
        long_target = entry + (entry - long_stop) * TARGET_R
        short_target = entry - (short_stop - entry) * TARGET_R
        long_result = common._simulate_trade(
            bars, entry_index, 1, long_stop, long_target, funding_times, funding_rates)
        short_result = common._simulate_trade(
            bars, entry_index, -1, short_stop, short_target, funding_times, funding_rates)
        if long_result["exit_ms"] >= train_end or short_result["exit_ms"] >= train_end:
            continue
        long_pnl = float(long_result["net_return_base_pct"])
        short_pnl = float(short_result["net_return_base_pct"])
        if long_pnl > 0 and long_pnl >= short_pnl + 0.05:
            label = 1
        elif short_pnl > 0 and short_pnl >= long_pnl + 0.05:
            label = 2
        else:
            label = 0
        x_rows.append(features[index].copy())
        labels.append(label)
        class_counts[LABEL_NAMES[label]] += 1
    return x_rows, labels, class_counts


def _predicted_trade_events(symbol: str, bars: np.ndarray, features: np.ndarray,
                            funding_times: np.ndarray, funding_rates: np.ndarray,
                            model, period: str) -> list[dict]:
    period_start, period_end = common._period_bounds(period)
    end_limit = len(bars) - common.MAX_HOLD_MINUTES - 1
    indices = np.flatnonzero((bars["t"] >= period_start) & (bars["t"] + 60_000 < period_end))
    indices = indices[(indices >= 500) & (indices < end_limit)]
    indices = indices[np.isfinite(features[indices]).all(axis=1)]
    records = []
    classes = list(int(value) for value in model.classes_)
    class_column = {label: classes.index(label) for label in classes}
    batch_size = 50_000
    for start in range(0, len(indices), batch_size):
        batch_indices = indices[start:start + batch_size]
        probabilities = model.predict_proba(features[batch_indices])
        for index_value, probability_row in zip(batch_indices, probabilities):
            index = int(index_value)
            p_long = float(probability_row[class_column[1]]) if 1 in class_column else 0.0
            p_short = float(probability_row[class_column[2]]) if 2 in class_column else 0.0
            if max(p_long, p_short) < min(THRESHOLDS):
                continue
            direction = 1 if p_long > p_short else -1
            probability = p_long if direction > 0 else p_short
            entry_index = index + 1
            entry = float(bars[entry_index]["o"])
            risk = STOP_DISTANCE * entry
            stop = entry - risk if direction > 0 else entry + risk
            target = entry + direction * TARGET_R * risk
            outcome = common._simulate_trade(
                bars, entry_index, direction, stop, target, funding_times, funding_rates)
            if outcome["exit_ms"] >= period_end:
                continue
            records.append({
                "symbol": symbol,
                "signal_index": index,
                "entry_index": entry_index,
                "signal_close_ms": int(bars[index]["t"]) + 60_000,
                "entry_ms": int(bars[entry_index]["t"]),
                "direction": direction,
                "entry_price": entry,
                "stop_price": stop,
                "target_price": target,
                "stop_distance_pct": 100 * STOP_DISTANCE,
                "probability_win": probability,
                "probability_idle": float(probability_row[class_column[0]]) if 0 in class_column else 0.0,
                "probability_long": p_long,
                "probability_short": p_short,
                "funding_times": funding_times,
                "funding_rates": funding_rates,
                **outcome,
            })
    return records


def _metrics(trades: list[dict], bars_by_symbol: dict[str, np.ndarray]) -> dict:
    return {label: common._metrics(trades, bars_by_symbol, label)
            for label in common.SIDE_COSTS}


def run(skip_download: bool = False) -> dict:
    del skip_download  # Input archives are cached and checksum-verified by the shared loader.
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    bars_by_symbol: dict[str, np.ndarray] = {}
    funding_by_symbol: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    input_manifest = []
    funding_manifest = []
    train_x: list[np.ndarray] = []
    train_y: list[int] = []
    train_classes = {name: 0 for name in LABEL_NAMES.values()}
    validation_rows: list[dict] = []
    confirmation_rows: list[dict] = []

    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
    except ImportError as exc:
        raise RuntimeError("install the project tree-research extra to run the frozen ML model") from exc

    for symbol in common.SYMBOLS:
        print(f"loading and labeling {symbol}", flush=True)
        bars, month_manifest = common.load_symbol_bars(symbol)
        funding_times, funding_rates, funding_rows = common.load_funding(symbol)
        bars_by_symbol[symbol] = bars
        funding_by_symbol[symbol] = (funding_times, funding_rates)
        input_manifest.extend(month_manifest)
        funding_manifest.extend(funding_rows)
        features, _ = build_features(bars)
        x_rows, labels, class_counts = _training_sample(
            symbol, bars, features, funding_times, funding_rates)
        train_x.extend(x_rows)
        train_y.extend(labels)
        for name, value in class_counts.items():
            train_classes[name] += value
        print(f"{symbol}: bars={len(bars)} train_labels={len(labels)} classes={class_counts}", flush=True)
        del features

    protocol_hash = hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()
    source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report = {
        "schema_version": 1,
        "series": SERIES,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "decision": "insufficient_training_events",
        "deployable": False,
        "full_goal_validated": False,
        "protocol_sha256": protocol_hash,
        "source_sha256": source_hash,
        "universe": list(common.SYMBOLS),
        "timeframe": "USD-M Futures 1m klines; model scored every minute",
        "first_month": common.FIRST_MONTH,
        "last_month": common.LAST_MONTH,
        "bars_per_symbol": {symbol: len(bars) for symbol, bars in bars_by_symbol.items()},
        "funding_points_per_symbol": {symbol: len(values[0])
                                       for symbol, values in funding_by_symbol.items()},
        "training_events_one_per_hour_after_offset_sampling": len(train_y),
        "minimum_training_events": MIN_TRAINING_EVENTS,
        "training_class_counts": train_classes,
        "feature_names": list(common.FEATURE_NAMES) + list(EXTRA_FEATURE_NAMES),
        "model": {"name": "HistGradientBoostingClassifier", "early_stopping": False,
                  "l2_regularization": 10.0, "learning_rate": 0.05, "max_iter": 100,
                  "max_leaf_nodes": 7, "min_samples_leaf": 40, "random_state": 548,
                  "classes": LABEL_NAMES, "fitted": False},
        "target_and_execution": {"stop_distance_pct": 100 * STOP_DISTANCE,
                                  "target_R_gross": TARGET_R,
                                  "max_hold_minutes": common.MAX_HOLD_MINUTES,
                                  "cooldown_minutes_after_exit": common.COOLDOWN_MINUTES,
                                  "side_costs_including_taker_and_slippage": common.SIDE_COSTS,
                                  "committed_notional_basis": "net operation PnL divided by entry notional",
                                  "allocation_per_pair": 0.25, "leverage": 1.0,
                                  "funding_included": True, "same_bar_stop_target_order": "stop first",
                                  "live_orders_enabled": False},
        "threshold_candidates": list(THRESHOLDS),
        "validation_sample_minimum": common.MIN_SCREEN_TRADES,
        "validation_minimum_trades_for_confirmation": MIN_VALIDATION_TRADES,
        "archive_count": len(input_manifest), "input_archives": input_manifest,
        "funding_archive_count": len(funding_manifest), "funding_archives": funding_manifest,
        "orders_sent": 0, "jev_calls": 0,
    }

    if len(train_y) < MIN_TRAINING_EVENTS or len(set(train_y)) < 3:
        report["decision"] = "insufficient_training_events_or_classes"
        OUTPUT_JSON.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n",
                               encoding="utf-8")
        return report

    x_train = np.asarray(train_x, dtype=np.float64)
    y_train = np.asarray(train_y, dtype=np.int8)
    model = HistGradientBoostingClassifier(
        early_stopping=False, l2_regularization=10.0, learning_rate=0.05,
        max_iter=100, max_leaf_nodes=7, min_samples_leaf=40, random_state=548,
    )
    model.fit(x_train, y_train)
    report["model"]["fitted"] = True
    report["model"]["classes_fitted"] = [int(value) for value in model.classes_]

    # Build validation and confirmation scores only after the 2024 model is frozen.
    for symbol in common.SYMBOLS:
        bars = bars_by_symbol[symbol]
        funding_times, funding_rates = funding_by_symbol[symbol]
        features, _ = build_features(bars)
        validation_rows.extend(_predicted_trade_events(
            symbol, bars, features, funding_times, funding_rates, model, "validation"))
        confirmation_rows.extend(_predicted_trade_events(
            symbol, bars, features, funding_times, funding_rates, model, "confirmation"))
        del features

    def choose(records: list[dict], threshold: float) -> list[dict]:
        return common._choose_trades(records, threshold)

    validation_gates = []
    for threshold in THRESHOLDS:
        selected = choose(validation_rows, threshold)
        by_cost = _metrics(selected, bars_by_symbol)
        validation_gates.append({"threshold": threshold, "trades": len(selected),
                                 "by_cost": by_cost,
                                 "passes_all_gates_both_costs": all(
                                     metric["passes_all_gates"] for metric in by_cost.values())})
    preliminary = [row for row in validation_gates if row["passes_all_gates_both_costs"]]
    eligible = [row for row in preliminary if row["trades"] >= MIN_VALIDATION_TRADES]
    selected_gate = max(
        eligible,
        key=lambda row: min(metric["ev_net_pct_per_trade_on_committed_notional"]
                            for metric in row["by_cost"].values()),
        default=None,
    )
    confirmation = None
    selected_validation: list[dict] = []
    selected_confirmation: list[dict] = []
    if selected_gate is not None:
        threshold = selected_gate["threshold"]
        selected_validation = choose(validation_rows, threshold)
        selected_confirmation = choose(confirmation_rows, threshold)
        confirm_metrics = _metrics(selected_confirmation, bars_by_symbol)
        passes = all(value["passes_all_gates"] for value in confirm_metrics.values())
        enough = len(selected_confirmation) >= MIN_VALIDATION_TRADES
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
    report.update({"decision": decision, "validation_events_scored_at_minimum_threshold": len(validation_rows),
                   "confirmation_events_scored_at_minimum_threshold": len(confirmation_rows),
                   "validation_thresholds": validation_gates,
                   "validation_preliminary_pass_count": len(preliminary),
                   "selected_threshold": None if selected_gate is None else selected_gate["threshold"],
                   "selected_validation": selected_gate, "confirmation": confirmation,
                   "full_goal_historical_sample_passed": report["full_goal_validated"]})
    OUTPUT_JSON.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n",
                           encoding="utf-8")
    if selected_gate is not None:
        common._write_trade_csv(OUTPUT_TRADES,
                                [("validation", row) for row in selected_validation]
                                + [("confirmation", row) for row in selected_confirmation])
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-download", action="store_true",
                        help="require and verify all cached archives")
    args = parser.parse_args()
    report = run(skip_download=args.skip_download)
    print(f"{report['decision']}: train={report['training_events_one_per_hour_after_offset_sampling']}; "
          f"selected_threshold={report.get('selected_threshold')}")


if __name__ == "__main__":
    main()
