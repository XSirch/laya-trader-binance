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
THRESHOLDS = (0.05, 0.075, 0.1, 0.15)


def get_archive(symbol: str, month: str) -> tuple[str, str, pd.DataFrame | None]:
    url = ("https://data.binance.vision/data/futures/um/monthly/fundingRate/"
           f"{symbol}/{symbol}-fundingRate-{month}.zip")
    response = requests.get(url, timeout=25)
    if response.status_code == 404:
        return symbol, month, None
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        with archive.open(archive.namelist()[0]) as stream:
            frame = pd.read_csv(stream, usecols=["calc_time", "last_funding_rate"])
    frame["symbol"] = symbol
    return symbol, month, frame


def funding_history() -> pd.DataFrame:
    cache = ROOT / "outputs/funding_2023_2025.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    months = pd.period_range("2023-01", "2025-12", freq="M").astype(str)
    tasks = [(symbol, month) for symbol in SYMBOLS for month in months]
    frames = []
    missing = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(get_archive, *task) for task in tasks]
        for future in as_completed(futures):
            symbol, month, frame = future.result()
            if frame is None:
                missing.append(f"{symbol}:{month}")
            else:
                frames.append(frame)
    if missing:
        raise RuntimeError(f"missing funding archives: {missing}")
    result = pd.concat(frames, ignore_index=True)
    result["calc_time"] = pd.to_datetime(result.calc_time, unit="ms", utc=True)
    result = result.drop_duplicates(["symbol", "calc_time"]).sort_values(["symbol", "calc_time"])
    result["funding_3event_mean"] = result.groupby("symbol").last_funding_rate.transform(
        lambda values: values.rolling(3, min_periods=1).mean()
    )
    cache.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(cache, index=False)
    print("funding_rows", len(result), "months", len(months), flush=True)
    return result


def load(split: str, funding: pd.DataFrame) -> pd.DataFrame:
    cols = FEATURES + ["symbol", "timestamp", "label_end_ts", "long_r", "short_r", "label_cost_r"]
    frame = pd.read_parquet(DATA / f"{split}.parquet", columns=cols)
    frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
    frame["label_end_ts"] = pd.to_datetime(frame.label_end_ts, utc=True)
    pieces = []
    for symbol in SYMBOLS:
        left = frame.loc[frame.symbol == symbol].sort_values("timestamp")
        right = funding.loc[funding.symbol == symbol].sort_values("calc_time")
        joined = pd.merge_asof(
            left, right.drop(columns="symbol"), left_on="timestamp", right_on="calc_time",
            direction="backward", allow_exact_matches=False,
            tolerance=pd.Timedelta(days=2),
        )
        joined = joined.loc[
            joined.calc_time.notna() &
            ((joined.timestamp - joined.calc_time) >= pd.Timedelta(hours=1))
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
    funding = funding_history()
    train, calibration, validation = [load(name, funding) for name in
                                      ("train", "calibration", "validation")]
    train = train.loc[train.timestamp >= pd.Timestamp("2023-01-01", tz="UTC")].copy()
    print("rows", {"train": len(train), "calibration": len(calibration),
                   "validation": len(validation)}, flush=True)
    symbols = sorted(train.symbol.unique())
    for name, use_funding in (("baseline", False), ("funding", True)):
        columns = FEATURES + (["last_funding_rate", "funding_3event_mean"] if use_funding else [])
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
        pred_cal = np.column_stack([output[0] for output in outputs])
        pred_val = np.column_stack([output[1] for output in outputs])
        candidates = [(threshold, score(calibration, pred_cal, threshold))
                      for threshold in THRESHOLDS]
        eligible = [(threshold, result) for threshold, result in candidates
                    if result["trades"] >= 100 and result["mean_R"] > 0
                    and result["profitable_months"] >= 4]
        chosen = max(eligible, key=lambda row: row[1]["mean_R"], default=None)
        print(name, json.dumps({"calibration": candidates, "selected": chosen,
                                "validation": score(validation, pred_val, chosen[0])
                                if chosen else None}, indent=2), flush=True)


if __name__ == "__main__":
    main()
