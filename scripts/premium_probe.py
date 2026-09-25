"""Exploratory 1h premium-index feature probe on already prepared labels."""

from __future__ import annotations

import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from sklearn.ensemble import HistGradientBoostingRegressor


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "outputs/one_hour_probe"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")
BASE = [
    "trend_fast_atr", "trend_slow_atr", "rsi14", "adx14", "dist_ema20_atr",
    "dist_ema200_atr", "ret_1_z", "ret_4_z", "volume_z", "flow_imbalance",
    "atr_pct", "close_location",
]
FEATURES = BASE + [f"tf_{tf}_{name}" for tf in ("4h", "1d") for name in BASE]
PREMIUM_FEATURES = ["premium_close", "premium_8h_mean", "premium_168h_z", "premium_change_8h"]
THRESHOLDS = (0.05, 0.075, 0.1, 0.15)


def get_archive(symbol: str, month: str) -> tuple[str, str, pd.DataFrame | None]:
    url = (
        "https://data.binance.vision/data/futures/um/monthly/premiumIndexKlines/"
        f"{symbol}/1h/{symbol}-1h-{month}.zip"
    )
    response = requests.get(url, timeout=30)
    if response.status_code == 404:
        return symbol, month, None
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        if archive.testzip() is not None:
            raise ValueError(f"bad ZIP member in {url}")
        with archive.open(archive.namelist()[0]) as stream:
            frame = pd.read_csv(stream, usecols=["close_time", "close"])
    frame["symbol"] = symbol
    return symbol, month, frame


def premium_history() -> pd.DataFrame:
    cache = ROOT / "outputs/premium_2023_2025.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    months = pd.period_range("2023-01", "2025-12", freq="M").astype(str)
    tasks = [(symbol, month) for symbol in SYMBOLS for month in months]
    frames = []
    missing = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(get_archive, *task) for task in tasks]
        for count, future in enumerate(as_completed(futures), 1):
            symbol, month, frame = future.result()
            if frame is None:
                missing.append(f"{symbol}:{month}")
            else:
                frames.append(frame)
            if count % 20 == 0 or count == len(tasks):
                print(f"premium archives {count}/{len(tasks)}", flush=True)
    if missing:
        raise RuntimeError(f"missing premium archives: {missing}")
    result = pd.concat(frames, ignore_index=True)
    result["close_time"] = pd.to_datetime(result.close_time, unit="ms", utc=True)
    result = result.drop_duplicates(["symbol", "close_time"]).sort_values(["symbol", "close_time"])
    gaps = result.groupby("symbol").close_time.diff().dropna()
    if (gaps > pd.Timedelta(hours=1)).any():
        print("premium gaps larger than one hour", int((gaps > pd.Timedelta(hours=1)).sum()), flush=True)
    grouped = result.groupby("symbol").close
    result["premium_close"] = result.close.astype(float)
    result["premium_8h_mean"] = grouped.transform(lambda x: x.rolling(8, min_periods=8).mean())
    result["premium_change_8h"] = grouped.transform(lambda x: x.diff(8))
    mean = grouped.transform(lambda x: x.rolling(168, min_periods=168).mean())
    std = grouped.transform(lambda x: x.rolling(168, min_periods=168).std())
    result["premium_168h_z"] = ((result.close - mean) / std.replace(0, np.nan)).clip(-10, 10)
    result = result.drop(columns="close")
    cache.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(cache, index=False)
    print("premium rows", len(result), flush=True)
    return result


def load(split: str, premium: pd.DataFrame) -> pd.DataFrame:
    cols = FEATURES + ["symbol", "timestamp", "label_end_ts", "long_r", "short_r", "label_cost_r"]
    frame = pd.read_parquet(DATA / f"{split}.parquet", columns=cols)
    frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
    frame["label_end_ts"] = pd.to_datetime(frame.label_end_ts, utc=True)
    pieces = []
    for symbol in SYMBOLS:
        left = frame.loc[frame.symbol == symbol].sort_values("timestamp")
        right = premium.loc[premium.symbol == symbol].sort_values("close_time")
        joined = pd.merge_asof(
            left, right.drop(columns="symbol"), left_on="timestamp", right_on="close_time",
            direction="backward", allow_exact_matches=False,
            tolerance=pd.Timedelta(hours=3),
        )
        joined = joined.loc[
            joined[PREMIUM_FEATURES].notna().all(axis=1)
            & ((joined.timestamp - joined.close_time) >= pd.Timedelta(hours=1))
        ].copy()
        pieces.append(joined)
    return pd.concat(pieces, ignore_index=True)


def nonoverlap(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.sort_values(["timestamp", "prediction"], ascending=[True, False])
    accepted = []
    occupied_until = {}
    for row in frame.itertuples():
        if row.timestamp >= occupied_until.get(row.symbol, pd.Timestamp.min.tz_localize("UTC")):
            accepted.append(row.Index)
            occupied_until[row.symbol] = row.label_end_ts
    return frame.loc[accepted]


def score(frame: pd.DataFrame, predictions: np.ndarray, threshold: float) -> dict:
    side = predictions.argmax(axis=1)
    selected = predictions.max(axis=1) >= threshold
    signals = frame.loc[selected, ["symbol", "timestamp", "label_end_ts", "label_cost_r"]].copy()
    signals["prediction"] = predictions.max(axis=1)[selected]
    signals["R"] = np.where(side == 0, frame.long_r, frame.short_r)[selected]
    executed = nonoverlap(signals)
    returns = executed.R.to_numpy()
    months = executed.groupby(executed.timestamp.dt.strftime("%Y-%m")).R.mean()
    stress = returns - executed.label_cost_r.to_numpy() * (4 / 14)
    return {
        "signals": int(selected.sum()), "trades": len(executed),
        "mean_R": round(float(returns.mean()), 5) if len(returns) else None,
        "stress_extra_4bps_mean_R": round(float(stress.mean()), 5) if len(stress) else None,
        "profitable_months": int((months > 0).sum()), "months": len(months),
        "monthly_R": months.round(5).to_dict(),
    }


def main() -> None:
    premium = premium_history()
    train, calibration, validation = [load(name, premium) for name in
                                      ("train", "calibration", "validation")]
    train = train.loc[train.timestamp >= pd.Timestamp("2023-01-01", tz="UTC")].copy()
    assert train.timestamp.max() < calibration.timestamp.min()
    assert calibration.timestamp.max() < validation.timestamp.min()
    print("rows", {"train": len(train), "calibration": len(calibration),
                   "validation": len(validation)}, flush=True)
    print("minimum premium lag", min((frame.timestamp - frame.close_time).min()
                                     for frame in (train, calibration, validation)), flush=True)
    symbols = sorted(train.symbol.unique())
    report = {}
    for name, use_premium in (("baseline", False), ("premium", True)):
        columns = FEATURES + (PREMIUM_FEATURES if use_premium else [])
        matrices = []
        for frame in (train, calibration, validation):
            x = frame[columns].reset_index(drop=True)
            onehot = pd.get_dummies(pd.Categorical(frame.symbol, categories=symbols),
                                    prefix="symbol", dtype=float).reset_index(drop=True)
            matrices.append(pd.concat([x, onehot], axis=1))
        outputs = []
        for side in ("long", "short"):
            model = HistGradientBoostingRegressor(
                max_iter=80, max_leaf_nodes=7, learning_rate=0.05,
                l2_regularization=20, min_samples_leaf=300,
                random_state=42, early_stopping=False,
            )
            model.fit(matrices[0], train[f"{side}_r"])
            outputs.append((model.predict(matrices[1]), model.predict(matrices[2])))
            print(f"model {name} {side} fitted", flush=True)
        pred_cal = np.column_stack([output[0] for output in outputs])
        pred_val = np.column_stack([output[1] for output in outputs])
        candidates = [(threshold, score(calibration, pred_cal, threshold))
                      for threshold in THRESHOLDS]
        eligible = [(threshold, result) for threshold, result in candidates
                    if result["trades"] >= 100 and result["mean_R"] > 0
                    and result["profitable_months"] >= 4]
        chosen = max(eligible, key=lambda row: row[1]["mean_R"], default=None)
        report[name] = {
            "calibration": candidates,
            "selected": chosen,
            "validation": score(validation, pred_val, chosen[0]) if chosen else None,
        }
        print(name, json.dumps(report[name], indent=2), flush=True)
    output = ROOT / "outputs/premium_probe_report.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("saved", output, flush=True)


if __name__ == "__main__":
    main()
