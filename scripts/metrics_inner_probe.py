import json
import sys
from pathlib import Path

import pandas as pd


root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "scripts"))
import metrics_probe as probe
from funding_probe import THRESHOLDS, score


probe.DATA = root / "outputs/one_hour_full_five"
metrics = probe.load_metrics(probe.download_archives())
frame = probe.load_split("train", metrics)
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
frames = (train, calibration, validation)
minimum_trades = max(100, int(len(calibration) * 0.005))
report = {"rows": [len(x) for x in frames], "minimum_calibration_trades": minimum_trades}
for variant, use_metrics in (("baseline", False), ("metrics", True)):
    predictions = probe.fit_predict(frames, use_metrics)
    options = [(threshold, score(calibration, predictions[0], threshold))
               for threshold in THRESHOLDS]
    eligible = [(threshold, result) for threshold, result in options
                if result["trades"] >= minimum_trades and result["mean_R"] > 0
                and result["profitable_months"] >= 4]
    selected = max(eligible, key=lambda row: row[1]["mean_R"], default=None)
    report[variant] = {
        "calibration": options,
        "selected": selected,
        "validation": score(validation, predictions[1], selected[0]) if selected else None,
    }
print(json.dumps(report, indent=2))
(root / "outputs/metrics_inner_probe_report.json").write_text(
    json.dumps(report, indent=2) + "\n", encoding="utf-8",
)
