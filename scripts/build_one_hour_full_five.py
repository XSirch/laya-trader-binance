"""Build uncapped 1h labels for the five-symbol CPU research universe through 2025."""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from laya_trader.config import load_config
from laya_trader.dataset.build import STATE_FEATURES, load_symbol_klines
from laya_trader.dataset.splits import split_frame
from laya_trader.features.core import _aggregate_ohlcv, build_feature_frame
from laya_trader.labels.triple_barrier import add_triple_barrier_labels


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/one_hour_full_five"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")
HIGHER = ("4h", "1d")


def hourly_candles(raw: pd.DataFrame) -> pd.DataFrame:
    raw = raw.loc[raw.timestamp < pd.Timestamp("2026-01-01", tz="UTC")].copy()
    complete = raw.groupby(raw.timestamp.dt.floor("1h"), sort=True).size().eq(4)
    hourly = _aggregate_ohlcv(raw, "1h")
    hourly = hourly.loc[hourly.timestamp.dt.floor("1h").map(complete)].copy()
    hourly = hourly.sort_values("timestamp").reset_index(drop=True)
    hourly["segment"] = hourly.timestamp.diff().dt.total_seconds().ne(3600).cumsum()
    return hourly


def main() -> None:
    cfg = load_config(ROOT / "configs/dataset.toml")
    required = ["atr14", *STATE_FEATURES]
    required += [f"tf_{tf}_{name}" for tf in HIGHER for name in STATE_FEATURES]
    frames: dict[str, list[pd.DataFrame]] = {name: [] for name in ("train", "calibration", "validation")}
    OUT.mkdir(parents=True, exist_ok=True)
    for symbol in SYMBOLS:
        start = time.monotonic()
        hourly = hourly_candles(load_symbol_klines(cfg, symbol))
        labeled_segments = []
        for _, segment in hourly.groupby("segment", sort=True):
            if len(segment) <= 250 + cfg.labels.horizon_bars:
                continue
            features = build_feature_frame(segment.drop(columns="segment"), HIGHER)
            features["symbol"] = symbol
            features = features.iloc[250:].dropna(subset=required).reset_index(drop=True)
            if len(features) <= cfg.labels.horizon_bars:
                continue
            labels = add_triple_barrier_labels(features, cfg.labels)
            if not labels.empty:
                labeled_segments.append(labels)
        if not labeled_segments:
            raise ValueError(f"no labeled rows for {symbol}")
        labeled = pd.concat(labeled_segments, ignore_index=True)
        splits = split_frame(labeled, cfg.splits, "1h")
        splits["train"] = splits["train"].loc[
            splits["train"].timestamp >= pd.Timestamp("2023-01-01", tz="UTC")
        ]
        for name in frames:
            frames[name].append(splits[name])
        print(
            "symbol", symbol, {name: len(splits[name]) for name in frames},
            "seconds", round(time.monotonic() - start, 1), flush=True,
        )
    for name, chunks in frames.items():
        result = pd.concat(chunks, ignore_index=True)
        path = OUT / f"{name}.parquet"
        result.to_parquet(path, index=False)
        print("saved", name, len(result), path.stat().st_size, flush=True)


if __name__ == "__main__":
    main()
