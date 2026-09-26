"""Research-only 15m book-depth pilot with a one-minute observation buffer."""

from __future__ import annotations

import json
import zipfile
from dataclasses import replace
from datetime import timedelta

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from book_depth_coverage_probe import ROOT, SYMBOLS, archive_path
from funding_probe import nonoverlap
from laya_trader.config import load_config
from laya_trader.dataset.build import load_symbol_klines
from laya_trader.features.core import compute_features
from laya_trader.labels.triple_barrier import add_triple_barrier_labels
from laya_trader.progress import ProgressReporter


FIRST_TRAIN = pd.Timestamp("2023-01-01", tz="UTC")
FIRST_CALIBRATION = pd.Timestamp("2023-07-01", tz="UTC")
FIRST_VALIDATION = pd.Timestamp("2024-01-01", tz="UTC")
END_VALIDATION = pd.Timestamp("2024-07-01", tz="UTC")
BASE = (
    "trend_fast_atr", "trend_slow_atr", "rsi14", "adx14",
    "dist_ema20_atr", "dist_ema200_atr", "ret_1_z", "ret_4_z",
    "volume_z", "flow_imbalance", "atr_pct", "close_location",
)
BOOK = (
    "book_imbalance_1_mean", "book_imbalance_5_mean",
    "book_imbalance_1_last", "book_depth_1_log",
)
THRESHOLDS = (0.05, 0.075, 0.10, 0.15)
MIN_SNAPSHOTS_PER_BAR = 20


def book_one_day(symbol: str, day: str, prices: pd.DataFrame) -> list[dict]:
    with zipfile.ZipFile(archive_path(symbol, day)) as archive:
        with archive.open(archive.namelist()[0]) as stream:
            frame = pd.read_csv(stream, usecols=["timestamp", "percentage", "depth", "notional"])
    frame = frame.loc[frame.percentage.isin((-5, -1, 1, 5))].copy()
    frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
    frame["depth"] = pd.to_numeric(frame.depth, errors="coerce")
    frame["notional"] = pd.to_numeric(frame.notional, errors="coerce")
    frame = frame.loc[frame.depth.gt(0) & frame.notional.gt(0)]
    frame = frame.drop_duplicates(["timestamp", "percentage"], keep="last")
    levels = [-5, -1, 1, 5]
    depth = frame.pivot(index="timestamp", columns="percentage", values="depth").reindex(columns=levels)
    notional = frame.pivot(index="timestamp", columns="percentage", values="notional").reindex(columns=levels)
    valid = depth.notna().all(axis=1) & notional.notna().all(axis=1)
    depth, notional = depth.loc[valid], notional.loc[valid]
    if depth.empty:
        return []
    bid1, ask1 = notional[-1], notional[1]
    bid5, ask5 = notional[-5], notional[5]
    quote = pd.DataFrame(index=depth.index)
    quote["book_imbalance_1"] = (bid1 - ask1) / (bid1 + ask1)
    quote["book_imbalance_5"] = (bid5 - ask5) / (bid5 + ask5)
    quote["book_depth_1_log"] = np.log1p(bid1 + ask1)
    quote["book_mid"] = (bid5 / depth[-5] + ask5 / depth[5]) / 2
    quote = quote.replace([np.inf, -np.inf], np.nan).dropna().sort_index()
    joined = pd.merge_asof(
        quote.reset_index(), prices, on="timestamp", direction="backward",
        tolerance=timedelta(minutes=15),
    ).dropna()
    joined = joined.loc[(joined.book_mid / joined.open - 1).abs() <= 0.10].copy()
    joined["bar_open"] = joined.timestamp.dt.floor("15min")
    joined = joined.loc[joined.timestamp <= joined.bar_open + timedelta(minutes=14)]
    rows = []
    for bar_open, group in joined.groupby("bar_open", sort=True):
        if len(group) < MIN_SNAPSHOTS_PER_BAR:
            continue
        rows.append({
            "symbol": symbol,
            "decision_time": bar_open + timedelta(minutes=15),
            "book_imbalance_1_mean": float(group.book_imbalance_1.mean()),
            "book_imbalance_5_mean": float(group.book_imbalance_5.mean()),
            "book_imbalance_1_last": float(group.book_imbalance_1.iloc[-1]),
            "book_depth_1_log": float(group.book_depth_1_log.median()),
        })
    return rows


def labeled_symbol(symbol: str, raw: pd.DataFrame, cfg) -> pd.DataFrame:
    labels_cfg = replace(cfg.labels, drop_ambiguous=False)
    pieces = []
    for _, segment in raw.groupby("_segment_id", sort=True):
        if len(segment) <= cfg.features.warmup_bars + labels_cfg.horizon_bars:
            continue
        features = compute_features(segment.drop(columns="_segment_id"))
        features["symbol"] = symbol
        features = features.iloc[cfg.features.warmup_bars:].dropna(subset=["atr14", *BASE])
        if len(features) <= labels_cfg.horizon_bars:
            continue
        labeled = add_triple_barrier_labels(features.reset_index(drop=True), labels_cfg)
        for side in ("long", "short"):
            ambiguous = labeled[f"{side}_ambiguous"]
            labeled.loc[ambiguous, f"{side}_r"] = -1.0 - labeled.loc[ambiguous, "label_cost_r"]
        columns = ["symbol", "timestamp", "label_end_ts", "long_r", "short_r", "label_cost_r", *BASE]
        pieces.append(labeled[columns])
    if not pieces:
        raise ValueError(f"no labeled segments for {symbol}")
    result = pd.concat(pieces, ignore_index=True)
    result["decision_time"] = result.timestamp + pd.Timedelta(milliseconds=1)
    return result


def build_rows(first_day: str, last_day: str, raw_start: str) -> tuple[pd.DataFrame, int]:
    cfg = load_config(ROOT / "configs/dataset.toml")
    cfg = replace(cfg, data=replace(cfg.data, start=raw_start, end=last_day))
    days = pd.date_range(first_day, last_day, freq="D").strftime("%Y-%m-%d")
    tasks = [(symbol, day) for symbol in SYMBOLS for day in days
             if archive_path(symbol, day).is_file()]
    book_rows = []
    frames = []
    progress = ProgressReporter("book depth 15m", len(tasks), unit="archives")
    done = 0
    for symbol in SYMBOLS:
        raw = load_symbol_klines(cfg, symbol)
        prices = raw[["open_time", "open"]].rename(columns={"open_time": "timestamp"})
        for name, day in (task for task in tasks if task[0] == symbol):
            book_rows.extend(book_one_day(name, day, prices))
            done += 1
            progress.update(done)
        labeled = labeled_symbol(symbol, raw, cfg)
        symbol_book = pd.DataFrame(row for row in book_rows if row["symbol"] == symbol)
        if symbol_book.empty:
            continue
        joined = labeled.merge(symbol_book.drop(columns="symbol"), on="decision_time", how="inner",
                               validate="one_to_one")
        joined = joined.loc[joined[list(BOOK)].notna().all(axis=1)]
        frames.append(joined)
        print("joined", symbol, len(joined), flush=True)
    if not frames:
        raise ValueError("no labeled book-depth rows")
    return pd.concat(frames, ignore_index=True), len(book_rows)


def inputs(frame: pd.DataFrame, with_book: bool) -> pd.DataFrame:
    columns = [*BASE, *(BOOK if with_book else ())]
    data = frame[columns].reset_index(drop=True)
    onehot = pd.get_dummies(pd.Categorical(frame.symbol, categories=SYMBOLS),
                            prefix="symbol", dtype=float).reset_index(drop=True)
    return pd.concat([data, onehot], axis=1)


def fit(train: pd.DataFrame, with_book: bool) -> list[HistGradientBoostingRegressor]:
    x = inputs(train, with_book)
    models = []
    for side in ("long", "short"):
        model = HistGradientBoostingRegressor(
            max_iter=80, max_leaf_nodes=7, learning_rate=0.05,
            l2_regularization=20, min_samples_leaf=300,
            random_state=42, early_stopping=False,
        )
        model.fit(x, train[f"{side}_r"])
        models.append(model)
        print("fitted", "book" if with_book else "baseline", side, flush=True)
    return models


def predictions(models: list[HistGradientBoostingRegressor], frame: pd.DataFrame,
                with_book: bool) -> np.ndarray:
    x = inputs(frame, with_book)
    return np.column_stack([model.predict(x) for model in models])


def score(frame: pd.DataFrame, predicted: np.ndarray, threshold: float) -> dict:
    side = predicted.argmax(axis=1)
    selected = predicted.max(axis=1) >= threshold
    signals = frame.loc[selected, ["symbol", "timestamp", "label_end_ts", "label_cost_r"]].copy()
    signals["prediction"] = predicted.max(axis=1)[selected]
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


def eligible(result: dict, minimum: int) -> bool:
    return (
        result["trades"] >= minimum and result["mean_R"] is not None
        and result["mean_R"] > 0 and result["stress_extra_4bps_mean_R"] > 0
        and result["months"] == 6 and result["profitable_months"] >= 4
    )


def main() -> None:
    early, book_count = build_rows("2023-01-01", "2023-12-31", "2022-12-01")
    train = early.loc[(early.timestamp >= FIRST_TRAIN)
                      & (early.label_end_ts < FIRST_CALIBRATION)].copy()
    calibration = early.loc[(early.timestamp >= FIRST_CALIBRATION)
                            & (early.label_end_ts < FIRST_VALIDATION)].copy()
    if train.empty or calibration.empty:
        raise ValueError("empty training or calibration period")
    minimum = max(100, int(len(calibration) * 0.005))
    report = {
        "hypothesis": "15m book imbalance known at least 1 minute before entry",
        "symbols": list(SYMBOLS), "features": list(BOOK),
        "periods": {"train": ["2023-01-01", "2023-06-30"],
                    "calibration": ["2023-07-01", "2023-12-31"],
                    "validation": ["2024-01-01", "2024-06-30"]},
        "book_rows": book_count,
        "rows": {"train": len(train), "calibration": len(calibration)},
        "minimum_calibration_trades": minimum,
        "thresholds": list(THRESHOLDS),
    }
    models = {}
    for name, with_book in (("baseline", False), ("book", True)):
        fitted = fit(train, with_book)
        predicted = predictions(fitted, calibration, with_book)
        options = [(threshold, score(calibration, predicted, threshold))
                   for threshold in THRESHOLDS]
        candidates = [(threshold, result) for threshold, result in options
                      if eligible(result, minimum)]
        selected = max(candidates, key=lambda row: row[1]["mean_R"], default=None)
        report[name] = {"calibration": options, "selected": selected, "validation": None}
        models[name] = fitted
        print(name, "selected", selected, flush=True)
    if report["book"]["selected"] is not None:
        late, late_book_count = build_rows("2024-01-01", "2024-06-30", "2023-12-01")
        validation = late.loc[(late.timestamp >= FIRST_VALIDATION)
                              & (late.label_end_ts < END_VALIDATION)].copy()
        report["validation_book_rows"] = late_book_count
        report["rows"]["validation"] = len(validation)
        report["minimum_validation_trades"] = max(100, int(len(validation) * 0.005))
        for name, with_book in (("baseline", False), ("book", True)):
            selected = report[name]["selected"]
            if selected is None:
                continue
            predicted = predictions(models[name], validation, with_book)
            result = score(validation, predicted, selected[0])
            report[name]["validation"] = result
            report[name]["validation_gate"] = eligible(result, report["minimum_validation_trades"])
    output = ROOT / "outputs/book_depth_15m_probe_report.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: {"selected": report[name]["selected"],
                             "validation": report[name]["validation"]}
                      for name in ("baseline", "book")}, indent=2), flush=True)
    print("saved", output, flush=True)


if __name__ == "__main__":
    main()
