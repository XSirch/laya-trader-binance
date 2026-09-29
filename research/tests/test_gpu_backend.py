import numpy as np
import pandas as pd
import pytest

from binance_multistrategy.config import ResearchConfig
from binance_multistrategy.learning import fit_heads
from binance_multistrategy.strategies import INPUT_FEATURES


def test_xgboost_cuda_heads_fit_on_gpu_when_requested():
    xgboost = pytest.importorskip("xgboost")
    if not xgboost.build_info().get("USE_CUDA", False):
        pytest.skip("Installed XGBoost build has no CUDA support")

    rng = np.random.default_rng(27)
    origin = pd.Timestamp("2024-01-01", tz="UTC")

    def sample(count, start):
        values = rng.normal(size=(count, len(INPUT_FEATURES)))
        frame = pd.DataFrame(values, columns=INPUT_FEATURES)
        frame["label"] = (values[:, 0] + 0.25 * values[:, 1] > 0).astype(int)
        frame["net_r"] = values[:, 0] * 0.5 - values[:, 1] * 0.1
        frame["signal_time"] = [start + pd.Timedelta(minutes=i) for i in range(count)]
        frame["label_end_time"] = frame.signal_time + pd.Timedelta(minutes=1)
        return frame

    train = sample(600, origin)
    calibration = sample(400, origin + pd.Timedelta(days=2))
    classifier, regressor, calibrator, diagnostics = fit_heads(
        train, calibration, ResearchConfig(), backend="xgboost_cuda"
    )

    assert diagnostics["ml_backend"] == "xgboost_cuda"
    assert classifier.get_params()["device"] == "cuda:0"
    assert regressor.get_params()["device"] == "cuda:0"
    assert calibrator.classes_.tolist() == [0, 1]
