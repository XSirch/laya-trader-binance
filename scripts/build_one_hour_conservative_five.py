"""Build five-symbol 1h research labels without future-dependent row exclusion."""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pandas as pd

from build_one_hour_full_five import HIGHER, SYMBOLS, hourly_candles
from laya_trader.config import load_config
from laya_trader.dataset.build import STATE_FEATURES, _even_cap, load_symbol_klines
from laya_trader.dataset.splits import split_frame
from laya_trader.features.core import build_feature_frame
from laya_trader.labels.triple_barrier import add_triple_barrier_labels


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/one_hour_conservative_five"


def main() -> None:
    cfg = load_config(ROOT / "configs/dataset.toml")
    conservative_labels = replace(cfg.labels, drop_ambiguous=False)
    required = ["atr14", *STATE_FEATURES]
    required += [f"tf_{tf}_{name}" for tf in HIGHER for name in STATE_FEATURES]
    splits_by_name: dict[str, list[pd.DataFrame]] = {
        name: [] for name in ("train", "train_even", "calibration", "validation")
    }
    OUT.mkdir(parents=True, exist_ok=True)
    for symbol in SYMBOLS:
        started = time.monotonic()
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
            labels = add_triple_barrier_labels(features, conservative_labels)
            if labels.empty:
                continue
            labeled_segments.append(labels)
        if not labeled_segments:
            raise ValueError(f"No 1h labels for {symbol}")
        labeled = pd.concat(labeled_segments, ignore_index=True)
        splits = split_frame(labeled, cfg.splits, "1h")
        splits["train_even"] = _even_cap(
            splits["train"], cfg.sampling.max_rows_per_symbol_per_split
        )
        splits["train"] = splits["train"].loc[
            splits["train"].timestamp >= pd.Timestamp("2023-01-01", tz="UTC")
        ]
        splits["train_even"] = splits["train_even"].loc[
            splits["train_even"].timestamp >= pd.Timestamp("2023-01-01", tz="UTC")
        ]
        for name, chunks in splits_by_name.items():
            chunks.append(splits[name])
        print("symbol", symbol,
              {name: {"rows": len(splits[name]),
                      "ambiguous_long": int(splits[name].long_ambiguous.sum()),
                      "ambiguous_short": int(splits[name].short_ambiguous.sum())}
               for name in splits_by_name},
              "seconds", round(time.monotonic() - started, 1), flush=True)
    for name, chunks in splits_by_name.items():
        frame = pd.concat(chunks, ignore_index=True)
        path = OUT / f"{name}.parquet"
        frame.to_parquet(path, index=False)
        print("saved", name, len(frame), path.stat().st_size, flush=True)


if __name__ == "__main__":
    main()
