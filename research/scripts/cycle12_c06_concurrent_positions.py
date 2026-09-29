from __future__ import annotations

import bisect
import csv
import hashlib
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "research"
sys.path.insert(0, str(RESEARCH / "scripts"))

import cycle02_multiframe_research as engine  # noqa: E402
import cycle06_minute_breakout_stop15m as cycle06  # noqa: E402


MARKET = "usd_m"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
MAX_HOLD_MINUTES = 1440
EXIT_MODE = "trend_loss"
SOURCE = RESEARCH / "results/cycle06_minute_breakout_stop15m_2026-09-28"
PROTOCOL = RESEARCH / "docs/CICLO12_C06_CONCORRENCIA_PROTOCOLO.md"
OUTPUT = RESEARCH / "results/cycle12_c06_concurrent_positions_2026-09-28"
INITIAL_EQUITY = 10_000.0


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_source() -> tuple[dict, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    report = json.loads((SOURCE / "research.json").read_text(encoding="utf-8"))
    if report["selected_candidates"] != 19 or report["initial_stop_atr_timeframe_minutes"] != 15:
        raise ValueError("unexpected Cycle 06 source report")
    candidates = pd.read_csv(SOURCE / "candidates.csv", parse_dates=["signal_time"])
    scores = pd.read_csv(SOURCE / "walk_forward_scores.csv", parse_dates=["signal_time"])
    labels = pd.read_csv(SOURCE / "candidate_labels.csv", parse_dates=["signal_time", "entry_time", "label_end_time"])
    if candidates["candidate_id"].duplicated().any() or scores["candidate_id"].duplicated().any():
        raise ValueError("duplicate candidate or score ID")
    scores["passed_fixed_cutoff"] = scores["passed_fixed_cutoff"].astype(str).str.lower().map(
        {"true": True, "false": False}
    )
    if scores["passed_fixed_cutoff"].isna().any():
        raise ValueError("unparseable fixed-cutoff decision")
    selected = scores.loc[scores["passed_fixed_cutoff"]].copy()
    if len(selected) != report["selected_candidates"]:
        raise ValueError("selected score count does not match Cycle 06 report")
    if not (selected["predicted_net_return"] > 0.012).all():
        raise ValueError("saved score decisions do not match the fixed C06 cutoff")
    start, end = pd.Timestamp(report["selection_start"]), pd.Timestamp(report["selection_end_exclusive"])
    pool = candidates.loc[
        (candidates["signal_time"] >= start)
        & (candidates["signal_time"] < end - pd.Timedelta(minutes=MAX_HOLD_MINUTES))
    ].copy()
    rows = pool.merge(selected[["candidate_id", "predicted_net_return"]], on="candidate_id", how="inner")
    if len(rows) != report["selected_candidates"]:
        raise ValueError("selected saved scores do not join to the original candidate pool")
    rows["probability"] = rows["predicted_net_return"]
    rows["expected_r"] = rows["predicted_net_return"]
    rows = rows.sort_values(
        ["signal_time", "probability", "expected_r", "symbol", "family"],
        ascending=[True, False, False, True, True],
    ).reset_index(drop=True)
    if set(rows["symbol"]) != set(SYMBOLS):
        raise ValueError("unexpected symbol cohort in selected candidates")
    return report, rows, labels, scores


def _load_market_data(expected_hash: str) -> tuple[dict, dict]:
    folder = RESEARCH / "data/usdm_btc_eth_1m"
    candles, provenance = engine.load_dataset(folder, MARKET)
    if provenance["data_sha256"] != expected_hash:
        raise ValueError("Cycle 06 dataset hash changed")
    candles = candles.loc[candles.open_time < engine.DATA_END].copy()
    arrays, ema_by_symbol = {}, {}
    for symbol, grouped in candles.groupby("symbol", sort=True):
        if symbol not in SYMBOLS:
            raise ValueError(f"unexpected dataset symbol: {symbol}")
        bars = grouped.reset_index(drop=True)
        arrays[symbol] = engine.MarketArrays(bars)
        bars_15m = engine.aggregate_minutes(bars, 15)
        exit_features = engine.indicators(bars_15m)
        ema_by_symbol[symbol] = {
            pd.Timestamp(timestamp): float(value)
            for timestamp, value in exit_features.ema21.items()
            if np.isfinite(value)
        }
    if set(arrays) != set(SYMBOLS):
        raise ValueError("dataset does not contain the two frozen symbols")
    return arrays, ema_by_symbol


def _marked_pnl(position: dict, timestamp: pd.Timestamp) -> float:
    index = bisect.bisect_right(position["path_ns"], timestamp.value) - 1
    return 0.0 if index < 0 else position["notional"] * float(position["path_returns"][index])


def _evaluate(rows: pd.DataFrame, labels: pd.DataFrame, arrays: dict, ema_by_symbol: dict,
              start: pd.Timestamp, end: pd.Timestamp, *, stress: bool, max_positions: int) -> tuple[dict, list[dict], list[dict]]:
    config = engine.gate_config(MARKET)
    cache: dict[tuple[str, bool], Any] = {}
    accepted: list[dict] = []
    active: list[dict] = []
    candidate_decisions: list[dict] = []
    cash = INITIAL_EQUITY
    skips = defaultdict(int)
    label_returns = labels.set_index("candidate_id")["net_return"]

    for row in rows.to_dict("records"):
        signal_time = pd.Timestamp(row["signal_time"])
        still_open = []
        for position in active:
            if position["exit_time"] <= signal_time:
                cash += position["pnl"]
            else:
                still_open.append(position)
        active = still_open

        if any(position["symbol"] == row["symbol"] for position in active):
            skips["same_symbol_open"] += 1
            candidate_decisions.append({"candidate_id": row["candidate_id"], "max_positions": max_positions,
                                        "decision": "skipped", "reason": "same_symbol_open"})
            continue
        if len(active) >= max_positions:
            skips["capacity_full"] += 1
            candidate_decisions.append({"candidate_id": row["candidate_id"], "max_positions": max_positions,
                                        "decision": "skipped", "reason": "capacity_full"})
            continue

        cache_key = (str(row["candidate_id"]), stress)
        if cache_key not in cache:
            cache[cache_key] = engine.simulate(
                arrays[row["symbol"]], row, config, EXIT_MODE, MAX_HOLD_MINUTES,
                ema_by_symbol[row["symbol"]], stress=stress, trace=True,
            )
        outcome = cache[cache_key]
        if outcome is None or outcome.exit_time > end:
            skips["no_complete_outcome"] += 1
            candidate_decisions.append({"candidate_id": row["candidate_id"], "max_positions": max_positions,
                                        "decision": "skipped", "reason": "no_complete_outcome"})
            continue
        expected_return = float(label_returns.loc[row["candidate_id"]])
        if not stress and abs(float(outcome.net_return) - expected_return) > 1e-10:
            raise ValueError(
                f"C06 label replay mismatch: {row['candidate_id']} "
                f"replay={outcome.net_return!r} label={expected_return!r} stress={stress}"
            )

        cost_multiplier = 2.0 if stress else 1.0
        friction = 2 * (config["fee_bps"] + config["slippage_bps"]) * cost_multiplier / 10_000
        stop_fraction = abs(outcome.entry_price - outcome.initial_stop) / outcome.entry_price
        exposure = min(engine.MAX_NOTIONAL_EQUITY, engine.RISK_FRACTION / (stop_fraction + friction))
        equity_at_signal = cash + sum(_marked_pnl(position, signal_time) for position in active)
        notional = equity_at_signal * exposure
        path_times = [
            pd.Timestamp(arrays[row["symbol"]].time.iloc[outcome.entry_index + offset])
            + pd.Timedelta(minutes=1)
            for offset in range(len(outcome.path_returns))
        ]
        position = {
            "candidate_id": row["candidate_id"],
            "symbol": row["symbol"],
            "side": int(row["side"]),
            "signal_time": signal_time,
            "entry_time": arrays[row["symbol"]].time.iloc[outcome.entry_index],
            "exit_time": outcome.exit_time,
            "exit_reason": outcome.exit_reason,
            "entry_price": outcome.entry_price,
            "exit_price": outcome.exit_price,
            "notional": notional,
            "net_return": outcome.net_return,
            "net_r": outcome.net_r,
            "pnl": notional * outcome.net_return,
            "path_returns": outcome.path_returns,
            "path_times": path_times,
            "path_ns": [timestamp.value for timestamp in path_times],
        }
        accepted.append(position)
        active.append(position)
        candidate_decisions.append({"candidate_id": row["candidate_id"], "max_positions": max_positions,
                                    "decision": "accepted", "reason": "capacity_available"})

    timeline: dict[pd.Timestamp, dict[int, float]] = defaultdict(dict)
    for position_index, position in enumerate(accepted):
        for timestamp, path_return in zip(position["path_times"], position["path_returns"]):
            timeline[timestamp][position_index] = position["notional"] * float(path_return)
    current_pnl: dict[int, float] = {}
    curve = []
    for timestamp in sorted(timeline):
        current_pnl.update(timeline[timestamp])
        curve.append({"time": timestamp, "equity": INITIAL_EQUITY + sum(current_pnl.values())})

    trades = [{key: value for key, value in position.items()
               if key not in {"path_returns", "path_times", "path_ns"}}
              for position in accepted]
    metrics = engine.metrics(trades, curve, INITIAL_EQUITY, start, end)
    metrics.update({"stress": stress, "max_concurrent_positions": max_positions,
                    "one_position_per_symbol": True,
                    "gross_notional_cap_per_position_equity_multiple": engine.MAX_NOTIONAL_EQUITY,
                    "skips_by_reason": dict(sorted(skips.items()))})
    return metrics, trades, candidate_decisions


def _assert_baseline_matches(actual: dict, expected: dict, label: str) -> None:
    fields = ("trades", "win_rate", "mean_net_return", "payoff_ratio", "profit_factor",
              "net_profit", "total_return", "max_drawdown", "active_weeks")
    for field in fields:
        a, e = actual[field], expected[field]
        if a is None or e is None:
            if a is not e:
                raise ValueError(f"baseline replay mismatch {label}/{field}: {a} != {e}")
        elif abs(float(a) - float(e)) > 1e-9:
            raise ValueError(f"baseline replay mismatch {label}/{field}: {a} != {e}")


def run() -> dict:
    if OUTPUT.exists():
        raise FileExistsError(f"refusing to overwrite prior result: {OUTPUT}")
    started = time.perf_counter()
    source_report, rows, labels, scores = _load_source()
    arrays, ema_by_symbol = _load_market_data(source_report["dataset_sha256"])
    start, end = pd.Timestamp(source_report["selection_start"]), pd.Timestamp(source_report["selection_end_exclusive"])
    results, all_trades, all_decisions = {}, [], []

    for stress_name, stress in (("base", False), ("stress", True)):
        for max_positions in (1, 2):
            metrics, trades, decisions = _evaluate(rows, labels, arrays, ema_by_symbol, start, end,
                                                    stress=stress, max_positions=max_positions)
            results[f"{stress_name}_max_positions_{max_positions}"] = metrics
            if max_positions == 1:
                _assert_baseline_matches(metrics, source_report[stress_name], stress_name)
            all_trades.extend({"case": stress_name, **trade} for trade in trades)
            all_decisions.extend({"case": stress_name, **decision} for decision in decisions)

    report = {
        "experiment_id": "C12-c06-concurrent-positions-2026-09-28",
        "status": "retrospective_execution_ablation",
        "market": MARKET,
        "symbols": list(SYMBOLS),
        "only_strategy_component_changed": "maximum concurrent positions: one global position to one per symbol, up to two",
        "unchanged": ["C06 saved model predictions", "fixed predicted EV cutoff 1.2%", "1m scanner",
                      "15m ATR initial stop", "EMA21/15m exit", "24h maximum hold", "per-trade sizing",
                      "fees, slippage, funding", "dataset", "evaluation window"],
        "selection_start": source_report["selection_start"],
        "selection_end_exclusive": source_report["selection_end_exclusive"],
        "candidate_count": len(rows),
        "score_file_sha256": digest(SOURCE / "walk_forward_scores.csv"),
        "candidate_file_sha256": digest(SOURCE / "candidates.csv"),
        "labels_file_sha256": digest(SOURCE / "candidate_labels.csv"),
        "source_report_sha256": digest(SOURCE / "research.json"),
        "dataset_sha256": source_report["dataset_sha256"],
        "protocol_sha256": digest(PROTOCOL),
        "script_sha256": digest(Path(__file__)),
        "accounting_validation": "one-position results exactly reproduce C06 base and stress metrics",
        "results": results,
        "elapsed_seconds": time.perf_counter() - started,
        "real_orders_sent": False,
        "training_performed": False,
        "independent_validation": False,
        "limits": [
            "Retrospective execution ablation on a previously examined window; not an independent validation.",
            "Two positions can double the maximum gross notional exposure relative to the C06 global cap.",
            "BTC and ETH positions can remain highly correlated; no portfolio liquidation simulation is added.",
            "Per-trade EV uses initial notional; account-level drawdown uses minute-close mark-to-market paths.",
        ],
    }

    OUTPUT.mkdir(parents=True, exist_ok=False)
    (OUTPUT / "research.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    with (OUTPUT / "trades.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = list(all_trades[0]) if all_trades else ["case", "candidate_id"]
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_trades)
    with (OUTPUT / "candidate_decisions.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = list(all_decisions[0]) if all_decisions else ["case", "candidate_id", "max_positions", "decision", "reason"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_decisions)
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False), flush=True)
    return report


if __name__ == "__main__":
    run()
