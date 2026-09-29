import importlib.util
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cycle03_direct_net_ev.py"
SPEC = importlib.util.spec_from_file_location("cycle03_direct_net_ev", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_predicted_ev_cutoff_is_strict_and_fixed():
    scores = pd.Series([0.011999, 0.012, 0.012001, None])
    assert MODULE.select_by_predicted_ev(scores).tolist() == [False, False, True, False]


def test_regression_diagnostics_compare_with_training_mean_baseline():
    actual = pd.Series([0.01, -0.01, 0.02, 0.00])
    predicted = pd.Series([0.008, -0.009, 0.018, 0.001])
    metrics = MODULE._finite_metrics(actual.to_numpy(), predicted.to_numpy())
    baseline = metrics["baseline_mean_rmse"]
    assert metrics["rows"] == 4
    assert metrics["mae"] < baseline
    assert metrics["rmse"] < baseline


def test_calibration_bins_are_monotonic_by_model_score():
    actual = pd.Series([0.001, 0.002, 0.003, 0.004, 0.005, 0.006])
    predicted = pd.Series([0.01, 0.02, 0.03, 0.04, 0.05, 0.06])
    bins = MODULE.calibration_bins(actual, predicted, bins=3)
    assert len(bins) == 3
    assert bins.predicted_mean.is_monotonic_increasing
    assert bins.realized_mean.is_monotonic_increasing
