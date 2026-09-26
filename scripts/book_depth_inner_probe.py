"""Research-only inner-period test of lagged book-depth features on BTC and ETH."""

from __future__ import annotations

import json
import zipfile
from datetime import timedelta

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from book_depth_coverage_probe import ROOT, SYMBOLS, archive_path, price_opens
from funding_probe import FEATURES, THRESHOLDS, score
from laya_trader.progress import ProgressReporter


DATA = ROOT / "outputs/one_hour_full_five/train.parquet"
FEATURES_BOOK = (
    "book_imbalance_1_mean", "book_imbalance_5_mean",
    "book_imbalance_1_last", "book_depth_1_log",
)
FIRST_DAY = "2023-01-01"
LAST_EARLY_DAY = "2024-06-30"
LAST_VALIDATION_DAY = "2024-12-31"


def hourly_one(symbol: str, day: str, prices: pd.DataFrame) -> list[dict]:
    with zipfile.ZipFile(archive_path(symbol, day)) as archive:
        with archive.open(archive.namelist()[0]) as stream:
            frame = pd.read_csv(stream, usecols=["timestamp", "percentage", "depth", "notional"])
    frame = frame.loc[frame.percentage.isin((-5, -1, 1, 5))].copy()
    frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
    frame["depth"] = pd.to_numeric(frame.depth, errors="coerce")
    frame["notional"] = pd.to_numeric(frame.notional, errors="coerce")
    frame = frame.loc[frame.depth.gt(0) & frame.notional.gt(0)]
    depth = frame.pivot(index="timestamp", columns="percentage", values="depth")
    notional = frame.pivot(index="timestamp", columns="percentage", values="notional")
    bands = (-5, -1, 1, 5)
    valid = depth[list(bands)].notna().all(axis=1) & notional[list(bands)].notna().all(axis=1)
    depth, notional = depth.loc[valid], notional.loc[valid]
    quote = pd.DataFrame(index=depth.index)
    bid1, ask1 = notional[-1], notional[1]
    bid5, ask5 = notional[-5], notional[5]
    quote["book_imbalance_1"] = (bid1 - ask1) / (bid1 + ask1)
    quote["book_imbalance_5"] = (bid5 - ask5) / (bid5 + ask5)
    quote["book_depth_1_log"] = np.log1p(bid1 + ask1)
    quote["book_mid"] = (bid5 / depth[-5] + ask5 / depth[5]) / 2
    quote = quote.replace([np.inf, -np.inf], np.nan).dropna().sort_index()
    start = pd.Timestamp(day, tz="UTC")
    source_prices = prices.loc[
        (prices.timestamp >= start) & (prices.timestamp < start + timedelta(days=1))
    ]
    joined = pd.merge_asof(
        quote.reset_index(), source_prices, on="timestamp", direction="backward",
        tolerance=timedelta(minutes=15),
    ).dropna()
    joined = joined.loc[(joined.book_mid / joined.open - 1).abs() <= 0.10].copy()
    joined["hour"] = joined.timestamp.dt.floor("1h")
    result = []
    for hour, group in joined.groupby("hour", sort=True):
        if len(group) < 60 or group.timestamp.dt.floor("15min").nunique() < 4:
            continue
        result.append({
            "symbol": symbol,
            "available_time": hour + timedelta(hours=2),
            "book_imbalance_1_mean": float(group.book_imbalance_1.mean()),
            "book_imbalance_5_mean": float(group.book_imbalance_5.mean()),
            "book_imbalance_1_last": float(group.book_imbalance_1.iloc[-1]),
            "book_depth_1_log": float(group.book_depth_1_log.median()),
        })
    return result


def hourly_features(last_day: str) -> pd.DataFrame:
    cache = ROOT / f"outputs/book_depth_hourly_causal_{FIRST_DAY}_{last_day}.parquet"
    if cache.is_file():
        return pd.read_parquet(cache)
    days = pd.date_range(FIRST_DAY, last_day, freq="D").strftime("%Y-%m-%d")
    tasks = [(symbol, day) for symbol in SYMBOLS for day in days
             if archive_path(symbol, day).is_file()]
    source_prices = {symbol: price_opens(symbol, FIRST_DAY, last_day) for symbol in SYMBOLS}
    rows = []
    progress = ProgressReporter("book depth hourly features", len(tasks), unit="days")
    for count, (symbol, day) in enumerate(tasks, 1):
        rows.extend(hourly_one(symbol, day, source_prices[symbol]))
        progress.update(count)
    result = pd.DataFrame(rows).sort_values(["symbol", "available_time"])
    result.to_parquet(cache, index=False)
    print("hourly book feature rows", len(result), flush=True)
    return result


def labeled_frames(book: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    columns = [*FEATURES, "symbol", "timestamp", "label_end_ts", "long_r", "short_r", "label_cost_r"]
    frame = pd.read_parquet(DATA, columns=columns)
    frame = frame.loc[frame.symbol.isin(SYMBOLS)].copy()
    frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
    frame["label_end_ts"] = pd.to_datetime(frame.label_end_ts, utc=True)
    pieces = []
    for symbol in SYMBOLS:
        left = frame.loc[frame.symbol == symbol].sort_values("timestamp")
        right = book.loc[book.symbol == symbol].sort_values("available_time")
        joined = pd.merge_asof(
            left, right.drop(columns="symbol"),
            left_on="timestamp", right_on="available_time",
            direction="backward", tolerance=timedelta(hours=1),
        )
        joined = joined.loc[joined[list(FEATURES_BOOK)].notna().all(axis=1)]
        pieces.append(joined)
    frame = pd.concat(pieces, ignore_index=True)
    train = frame.loc[
        (frame.timestamp >= pd.Timestamp("2023-01-01", tz="UTC"))
        & (frame.label_end_ts < pd.Timestamp("2024-01-01", tz="UTC"))
    ].copy()
    calibration = frame.loc[
        (frame.timestamp >= pd.Timestamp("2024-01-01", tz="UTC"))
        & (frame.label_end_ts < pd.Timestamp("2024-07-01", tz="UTC"))
    ].copy()
    validation = frame.loc[
        (frame.timestamp >= pd.Timestamp("2024-07-01", tz="UTC"))
        & (frame.label_end_ts < pd.Timestamp("2025-01-01", tz="UTC"))
    ].copy()
    return train, calibration, validation


def inputs(frame: pd.DataFrame, with_book: bool) -> pd.DataFrame:
    columns = [*FEATURES, *(FEATURES_BOOK if with_book else ())]
    data = frame[columns].reset_index(drop=True)
    onehot = pd.get_dummies(
        pd.Categorical(frame.symbol, categories=SYMBOLS), prefix="symbol", dtype=float,
    ).reset_index(drop=True)
    return pd.concat([data, onehot], axis=1)


def models_and_predictions(
    train: pd.DataFrame, calibration: pd.DataFrame, with_book: bool,
) -> tuple[list[HistGradientBoostingRegressor], np.ndarray]:
    x_train = inputs(train, with_book)
    x_calibration = inputs(calibration, with_book)
    models = []
    predictions = []
    for side in ("long", "short"):
        model = HistGradientBoostingRegressor(
            max_iter=80, max_leaf_nodes=7, learning_rate=0.05,
            l2_regularization=20, min_samples_leaf=300,
            random_state=42, early_stopping=False,
        )
        model.fit(x_train, train[f"{side}_r"])
        predictions.append(model.predict(x_calibration))
        models.append(model)
        print("fitted", "book" if with_book else "baseline", side, flush=True)
    return models, np.column_stack(predictions)


def main() -> None:
    book = hourly_features(LAST_EARLY_DAY)
    train, calibration, _ = labeled_frames(book)
    minimum = max(100, int(len(calibration) * 0.005))
    report = {
        "features": list(FEATURES_BOOK),
        "lag": "source hour ends at least one hour before labeled timestamp",
        "periods": [FIRST_DAY, LAST_EARLY_DAY],
        "hourly_book_rows": len(book),
        "rows": {"train": len(train), "calibration": len(calibration)},
        "minimum_calibration_trades": minimum,
    }
    variants = {}
    for name, with_book in (("baseline", False), ("book", True)):
        models, predictions = models_and_predictions(train, calibration, with_book)
        options = [(threshold, score(calibration, predictions, threshold))
                   for threshold in THRESHOLDS]
        eligible = [(threshold, result) for threshold, result in options
                    if result["trades"] >= minimum and result["mean_R"] is not None
                    and result["mean_R"] > 0 and result["stress_extra_4bps_mean_R"] > 0
                    and result["profitable_months"] >= 4]
        selected = max(eligible, key=lambda row: row[1]["mean_R"], default=None)
        report[name] = {"calibration": options, "selected": selected, "validation": None}
        variants[name] = (with_book, models)
        print(name, "selected", selected, flush=True)
    if report["book"]["selected"] is not None:
        full_book = hourly_features(LAST_VALIDATION_DAY)
        _, _, validation = labeled_frames(full_book)
        report["rows"]["validation"] = len(validation)
        minimum_validation = max(100, int(len(validation) * 0.005))
        report["minimum_validation_trades"] = minimum_validation
        for name, (with_book, models) in variants.items():
            selected = report[name]["selected"]
            if selected is None:
                continue
            x = inputs(validation, with_book)
            predictions = np.column_stack([model.predict(x) for model in models])
            report[name]["validation"] = score(validation, predictions, selected[0])
    output = ROOT / "outputs/book_depth_inner_probe_report.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: {"selected": report[name]["selected"],
                             "validation": report[name]["validation"]}
                      for name in ("baseline", "book")}, indent=2), flush=True)
    print("saved", output, flush=True)


if __name__ == "__main__":
    main()
