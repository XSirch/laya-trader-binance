from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd

from laya_trader.config import AppConfig, load_config
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
    files = sorted(root.glob(f"{symbol}-{cfg.data.interval}-*.zip"))
    if not files:
        raise FileNotFoundError(f"no downloaded archives for {symbol} under {root}")
    frames = [_read_zip(path) for path in files]
    return normalize_klines(pd.concat(frames, ignore_index=True))


def _required_columns(cfg: AppConfig) -> list[str]:
    cols = ["atr14", *STATE_FEATURES]
    for tf in cfg.features.higher_timeframes:
        cols.extend(f"tf_{tf}_{name}" for name in STATE_FEATURES)
    return cols


def prepare_symbol(cfg: AppConfig, symbol: str) -> pd.DataFrame:
    raw = load_symbol_klines(cfg, symbol)
    features = build_feature_frame(raw, cfg.features.higher_timeframes)
    features["symbol"] = symbol
    features = features.iloc[cfg.features.warmup_bars :].copy()
    required = _required_columns(cfg)
    missing = [c for c in required if c not in features]
    if missing:
        raise ValueError(f"feature pipeline did not produce required columns: {missing}")
    features = features.dropna(subset=required).reset_index(drop=True)
    labeled = add_triple_barrier_labels(features, cfg.labels)
    return labeled


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
        if not combined.empty:
            combined.to_parquet(out_dir / f"{name}.parquet", index=False)
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
