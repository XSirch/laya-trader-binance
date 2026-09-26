"""Reassess positioning metrics after removing future-dependent row exclusion."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

import metrics_probe as probe
from funding_probe import THRESHOLDS, score


ROOT = Path(__file__).resolve().parents[1]
probe.DATA = ROOT / "outputs/one_hour_conservative_five"
probe.VALIDATE = True
EVEN_TRAIN = "--even-train" in sys.argv
OUTPUT = ROOT / ("outputs/metrics_conservative_even_report.json"
                 if EVEN_TRAIN else "outputs/metrics_conservative_report.json")


def main() -> None:
    train_name = "train_even" if EVEN_TRAIN else "train"
    for name in (train_name, "calibration", "validation"):
        if not (probe.DATA / f"{name}.parquet").is_file():
            raise FileNotFoundError(f"Run build_one_hour_conservative_five.py: {name}")
    metrics = probe.load_metrics(probe.download_archives())
    names = ("train", "calibration", "validation")
    frames = (probe.load_split(train_name, metrics),
              probe.load_split("calibration", metrics),
              probe.load_split("validation", metrics))
    frames = (frames[0].loc[
        frames[0].timestamp >= pd.Timestamp("2023-01-01", tz="UTC")
    ].copy(), *frames[1:])
    minimum_calibration = max(100, int(len(frames[1]) * 0.005))
    minimum_validation = max(100, int(len(frames[2]) * 0.005))
    report = {
        "method": "same historical metrics model; retain ambiguous rows and count same-bar target/stop as stop",
        "train_sampling": "even cap of 5000 per symbol" if EVEN_TRAIN else "full 2023-2024",
        "rows": dict(zip(names, map(len, frames))),
        "minimum_calibration_trades": minimum_calibration,
        "minimum_validation_trades": minimum_validation,
    }
    for variant, use_metrics in (("baseline", False), ("metrics", True)):
        predictions = probe.fit_predict(frames, use_metrics)
        calibration = [(threshold, score(frames[1], predictions[0], threshold))
                       for threshold in THRESHOLDS]
        eligible = [(threshold, result) for threshold, result in calibration
                    if result["trades"] >= minimum_calibration
                    and result["mean_R"] > 0
                    and result["profitable_months"] >= 4]
        selected = max(eligible, key=lambda row: row[1]["mean_R"], default=None)
        validation = (score(frames[2], predictions[1], selected[0])
                      if selected else None)
        report[variant] = {
            "calibration": calibration,
            "selected": selected,
            "validation": validation,
            "validation_gate": (validation["trades"] >= minimum_validation
                                and validation["mean_R"] > 0
                                and validation["stress_extra_4bps_mean_R"] > 0
                                and validation["profitable_months"] >= 4)
            if validation else None,
        }
        if variant == "metrics" and selected:
            trades = probe.selected_trades(frames[2], predictions[1], selected[0])
            trades.to_parquet(ROOT / ("outputs/metrics_conservative_even_validation_trades.parquet"
                                      if EVEN_TRAIN else
                                      "outputs/metrics_conservative_validation_trades.parquet"),
                              index=False)
        print(variant, "selected", selected, "validation", validation, flush=True)
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("saved", OUTPUT, flush=True)


if __name__ == "__main__":
    main()
