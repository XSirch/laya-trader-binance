"""Exploratory daily-bar directional model with a five-day trading horizon."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from funding_probe import nonoverlap, score
from laya_trader.config import load_config
from laya_trader.dataset.build import load_symbol_klines
from laya_trader.dataset.splits import split_frame
from laya_trader.features.core import _aggregate_ohlcv, compute_features
from laya_trader.labels.triple_barrier import add_triple_barrier_labels


ROOT = Path(__file__).resolve().parents[1]
FEATURES = (
    "trend_fast_atr", "trend_slow_atr", "rsi14", "adx14",
    "dist_ema20_atr", "dist_ema200_atr", "ret_1_z", "ret_4_z",
    "volume_z", "flow_imbalance", "atr_pct", "close_location",
)
THRESHOLDS = (0.05, 0.10, 0.15, 0.20)


def daily_candles(raw: pd.DataFrame) -> pd.DataFrame:
    raw = raw.loc[raw.timestamp < pd.Timestamp("2026-01-01", tz="UTC")].copy()
    complete = raw.groupby(raw.timestamp.dt.floor("1d"), sort=True).size().eq(96)
    daily = _aggregate_ohlcv(raw, "1d")
    daily = daily.loc[daily.timestamp.dt.floor("1d").map(complete)].copy()
    daily = daily.sort_values("timestamp").reset_index(drop=True)
    daily["segment"] = daily.timestamp.diff().dt.total_seconds().ne(86400).cumsum()
    return daily


def build() -> tuple[dict[str, pd.DataFrame], tuple[str, ...]]:
    cfg = load_config(ROOT / "configs/dataset.toml")
    labels_cfg = replace(
        cfg.labels, horizon_bars=5, take_profit_atr=3.0,
        stop_loss_atr=2.0, drop_ambiguous=False,
    )
    symbols = cfg.data.symbols
    frames: dict[str, list[pd.DataFrame]] = {name: [] for name in ("train", "calibration", "validation")}
    for symbol in symbols:
        start = time.monotonic()
        daily = daily_candles(load_symbol_klines(cfg, symbol))
        labeled_segments = []
        for _, segment in daily.groupby("segment", sort=True):
            if len(segment) <= 200 + labels_cfg.horizon_bars:
                continue
            features = compute_features(segment.drop(columns="segment"))
            features["symbol"] = symbol
            features = features.iloc[200:].dropna(subset=["atr14", *FEATURES])
            if len(features) <= labels_cfg.horizon_bars:
                continue
            labeled = add_triple_barrier_labels(features.reset_index(drop=True), labels_cfg)
            labeled.loc[labeled.long_ambiguous, "long_r"] = (
                -1.0 - labeled.loc[labeled.long_ambiguous, "label_cost_r"]
            )
            labeled.loc[labeled.short_ambiguous, "short_r"] = (
                -1.0 - labeled.loc[labeled.short_ambiguous, "label_cost_r"]
            )
            labeled_segments.append(labeled)
        if not labeled_segments:
            print("symbol", symbol, "no labels", flush=True)
            continue
        labeled = pd.concat(labeled_segments, ignore_index=True)
        splits = split_frame(labeled, cfg.splits, "1d")
        splits["train"] = splits["train"].loc[
            splits["train"].timestamp >= pd.Timestamp("2023-01-01", tz="UTC")
        ]
        for name in frames:
            frames[name].append(splits[name])
        print(
            "symbol", symbol, {name: len(splits[name]) for name in frames},
            "seconds", round(time.monotonic() - start, 1), flush=True,
        )
    merged = {name: pd.concat(chunks, ignore_index=True) for name, chunks in frames.items()}
    print("rows", {name: len(frame) for name, frame in merged.items()}, flush=True)
    return merged, symbols


def matrices(splits: dict[str, pd.DataFrame], symbols: tuple[str, ...]) -> dict[str, pd.DataFrame]:
    result = {}
    for name, frame in splits.items():
        onehot = pd.get_dummies(
            pd.Categorical(frame.symbol, categories=symbols), prefix="symbol", dtype=float,
        ).reset_index(drop=True)
        result[name] = pd.concat([frame[list(FEATURES)].reset_index(drop=True), onehot], axis=1)
    return result


def selected_trades(frame: pd.DataFrame, predictions: np.ndarray, threshold: float) -> pd.DataFrame:
    side = predictions.argmax(axis=1)
    selected = predictions.max(axis=1) >= threshold
    signals = frame.loc[selected, ["symbol", "timestamp", "label_end_ts", "label_cost_r"]].copy()
    signals["prediction"] = predictions.max(axis=1)[selected]
    signals["side"] = np.where(side[selected] == 0, "long", "short")
    signals["R"] = np.where(side == 0, frame.long_r, frame.short_r)[selected]
    return nonoverlap(signals).reset_index(drop=True)


def main() -> None:
    splits, symbols = build()
    x = matrices(splits, symbols)
    predictions: dict[str, list[np.ndarray]] = {"calibration": [], "validation": []}
    for side in ("long", "short"):
        model = HistGradientBoostingRegressor(
            max_iter=80, max_leaf_nodes=7, learning_rate=0.05,
            l2_regularization=20, min_samples_leaf=100,
            random_state=42, early_stopping=False,
        )
        model.fit(x["train"], splits["train"][f"{side}_r"])
        for name in predictions:
            predictions[name].append(model.predict(x[name]))
        print("fitted", side, flush=True)
    pred_cal = np.column_stack(predictions["calibration"])
    pred_val = np.column_stack(predictions["validation"])
    options = [(threshold, score(splits["calibration"], pred_cal, threshold))
               for threshold in THRESHOLDS]
    minimum_cal = max(100, int(len(splits["calibration"]) * 0.005))
    eligible = [(threshold, result) for threshold, result in options
                if result["trades"] >= minimum_cal and result["mean_R"] > 0
                and result["profitable_months"] >= 4]
    selected = max(eligible, key=lambda row: row[1]["mean_R"], default=None)
    validation = score(splits["validation"], pred_val, selected[0]) if selected else None
    minimum_val = max(100, int(len(splits["validation"]) * 0.005))
    report = {
        "hypothesis": "daily bars, five-day horizon, 3 ATR take, 2 ATR stop, 14 bps round trip",
        "symbols": list(symbols),
        "rows": {name: len(frame) for name, frame in splits.items()},
        "minimum_calibration_trades": minimum_cal,
        "minimum_validation_trades": minimum_val,
        "calibration": options,
        "selected": selected,
        "validation": validation,
        "validation_gate": (
            validation["trades"] >= minimum_val and validation["mean_R"] > 0
            and validation["profitable_months"] >= 4
        ) if validation else None,
    }
    if selected:
        selected_trades(splits["validation"], pred_val, selected[0]).to_parquet(
            ROOT / "outputs/daily_trend_validation_trades.parquet", index=False,
        )
    output = ROOT / "outputs/daily_trend_probe_report.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    print("saved", output, flush=True)


if __name__ == "__main__":
    main()
