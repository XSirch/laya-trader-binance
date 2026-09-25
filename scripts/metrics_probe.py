"""Exploratory 1h positioning-metrics probe with a one-hour availability lag."""

from __future__ import annotations

import io
import json
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from sklearn.ensemble import HistGradientBoostingRegressor

from funding_probe import FEATURES, SYMBOLS, THRESHOLDS, nonoverlap, score
from laya_trader.progress import ProgressReporter


ROOT = Path(__file__).resolve().parents[1]
FULL_DATA = "--full-data" in sys.argv
DATA = ROOT / ("outputs/one_hour_full_five" if FULL_DATA else "outputs/one_hour_probe")
ARCHIVES = ROOT / "outputs/metrics_daily"
VALIDATE = "--validation" in sys.argv
METRIC_COLUMNS = (
    "create_time", "sum_open_interest_value",
    "sum_toptrader_long_short_ratio", "count_long_short_ratio",
    "sum_taker_long_short_vol_ratio",
)
NEW_FEATURES = (
    "oi_change_24h", "top_trader_ratio", "global_ratio",
    "top_minus_global_log", "taker_ratio_1h",
)


def archive_path(symbol: str, day: str) -> Path:
    return ARCHIVES / symbol / f"{symbol}-metrics-{day}.zip"


def download_one(symbol: str, day: str) -> tuple[str, str, bool]:
    path = archive_path(symbol, day)
    if path.is_file():
        return symbol, day, True
    url = (
        "https://data.binance.vision/data/futures/um/daily/metrics/"
        f"{symbol}/{symbol}-metrics-{day}.zip"
    )
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 404:
                return symbol, day, False
            response.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                if archive.testzip() is not None:
                    raise ValueError(f"bad ZIP member: {url}")
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".zip.tmp")
            temporary.write_bytes(response.content)
            temporary.replace(path)
            return symbol, day, True
        except (requests.RequestException, zipfile.BadZipFile, ValueError):
            if attempt == 2:
                raise
            time.sleep(1 + 2 * attempt)
    raise AssertionError("unreachable")


def download_archives() -> list[tuple[str, str]]:
    last = "2025-12-31" if VALIDATE else "2025-06-30"
    days = pd.date_range("2023-01-01", last, freq="D").strftime("%Y-%m-%d")
    tasks = [(symbol, day) for symbol in SYMBOLS for day in days]
    missing = []
    progress = ProgressReporter("metrics archives", len(tasks), unit="days")
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(download_one, *task) for task in tasks]
        for count, future in enumerate(as_completed(futures), 1):
            symbol, day, found = future.result()
            if not found:
                missing.append(f"{symbol}:{day}")
            progress.update(count)
    if missing:
        raise RuntimeError(f"missing metrics archives ({len(missing)}): {missing[:20]}")
    print("metrics archives complete", len(tasks), flush=True)
    return tasks


def load_metrics(tasks: list[tuple[str, str]]) -> dict[str, pd.DataFrame]:
    result = {}
    by_symbol = {symbol: [] for symbol in SYMBOLS}
    for symbol, day in tasks:
        with zipfile.ZipFile(archive_path(symbol, day)) as archive:
            with archive.open(archive.namelist()[0]) as stream:
                by_symbol[symbol].append(pd.read_csv(stream, usecols=list(METRIC_COLUMNS)))
    for symbol, frames in by_symbol.items():
        frame = pd.concat(frames, ignore_index=True)
        frame["create_time"] = pd.to_datetime(frame.create_time, utc=True)
        frame = frame.sort_values("create_time").drop_duplicates("create_time")
        for column in METRIC_COLUMNS[1:]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        oi = frame.sum_open_interest_value.where(frame.sum_open_interest_value > 0)
        lagged = oi.shift(288)
        exact_day = frame.create_time.diff(288) == timedelta(days=1)
        frame["oi_change_24h"] = np.log(oi / lagged).where(exact_day)
        frame["top_trader_ratio"] = frame.sum_toptrader_long_short_ratio
        frame["global_ratio"] = frame.count_long_short_ratio
        frame["top_minus_global_log"] = np.log(
            frame.top_trader_ratio.where(frame.top_trader_ratio > 0)
            / frame.global_ratio.where(frame.global_ratio > 0)
        )
        frame["taker_ratio_1h"] = frame.sum_taker_long_short_vol_ratio.rolling(
            12, min_periods=12,
        ).mean()
        frame["available_time"] = frame.create_time + timedelta(hours=1)
        result[symbol] = frame[["create_time", "available_time", *NEW_FEATURES]].copy()
        print("metrics rows", symbol, len(frame), flush=True)
    return result


def load_split(name: str, metrics: dict[str, pd.DataFrame]) -> pd.DataFrame:
    columns = [*FEATURES, "symbol", "timestamp", "label_end_ts", "long_r", "short_r", "label_cost_r"]
    frame = pd.read_parquet(DATA / f"{name}.parquet", columns=columns)
    frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
    frame["label_end_ts"] = pd.to_datetime(frame.label_end_ts, utc=True)
    pieces = []
    for symbol in SYMBOLS:
        left = frame.loc[frame.symbol == symbol].sort_values("timestamp")
        right = metrics[symbol].sort_values("available_time")
        joined = pd.merge_asof(
            left, right, left_on="timestamp", right_on="available_time",
            direction="backward", tolerance=timedelta(hours=2),
        )
        joined = joined.loc[joined[list(NEW_FEATURES)].notna().all(axis=1)].copy()
        if not joined.empty:
            assert (joined.timestamp - joined.create_time >= timedelta(hours=1)).all()
        pieces.append(joined)
    return pd.concat(pieces, ignore_index=True)


def inputs(frames: tuple[pd.DataFrame, ...], use_metrics: bool) -> list[pd.DataFrame]:
    columns = [*FEATURES, *(NEW_FEATURES if use_metrics else ())]
    matrices = []
    for frame in frames:
        onehot = pd.get_dummies(
            pd.Categorical(frame.symbol, categories=SYMBOLS), prefix="symbol", dtype=float,
        ).reset_index(drop=True)
        matrices.append(pd.concat([frame[columns].reset_index(drop=True), onehot], axis=1))
    return matrices


def fit_predict(frames: tuple[pd.DataFrame, ...], use_metrics: bool) -> list[np.ndarray]:
    matrices = inputs(frames, use_metrics)
    outputs = [[] for _ in frames[1:]]
    for side in ("long", "short"):
        model = HistGradientBoostingRegressor(
            max_iter=80, max_leaf_nodes=7, learning_rate=0.05,
            l2_regularization=20, min_samples_leaf=300,
            random_state=42, early_stopping=False,
        )
        model.fit(matrices[0], frames[0][f"{side}_r"])
        for output, x in zip(outputs, matrices[1:]):
            output.append(model.predict(x))
        print("fitted", "metrics" if use_metrics else "baseline", side, flush=True)
    return [np.column_stack(output) for output in outputs]


def selected_trades(frame: pd.DataFrame, predictions: np.ndarray, threshold: float) -> pd.DataFrame:
    side = predictions.argmax(axis=1)
    selected = predictions.max(axis=1) >= threshold
    signals = frame.loc[selected, ["symbol", "timestamp", "label_end_ts", "label_cost_r"]].copy()
    signals["prediction"] = predictions.max(axis=1)[selected]
    signals["side"] = np.where(side[selected] == 0, "long", "short")
    signals["R"] = np.where(side == 0, frame.long_r, frame.short_r)[selected]
    return nonoverlap(signals).reset_index(drop=True)


def main() -> None:
    metrics = load_metrics(download_archives())
    names = ("train", "calibration", "validation") if VALIDATE else ("train", "calibration")
    frames = tuple(load_split(name, metrics) for name in names)
    frames = (frames[0].loc[frames[0].timestamp >= pd.Timestamp("2023-01-01", tz="UTC")].copy(), *frames[1:])
    print("sample rows", dict(zip(names, map(len, frames))), flush=True)
    minimum_calibration_trades = max(100, int(len(frames[1]) * 0.005))
    minimum_validation_trades = max(100, int(len(frames[2]) * 0.005)) if VALIDATE else None
    report = {
        "features": list(NEW_FEATURES),
        "rows": dict(zip(names, map(len, frames))),
        "minimum_calibration_trades": minimum_calibration_trades,
        "minimum_validation_trades": minimum_validation_trades,
    }
    for variant, use_metrics in (("baseline", False), ("metrics", True)):
        predictions = fit_predict(frames, use_metrics)
        calibration = [(threshold, score(frames[1], predictions[0], threshold))
                       for threshold in THRESHOLDS]
        eligible = [(threshold, result) for threshold, result in calibration
                    if result["trades"] >= minimum_calibration_trades and result["mean_R"] > 0
                    and result["profitable_months"] >= 4]
        selected = max(eligible, key=lambda row: row[1]["mean_R"], default=None)
        validation = (
            score(frames[2], predictions[1], selected[0]) if VALIDATE and selected else None
        )
        report[variant] = {
            "calibration": calibration,
            "selected": selected,
            "validation": validation,
            "validation_gate": (
                validation["trades"] >= minimum_validation_trades
                and validation["mean_R"] > 0
                and validation["profitable_months"] >= 4
            ) if validation else None,
        }
        if variant == "metrics" and VALIDATE and selected:
            trades = selected_trades(frames[2], predictions[1], selected[0])
            trades.to_parquet(
                ROOT / f"outputs/metrics_probe_{'full_' if FULL_DATA else ''}validation_trades.parquet",
                index=False,
            )
        print(variant, "selected", selected, flush=True)
    output = ROOT / (
        f"outputs/metrics_probe_{'full_' if FULL_DATA else ''}"
        f"{'validation' if VALIDATE else 'calibration'}_report.json"
    )
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        variant: {"selected": report[variant]["selected"],
                  "validation": report[variant]["validation"]}
        for variant in ("baseline", "metrics")
    }, indent=2), flush=True)
    print("saved", output, flush=True)


if __name__ == "__main__":
    main()
