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

SERIES = "futures_liquidity_sweep_20260927"
PROTOCOL = ROOT / "docs" / "futures_liquidity_sweep_protocol_2026-09-27.md"
OUTPUT_DIR = ROOT / "results" / SERIES
OUTPUT_JSON = OUTPUT_DIR / "research.json"
OUTPUT_STATIC_TRADES = OUTPUT_DIR / "static_signal_trades.csv"
OUTPUT_SELECTED_TRADES = OUTPUT_DIR / "selected_trades.csv"
MIN_TRAINING_EVENTS = 400
MIN_VALIDATION_TRADES = 100
THRESHOLDS = tuple(round(value, 2) for value in np.arange(0.55, 0.901, 0.05))
STOP_MIN_PCT = 0.015
STOP_MAX_PCT = 0.02
common.TARGET_R = 1.9


def build_events(symbol: str, bars: np.ndarray, funding_times: np.ndarray,
                 funding_rates: np.ndarray) -> list[dict]:
    features, parts = common.build_features(bars)
    high60 = common._rolling_extreme(bars["h"].astype(np.float64, copy=False), 60, True)
    low60 = common._rolling_extreme(bars["l"].astype(np.float64, copy=False), 60, False)
    close = bars["c"].astype(np.float64, copy=False)
    records = []
    start_index = 153
    end_index = len(bars) - common.MAX_HOLD_MINUTES - 1
    for index in range(start_index, end_index):
        imbalance = float(parts["imb5"][index])
        return5 = float(parts["ret5"][index])
        median_volume = float(parts["med_qv5"][index])
        volume5 = float(parts["qv5"][index])
        prior_high = float(high60[index - 5])
        prior_low = float(low60[index - 5])
        if not (math.isfinite(median_volume) and median_volume > 0
                and volume5 >= 1.5 * median_volume):
            continue
        low5 = float(parts["low5"][index])
        high5 = float(parts["high5"][index])
        if low5 < prior_low and close[index] > prior_low and return5 > 0 and imbalance >= 0.20:
            direction = 1
            boundary = low5
        elif high5 > prior_high and close[index] < prior_high and return5 < 0 and imbalance <= -0.20:
            direction = -1
            boundary = high5
        else:
            continue

        entry_index = index + 1
        entry = float(bars[entry_index]["o"])
        atr = float(parts["atr14"][index])
        if not math.isfinite(atr) or atr <= 0:
            continue
        buffer = 0.1 * atr
        stop = float(boundary - buffer) if direction > 0 else float(boundary + buffer)
        risk = direction * (entry - stop)
        risk_pct = risk / entry
        if not (STOP_MIN_PCT <= risk_pct <= STOP_MAX_PCT):
            continue
        target = entry + direction * common.TARGET_R * risk
        vector = features[index]
        if not np.isfinite(vector).all():
            continue
        outcome = common._simulate_trade(
            bars, entry_index, direction, stop, target, funding_times, funding_rates)
        records.append({
            "symbol": symbol, "signal_index": index, "entry_index": entry_index,
            "signal_close_ms": int(bars[index]["t"]) + 60_000,
            "entry_ms": int(bars[entry_index]["t"]), "direction": direction,
            "entry_price": entry, "stop_price": stop, "target_price": target,
            "stop_distance_pct": 100 * risk_pct, "features": vector.tolist(),
            **outcome,
        })
    return records


def _public_metrics(trades: list[dict], bars_by_symbol: dict[str, np.ndarray]) -> dict:
    return {
        label: common._metrics(trades, bars_by_symbol, label)
        for label in common.SIDE_COSTS
    }


def run(skip_download: bool = False) -> dict:
    del skip_download  # This replay reuses only locally cached, checksum-verified archives.
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    bars_by_symbol: dict[str, np.ndarray] = {}
    funding_by_symbol: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    input_manifest = []
    funding_manifest = []
    all_events = []

    for symbol in common.SYMBOLS:
        print(f"loading and evaluating {symbol}", flush=True)
        bars, month_manifest = common.load_symbol_bars(symbol)
        funding_times, funding_rates, funding_rows = common.load_funding(symbol)
        bars_by_symbol[symbol] = bars
        funding_by_symbol[symbol] = (funding_times, funding_rates)
        input_manifest.extend(month_manifest)
        funding_manifest.extend(funding_rows)
        events = build_events(symbol, bars, funding_times, funding_rates)
        all_events.extend(events)
        print(f"{symbol}: bars={len(bars)} funding={len(funding_times)} events={len(events)}", flush=True)

    common._funding_for_trade_metrics(all_events, funding_by_symbol)
    train_rows = common._decluster_training(common._score_period(all_events, "train"))
    validation_rows = common._score_period(all_events, "validation")
    confirmation_rows = common._score_period(all_events, "confirmation")

    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
    except ImportError as exc:
        raise RuntimeError("install the project tree-research extra to run the frozen ML model") from exc

    protocol_hash = hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()
    source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    common_meta = {
        "schema_version": 1,
        "series": SERIES,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "deployable": False,
        "full_goal_validated": False,
        "protocol_sha256": protocol_hash,
        "source_sha256": source_hash,
        "universe": list(common.SYMBOLS),
        "timeframe": "USD-M Futures 1m klines",
        "first_month": common.FIRST_MONTH,
        "last_month": common.LAST_MONTH,
        "bars_per_symbol": {symbol: len(bars) for symbol, bars in bars_by_symbol.items()},
        "funding_points_per_symbol": {symbol: len(values[0])
                                       for symbol, values in funding_by_symbol.items()},
        "events_by_symbol": {symbol: sum(row["symbol"] == symbol for row in all_events)
                             for symbol in common.SYMBOLS},
        "training_events_after_60m_declustering": len(train_rows),
        "minimum_training_events": MIN_TRAINING_EVENTS,
        "validation_events": len(validation_rows),
        "confirmation_events": len(confirmation_rows),
        "model": {
            "name": "HistGradientBoostingClassifier",
            "early_stopping": False,
            "l2_regularization": 10.0,
            "learning_rate": 0.05,
            "max_iter": 100,
            "max_leaf_nodes": 7,
            "min_samples_leaf": 40,
            "random_state": 548,
            "label": "positive net trade PnL at base cost",
            "fitted": False,
        },
        "target_and_execution": {
            "target_R_gross": common.TARGET_R,
            "minimum_stop_pct": 100 * STOP_MIN_PCT,
            "maximum_stop_pct": 100 * STOP_MAX_PCT,
            "max_hold_minutes": common.MAX_HOLD_MINUTES,
            "cooldown_minutes_after_exit": common.COOLDOWN_MINUTES,
            "side_costs_including_taker_and_slippage": common.SIDE_COSTS,
            "committed_notional_basis": "net operation PnL divided by entry notional",
            "allocation_per_pair": 0.25,
            "leverage": 1.0,
            "funding_included": True,
            "same_bar_stop_target_order": "stop first",
            "live_orders_enabled": False,
        },
        "threshold_candidates": list(THRESHOLDS),
        "validation_sample_minimum": common.MIN_SCREEN_TRADES,
        "validation_minimum_trades_for_confirmation": MIN_VALIDATION_TRADES,
        "archive_count": len(input_manifest),
        "input_archives": input_manifest,
        "funding_archive_count": len(funding_manifest),
        "funding_archives": funding_manifest,
        "orders_sent": 0,
        "jev_calls": 0,
    }

    if (len(train_rows) < MIN_TRAINING_EVENTS
            or len({int(row["net_return_base_pct"] > 0) for row in train_rows}) < 2):
        static_validation = common._choose_trades(validation_rows, 0.0)
        static_confirmation = common._choose_trades(confirmation_rows, 0.0)
        common_meta.update({
            "decision": "insufficient_training_events",
            "unfiltered_signal_diagnostic": {
                "validation": _public_metrics(static_validation, bars_by_symbol),
                "confirmation_diagnostic": _public_metrics(static_confirmation, bars_by_symbol),
            },
        })
        OUTPUT_JSON.write_text(json.dumps(common_meta, sort_keys=True, indent=2, allow_nan=False) + "\n",
                               encoding="utf-8")
        common._write_trade_csv(
            OUTPUT_STATIC_TRADES,
            [("validation", row) for row in static_validation]
            + [("confirmation_diagnostic", row) for row in static_confirmation],
        )
        return common_meta

    x_train = np.asarray([row["features"] for row in train_rows], dtype=np.float64)
    y_train = np.asarray([row["net_return_base_pct"] > 0 for row in train_rows], dtype=np.int8)
    model = HistGradientBoostingClassifier(
        early_stopping=False,
        l2_regularization=10.0,
        learning_rate=0.05,
        max_iter=100,
        max_leaf_nodes=7,
        min_samples_leaf=40,
        random_state=548,
    )
    model.fit(x_train, y_train)
    common_meta["model"]["fitted"] = True
    common_meta["model"]["training_wins"] = int(np.sum(y_train))
    for rows in (validation_rows, confirmation_rows):
        if rows:
            probabilities = model.predict_proba(
                np.asarray([row["features"] for row in rows], dtype=np.float64))[:, 1]
            for row, probability in zip(rows, probabilities):
                row["probability_win"] = float(probability)

    validation_gates = [
        common._gate_for_threshold(validation_rows, bars_by_symbol, threshold)
        for threshold in THRESHOLDS
    ]
    preliminary_passes = [row for row in validation_gates
                          if row["passes_all_gates_both_costs"]]
    eligible = [row for row in preliminary_passes if row["trades"] >= MIN_VALIDATION_TRADES]
    selected = max(
        eligible,
        key=lambda row: min(metric["ev_net_pct_per_trade_on_committed_notional"]
                            for metric in row["by_cost"].values()),
        default=None,
    )
    confirmation = None
    selected_validation_trades: list[dict] = []
    selected_confirmation_trades: list[dict] = []
    if selected is not None:
        threshold = selected["threshold"]
        selected_validation_trades = common._choose_trades(validation_rows, threshold)
        selected_confirmation_trades = common._choose_trades(confirmation_rows, threshold)
        confirmation_metrics = _public_metrics(selected_confirmation_trades, bars_by_symbol)
        confirmation_passes = all(item["passes_all_gates"]
                                  for item in confirmation_metrics.values())
        confirmation_enough_trades = len(selected_confirmation_trades) >= MIN_VALIDATION_TRADES
        confirmation = {
            "threshold_frozen_from_2025": threshold,
            "trades": len(selected_confirmation_trades),
            "at_least_100_trades": confirmation_enough_trades,
            "passes_all_gates_both_costs": confirmation_passes,
            "by_cost": confirmation_metrics,
        }
        common_meta["full_goal_validated"] = confirmation_enough_trades and confirmation_passes

    if selected is not None:
        decision = "validation_gates_passed_confirmation_pending"
    elif preliminary_passes:
        decision = "screen_passed_but_fewer_than_100_validation_trades"
    else:
        decision = "no_threshold_passed_validation"
    common_meta.update({
        "decision": decision,
        "validation_thresholds": validation_gates,
        "validation_preliminary_pass_count": len(preliminary_passes),
        "selected_threshold": None if selected is None else selected["threshold"],
        "selected_validation": selected,
        "confirmation": confirmation,
        "full_goal_historical_sample_passed": common_meta["full_goal_validated"],
    })
    OUTPUT_JSON.write_text(json.dumps(common_meta, sort_keys=True, indent=2, allow_nan=False) + "\n",
                           encoding="utf-8")
    if selected is not None:
        all_selected = [("validation", row) for row in selected_validation_trades]
        all_selected.extend(("confirmation", row) for row in selected_confirmation_trades)
        common._write_trade_csv(OUTPUT_SELECTED_TRADES, all_selected)
    return common_meta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-download", action="store_true",
                        help="require and verify all cached archives")
    args = parser.parse_args()
    report = run(skip_download=args.skip_download)
    print(f"{report['decision']}: train={report['training_events_after_60m_declustering']}; "
          f"validation={report['validation_events']}; confirmation={report['confirmation_events']}; "
          f"selected_threshold={report.get('selected_threshold')}")


if __name__ == "__main__":
    main()
