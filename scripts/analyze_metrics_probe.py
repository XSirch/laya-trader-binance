import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


root = Path(__file__).resolve().parents[1]
name = "metrics_probe_full_validation_trades.parquet" if "--full" in sys.argv else "metrics_probe_validation_trades.parquet"
trades = pd.read_parquet(root / "outputs" / name)
trades["timestamp"] = pd.to_datetime(trades.timestamp, utc=True)
trades["week"] = trades.timestamp.dt.tz_localize(None).dt.to_period("W").astype(str)
trades["stress_R"] = trades.R - trades.label_cost_r * (4 / 14)
weeks = trades.groupby("week").agg(
    r_sum=("R", "sum"), stress_sum=("stress_R", "sum"), count=("R", "size")
)
random = np.random.default_rng(42)
samples = random.integers(0, len(weeks), size=(20000, len(weeks)))
counts = weeks["count"].to_numpy()[samples].sum(axis=1)
mean = weeks.r_sum.to_numpy()[samples].sum(axis=1) / counts
stress = weeks.stress_sum.to_numpy()[samples].sum(axis=1) / counts
report = {
    "trades": len(trades),
    "weeks_with_trades": len(weeks),
    "mean_R": float(trades.R.mean()),
    "week_bootstrap_95pct_R": np.quantile(mean, [0.025, 0.975]).tolist(),
    "stressed_mean_R": float(trades.stress_R.mean()),
    "week_bootstrap_95pct_stress_R": np.quantile(stress, [0.025, 0.975]).tolist(),
    "by_symbol": trades.groupby("symbol").R.agg(["size", "mean"]).round(4).to_dict("index"),
    "by_side": trades.groupby("side").R.agg(["size", "mean"]).round(4).to_dict("index"),
}
print(json.dumps(report, indent=2))
