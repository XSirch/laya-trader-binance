"""Exploratory 1h wider-barrier labels on the five-symbol research sample."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from laya_trader.config import load_config
from laya_trader.dataset.build import load_symbol_klines
from laya_trader.features.core import _aggregate_ohlcv, build_feature_frame


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "outputs/one_hour_probe"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")
BASE = (
    "trend_fast_atr", "trend_slow_atr", "rsi14", "adx14", "dist_ema20_atr",
    "dist_ema200_atr", "ret_1_z", "ret_4_z", "volume_z", "flow_imbalance",
    "atr_pct", "close_location",
)
FEATURES = (*BASE, *(f"tf_{tf}_{name}" for tf in ("4h", "1d") for name in BASE))
HORIZON = 24
STOP_ATR = 2.0
TAKE_ATR = 3.0
ROUND_TRIP_BPS = 14.0
THRESHOLDS = (0.05, 0.10, 0.15, 0.20)
FULL_TRAIN = "--full-train" in sys.argv


def hourly_candles(cfg, symbol: str) -> pd.DataFrame:
    raw = load_symbol_klines(cfg, symbol)
    raw = raw.loc[raw.timestamp < pd.Timestamp("2026-01-01", tz="UTC")].copy()
    groups = raw.timestamp.dt.floor("1h")
    complete = raw.groupby(groups, sort=True).size().eq(4)
    hourly = _aggregate_ohlcv(raw, "1h")
    hourly = hourly.loc[hourly.timestamp.dt.floor("1h").map(complete)].copy()
    hourly = hourly.sort_values("timestamp").reset_index(drop=True)
    hourly["segment"] = hourly.timestamp.diff().dt.total_seconds().ne(3600).cumsum()
    return hourly


def first_hit(mask: np.ndarray) -> np.ndarray:
    return np.where(mask.any(axis=1), mask.argmax(axis=1), HORIZON)


def relabel(rows: pd.DataFrame, hourly: pd.DataFrame) -> pd.DataFrame:
    row_pos = pd.Index(hourly.timestamp).get_indexer(rows.timestamp)
    valid = (row_pos >= 0) & (row_pos + HORIZON < len(hourly))
    result = rows.loc[valid].copy().reset_index(drop=True)
    pos = row_pos[valid]
    same_segment = (
        hourly.segment.to_numpy()[pos] == hourly.segment.to_numpy()[pos + HORIZON]
    )
    result = result.loc[same_segment].copy().reset_index(drop=True)
    pos = pos[same_segment]
    atr = result.atr14.to_numpy(float)
    opening = hourly.open.to_numpy(float)
    entry = opening[pos + 1]
    valid = np.isfinite(atr) & (atr > 0) & np.isfinite(entry) & (entry > 0)
    result = result.loc[valid].copy().reset_index(drop=True)
    pos, atr, entry = pos[valid], atr[valid], entry[valid]

    high = np.lib.stride_tricks.sliding_window_view(hourly.high.to_numpy(float)[1:], HORIZON)[pos]
    low = np.lib.stride_tricks.sliding_window_view(hourly.low.to_numpy(float)[1:], HORIZON)[pos]
    risk = STOP_ATR * atr
    long_tp = first_hit(high >= (entry + TAKE_ATR * atr)[:, None])
    long_sl = first_hit(low <= (entry - risk)[:, None])
    short_tp = first_hit(low <= (entry - TAKE_ATR * atr)[:, None])
    short_sl = first_hit(high >= (entry + risk)[:, None])
    exit_close = hourly.close.to_numpy(float)[pos + HORIZON]
    cost_r = ROUND_TRIP_BPS * 1e-4 / (risk / entry)
    # Same-bar TP and stop are treated as a stop, the conservative outcome.
    result["long_r"] = np.where(
        long_tp < long_sl, TAKE_ATR / STOP_ATR,
        np.where(long_sl < HORIZON, -1.0, (exit_close - entry) / risk),
    ) - cost_r
    result["short_r"] = np.where(
        short_tp < short_sl, TAKE_ATR / STOP_ATR,
        np.where(short_sl < HORIZON, -1.0, (entry - exit_close) / risk),
    ) - cost_r
    result["label_cost_r"] = cost_r
    result["label_end_ts"] = hourly.timestamp.to_numpy()[pos + HORIZON]
    return result


def build_labels() -> dict[str, pd.DataFrame]:
    cfg = load_config(ROOT / "configs/dataset.toml")
    columns = [*FEATURES, "symbol", "timestamp", "atr14"]
    splits = {
        name: pd.read_parquet(DATA / f"{name}.parquet", columns=columns)
        for name in ("train", "calibration", "validation")
    }
    result: dict[str, list[pd.DataFrame]] = {name: [] for name in splits}
    for symbol in SYMBOLS:
        start = time.monotonic()
        hourly = hourly_candles(cfg, symbol)
        for name, frame in splits.items():
            if name == "train" and FULL_TRAIN:
                subset = build_feature_frame(hourly.drop(columns="segment"), ("4h", "1d"))
                subset["symbol"] = symbol
                subset = subset.loc[
                    (subset.timestamp >= pd.Timestamp("2023-01-01", tz="UTC"))
                    & (subset.timestamp < pd.Timestamp("2025-01-01", tz="UTC"))
                ].dropna(subset=["atr14", *FEATURES])
            else:
                subset = frame.loc[frame.symbol == symbol]
            labeled = relabel(subset, hourly)
            result[name].append(labeled)
        print(
            "labeled", symbol, {name: len(result[name][-1]) for name in result},
            "seconds", round(time.monotonic() - start, 1), flush=True,
        )
    merged = {name: pd.concat(chunks, ignore_index=True) for name, chunks in result.items()}
    merged["train"] = merged["train"].loc[
        merged["train"].timestamp >= pd.Timestamp("2023-01-01", tz="UTC")
    ].reset_index(drop=True)
    cutoffs = {
        "train": cfg.splits.train_end,
        "calibration": cfg.splits.calibration_end,
        "validation": cfg.splits.validation_end,
    }
    for name, cutoff in cutoffs.items():
        merged[name] = merged[name].loc[
            merged[name].label_end_ts <= pd.Timestamp(cutoff)
        ].reset_index(drop=True)
    assert merged["train"].timestamp.max() < merged["calibration"].timestamp.min()
    assert merged["calibration"].timestamp.max() < merged["validation"].timestamp.min()
    print("rows", {name: len(frame) for name, frame in merged.items()}, flush=True)
    return merged


def inputs(splits: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    result = {}
    for name, frame in splits.items():
        onehot = pd.get_dummies(
            pd.Categorical(frame.symbol, categories=SYMBOLS), prefix="symbol", dtype=float,
        ).reset_index(drop=True)
        result[name] = pd.concat([frame[list(FEATURES)].reset_index(drop=True), onehot], axis=1)
    return result


def executed_trades(frame: pd.DataFrame, predictions: np.ndarray, threshold: float) -> pd.DataFrame:
    side = predictions.argmax(axis=1)
    selected = predictions.max(axis=1) >= threshold
    signals = frame.loc[selected, ["symbol", "timestamp", "label_end_ts", "label_cost_r"]].copy()
    signals["prediction"] = predictions.max(axis=1)[selected]
    signals["side"] = np.where(side[selected] == 0, "long", "short")
    signals["R"] = np.where(side == 0, frame.long_r, frame.short_r)[selected]
    signals = signals.sort_values(["timestamp", "prediction"], ascending=[True, False])
    accepted = []
    occupied_until = {}
    for row in signals.itertuples():
        if row.timestamp >= occupied_until.get(row.symbol, pd.Timestamp.min.tz_localize("UTC")):
            accepted.append(row.Index)
            occupied_until[row.symbol] = row.label_end_ts
    return signals.loc[accepted].reset_index(drop=True)


def score(frame: pd.DataFrame, predictions: np.ndarray, threshold: float) -> dict:
    selected = predictions.max(axis=1) >= threshold
    executed = executed_trades(frame, predictions, threshold)
    returns = executed.R.to_numpy()
    stressed = returns - executed.label_cost_r.to_numpy() * (4 / ROUND_TRIP_BPS)
    monthly = executed.groupby(executed.timestamp.dt.strftime("%Y-%m")).R.mean()
    return {
        "signals": int(selected.sum()),
        "trades": len(executed),
        "mean_R": round(float(returns.mean()), 5) if len(returns) else None,
        "stress_extra_4bps_mean_R": round(float(stressed.mean()), 5) if len(stressed) else None,
        "profitable_months": int((monthly > 0).sum()),
        "months": len(monthly),
        "monthly_R": monthly.round(5).to_dict(),
    }


def main() -> None:
    splits = build_labels()
    matrices = inputs(splits)
    predictions: dict[str, list[np.ndarray]] = {"calibration": [], "validation": []}
    for side in ("long", "short"):
        model = HistGradientBoostingRegressor(
            max_iter=80, max_leaf_nodes=7, learning_rate=0.05,
            l2_regularization=20, min_samples_leaf=300,
            random_state=42, early_stopping=False,
        )
        model.fit(matrices["train"], splits["train"][f"{side}_r"])
        for name in predictions:
            predictions[name].append(model.predict(matrices[name]))
        print("fitted", side, flush=True)
    pred_cal = np.column_stack(predictions["calibration"])
    pred_val = np.column_stack(predictions["validation"])
    candidates = [(threshold, score(splits["calibration"], pred_cal, threshold))
                  for threshold in THRESHOLDS]
    eligible = [(threshold, result) for threshold, result in candidates
                if result["trades"] >= 100 and result["mean_R"] > 0
                and result["profitable_months"] >= 4]
    chosen = max(eligible, key=lambda row: row[1]["mean_R"], default=None)
    report = {
        "hypothesis": "1h bars, 24h horizon, take 3 ATR, stop 2 ATR, 14 bps round trip",
        "training_sample": "full 2023-2024 hourly bars" if FULL_TRAIN else "existing even sample",
        "rows": {name: len(frame) for name, frame in splits.items()},
        "calibration": candidates,
        "selected": chosen,
        "validation": score(splits["validation"], pred_val, chosen[0]) if chosen else None,
    }
    if chosen:
        trades = executed_trades(splits["validation"], pred_val, chosen[0])
        suffix = "full_train_" if FULL_TRAIN else ""
        trades.to_parquet(
            ROOT / f"outputs/wide_barrier_{suffix}validation_trades.parquet", index=False,
        )
    output = ROOT / (
        "outputs/wide_barrier_full_train_report.json" if FULL_TRAIN
        else "outputs/wide_barrier_probe_report.json"
    )
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    print("saved", output, flush=True)


if __name__ == "__main__":
    main()
