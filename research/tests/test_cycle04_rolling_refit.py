import importlib.util
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cycle04_rolling_refit.py"
SPEC = importlib.util.spec_from_file_location("cycle04_rolling_refit", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_month_folds_cover_window_without_gaps_or_overlap():
    start = pd.Timestamp("2026-01-02T00:00:00Z")
    end = pd.Timestamp("2026-09-01T00:00:00Z")
    folds = MODULE.month_folds(start, end)

    assert folds[0] == (start, pd.Timestamp("2026-02-01T00:00:00Z"))
    assert folds[-1] == (pd.Timestamp("2026-08-01T00:00:00Z"), end)
    assert all(left_end == right_start for (_, left_end), (right_start, _) in zip(folds, folds[1:]))
    assert folds[0][0] == start
    assert folds[-1][1] == end


def test_training_labels_exclude_unmatured_labels_and_embargo_boundary():
    labels = pd.DataFrame({
        "signal_time": pd.to_datetime([
            "2025-12-30T00:00:00Z",
            "2025-12-31T00:00:00Z",
            "2025-12-30T12:00:00Z",
        ], utc=True),
        "label_end_time": pd.to_datetime([
            "2025-12-31T23:59:00Z",
            "2025-12-31T12:00:00Z",
            "2026-01-01T00:01:00Z",
        ], utc=True),
        "candidate_id": ["matured", "embargo", "not_matured"],
    })

    training = MODULE.matured_training_labels(
        labels, pd.Timestamp("2026-01-01T00:00:00Z")
    )

    assert training.candidate_id.tolist() == ["matured"]
    assert (training.label_end_time < pd.Timestamp("2026-01-01T00:00:00Z")).all()


def test_month_candidates_keeps_full_fold_and_does_not_add_month_end_embargo():
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    end = pd.Timestamp("2026-02-01T00:00:00Z")
    labels = pd.DataFrame({
        "signal_time": pd.to_datetime([
            "2026-01-01T00:00:00Z",
            "2026-01-31T23:59:00Z",
            "2026-02-01T00:00:00Z",
        ], utc=True),
        "candidate_id": ["first", "last", "next_month"],
    })

    selected = MODULE.month_candidates(labels, start, end)

    assert selected.candidate_id.tolist() == ["first", "last"]
