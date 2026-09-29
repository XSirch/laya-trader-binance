"""Cycle 02 15m entries, 1h/4h context, 1m execution and ML filters.

All historical results from this script are retrospective development evidence.
It never connects to authenticated endpoints or submits orders.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import sys
import time
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore", category=DeprecationWarning)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str((ROOT / "research/src").resolve()))

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from threadpoolctl import threadpool_limits

from binance_multistrategy.data import load_dataset
from binance_multistrategy.features import HIGHER_FEATURES, MODEL_BASE_FEATURES, indicators
from binance_multistrategy.learning import logit
from binance_multistrategy.simulation import MarketArrays, exit_trigger, ratchet_stop


DATA_END = pd.Timestamp("2026-09-01T00:00:00Z")
TRAIN_END = pd.Timestamp("2025-07-01T00:00:00Z")
CALIBRATION_END = pd.Timestamp("2026-01-01T00:00:00Z")
SELECTION_END = DATA_END
EMBARGO_MINUTES = 1440
MIN_NET_EV = .012
MIN_PAYOFF = 1.0
MIN_PROFIT_FACTOR = 1.25
MIN_TRADES = 200
MIN_ACTIVE_WEEKS = 8
PREFERRED_WIN_RATE = .70
RISK_FRACTION = .0025
MAX_NOTIONAL_EQUITY = 1.0
MIN_EXPECTED_R = .05
THRESHOLDS = tuple(round(x, 2) for x in np.arange(.35, .801, .05))
OUTPUT = ROOT / "research/results/cycle02_multiframe_corrected_2026-09-28"
FEATURES = tuple(MODEL_BASE_FEATURES
                 + [f"1h_{name}" for name in HIGHER_FEATURES]
                 + [f"4h_{name}" for name in HIGHER_FEATURES]
                 + ["side"])
FAMILIES = ("trend_resumption", "breakout_continuation")
HORIZONS = (("6h", 360), ("24h", 1440))
EXITS = (
    ("fixed", "fixed_1ATR_stop_1.5R_target"),
    ("trailing", "1ATR_stop_trailing_activate_1R_distance_1ATR"),
    ("trend_loss", "1ATR_hard_stop_15m_EMA21_trend_loss"),
)


@dataclass
class CycleOutcome:
    entry_index: int
    exit_index: int
    entry_price: float
    exit_price: float
    initial_stop: float
    final_stop: float
    target: float
    net_return: float
    net_r: float
    fee_per_unit: float
    funding_per_unit: float
    exit_reason: str
    exit_time: pd.Timestamp
    path_returns: np.ndarray


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def aggregate_minutes(bars: pd.DataFrame, minutes: int) -> pd.DataFrame:
    indexed = bars.copy()
    indexed.index = pd.DatetimeIndex(indexed.open_time) + pd.Timedelta(minutes=1)
    indexed.index.name = "close_time"
    rule = indexed.resample(f"{minutes}min", closed="right", label="right", origin="epoch")
    columns = {"open": "first", "high": "max", "low": "min", "close": "last",
               "volume": "sum", "taker_buy_base": "sum"}
    grouped = rule.agg(columns)
    counts = rule.close.count()
    return grouped.loc[counts == minutes].copy()


def market_features(bars: pd.DataFrame) -> tuple[pd.DataFrame, dict[pd.Timestamp, float]]:
    bars15 = aggregate_minutes(bars, 15)
    bars60 = aggregate_minutes(bars, 60)
    bars240 = aggregate_minutes(bars, 240)
    f15 = indicators(bars15)
    contexts = {60: indicators(bars60), 240: indicators(bars240)}
    for timeframe, label in ((60, "1h"), (240, "4h")):
        frame = contexts[timeframe].reindex(f15.index, method="ffill")
        for name in HIGHER_FEATURES:
            f15[f"{label}_{name}"] = frame[name].to_numpy(dtype=float)
    f15["close"] = bars15.close.to_numpy(dtype=float)
    f15["open"] = bars15.open.to_numpy(dtype=float)
    f15["high"] = bars15.high.to_numpy(dtype=float)
    f15["low"] = bars15.low.to_numpy(dtype=float)
    f15["volume"] = bars15.volume.to_numpy(dtype=float)
    f15["don_high20"] = bars15.high.shift().rolling(20, min_periods=20).max().to_numpy(dtype=float)
    f15["don_low20"] = bars15.low.shift().rolling(20, min_periods=20).min().to_numpy(dtype=float)
    f15["volume_median20"] = bars15.volume.shift().rolling(20, min_periods=20).median().to_numpy(dtype=float)
    contexts60 = contexts[60].reindex(f15.index, method="ffill")
    contexts240 = contexts[240].reindex(f15.index, method="ffill")
    close60 = bars60.close.reindex(f15.index, method="ffill")
    close240 = bars240.close.reindex(f15.index, method="ffill")
    ema60 = contexts60.ema200
    ema240 = contexts240.ema200
    f15["context_long"] = ((close60 > ema60) & (ema60 > contexts[60].ema200.shift(5).reindex(f15.index, method="ffill"))
                           & (close240 > ema240) & (ema240 > contexts[240].ema200.shift(5).reindex(f15.index, method="ffill"))).to_numpy(dtype=bool)
    f15["context_short"] = ((close60 < ema60) & (ema60 < contexts[60].ema200.shift(5).reindex(f15.index, method="ffill"))
                            & (close240 < ema240) & (ema240 < contexts[240].ema200.shift(5).reindex(f15.index, method="ffill"))).to_numpy(dtype=bool)
    f15["prior_close"] = bars15.close.shift().to_numpy(dtype=float)
    f15["prior_ema21"] = f15.ema21.shift().to_numpy(dtype=float)
    return f15, {pd.Timestamp(t): float(v) for t, v in f15.ema21.items() if np.isfinite(v)}


def generate_candidates(features: pd.DataFrame, symbol: str, market: str,
                        minute_times: pd.DatetimeIndex) -> pd.DataFrame:
    records = []
    sides = (1,) if market == "spot" else (1, -1)
    signal_times = pd.DatetimeIndex(features.index)
    for family in FAMILIES:
        for side in sides:
            context = features.context_long if side == 1 else features.context_short
            if family == "trend_resumption":
                signal = ((side * (features.close - features.ema21) > 0)
                          & (side * (features.prior_close - features.prior_ema21) <= 0))
            else:
                breakout = (features.close > features.don_high20) if side == 1 else (features.close < features.don_low20)
                signal = breakout & (features.volume >= 1.3 * features.volume_median20)
            valid = (context & signal & features.atr.notna() & features.ema21.notna()
                     & features.atr_pct.notna())
            indices = np.flatnonzero(valid.fillna(False).to_numpy(dtype=bool))
            last_signal = None
            for i in indices:
                signal_time = pd.Timestamp(signal_times[i])
                if last_signal is not None and signal_time - last_signal < pd.Timedelta(minutes=15):
                    continue
                next_minute = int(minute_times.searchsorted(signal_time, side="left"))
                if next_minute <= 0 or next_minute >= len(minute_times) or minute_times[next_minute] != signal_time:
                    continue
                values = features.iloc[i]
                if not np.isfinite(float(values.atr)) or float(values.atr) <= 0:
                    continue
                row = {name: float(values[name]) if pd.notna(values[name]) else np.nan for name in FEATURES[:-1]}
                row.update({"candidate_id": f"{symbol}|{family}|{side}|{signal_time.isoformat()}",
                            "symbol": symbol, "market": market, "family": family,
                            "side": side, "regime": side, "signal_time": signal_time,
                            "signal_index": next_minute - 1, "atr": float(values.atr),
                            "stop_atr": 1.0, "target_r": 1.5,
                            "ema21": float(values.ema21),
                            "stop_fraction_signal": float(values.atr / values.close)})
                row["side"] = side
                records.append(row)
                last_signal = signal_time
    return pd.DataFrame(records)


def simulate(arrays: MarketArrays, row: dict, config: dict, exit_mode: str,
             max_hold: int, ema21_by_close: dict[pd.Timestamp, float],
             *, stress: bool = False, trace: bool = False) -> CycleOutcome | None:
    if exit_mode not in {"fixed", "trailing", "trend_loss"}:
        raise ValueError(f"Unknown canonical exit mode: {exit_mode}")
    entry_index = int(row["signal_index"]) + 1
    last_index = entry_index + max_hold - 1
    if entry_index <= 0 or last_index >= len(arrays):
        return None
    side = int(row["side"])
    if config["market"] == "spot" and side < 0:
        raise ValueError("Spot cannot open a short position")
    multiplier = 2.0 if stress else 1.0
    fee_rate = config["fee_bps"] * multiplier / 10_000
    slip_rate = config["slippage_bps"] * multiplier / 10_000
    values = arrays.values
    entry = float(values["open"][entry_index]) * (1 + side * slip_rate)
    distance = float(row["atr"]) * float(row["stop_atr"])
    if not np.isfinite(distance) or distance <= 0:
        return None
    initial_stop = entry - side * distance
    stop = initial_stop
    target = (entry + side * distance * 1.5 if exit_mode == "fixed"
              else (math.inf if side == 1 else -math.inf))
    best = entry
    funding = 0.0
    path: list[float] = []
    times = arrays.time
    for k in range(entry_index, last_index + 1):
        exit_raw, reason = exit_trigger(side, values["open"][k], values["high"][k],
                                        values["low"][k], stop, target)
        close_time = pd.Timestamp(times.iloc[k]) + pd.Timedelta(minutes=1)
        if exit_raw is None and exit_mode == "trend_loss" and close_time in ema21_by_close:
            if side * (float(values["close"][k]) - ema21_by_close[close_time]) <= 0:
                exit_raw, reason = float(values["close"][k]), "trend_ema21_loss"
        if exit_raw is None and k == last_index:
            exit_raw, reason = float(values["close"][k]), "time_stop"
        signed_rate = side * float(values["funding_rate"][k])
        if signed_rate > 0:
            funding += signed_rate * float(values["mark_high"][k])
        elif signed_rate < 0 and k > entry_index and exit_raw is None:
            funding += signed_rate * float(values["mark_low"][k])
        if exit_raw is not None:
            exit_fill = float(exit_raw) * (1 - side * slip_rate)
            fees = fee_rate * (entry + exit_fill)
            pnl_unit = side * (exit_fill - entry) - fees - funding
            net_return = pnl_unit / entry
            if trace:
                path.append(net_return)
            return CycleOutcome(entry_index, k, entry, exit_fill, initial_stop, stop, target,
                                net_return, pnl_unit / distance, fees, funding, str(reason),
                                close_time, np.asarray(path, dtype=float))
        if trace:
            mark = float(values["mark_close"][k]) * (1 - side * slip_rate)
            mark_fees = fee_rate * (entry + mark)
            path.append((side * (mark - entry) - mark_fees - funding) / entry)
        best = max(best, float(values["high"][k])) if side == 1 else min(best, float(values["low"][k]))
        if exit_mode == "trailing":
            stop = ratchet_stop(side, entry, stop, best, distance, 1.0, 1.0)
    raise AssertionError("A fully observed trade must exit by stop, trend loss, target, or time")


def apply_labels(candidates: pd.DataFrame, arrays: dict[str, MarketArrays],
                 configs: dict[str, dict], exit_mode: str, max_hold: int,
                 ema_by_symbol: dict[str, dict[pd.Timestamp, float]],
                 *, smoke_limit: int | None = None) -> pd.DataFrame:
    rows = candidates.head(smoke_limit) if smoke_limit else candidates
    labeled = []
    total = len(rows)
    for number, record in enumerate(rows.to_dict("records"), 1):
        outcome = simulate(arrays[record["symbol"]], record, configs[record["market"]],
                           exit_mode, max_hold, ema_by_symbol[record["symbol"]])
        if outcome is None:
            continue
        record.update({"label": int(outcome.net_return > 0), "net_return": outcome.net_return,
                       "net_r": outcome.net_r, "label_end_time": outcome.exit_time,
                       "exit_reason": outcome.exit_reason, "entry_time": arrays[record["symbol"]].time.iloc[outcome.entry_index]})
        labeled.append(record)
        if number % 1000 == 0:
            print(f"LABEL_PROGRESS {number}/{total}", flush=True)
    return pd.DataFrame(labeled)


def split_labels(labels: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    gap = pd.Timedelta(minutes=EMBARGO_MINUTES)
    train = labels.loc[(labels.signal_time < TRAIN_END - gap)
                       & (labels.label_end_time < TRAIN_END)].copy()
    calibration = labels.loc[(labels.signal_time >= TRAIN_END + gap)
                             & (labels.signal_time < CALIBRATION_END - gap)
                             & (labels.label_end_time < CALIBRATION_END)].copy()
    selection = labels.loc[(labels.signal_time >= CALIBRATION_END + gap)
                           & (labels.signal_time < SELECTION_END - gap)
                           & (labels.label_end_time < SELECTION_END)].copy()
    if not train.empty and not calibration.empty and train.label_end_time.max() >= calibration.signal_time.min():
        raise AssertionError("Training and calibration labels overlap")
    if not calibration.empty and not selection.empty and calibration.label_end_time.max() >= selection.signal_time.min():
        raise AssertionError("Calibration and selection labels overlap")
    return train, calibration, selection


def fit_filter(train: pd.DataFrame, calibration: pd.DataFrame, backend: str) -> tuple[Any, Any, Any, dict]:
    for name, frame in (("train", train), ("calibration", calibration)):
        counts = frame.label.value_counts()
        if len(frame) < 300 or len(counts) != 2 or counts.min() < 30:
            raise ValueError(f"Insufficient {name} data: n={len(frame)}, classes={counts.to_dict()}")
    x_train = train[list(FEATURES)].astype(float).replace([np.inf, -np.inf], np.nan)
    x_cal = calibration[list(FEATURES)].astype(float).replace([np.inf, -np.inf], np.nan)
    if backend == "hist_cpu":
        common = dict(max_iter=160, learning_rate=.05, max_leaf_nodes=15,
                      min_samples_leaf=60, l2_regularization=10,
                      early_stopping=False, random_state=27)
        classifier = HistGradientBoostingClassifier(**common)
        regressor = HistGradientBoostingRegressor(loss="squared_error", **common)
    elif backend == "xgboost_cuda":
        import xgboost
        from xgboost import XGBClassifier, XGBRegressor
        if not xgboost.build_info().get("USE_CUDA", False):
            raise RuntimeError("XGBoost has no CUDA build; refusing CPU fallback")
        common = dict(n_estimators=320, max_depth=4, learning_rate=.04,
                      subsample=.8, colsample_bytree=.8, min_child_weight=40,
                      reg_lambda=10, max_bin=256, tree_method="hist",
                      device="cuda:0", n_jobs=4, random_state=27, verbosity=0)
        classifier = XGBClassifier(objective="binary:logistic", eval_metric="logloss", **common)
        regressor = XGBRegressor(objective="reg:squarederror", **common)
    else:
        raise ValueError(f"Unknown backend {backend}")
    fit_threads = 1 if backend == "hist_cpu" else 4
    with threadpool_limits(limits=fit_threads):
        classifier.fit(x_train, train.label.astype(int))
        regressor.fit(x_train, train.net_r.astype(float))
        raw = classifier.predict_proba(x_cal)[:, 1]
        calibrator = LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000, random_state=27)
        calibrator.fit(logit(raw).reshape(-1, 1), calibration.label.astype(int))
        calibrated = calibrator.predict_proba(logit(raw).reshape(-1, 1))[:, 1]
    diagnostics = {"backend": backend, "train_rows": len(train),
                   "calibration_rows": len(calibration),
                   "train_positive_rate": float(train.label.mean()),
                   "calibration_positive_rate": float(calibration.label.mean()),
                   "calibration_raw_brier": float(brier_score_loss(calibration.label, raw)),
                   "calibration_fitted_brier": float(brier_score_loss(calibration.label, calibrated)),
                   "calibration_fitted_log_loss": float(log_loss(calibration.label, calibrated)),
                   "calibration_is_in_sample_for_logistic_fit": True}
    return classifier, regressor, calibrator, diagnostics


def score_rows(rows: pd.DataFrame, classifier: Any, regressor: Any, calibrator: Any) -> pd.DataFrame:
    scored = rows.copy()
    x = scored[list(FEATURES)].astype(float).replace([np.inf, -np.inf], np.nan)
    raw = classifier.predict_proba(x)[:, 1]
    scored["probability"] = calibrator.predict_proba(logit(raw).reshape(-1, 1))[:, 1]
    scored["expected_r"] = regressor.predict(x)
    return scored


def metrics(trades: list[dict], equity_curve: list[dict], initial: float,
            start: pd.Timestamp, end: pd.Timestamp) -> dict:
    if not trades:
        return {"trades": 0, "win_rate": None, "mean_net_return": None,
                "payoff_ratio": None, "profit_factor": None, "net_profit": 0.0,
                "total_return": 0.0, "max_drawdown": 0.0,
                "active_weeks": 0, "start": start.isoformat(), "end_exclusive": end.isoformat()}
    returns = np.asarray([r["net_return"] for r in trades], dtype=float)
    pnl = np.asarray([r["pnl"] for r in trades], dtype=float)
    winners, losers = returns[returns > 0], returns[returns < 0]
    profit_wins, profit_losses = pnl[pnl > 0], pnl[pnl < 0]
    payoff_ratio = float(winners.mean() / abs(losers.mean())) if len(winners) and len(losers) else None
    pf = float(profit_wins.sum() / abs(profit_losses.sum())) if len(profit_losses) else None
    curve = np.asarray([initial] + [float(row["equity"]) for row in equity_curve], dtype=float)
    peaks = np.maximum.accumulate(curve)
    drawdown = 1 - curve / peaks
    exits = pd.to_datetime([r["exit_time"] for r in trades], utc=True).tz_convert(None)
    active_weeks = int(exits.to_period("W-SUN").nunique())
    return {"trades": len(trades), "win_rate": float((returns > 0).mean()),
            "mean_net_return": float(returns.mean()), "payoff_ratio": payoff_ratio,
            "profit_factor": pf, "net_profit": float(pnl.sum()),
            "total_return": float(pnl.sum() / initial),
            "max_drawdown": float(drawdown.max(initial=0)),
            "active_weeks": active_weeks, "start": start.isoformat(),
            "end_exclusive": end.isoformat()}


def passes(base: dict, stress: dict) -> tuple[bool, list[str]]:
    failures = []
    if base["trades"] < MIN_TRADES:
        failures.append("base_trades_below_200")
    if base["active_weeks"] < MIN_ACTIVE_WEEKS:
        failures.append("base_active_weeks_below_8")
    if base["mean_net_return"] is None or base["mean_net_return"] <= MIN_NET_EV:
        failures.append("base_ev_not_above_1_2_percent")
    if base["payoff_ratio"] is None or base["payoff_ratio"] < MIN_PAYOFF:
        failures.append("base_payoff_below_1")
    if base["profit_factor"] is None or base["profit_factor"] < MIN_PROFIT_FACTOR:
        failures.append("base_profit_factor_below_1_25")
    if stress["net_profit"] <= 0:
        failures.append("stress_not_positive")
    return not failures, failures


def evaluate_portfolio(rows: pd.DataFrame, arrays: dict[str, MarketArrays],
                       configs: dict[str, dict], exit_mode: str, max_hold: int,
                       ema_by_symbol: dict[str, dict[pd.Timestamp, float]],
                       start: pd.Timestamp, end: pd.Timestamp, *, stress: bool,
                       outcome_cache: dict[tuple[str, bool], CycleOutcome | None]) -> tuple[dict, list[dict]]:
    rows = rows.loc[(rows.signal_time >= start)
                    & (rows.signal_time < end - pd.Timedelta(minutes=max_hold))].copy()
    rows = rows.sort_values(["signal_time", "probability", "expected_r", "symbol", "family"],
                            ascending=[True, False, False, True, True])
    cash = 10_000.0
    next_free = start
    trades = []
    curve = []
    for row in rows.to_dict("records"):
        if pd.Timestamp(row["signal_time"]) < next_free or cash <= 0:
            continue
        cache_key = (str(row["candidate_id"]), stress)
        if cache_key not in outcome_cache:
            outcome_cache[cache_key] = simulate(arrays[row["symbol"]], row,
                                                configs[row["market"]], exit_mode,
                                                max_hold, ema_by_symbol[row["symbol"]],
                                                stress=stress, trace=True)
        outcome = outcome_cache[cache_key]
        if outcome is None or outcome.exit_time > end:
            continue
        cost_mult = 2.0 if stress else 1.0
        friction = 2 * (configs[row["market"]]["fee_bps"]
                        + configs[row["market"]]["slippage_bps"]) * cost_mult / 10_000
        stop_fraction = abs(outcome.entry_price - outcome.initial_stop) / outcome.entry_price
        exposure = min(MAX_NOTIONAL_EQUITY, RISK_FRACTION / (stop_fraction + friction))
        notional = cash * exposure
        pnl = notional * outcome.net_return
        for offset, path_return in enumerate(outcome.path_returns):
            mark_time = pd.Timestamp(arrays[row["symbol"]].time.iloc[outcome.entry_index + offset]) + pd.Timedelta(minutes=1)
            curve.append({"time": mark_time, "equity": cash + notional * float(path_return)})
        cash += pnl
        trades.append({"candidate_id": row["candidate_id"], "symbol": row["symbol"],
                       "market": row["market"], "side": row["side"], "family": row["family"],
                       "signal_time": row["signal_time"],
                       "entry_time": arrays[row["symbol"]].time.iloc[outcome.entry_index],
                       "exit_time": outcome.exit_time, "exit_reason": outcome.exit_reason,
                       "entry_price": outcome.entry_price, "exit_price": outcome.exit_price,
                       "notional": notional, "net_return": outcome.net_return,
                       "net_r": outcome.net_r, "pnl": pnl, "equity_after": cash})
        next_free = outcome.exit_time
    result = metrics(trades, curve, 10_000.0, start, end)
    result.update({"stress": stress, "one_global_position": True,
                   "last_entry_buffer_minutes": max_hold,
                   "drawdown_measure": "minute-close mark-to-market plus simulated exit"})
    return result, trades


def gate_config(market: str) -> dict:
    if market == "spot":
        return {"market": market, "fee_bps": 10.0, "slippage_bps": 5.0,
                "stress_multiplier": 2.0}
    return {"market": market, "fee_bps": 5.0, "slippage_bps": 5.0,
            "stress_multiplier": 2.0}


def run_variant(market: str, family: str, horizon_name: str, max_hold: int,
                exit_name: str, exit_plan: str, candidates: pd.DataFrame,
                arrays: dict[str, MarketArrays], config: dict,
                ema_by_symbol: dict[str, dict[pd.Timestamp, float]],
                backend_filter: str | None = None, *, smoke: bool = False,
                precomputed_labels: pd.DataFrame | None = None) -> tuple[dict, list[dict]]:
    variant_id = f"{market.upper()}-{family.upper()}-{horizon_name.upper()}-{exit_name.upper()}"
    pool = candidates.loc[candidates.family == family].copy()
    labels = (precomputed_labels if precomputed_labels is not None else
              apply_labels(pool, arrays, {market: config}, exit_name, max_hold,
                           ema_by_symbol, smoke_limit=5 if smoke else None))
    if smoke:
        stress_outcome = None
        if not pool.empty:
            sample = pool.iloc[0].to_dict()
            stress_outcome = simulate(arrays[sample["symbol"]], sample, config,
                                      exit_name, max_hold, ema_by_symbol[sample["symbol"]],
                                      stress=True, trace=True)
        return {"variant_id": variant_id, "candidates": len(pool),
                "smoke_labeled": len(labels), "smoke_positive": int(labels.label.sum()) if not labels.empty else 0,
                "stress_smoke_exit_reason": stress_outcome.exit_reason if stress_outcome else None}, []
    train, calibration, selection_labels = split_labels(labels)
    selection_start = CALIBRATION_END + pd.Timedelta(minutes=EMBARGO_MINUTES)
    selection_pool = pool.loc[(pool.signal_time >= selection_start)
                              & (pool.signal_time < SELECTION_END - pd.Timedelta(minutes=max_hold))].copy()
    base_rows = selection_pool.copy()
    base_rows["probability"], base_rows["expected_r"] = 1.0, 1.0
    baseline_cache: dict[tuple[str, bool], CycleOutcome | None] = {}
    rule_base, _ = evaluate_portfolio(base_rows, arrays, {market: config}, exit_name,
                                      max_hold, ema_by_symbol, selection_start,
                                      SELECTION_END, stress=False,
                                      outcome_cache=baseline_cache)
    rule_stress, _ = evaluate_portfolio(base_rows, arrays, {market: config}, exit_name,
                                        max_hold, ema_by_symbol, selection_start,
                                        SELECTION_END, stress=True,
                                        outcome_cache=baseline_cache)
    rule_gate, rule_failures = passes(rule_base, rule_stress)
    record = {"variant_id": variant_id, "market": market, "family": family,
              "horizon": horizon_name, "max_hold_minutes": max_hold,
              "exit_mode": exit_name, "exit_plan": exit_plan, "candidate_count": len(pool),
              "labeled_count": len(labels), "train_rows": len(train),
              "train_class_counts": train.label.value_counts().sort_index().to_dict() if not train.empty else {},
              "calibration_rows": len(calibration),
              "calibration_class_counts": calibration.label.value_counts().sort_index().to_dict() if not calibration.empty else {},
              "selection_label_rows": len(selection_labels),
              "rule_baseline": {"base": rule_base, "stress": rule_stress,
                                "gate_passed": rule_gate, "failures": rule_failures},
              "backend": backend_filter, "training_performed": backend_filter is not None,
              "threshold_results": [], "selected_threshold": None,
              "research_gate_passed": False, "status": "target_not_demonstrated"}
    if backend_filter is None:
        return record, []
    try:
        classifier, regressor, calibrator, train_diag = fit_filter(train, calibration, backend_filter)
    except ValueError as exc:
        record["status"] = "insufficient_ml_training_data"
        record["training_error"] = str(exc)
        return record, []
    selection_scored = score_rows(selection_pool, classifier, regressor, calibrator)
    selection_cache: dict[tuple[str, bool], CycleOutcome | None] = {}
    for threshold in THRESHOLDS:
        eligible = selection_scored.loc[(selection_scored.probability >= threshold)
                                        & (selection_scored.expected_r >= MIN_EXPECTED_R)].copy()
        base, base_trades = evaluate_portfolio(eligible, arrays, {market: config},
                                              exit_name, max_hold, ema_by_symbol,
                                              selection_start, SELECTION_END, stress=False,
                                              outcome_cache=selection_cache)
        stress, stress_trades = evaluate_portfolio(eligible, arrays, {market: config},
                                                   exit_name, max_hold, ema_by_symbol,
                                                   selection_start, SELECTION_END, stress=True,
                                                   outcome_cache=selection_cache)
        passed, failures = passes(base, stress)
        record["threshold_results"].append({"threshold": threshold, "eligible_candidates": len(eligible),
                                            "base": base, "stress": stress,
                                            "gate_passed": passed, "failures": failures,
                                            "base_trades": base_trades,
                                            "stress_trades": stress_trades})
    eligible_results = [r for r in record["threshold_results"] if r["gate_passed"]]
    if eligible_results:
        chosen = min(eligible_results, key=lambda r: (
            r["base"]["max_drawdown"], -r["base"]["mean_net_return"],
            abs((r["base"]["win_rate"] or 0) - PREFERRED_WIN_RATE)))
        record["research_gate_passed"] = True
        record["status"] = "historical_selection_gates_met_not_prospective"
    elif record["threshold_results"]:
        chosen = max(record["threshold_results"], key=lambda r: (
            r["base"]["mean_net_return"] if r["base"]["mean_net_return"] is not None else -1,
            -r["base"]["max_drawdown"], r["base"]["trades"]))
    record["selected_threshold"] = chosen["threshold"]
    record["selected_result"] = {k: v for k, v in chosen.items()
                                  if k not in {"base_trades", "stress_trades"}}
    record["train_diagnostics"] = train_diag
    record["model_backend"] = backend_filter
    record["training_device"] = "cuda:0" if backend_filter == "xgboost_cuda" else "cpu"
    model_dir = OUTPUT / variant_id / backend_filter
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / "filter.joblib"
    joblib.dump({"classifier": classifier, "regressor": regressor,
                 "calibrator": calibrator, "features": list(FEATURES),
                 "threshold": record["selected_threshold"],
                 "minimum_expected_r": MIN_EXPECTED_R}, model_path, compress=3)
    record["model_path"] = str(model_path.relative_to(ROOT)).replace("\\", "/")
    record["model_sha256"] = digest(model_path)
    pred_path = model_dir / "selection_scores.csv"
    selection_scored.to_csv(pred_path, index=False, encoding="utf-8", lineterminator="\n")
    record["selection_scores_sha256"] = digest(pred_path)
    return record, []


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="build candidates and label five only; no model training")
    parser.add_argument("--market", choices=("spot", "usd_m"))
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    markets = [args.market] if args.market else ["spot", "usd_m"]
    all_reports = []
    all_data = []
    exit_preflight_records = []
    for market in markets:
        folder = "spot_btc_eth_1m" if market == "spot" else "usdm_btc_eth_1m"
        dataset_path = ROOT / "research/data" / folder
        candles, provenance = load_dataset(dataset_path, market)
        candles = candles.loc[candles.open_time < DATA_END].copy()
        config = gate_config(market)
        arrays: dict[str, MarketArrays] = {}
        ema_by_symbol: dict[str, dict[pd.Timestamp, float]] = {}
        candidate_frames = []
        for symbol, grouped in candles.groupby("symbol", sort=True):
            bars = grouped.reset_index(drop=True)
            arrays[symbol] = MarketArrays(bars)
            feature_frame, ema_map = market_features(bars)
            ema_by_symbol[symbol] = ema_map
            generated = generate_candidates(feature_frame, symbol, market,
                                            pd.DatetimeIndex(bars.open_time))
            candidate_frames.append(generated)
            print(f"CANDIDATES {market}/{symbol}: bars_1m={len(bars)} bars_15m={len(feature_frame)} events={len(generated)}", flush=True)
            del feature_frame, generated, bars
            gc.collect()
        candidates = pd.concat(candidate_frames, ignore_index=True)
        candidates = candidates.sort_values(["signal_time", "symbol", "family", "side"]).reset_index(drop=True)
        candidates["candidate_id"] = candidates.candidate_id.astype(str)
        data_record = {"market": market, "dataset_path": str(dataset_path.relative_to(ROOT)).replace("\\", "/"),
                       "dataset_sha256": provenance["data_sha256"],
                       "manifest_sha256": digest(dataset_path / "dataset.json"),
                       "rows": len(candles), "symbols": sorted(candles.symbol.unique()),
                       "first_open": pd.Timestamp(candles.open_time.min()).isoformat(),
                       "end_exclusive": DATA_END.isoformat(),
                       "source_receipts": len(provenance.get("receipts", [])),
                       "verified": bool(provenance.get("verified", False))}
        all_data.append(data_record)
        if args.smoke:
            for family in FAMILIES:
                for horizon_name, max_hold in HORIZONS:
                    for exit_name, exit_plan in EXITS:
                        variant_record, _ = run_variant(market, family, horizon_name,
                                                        max_hold, exit_name, exit_plan,
                                                        candidates, arrays, config,
                                                        ema_by_symbol, smoke=True)
                        print(json.dumps({"smoke": variant_record, "data": data_record}, ensure_ascii=False), flush=True)
            del candidates, arrays, ema_by_symbol, candles
            gc.collect()
            continue
        label_manifest: dict[str, dict[str, dict[str, Any]]] = {}
        for family in FAMILIES:
            for horizon_name, max_hold in HORIZONS:
                pool = candidates.loc[candidates.family == family].copy()
                manifest: dict[str, dict[str, Any]] = {}
                for exit_name, exit_plan in EXITS:
                    variant_id = f"{market.upper()}-{family.upper()}-{horizon_name.upper()}-{exit_name.upper()}"
                    print(f"LABEL_VARIANT_START {variant_id}", flush=True)
                    variant_dir = OUTPUT / variant_id
                    variant_dir.mkdir(parents=True, exist_ok=True)
                    labels = apply_labels(pool, arrays, {market: config}, exit_name,
                                          max_hold, ema_by_symbol)
                    labels_path = variant_dir / "candidate_labels.csv"
                    labels.to_csv(labels_path, index=False, encoding="utf-8", lineterminator="\n")
                    manifest[exit_name] = {
                        "variant_id": variant_id,
                        "labels_path": labels_path,
                        "labels_sha256": digest(labels_path),
                        "labeled_rows": len(labels),
                    }
                    print(f"LABEL_VARIANT_DONE {variant_id}: labeled={len(labels)} sha256={manifest[exit_name]['labels_sha256']}", flush=True)
                    del labels
                if len({row["labels_sha256"] for row in manifest.values()}) == 1:
                    raise RuntimeError(
                        f"Exit modes produced identical labels before training: {market}/{family}/{horizon_name}"
                    )
                print(f"EXIT_MODES_DISTINCT {market}/{family}/{horizon_name}", flush=True)
                exit_preflight_records.append({
                    "market": market,
                    "family": family,
                    "horizon": horizon_name,
                    "label_hashes": {mode: row["labels_sha256"]
                                     for mode, row in manifest.items()},
                    "distinct_label_hashes": len({row["labels_sha256"]
                                                   for row in manifest.values()}),
                })
                label_manifest[f"{family}:{horizon_name}"] = manifest
                del pool
                gc.collect()

        for family in FAMILIES:
            for horizon_name, max_hold in HORIZONS:
                pool = candidates.loc[candidates.family == family].copy()
                manifest = label_manifest[f"{family}:{horizon_name}"]
                for exit_name, exit_plan in EXITS:
                    variant_id = f"{market.upper()}-{family.upper()}-{horizon_name.upper()}-{exit_name.upper()}"
                    print(f"VARIANT_START {variant_id}", flush=True)
                    labels_path = manifest[exit_name]["labels_path"]
                    labels = pd.read_csv(labels_path)
                    for column in ("signal_time", "entry_time", "label_end_time"):
                        labels[column] = pd.to_datetime(labels[column], utc=True)
                    if labels.empty:
                        all_reports.append({"variant_id": variant_id, "market": market,
                                            "family": family, "horizon": horizon_name,
                                            "exit_mode": exit_name, "exit_plan": exit_plan,
                                            "status": "no_complete_labels"})
                        for backend in ("hist_cpu", "xgboost_cuda"):
                            all_reports.append({"variant_id": variant_id, "market": market,
                                                "backend": backend, "status": "no_complete_labels",
                                                "training_performed": False})
                        continue
                    # Rules and both ML backends share labels from this exact exit mode.
                    rule_record, _ = run_variant(market, family, horizon_name, max_hold,
                                                 exit_name, exit_plan, pool, arrays,
                                                 config, ema_by_symbol, backend_filter=None,
                                                 precomputed_labels=labels)
                    all_reports.append(rule_record)
                    train, calibration, selection = split_labels(labels)
                    for backend in ("hist_cpu", "xgboost_cuda"):
                        print(f"TRAIN_START {variant_id}/{backend}: train={len(train)} calibration={len(calibration)} selection={len(selection)}", flush=True)
                        record, _ = run_variant(market, family, horizon_name, max_hold,
                                               exit_name, exit_plan, pool, arrays,
                                               config, ema_by_symbol, backend_filter=backend,
                                               precomputed_labels=labels)
                        record["candidate_labels_path"] = str(labels_path.relative_to(ROOT)).replace("\\", "/")
                        record["candidate_labels_sha256"] = manifest[exit_name]["labels_sha256"]
                        all_reports.append(record)
                        print(f"TRAIN_DONE {variant_id}/{backend}: status={record.get('status')} threshold={record.get('selected_threshold')}", flush=True)
                    del labels
                del pool
                gc.collect()
        del candidates, arrays, ema_by_symbol, candles
        gc.collect()

    if args.smoke:
        print(json.dumps({"smoke_completed": True, "markets": markets,
                          "variants_per_market": 12, "training_performed": False,
                          "real_orders_sent": False}, ensure_ascii=False), flush=True)
        return

    report = {"created_utc": pd.Timestamp.now(tz="UTC").isoformat(),
              "status": "historical_exploratory_not_prospective",
              "pre_registration": "research/docs/CICLO02_PRE_REGISTRO.md",
              "correction_protocol": "research/docs/CICLO02_CORRECAO_SAIDAS_PROTOCOLO.md",
              "canonical_exit_modes": [name for name, _ in EXITS],
              "exit_mode_label_preflight": exit_preflight_records,
              "markets": markets, "data": all_data,
              "train_end_exclusive": TRAIN_END.isoformat(),
              "calibration_end_exclusive": CALIBRATION_END.isoformat(),
              "selection_end_exclusive": SELECTION_END.isoformat(),
              "embargo_minutes": EMBARGO_MINUTES, "features": list(FEATURES),
              "threshold_grid": list(THRESHOLDS), "minimum_expected_r": MIN_EXPECTED_R,
              "models": all_reports,
              "training_performed": any(row.get("training_performed", False) for row in all_reports),
              "gpu_training_performed": any(row.get("training_device") == "cuda:0" for row in all_reports),
              "real_orders_sent": False,
              "limitations": ["All historical periods are retrospective and previously inspected for related strategies.",
                              "Thresholds are selected on the historical selection block and require a later prospective paper evaluation.",
                              "XGBoost CUDA histogram training can be nondeterministic.",
                              "One-minute OHLC does not reveal intraminute order; ambiguous same-minute stop/target uses stop first."]}
    summary_path = OUTPUT / "research.json"
    summary_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False,
                                       default=lambda v: v.item() if isinstance(v, np.generic) else str(v)) + "\n",
                                encoding="utf-8")
    print(json.dumps({"status": report["status"], "variants": len(all_reports),
                      "training": report["training_performed"],
                      "gpu_training": report["gpu_training_performed"],
                      "output": str(summary_path)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
