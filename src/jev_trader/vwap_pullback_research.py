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

SERIES = "vwap_pullback_20260927"
PROTOCOL = ROOT / "docs" / "vwap_pullback_protocol_2026-09-27.md"
OUTPUT_DIR = ROOT / "results" / SERIES
OUTPUT_JSON = OUTPUT_DIR / "research.json"
OUTPUT_CSV = OUTPUT_DIR / "signal_trades.csv"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
VWAP_WINDOW = 60
VOLUME_WINDOW = 5
VOLUME_MEDIAN_WINDOW = 144
MIN_VOLUME_MULTIPLE = 1.5
STOP_ATR = 1.0
TARGET_ATR = 1.5
MAX_HOLD = 60
COOLDOWN_MS = 30 * 60_000
ALLOCATION = 0.25
SIDE_COSTS = {"base": 0.0010, "stress": 0.0015}
MIN_TRAIN = 400
MIN_SCREEN = 30
MIN_CONFIRM = 100
THRESHOLDS = tuple(round(value, 2) for value in np.arange(0.55, 0.901, 0.05))
FEATURE_NAMES = (
    "ema200_15m_distance_pct", "ema200_15m_slope_60m_pct", "vwap_60m_distance_pct",
    "relative_quote_volume_5m", "taker_imbalance_5m", "atr14_pct",
    "realized_volatility_60m_pct", "return_5m_pct", "return_15m_pct",
    "return_60m_pct", "rsi14",
)


def _ema(values: np.ndarray, span: int) -> np.ndarray:
    result = np.full(len(values), np.nan, dtype=np.float64)
    if len(values) == 0:
        return result
    alpha = 2.0 / (span + 1.0)
    result[0] = values[0]
    for index in range(1, len(values)):
        result[index] = alpha * values[index] + (1.0 - alpha) * result[index - 1]
    return result


def _rsi(close: np.ndarray, index: int, period: int = 14) -> float:
    changes = np.diff(close[index - period:index + 1].astype(np.float64, copy=False))
    gains = np.maximum(changes, 0.0)
    losses = np.maximum(-changes, 0.0)
    average_gain = float(np.mean(gains))
    average_loss = float(np.mean(losses))
    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + average_gain / average_loss)


def _indicators(bars: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    close = bars["c"].astype(np.float64, copy=False)
    quote_volume = bars["qv"].astype(np.float64, copy=False)
    base_volume = np.divide(quote_volume, close, out=np.zeros(len(close)), where=close > 0)
    prefix_quote = np.concatenate(([0.0], np.cumsum(quote_volume, dtype=np.float64)))
    prefix_base = np.concatenate(([0.0], np.cumsum(base_volume, dtype=np.float64)))
    vwap = np.full(len(close), np.nan, dtype=np.float64)
    start = np.arange(VWAP_WINDOW - 1, len(close)) - VWAP_WINDOW + 1
    end = np.arange(VWAP_WINDOW, len(close) + 1)
    qsum = prefix_quote[end] - prefix_quote[start]
    bsum = prefix_base[end] - prefix_base[start]
    vwap[VWAP_WINDOW - 1:] = np.divide(qsum, bsum, out=np.full(len(qsum), np.nan), where=bsum > 0)

    features, parts = common.build_features(bars)
    compact = np.column_stack((features[:, 3], features[:, 1], features[:, 13], parts["atr14"]))
    times = bars["t"]
    close15_indices = np.flatnonzero((times + 60_000) % 900_000 == 0)
    ema15 = _ema(close[close15_indices], 200)
    ema_position = np.searchsorted(close15_indices, np.arange(len(close)), side="right") - 1
    ema_at_index = np.full(len(close), np.nan, dtype=np.float64)
    slope_at_index = np.full(len(close), np.nan, dtype=np.float64)
    valid = ema_position >= 4
    positions = ema_position[valid]
    ema_at_index[valid] = ema15[positions]
    slope_at_index[valid] = 100 * (ema15[positions] / ema15[positions - 4] - 1.0)
    return vwap, compact, ema_at_index, slope_at_index


def _funding_return(funding: dict[str, tuple[np.ndarray, np.ndarray]], symbol: str,
                    direction: int, start_ms: int, end_ms: int) -> float:
    times, rates = funding[symbol]
    return -direction * common._funding_sum(times, rates, start_ms, end_ms)


def _simulate(symbol: str, bars: np.ndarray, index: int, direction: int,
              atr: float, funding: dict[str, tuple[np.ndarray, np.ndarray]]) -> dict | None:
    entry_index = index + 1
    entry = float(bars[entry_index]["o"])
    risk = STOP_ATR * atr
    target_risk = TARGET_ATR * atr
    if risk <= 0:
        return None
    if direction > 0:
        stop, target = entry - risk, entry + target_risk
        if entry <= stop or entry >= target:
            return None
    else:
        stop, target = entry + risk, entry - target_risk
        if entry >= stop or entry <= target:
            return None

    end_index = min(entry_index + MAX_HOLD, len(bars) - 1)
    exit_index = end_index
    exit_price = float(bars[exit_index]["o"])
    reason = "time"
    entry_ms = int(bars[entry_index]["t"])
    path = []
    for current in range(entry_index, end_index):
        bar = bars[current]
        open_price, high, low = float(bar["o"]), float(bar["h"]), float(bar["l"])
        adverse_price = low if direction > 0 else high
        mark_gross = direction * (adverse_price / entry - 1.0)
        mark_time = int(bar["t"]) + 59_999
        mark_funding = _funding_return(funding, symbol, direction, entry_ms, mark_time)
        path.append({
            "timestamp": mark_time,
            "base_return_pct": 100 * (mark_gross - SIDE_COSTS["base"] + mark_funding),
            "stress_return_pct": 100 * (mark_gross - SIDE_COSTS["stress"] + mark_funding),
        })
        stop_hit = low <= stop if direction > 0 else high >= stop
        target_hit = high >= target if direction > 0 else low <= target
        if stop_hit:
            exit_index = current + 1
            next_open = float(bars[exit_index]["o"])
            exit_price = next_open if (next_open < stop if direction > 0 else next_open > stop) else stop
            reason = "stop"
            break
        if target_hit:
            exit_index = current + 1
            next_open = float(bars[exit_index]["o"])
            exit_price = next_open if (next_open > target if direction > 0 else next_open < target) else target
            reason = "target"
            break

    exit_ms = int(bars[exit_index]["t"])
    gross = direction * (exit_price / entry - 1.0)
    funding_pnl = _funding_return(funding, symbol, direction, entry_ms, exit_ms)
    result = {
        "symbol": symbol, "direction": direction, "entry_ms": entry_ms,
        "exit_ms": exit_ms, "entry_index": entry_index, "exit_index": exit_index,
        "entry_price": entry, "exit_price": exit_price, "stop_price": stop,
        "target_price": target, "reason": reason, "gross_return_pct": 100 * gross,
        "funding_return_pct": 100 * funding_pnl,
    }
    for label, side_cost in SIDE_COSTS.items():
        result[f"net_return_{label}_pct"] = 100 * (gross - 2 * side_cost + funding_pnl)
    path.append({"timestamp": exit_ms,
                 "base_return_pct": result["net_return_base_pct"],
                 "stress_return_pct": result["net_return_stress_pct"]})
    result["path"] = path
    return result


def _event_features(index: int, direction: int, close: np.ndarray, vwap: np.ndarray,
                    compact: np.ndarray, ema: np.ndarray, ema_slope: np.ndarray) -> list[float]:
    ret = lambda horizon: 100 * (close[index] / close[index - horizon] - 1.0)
    return [
        100 * (close[index] / ema[index] - 1.0), direction * ema_slope[index],
        direction * 100 * (close[index] / vwap[index] - 1.0),
        compact[index, 0], direction * compact[index, 1],
        100 * compact[index, 3] / close[index], 100 * compact[index, 2],
        direction * ret(5), direction * ret(15), direction * ret(60), _rsi(close, index),
    ]


def _build_events(bars_by_symbol: dict[str, np.ndarray], indicators: dict[str, tuple],
                  funding: dict[str, tuple[np.ndarray, np.ndarray]]) -> list[dict]:
    events = []
    for symbol in SYMBOLS:
        bars = bars_by_symbol[symbol]
        close = bars["c"].astype(np.float64, copy=False)
        vwap, compact, ema, ema_slope = indicators[symbol]
        stop_index = len(bars) - MAX_HOLD - 2
        start_index = 5 * 200 * 15 + 1440
        for index in range(start_index, stop_index):
            if not (np.isfinite(vwap[index]) and np.isfinite(vwap[index - 1])
                    and np.isfinite(ema[index]) and np.isfinite(ema_slope[index])
                    and np.isfinite(compact[index]).all()):
                continue
            long_signal = (close[index] > vwap[index] and close[index - 1] <= vwap[index - 1]
                           and close[index] > ema[index] and ema_slope[index] > 0
                           and compact[index, 0] >= MIN_VOLUME_MULTIPLE)
            short_signal = (close[index] < vwap[index] and close[index - 1] >= vwap[index - 1]
                            and close[index] < ema[index] and ema_slope[index] < 0
                            and compact[index, 0] >= MIN_VOLUME_MULTIPLE)
            if not (long_signal or short_signal):
                continue
            direction = 1 if long_signal else -1
            trade = _simulate(symbol, bars, index, direction,
                              float(compact[index, 3]), funding)
            if trade is None:
                continue
            feature = _event_features(index, direction, close, vwap, compact,
                                      ema, ema_slope)
            if not np.isfinite(feature).all():
                continue
            events.append({"signal_index": index, "signal_ms": int(bars[index]["t"]) + 60_000,
                           "feature_vector": feature, **trade})
    return events


def _decluster(events: list[dict]) -> list[dict]:
    chosen, next_allowed = [], {}
    for row in sorted(events, key=lambda item: (item["symbol"], item["entry_ms"])):
        if row["entry_ms"] >= next_allowed.get(row["symbol"], 0):
            chosen.append(row)
            next_allowed[row["symbol"]] = row["entry_ms"] + MAX_HOLD * 60_000
    return sorted(chosen, key=lambda item: (item["entry_ms"], item["symbol"]))


def _choose(events: list[dict], threshold: float) -> list[dict]:
    chosen, next_allowed = [], {}
    for row in sorted(events, key=lambda item: (item["entry_ms"], item["symbol"])):
        if row.get("probability_win", 0.0) < threshold:
            continue
        if row["entry_ms"] < next_allowed.get(row["symbol"], 0):
            continue
        chosen.append(row)
        next_allowed[row["symbol"]] = row["exit_ms"] + COOLDOWN_MS
    return chosen


def _metrics(trades: list[dict], cost_label: str) -> dict:
    values = [float(row[f"net_return_{cost_label}_pct"]) for row in trades]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    win_rate = len(wins) / len(values) if values else None
    mean_win = math.fsum(wins) / len(wins) if wins else None
    mean_loss = math.fsum(losses) / len(losses) if losses else None
    payoff = mean_win / abs(mean_loss) if mean_win is not None and mean_loss is not None else None
    deltas = {}
    for row in trades:
        previous = 0.0
        for point in row["path"]:
            timestamp = int(point["timestamp"])
            current = float(point[f"{cost_label}_return_pct"])
            deltas[timestamp] = deltas.get(timestamp, 0.0) + ALLOCATION * (current - previous)
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
    return {"closed_trades": len(values), "wins": len(wins), "losses": len(losses),
            "win_rate_pct": None if win_rate is None else 100 * win_rate,
            "net_payoff_ratio": payoff,
            "ev_net_pct_per_trade_on_committed_notional": ev,
            "portfolio_return_pct_non_compounded_25pct_allocation": equity - 100,
            "max_adverse_drawdown_pct": max_dd, "gate_checks": checks,
            "passes_all_gates": all(checks.values())}


def _period(events: list[dict], name: str) -> list[dict]:
    start, end = common._period_bounds(name)
    return [row for row in events if start <= row["entry_ms"] < end and row["exit_ms"] < end]


def _write_trades(records: list[tuple[str, dict]]) -> None:
    fields = ["period", "symbol", "entry_ms", "exit_ms", "direction", "entry_price",
              "stop_price", "target_price", "exit_price", "reason", "gross_return_pct",
              "funding_return_pct", "net_return_base_pct", "net_return_stress_pct",
              "probability_win"]
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for label, row in records:
            writer.writerow({"period": label, **{key: row.get(key) for key in fields if key != "period"}})


def run() -> dict:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    bars_by_symbol, indicators, funding = {}, {}, {}
    bar_manifest, funding_manifest = {}, {}
    for symbol in SYMBOLS:
        bars, bar_rows = common.load_symbol_bars(symbol)
        ft, fr, funding_rows = common.load_funding(symbol)
        bars_by_symbol[symbol] = bars
        funding[symbol] = (ft, fr)
        indicators[symbol] = _indicators(bars)
        for row in bar_rows:
            bar_manifest[(symbol, row["month"])] = row
        for row in funding_rows:
            funding_manifest[(symbol, row["month"])] = row
    reference_times = bars_by_symbol[SYMBOLS[0]]["t"]
    if any(not np.array_equal(reference_times, bars_by_symbol[s]["t"]) for s in SYMBOLS[1:]):
        raise ValueError("the four one-minute series do not share identical timestamps")
    print("building VWAP reclaim events", flush=True)
    events = _build_events(bars_by_symbol, indicators, funding)
    train = _decluster(_period(events, "train"))
    validation, confirmation = _period(events, "validation"), _period(events, "confirmation")
    static_validation, static_confirmation = _choose(validation, 0.0), _choose(confirmation, 0.0)
    report = {
        "schema_version": 1, "series": SERIES,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "decision": "insufficient_training_events", "deployable": False,
        "full_goal_validated": False,
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        "universe": list(SYMBOLS), "timeframe": "USD-M Futures 1m; trend 15m",
        "first_month": common.FIRST_MONTH, "last_month": common.LAST_MONTH,
        "candidate_events": len(events), "training_events_after_symbol_60m_declustering": len(train),
        "validation_events": len(validation), "confirmation_events": len(confirmation),
        "feature_names": list(FEATURE_NAMES),
        "model": {"name": "HistGradientBoostingClassifier", "early_stopping": False,
                  "l2_regularization": 10.0, "learning_rate": 0.05, "max_iter": 100,
                  "max_leaf_nodes": 7, "min_samples_leaf": 40, "random_state": 773,
                  "label": "net positive PnL at base cost", "fitted": False},
        "fixed_rule": {"vwap_window_minutes": VWAP_WINDOW, "ema_trend": "15m EMA200 with 4-bar slope",
                       "volume_multiple_minimum": MIN_VOLUME_MULTIPLE,
                       "stop_atr": STOP_ATR, "target_atr": TARGET_ATR,
                       "max_hold_minutes": MAX_HOLD, "cooldown_minutes": 30,
                       "gross_notional_allocation": ALLOCATION, "side_costs_per_order": SIDE_COSTS,
                       "funding_included": True, "leverage": 1.0,
                       "same_bar_stop_target_order": "stop first", "live_orders_enabled": False},
        "threshold_candidates": list(THRESHOLDS), "minimum_validation_trades": MIN_CONFIRM,
        "archive_count": len(bar_manifest), "input_archives": list(bar_manifest.values()),
        "funding_archive_count": len(funding_manifest),
        "funding_archives": list(funding_manifest.values()), "orders_sent": 0, "jev_calls": 0,
        "unfiltered_signal_diagnostic": {
            "validation": {label: _metrics(static_validation, label) for label in SIDE_COSTS},
            "confirmation_diagnostic": {label: _metrics(static_confirmation, label)
                                        for label in SIDE_COSTS},
        },
    }
    if len(train) < MIN_TRAIN or len({row["net_return_base_pct"] > 0 for row in train}) < 2:
        OUTPUT_JSON.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n",
                               encoding="utf-8")
        _write_trades([("validation", row) for row in static_validation]
                      + [("confirmation_diagnostic", row) for row in static_confirmation])
        return report

    from sklearn.ensemble import HistGradientBoostingClassifier

    x_train = np.asarray([row["feature_vector"] for row in train], dtype=np.float64)
    y_train = np.asarray([row["net_return_base_pct"] > 0 for row in train], dtype=np.int8)
    model = HistGradientBoostingClassifier(
        early_stopping=False, l2_regularization=10.0, learning_rate=0.05,
        max_iter=100, max_leaf_nodes=7, min_samples_leaf=40, random_state=773)
    model.fit(x_train, y_train)
    report["model"]["fitted"] = True
    report["model"]["training_wins"] = int(np.sum(y_train))
    for rows in (validation, confirmation):
        if rows:
            p = model.predict_proba(np.asarray([row["feature_vector"] for row in rows]))[:, 1]
            for row, probability in zip(rows, p):
                row["probability_win"] = float(probability)

    threshold_results = []
    for threshold in THRESHOLDS:
        selected = _choose(validation, threshold)
        by_cost = {label: _metrics(selected, label) for label in SIDE_COSTS}
        threshold_results.append({"threshold": threshold, "trades": len(selected),
                                  "by_cost": by_cost,
                                  "passes_all_gates_both_costs": all(
                                      metric["passes_all_gates"] for metric in by_cost.values())})
    eligible = [row for row in threshold_results
                if row["trades"] >= MIN_CONFIRM and row["passes_all_gates_both_costs"]]
    selected_gate = max(eligible,
                        key=lambda row: min(metric["ev_net_pct_per_trade_on_committed_notional"]
                                            for metric in row["by_cost"].values()), default=None)
    selected_validation, selected_confirmation, confirmation_metrics = [], [], None
    if selected_gate is not None:
        threshold = selected_gate["threshold"]
        selected_validation = _choose(validation, threshold)
        selected_confirmation = _choose(confirmation, threshold)
        confirmation_metrics = {label: _metrics(selected_confirmation, label) for label in SIDE_COSTS}
        enough = len(selected_confirmation) >= MIN_CONFIRM
        passes = all(metric["passes_all_gates"] for metric in confirmation_metrics.values())
        report["full_goal_validated"] = enough and passes
        confirmation_report = {"threshold_frozen_from_2025": threshold,
                               "trades": len(selected_confirmation),
                               "at_least_100_trades": enough,
                               "passes_all_gates_both_costs": passes,
                               "by_cost": confirmation_metrics}
    else:
        confirmation_report = None
    report.update({"decision": "validation_gates_passed_confirmation_pending" if selected_gate
                   else "no_threshold_passed_validation",
                   "validation_thresholds": threshold_results,
                   "selected_threshold": None if selected_gate is None else selected_gate["threshold"],
                   "selected_validation": selected_gate, "confirmation": confirmation_report,
                   "full_goal_historical_sample_passed": report["full_goal_validated"]})
    OUTPUT_JSON.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n",
                           encoding="utf-8")
    if selected_gate:
        records = [("validation", row) for row in selected_validation]
        records.extend(("confirmation", row) for row in selected_confirmation)
    else:
        records = [("validation", row) for row in static_validation]
        records.extend(("confirmation_diagnostic", row) for row in static_confirmation)
    _write_trades(records)
    return report


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    result = run()
    print(f"{result['decision']}: candidates={result['candidate_events']}; "
          f"train={result['training_events_after_symbol_60m_declustering']}; "
          f"validation={result['validation_events']}; confirmation={result['confirmation_events']}; "
          f"threshold={result.get('selected_threshold')}")


if __name__ == "__main__":
    main()
