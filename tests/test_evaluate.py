import json
from pathlib import Path

import numpy as np
import pytest

from laya_trader.laya import evaluate


def threshold_arrays(n: int, eligible: int, r: float) -> dict[str, np.ndarray]:
    return {
        "action_probabilities": np.tile([0.7, 0.2, 0.1], (n, 1)),
        "action_index": np.zeros(n, dtype=int),
        "tradeable": np.r_[np.full(eligible, 0.9), np.full(n - eligible, 0.1)],
        "long_r": np.full(n, r),
        "short_r": np.full(n, -1.0),
    }


def threshold_predictions(n: int) -> list[dict]:
    rows = []
    for index in range(n):
        timestamp = f"2025-{index % 6 + 1:02d}-{index // 6 % 28 + 1:02d}T00:00:00+00:00"
        rows.append(
            {
                "symbol": "BTCUSDT",
                "decision_time": timestamp,
                "diagnostics": {"label_end_time": timestamp},
            }
        )
    return rows


def test_threshold_selection_requires_minimum_trades_and_positive_net_return():
    predictions = threshold_predictions(1000)
    for eligible, realized_r in ((99, 1.0), (100, -1.0)):
        grid, selection = evaluate._select_thresholds(
            predictions, threshold_arrays(1000, eligible, realized_r)
        )
        assert selection == {
            "minimum_trades": 100,
            "minimum_profitable_months": 4,
            "selected": None,
        }
        assert not any(row["eligible_for_selection"] for row in grid)

    grid, selection = evaluate._select_thresholds(predictions, threshold_arrays(1000, 100, 1.0))
    assert selection["selected"] is not None
    assert sum(row["eligible_for_selection"] for row in grid) > 0


def test_threshold_selection_rejects_three_profitable_months():
    predictions = threshold_predictions(1000)
    arrays = threshold_arrays(1000, 100, 1.0)
    for index in range(100):
        if index % 6 >= 3:
            arrays["long_r"][index] = -0.1
    grid, selection = evaluate._select_thresholds(predictions, arrays)
    assert selection["selected"] is None
    assert all(not row["eligible_for_selection"] for row in grid)


def test_nonoverlap_holds_same_symbol_through_label_horizon():
    predictions = [
        {"symbol": "BTCUSDT", "decision_time": "2025-01-01T00:00:00+00:00",
         "diagnostics": {"label_end_time": "2025-01-01T03:00:00+00:00"}},
        {"symbol": "BTCUSDT", "decision_time": "2025-01-01T01:00:00+00:00",
         "diagnostics": {"label_end_time": "2025-01-01T04:00:00+00:00"}},
        {"symbol": "ETHUSDT", "decision_time": "2025-01-01T01:00:00+00:00",
         "diagnostics": {"label_end_time": "2025-01-01T04:00:00+00:00"}},
    ]
    arrays = threshold_arrays(3, 3, 1.0)
    accepted = evaluate._nonoverlap_mask(predictions, arrays, np.ones(3, dtype=bool))
    assert accepted.tolist() == [True, False, True]


def test_action_ece_uses_class_probability_not_entropy_confidence():
    action = np.asarray([[0.8, 0.1, 0.1], [0.6, 0.3, 0.1]])
    target = np.asarray([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    arrays = {
        "action_probabilities": action,
        "action_index": action.argmax(axis=1),
        "action_confidence": np.zeros(2),
        "target_action": target,
        "tradeable": np.full(2, 0.5),
        "target_tradeable": np.tile([0.5, 0.5], (2, 1)),
        "edge_probabilities": np.tile([0.2] * 5, (2, 1)),
        "target_edge": np.tile([0.2] * 5, (2, 1)),
    }
    assert evaluate._model_metrics(arrays)["action_ece"] == pytest.approx(0.4)


def test_random_baseline_matches_actual_directional_trade_count(monkeypatch):
    monkeypatch.setattr(evaluate, "_majority_action", lambda _: 0)
    monkeypatch.setattr(evaluate, "_ema_action", lambda _: 2)
    arrays = {
        "action_index": np.asarray([0, 1, 2, 0, 2, 1, 2, 0, 1, 2]),
        "long_r": np.full(10, 1.0),
        "short_r": np.full(10, -1.0),
    }
    taken_mask = np.asarray([True] * 5 + [False] * 5)
    reports = evaluate._baseline_reports([{}] * 10, arrays, taken_mask, Path("unused"))
    assert reports["random_direction_same_trade_frequency"]["trades"] == 3


def test_no_selection_archives_stale_threshold_file(tmp_path: Path):
    threshold_path = tmp_path / "thresholds.json"
    threshold_path.write_text('{"tradeable_min": 0.5}', encoding="utf-8")

    evaluate._save_selected_thresholds(None, threshold_path)

    assert not threshold_path.exists()
    archived = list(tmp_path.glob("thresholds.stale-*.json"))
    assert len(archived) == 1
    assert archived[0].read_text(encoding="utf-8") == '{"tradeable_min": 0.5}'


def test_threshold_gate_rejects_overlapping_trades():
    predictions = threshold_predictions(1000)
    for row in predictions:
        row["decision_time"] = "2025-01-01T00:00:00+00:00"
        row["diagnostics"]["label_end_time"] = "2025-01-01T04:00:00+00:00"
    gate = evaluate._threshold_gate(
        predictions, threshold_arrays(1000, 1000, 1.0), np.ones(1000, dtype=bool)
    )
    assert gate["nonoverlap_by_symbol"]["trades"] == 1
    assert not gate["eligible_for_selection"]


def test_selection_data_must_precede_evaluation_data():
    calibration = [{"decision_time": "2025-06-30T23:45:00+00:00"}]
    validation = [{"decision_time": "2025-07-01T00:00:00+00:00"}]
    evaluate._check_selection_order(calibration, validation)
    with pytest.raises(ValueError, match="must end before"):
        evaluate._check_selection_order(validation, calibration)
    with pytest.raises(ValueError, match="must both contain"):
        evaluate._check_selection_order([], validation)


def test_threshold_selection_requires_distinct_calibration_file(tmp_path: Path):
    data = tmp_path / "validation.jsonl"
    with pytest.raises(SystemExit) as error:
        evaluate.main([
            "--checkpoint", "unused", "--data", str(data),
            "--output-json", str(tmp_path / "report.json"),
            "--output-md", str(tmp_path / "report.md"),
            "--select-thresholds", "--selection-data", str(data),
        ])
    assert error.value.code == 2


def test_validation_failure_does_not_leave_active_thresholds(tmp_path: Path, monkeypatch):
    calibration = tmp_path / "calibration.jsonl"
    validation = tmp_path / "validation.jsonl"
    threshold_path = tmp_path / "thresholds.json"
    threshold_path.write_text('{"tradeable_min": 0.5}', encoding="utf-8")
    monkeypatch.setattr(
        evaluate, "_load_predictions",
        lambda _, path, __: [{"decision_time": (
            "2025-01-01T00:00:00+00:00" if path == calibration else
            "2025-07-01T00:00:00+00:00"
        )}],
    )
    monkeypatch.setattr(
        evaluate, "evaluate_predictions",
        lambda _, thresholds, __, include_threshold_grid: (
            {"threshold_grid": [], "threshold_selection": {
                "selected": {"tradeable_min": 0.5, "action_probability_min": 0.4}
            }} if include_threshold_grid else {"thresholds": thresholds, "signal_level_realized_R": {}}
        ),
    )
    monkeypatch.setattr(evaluate, "_arrays", lambda _: threshold_arrays(1, 1, 1.0))
    monkeypatch.setattr(evaluate, "_threshold_gate", lambda *_: {"eligible_for_selection": False})
    monkeypatch.setattr(evaluate, "render_markdown", lambda *_: "report\n")

    assert evaluate.main([
        "--checkpoint", "unused", "--data", str(validation),
        "--selection-data", str(calibration),
        "--output-json", str(tmp_path / "report.json"),
        "--output-md", str(tmp_path / "report.md"),
        "--select-thresholds", "--threshold-output", str(threshold_path),
    ]) == 0
    assert not threshold_path.exists()
    assert len(list(tmp_path.glob("thresholds.stale-*.json"))) == 1
    assert not json.loads((tmp_path / "report.json").read_text())["thresholds_pass_basic_gate"]
