import json
import numpy as np
import pandas as pd
import pytest
import sklearn
from binance_multistrategy.config import ResearchConfig
from binance_multistrategy.learning import TrainedGate, fit_heads, purged_window, code_fingerprint, train_pipeline
from binance_multistrategy.strategies import INPUT_FEATURES
from binance_multistrategy.cli import build_parser
from conftest import synthetic_bars


def artificial_labels(n, start, seed):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, len(INPUT_FEATURES)))
    df = pd.DataFrame(x, columns=INPUT_FEATURES)
    df["label"] = (df.ret1 > 0).astype(int)
    df["net_r"] = np.where(df.label == 1, 2., -1.)
    df["signal_time"] = pd.date_range(start, periods=n, freq="min", tz="UTC")
    df["label_end_time"] = df.signal_time + pd.Timedelta(minutes=10)
    return df


def test_purging_removes_overlapping_labels():
    rows = artificial_labels(1000, "2020-01-01", 1)
    start = pd.Timestamp("2020-01-01", tz="UTC")
    end = start + pd.Timedelta(minutes=990)
    filtered = purged_window(rows, start, end, 20)
    assert filtered.label_end_time.max() < end
    assert filtered.signal_time.min() >= start + pd.Timedelta(minutes=20)
    assert filtered.signal_time.max() < end - pd.Timedelta(minutes=20)


def test_ml_fit_calibrate_save_score_schema(tmp_path):
    train, cal = artificial_labels(1200, "2020-01-01", 1), artificial_labels(400, "2020-02-01", 2)
    cfg = ResearchConfig(n_threads=1)
    clf, reg, calibrator, report = fit_heads(train, cal, cfg)
    model = TrainedGate(clf, reg, calibrator, cfg, list(INPUT_FEATURES),
                        {"sklearn_version": sklearn.__version__, "code_sha256": code_fingerprint()}, .7, False)
    scored = model.score(cal)
    assert scored.probability.between(0, 1).all()
    assert np.isfinite(scored.expected_r).all()
    model.save(tmp_path / "synthetic_software_test_only.joblib")
    loaded = TrainedGate.load(tmp_path / "synthetic_software_test_only.joblib")
    np.testing.assert_allclose(loaded.score(cal).probability, scored.probability)
    with pytest.raises(ValueError, match="schema"):
        loaded.score(cal.drop(columns=[INPUT_FEATURES[0]]))
    # This verifies ML plumbing; no synthetic win rate is a financial result.


def test_training_overlap_is_rejected():
    train = artificial_labels(1000, "2020-01-01", 1)
    cal = artificial_labels(400, "2020-01-01", 2)
    with pytest.raises(ValueError, match="overlaps"):
        fit_heads(train, cal, ResearchConfig())


def test_training_one_class_is_rejected():
    train = artificial_labels(1000, "2020-01-01", 1)
    train["label"] = 1
    cal = artificial_labels(400, "2020-02-01", 2)
    with pytest.raises(ValueError, match="Insufficient"):
        fit_heads(train, cal, ResearchConfig())


def test_cli_has_no_live_order_command():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["live"])


def test_pipeline_end_to_end_synthetic_only(tmp_path):
    data = synthetic_bars(52000, 25)
    config = ResearchConfig(fee_bps=1, slippage_bps=1, bootstrap_iterations=20, n_threads=1)
    report = train_pipeline(data, {"source": "SYNTHETIC SOFTWARE TEST ONLY", "data_sha256": "synthetic"}, config,
                            pd.Timestamp("2020-01-17", tz="UTC"), pd.Timestamp("2020-01-25", tz="UTC"),
                            pd.Timestamp("2020-02-05", tz="UTC"), tmp_path)
    assert report["trained"] is True
    assert (tmp_path / "model.joblib").is_file()
    assert report["status"] == "target_not_demonstrated"
    metadata = report["metadata"]
    assert pd.Timestamp(metadata["max_training_label_end"]) < pd.Timestamp(metadata["min_calibration_signal_time"])
    assert pd.Timestamp(metadata["max_calibration_label_end"]) < pd.Timestamp(metadata["calibration_end"])
    TrainedGate.load(tmp_path / "model.joblib")


def test_future_data_does_not_change_trained_predictions(tmp_path):
    data = synthetic_bars(52000, 25)
    boundary = pd.Timestamp("2020-02-05", tz="UTC")
    changed = data.copy()
    mask = changed.open_time >= boundary
    for c in ["open", "high", "low", "close", "mark_open", "mark_high", "mark_low", "mark_close"]:
        changed.loc[mask, c] *= 3
    config = ResearchConfig(fee_bps=1, slippage_bps=1, bootstrap_iterations=10, n_threads=1)
    kwargs = (pd.Timestamp("2020-01-17", tz="UTC"), pd.Timestamp("2020-01-25", tz="UTC"), boundary)
    for name, candles in [("a", data), ("b", changed)]:
        train_pipeline(candles, {"source": "SYNTHETIC SOFTWARE TEST ONLY"}, config, *kwargs, tmp_path / name)
    a, b = TrainedGate.load(tmp_path / "a/model.joblib"), TrainedGate.load(tmp_path / "b/model.joblib")
    probe = artificial_labels(100, "2020-02-01", 35)
    np.testing.assert_array_equal(a.score(probe).probability, b.score(probe).probability)
    np.testing.assert_array_equal(a.score(probe).expected_r, b.score(probe).expected_r)
    assert not a.classifier.early_stopping
