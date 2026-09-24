from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from laya_trader.config import AppConfig, interval_to_timedelta, load_config
from laya_trader.data.binance_public import month_keys
from laya_trader.dataset.splits import split_frame
from laya_trader.dataset.state import build_state
from laya_trader.features.core import KLINE_COLUMNS, build_feature_frame, normalize_klines
from laya_trader.labels.triple_barrier import add_triple_barrier_labels

STATE_FEATURES = (
    "trend_fast_atr",
    "trend_slow_atr",
    "rsi14",
    "adx14",
    "dist_ema20_atr",
    "dist_ema200_atr",
    "ret_1_z",
    "ret_4_z",
    "volume_z",
    "flow_imbalance",
    "atr_pct",
    "close_location",
)


def _read_zip(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        if not names:
            raise ValueError(f"empty archive: {path}")
        with zf.open(names[0]) as fh:
            frame = pd.read_csv(fh, header=None)
    if frame.shape[1] != len(KLINE_COLUMNS):
        raise ValueError(f"{path}: expected {len(KLINE_COLUMNS)} columns, got {frame.shape[1]}")
    numeric_open_time = pd.to_numeric(frame.iloc[:, 0], errors="coerce")
    frame = frame.loc[numeric_open_time.notna()].copy()
    frame.columns = KLINE_COLUMNS
    return frame


def _configured_archive_paths(
    root: Path,
    symbol: str,
    interval: str,
    start: str,
    end: str,
) -> list[Path]:
    return [
        path
        for month in month_keys(start, end)
        if (path := root / f"{symbol}-{interval}-{month}.zip").exists()
    ]


def _range_bound(value: str, *, end: bool) -> pd.Timestamp:
    raw = str(value).strip()
    ts = pd.Timestamp(raw)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    if end and re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        ts = ts + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    return ts


def _clip_to_configured_range(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    start_ts = _range_bound(start, end=False)
    end_ts = _range_bound(end, end=True)
    if start_ts > end_ts:
        raise ValueError(f"data.start {start!r} is after data.end {end!r}")
    out = df.loc[(df["timestamp"] >= start_ts) & (df["timestamp"] <= end_ts)].copy()
    return out.reset_index(drop=True)


def _mark_contiguous_segments(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    if df.empty:
        return df.assign(_segment_id=pd.Series(dtype="int64"))
    expected = interval_to_timedelta(interval)
    diffs = df["open_time"].diff()
    starts = diffs.ne(expected)
    starts.iloc[0] = True
    out = df.copy()
    out["_segment_id"] = starts.cumsum().astype(int) - 1
    return out


def load_symbol_klines(cfg: AppConfig, symbol: str) -> pd.DataFrame:
    root = (
        cfg.data.raw_dir
        / "binance"
        / "futures"
        / cfg.data.market
        / "monthly"
        / "klines"
        / symbol
        / cfg.data.interval
    )
    files = _configured_archive_paths(
        root,
        symbol,
        cfg.data.interval,
        cfg.data.start,
        cfg.data.end,
    )
    if not files:
        raise FileNotFoundError(
            f"no downloaded archives for {symbol} in configured range under {root}"
        )
    frames = [_read_zip(path) for path in files]
    normalized = normalize_klines(pd.concat(frames, ignore_index=True))
    clipped = _clip_to_configured_range(normalized, cfg.data.start, cfg.data.end)
    if clipped.empty:
        raise ValueError(f"{symbol}: no candles inside configured data range")
    return _mark_contiguous_segments(clipped, cfg.data.interval)


def _required_columns(cfg: AppConfig) -> list[str]:
    cols = ["atr14", *STATE_FEATURES]
    for tf in cfg.features.higher_timeframes:
        cols.extend(f"tf_{tf}_{name}" for name in STATE_FEATURES)
    return cols


def prepare_symbol(cfg: AppConfig, symbol: str) -> pd.DataFrame:
    raw = load_symbol_klines(cfg, symbol)
    required = _required_columns(cfg)
    labeled_segments: list[pd.DataFrame] = []

    for segment_id, segment in raw.groupby("_segment_id", sort=True):
        segment = segment.drop(columns=["_segment_id"]).reset_index(drop=True)
        if len(segment) <= cfg.features.warmup_bars + cfg.labels.horizon_bars:
            continue

        features = build_feature_frame(segment, cfg.features.higher_timeframes)
        features["symbol"] = symbol
        features["_segment_id"] = int(segment_id)
        features = features.iloc[cfg.features.warmup_bars :].copy()

        missing = [name for name in required if name not in features]
        if missing:
            raise ValueError(f"feature pipeline did not produce required columns: {missing}")
        features = features.dropna(subset=required).reset_index(drop=True)
        if len(features) <= cfg.labels.horizon_bars:
            continue

        labeled = add_triple_barrier_labels(features, cfg.labels)
        if not labeled.empty:
            labeled_segments.append(labeled)

    if not labeled_segments:
        raise ValueError(
            f"{symbol}: no contiguous segment is long enough to build fully causal labels"
        )
    return pd.concat(labeled_segments, ignore_index=True)


def _targets(row: pd.Series) -> dict:
    return {
        "action": [float(row["target_long"]), float(row["target_short"]), float(row["target_flat"])],
        "tradeable": [float(row["target_trade_false"]), float(row["target_trade_true"])],
        "edge_quality": [float(row[f"target_edge_{i}"]) for i in range(5)],
    }


def _record(row: pd.Series, cfg: AppConfig) -> dict:
    symbol = str(row["symbol"])
    state = build_state(
        row,
        symbol=symbol,
        interval=cfg.data.interval,
        higher_timeframes=cfg.features.higher_timeframes,
        include_symbol=cfg.features.include_symbol,
    )
    ts = pd.Timestamp(row["timestamp"])
    return {
        "id": f"{symbol}:{ts.isoformat()}",
        "symbol": symbol,
        "decision_time": ts.isoformat(),
        "state": state,
        "targets": _targets(row),
        "diagnostics": {
            "long_r": round(float(row["long_r"]), 6),
            "short_r": round(float(row["short_r"]), 6),
            "cost_r": round(float(row["label_cost_r"]), 6),
            "label_end_time": pd.Timestamp(row["label_end_ts"]).isoformat(),
        },
    }


def _even_cap(df: pd.DataFrame, cap: int) -> pd.DataFrame:
    if cap <= 0 or len(df) <= cap:
        return df
    idx = np.linspace(0, len(df) - 1, cap, dtype=int)
    return df.iloc[np.unique(idx)].reset_index(drop=True)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def build_dataset(config_path: str | Path) -> dict:
    cfg = load_config(config_path)
    out_dir = cfg.data.dataset_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    per_split: dict[str, list[pd.DataFrame]] = {
        k: [] for k in ("train", "calibration", "validation", "test")
    }
    errors: dict[str, str] = {}

    for symbol in cfg.data.symbols:
        try:
            labeled = prepare_symbol(cfg, symbol)
        except (FileNotFoundError, ValueError) as exc:
            errors[symbol] = str(exc)
            print(f"skip {symbol}: {exc}")
            continue
        splits = split_frame(labeled, cfg.splits, cfg.data.interval)
        for name, frame in splits.items():
            frame = _even_cap(frame, cfg.sampling.max_rows_per_symbol_per_split)
            if not frame.empty:
                per_split[name].append(frame)
        print(symbol, {k: len(v) for k, v in splits.items()})

    manifest: dict = {
        "schema_version": 1,
        "config_sha256": hashlib.sha256(Path(config_path).read_bytes()).hexdigest(),
        "label_policy": {
            "horizon_bars": cfg.labels.horizon_bars,
            "take_profit_atr": cfg.labels.take_profit_atr,
            "stop_loss_atr": cfg.labels.stop_loss_atr,
            "fee_bps_per_side": cfg.labels.fee_bps_per_side,
            "slippage_bps_per_side": cfg.labels.slippage_bps_per_side,
            "min_edge_r": cfg.labels.min_edge_r,
        },
        "splits": {},
        "errors": errors,
    }

    for name, frames in per_split.items():
        combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        records = [_record(row, cfg) for _, row in combined.iterrows()]
        _write_jsonl(out_dir / f"{name}.jsonl", records)
        parquet_path = out_dir / f"{name}.parquet"
        if not combined.empty:
            combined.to_parquet(parquet_path, index=False)
            action = np.argmax(
                combined[["target_long", "target_short", "target_flat"]].to_numpy(), axis=1
            )
            counts = {
                "LONG": int((action == 0).sum()),
                "SHORT": int((action == 1).sum()),
                "FLAT": int((action == 2).sum()),
            }
            manifest["splits"][name] = {
                "rows": len(combined),
                "symbols": sorted(combined["symbol"].unique().tolist()),
                "start": pd.Timestamp(combined["timestamp"].min()).isoformat(),
                "end": pd.Timestamp(combined["timestamp"].max()).isoformat(),
                "argmax_action": counts,
            }
        else:
            parquet_path.unlink(missing_ok=True)
            manifest["splits"][name] = {"rows": 0, "symbols": [], "argmax_action": {}}

    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build leakage-aware Laya trading dataset")
    parser.add_argument("--config", default="configs/dataset.toml")
    args = parser.parse_args(argv)
    manifest = build_dataset(args.config)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
