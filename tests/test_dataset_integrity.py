from pathlib import Path

import pandas as pd

from laya_trader.config import AppConfig, DataConfig
from laya_trader.dataset import build as build_module
from laya_trader.dataset.build import (
    _clip_to_configured_range,
    _configured_archive_paths,
    _mark_contiguous_segments,
)


def test_archive_selection_ignores_stale_months(tmp_path: Path):
    for month in ("2024-12", "2025-01", "2025-02"):
        (tmp_path / f"BTCUSDT-15m-{month}.zip").touch()

    paths = _configured_archive_paths(
        tmp_path,
        "BTCUSDT",
        "15m",
        "2025-01-10",
        "2025-01-20",
    )

    assert [path.name for path in paths] == ["BTCUSDT-15m-2025-01.zip"]


def test_midmonth_end_is_inclusive_but_does_not_leak_next_day():
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2025-01-14T23:59:59Z",
                    "2025-01-15T00:14:59Z",
                    "2025-01-15T23:59:59Z",
                    "2025-01-16T00:14:59Z",
                ],
                utc=True,
            )
        }
    )

    clipped = _clip_to_configured_range(frame, "2025-01-15", "2025-01-15")

    assert len(clipped) == 2
    assert clipped["timestamp"].max() < pd.Timestamp("2025-01-16T00:00:00Z")


def test_missing_candle_starts_new_contiguous_segment():
    frame = pd.DataFrame(
        {
            "open_time": pd.to_datetime(
                [
                    "2025-01-01T00:00:00Z",
                    "2025-01-01T00:15:00Z",
                    "2025-01-01T00:45:00Z",
                    "2025-01-01T01:00:00Z",
                ],
                utc=True,
            )
        }
    )

    marked = _mark_contiguous_segments(frame, "15m")

    assert marked["_segment_id"].tolist() == [0, 0, 1, 1]


def test_empty_rebuild_removes_stale_parquet(tmp_path: Path, monkeypatch):
    cfg_file = tmp_path / "dataset.toml"
    cfg_file.write_text("", encoding="utf-8")
    cfg = AppConfig(data=DataConfig(dataset_dir=tmp_path, symbols=()))

    monkeypatch.setattr(build_module, "load_config", lambda _: cfg)

    stale = tmp_path / "train.parquet"
    stale.write_bytes(b"stale")

    manifest = build_module.build_dataset(cfg_file)

    assert manifest["splits"]["train"]["rows"] == 0
    assert not stale.exists()
