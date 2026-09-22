import pandas as pd

from laya_trader.config import SplitConfig
from laya_trader.dataset.splits import split_frame


def test_split_purges_cross_boundary_labels_and_embargoes_next_split():
    ts = pd.date_range("2024-12-31 22:00", periods=20, freq="15min", tz="UTC")
    df = pd.DataFrame({"timestamp": ts, "label_end_ts": ts + pd.Timedelta(hours=1)})
    cfg = SplitConfig(
        train_end="2024-12-31T23:59:59Z",
        calibration_end="2025-01-01T02:59:59Z",
        validation_end="2025-01-01T04:59:59Z",
        test_end="2025-01-01T23:59:59Z",
        embargo_bars=4,
    )
    splits = split_frame(df, cfg, "15m")
    assert (splits["train"]["label_end_ts"] <= pd.Timestamp(cfg.train_end)).all()
    if not splits["calibration"].empty:
        assert (
            splits["calibration"]["timestamp"].min()
            > pd.Timestamp(cfg.train_end) + pd.Timedelta(hours=1)
        )
