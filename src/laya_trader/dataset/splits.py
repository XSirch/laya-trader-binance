from __future__ import annotations

import pandas as pd

from laya_trader.config import SplitConfig, interval_to_timedelta


def split_frame(df: pd.DataFrame, cfg: SplitConfig, interval: str) -> dict[str, pd.DataFrame]:
    if "timestamp" not in df or "label_end_ts" not in df:
        raise ValueError("split_frame requires timestamp and label_end_ts")

    x = df.copy()
    x["timestamp"] = pd.to_datetime(x["timestamp"], utc=True)
    x["label_end_ts"] = pd.to_datetime(x["label_end_ts"], utc=True)

    train_end = pd.Timestamp(cfg.train_end)
    calib_end = pd.Timestamp(cfg.calibration_end)
    val_end = pd.Timestamp(cfg.validation_end)
    test_end = pd.Timestamp(cfg.test_end)
    embargo = interval_to_timedelta(interval) * cfg.embargo_bars

    ranges = {
        "train": (None, train_end),
        "calibration": (train_end + embargo, calib_end),
        "validation": (calib_end + embargo, val_end),
        "test": (val_end + embargo, test_end),
    }
    result: dict[str, pd.DataFrame] = {}
    for name, (start, end) in ranges.items():
        mask = x["timestamp"] <= end
        if start is not None:
            mask &= x["timestamp"] > start
        # Purge: the future horizon used for the label must remain inside the same split.
        mask &= x["label_end_ts"] <= end
        result[name] = x.loc[mask].copy().reset_index(drop=True)
    return result
