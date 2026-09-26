from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DataConfig:
    market: str = "um"
    interval: str = "15m"
    start: str = "2020-01-01"
    end: str = "2026-08-31"
    raw_dir: Path = Path("data/raw")
    processed_dir: Path = Path("data/processed")
    dataset_dir: Path = Path("data/dataset")
    workers: int = 8
    symbols: tuple[str, ...] = ()


@dataclass(frozen=True)
class FeatureConfig:
    warmup_bars: int = 250
    higher_timeframes: tuple[str, ...] = ("1h", "4h")
    include_symbol: bool = True


@dataclass(frozen=True)
class LabelConfig:
    horizon_bars: int = 16
    take_profit_atr: float = 2.0
    stop_loss_atr: float = 1.0
    fee_bps_per_side: float = 5.0
    slippage_bps_per_side: float = 2.0
    min_edge_r: float = 0.10
    target_temperature: float = 0.35
    tradeable_temperature: float = 0.25
    drop_ambiguous: bool = False


@dataclass(frozen=True)
class SplitConfig:
    train_end: str = "2024-12-31T23:59:59Z"
    calibration_end: str = "2025-06-30T23:59:59Z"
    validation_end: str = "2025-12-31T23:59:59Z"
    test_end: str = "2026-08-31T23:59:59Z"
    embargo_bars: int = 16


@dataclass(frozen=True)
class SamplingConfig:
    seed: int = 42
    max_rows_per_symbol_per_split: int = 5_000


@dataclass(frozen=True)
class AppConfig:
    data: DataConfig = field(default_factory=DataConfig)
    features: FeatureConfig = field(default_factory=FeatureConfig)
    labels: LabelConfig = field(default_factory=LabelConfig)
    splits: SplitConfig = field(default_factory=SplitConfig)
    sampling: SamplingConfig = field(default_factory=SamplingConfig)


def _section(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key, {})
    if not isinstance(value, dict):
        raise TypeError(f"[{key}] must be a TOML table")
    return value


def load_config(path: str | Path) -> AppConfig:
    path = Path(path)
    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    data = _section(raw, "data")
    features = _section(raw, "features")
    labels = _section(raw, "labels")
    splits = _section(raw, "splits")
    sampling = _section(raw, "sampling")

    root = path.parent.parent if path.parent.name == "configs" else Path.cwd()

    def rel(p: str) -> Path:
        q = Path(p)
        return q if q.is_absolute() else root / q

    return AppConfig(
        data=DataConfig(
            market=str(data.get("market", "um")),
            interval=str(data.get("interval", "15m")),
            start=str(data.get("start", "2020-01-01")),
            end=str(data.get("end", "2026-08-31")),
            raw_dir=rel(str(data.get("raw_dir", "data/raw"))),
            processed_dir=rel(str(data.get("processed_dir", "data/processed"))),
            dataset_dir=rel(str(data.get("dataset_dir", "data/dataset"))),
            workers=int(data.get("workers", 8)),
            symbols=tuple(str(x).upper() for x in data.get("symbols", [])),
        ),
        features=FeatureConfig(
            warmup_bars=int(features.get("warmup_bars", 250)),
            higher_timeframes=tuple(str(x) for x in features.get("higher_timeframes", ["1h", "4h"])),
            include_symbol=bool(features.get("include_symbol", True)),
        ),
        labels=LabelConfig(**{k: labels[k] for k in LabelConfig.__dataclass_fields__ if k in labels}),
        splits=SplitConfig(**{k: splits[k] for k in SplitConfig.__dataclass_fields__ if k in splits}),
        sampling=SamplingConfig(
            seed=int(sampling.get("seed", 42)),
            max_rows_per_symbol_per_split=int(
                sampling.get("max_rows_per_symbol_per_split", 5_000)
            ),
        ),
    )


def interval_to_timedelta(interval: str):
    import pandas as pd

    unit = interval[-1]
    value = int(interval[:-1])
    if unit == "m":
        return pd.Timedelta(minutes=value)
    if unit == "h":
        return pd.Timedelta(hours=value)
    if unit == "d":
        return pd.Timedelta(days=value)
    if unit == "w":
        return pd.Timedelta(weeks=value)
    raise ValueError(f"unsupported interval: {interval!r}")
