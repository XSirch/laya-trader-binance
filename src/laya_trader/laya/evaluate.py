from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

import laya
import numpy as np
import torch
from laya.common import collate_items, confidence_from_probs, temp_bucket

from laya_trader.laya.questions import ACTION_KEYS
from laya_trader.laya.records import record_to_items

THRESHOLDS = (0.50, 0.60, 0.70, 0.80)
ACTION_THRESHOLDS = (0.40, 0.50, 0.60, 0.70)
QUESTION_IDS = ("action", "tradeable", "edge_quality")
ACTION_TO_INDEX = {name: index for index, name in enumerate(ACTION_KEYS)}


def _records(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def _batches(path: Path, size: int) -> Iterable[list[dict]]:
    batch: list[dict] = []
    for record in _records(path):
        batch.append(record)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _softmax(values: np.ndarray) -> np.ndarray:
    shifted = values - values.max(axis=-1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=-1, keepdims=True)


def _temperature(agent, qtype: int, options: int) -> float:
    key = temp_bucket(qtype, options)
    fitted = agent.cfg.get("temperature_by_options", {})
    if key in fitted:
        return max(float(fitted[key]), 1e-6)
    return max(float(agent.cfg.get("temperature", [1.0] * 4)[qtype]), 1e-6)


def _predict_batch(agent, batch: list[dict]) -> list[dict]:
    groups = [
        record_to_items(
            record,
            agent.tok,
            int(agent.cfg.get("max_len", 512)),
            int(agent.cfg.get("head_max_len", 192)),
        )
        for record in batch
    ]
    collated = collate_items(groups, agent.tok.pad_token_id)
    device = agent.device
    tensors = {
        key: value.to(device)
        for key, value in collated.items()
        if torch.is_tensor(value)
    }
    use_amp = device.type == "cuda"
    amp_dtype = getattr(agent, "dtype", torch.bfloat16)
    with torch.no_grad(), torch.autocast(
        device_type=device.type,
        dtype=amp_dtype,
        enabled=use_amp,
    ):
        logits, _ = agent.model(
            tensors["input_ids"],
            tensors["attention_mask"],
            tensors["marker_pos"],
            tensors["marker_mask"],
            tensors["qtype"],
        )
    logits = logits.float().cpu().numpy()

    predicted: list[dict] = []
    for row_index, record in enumerate(batch):
        answers: dict[str, dict] = {}
        for question_index, question_id in enumerate(QUESTION_IDS):
            item = groups[row_index][question_index]
            flat_index = row_index * len(QUESTION_IDS) + question_index
            options = len(item["markers"])
            probabilities = _softmax(
                logits[flat_index, :options] / _temperature(agent, item["qtype"], options)
            )
            confidence = float(confidence_from_probs(probabilities, options))
            if question_id == "action":
                answers[question_id] = {
                    "probabilities": probabilities.tolist(),
                    "choice_index": int(probabilities.argmax()),
                    "confidence": confidence,
                }
            elif question_id == "tradeable":
                answers[question_id] = {
                    "probabilities": probabilities.tolist(),
                    "noul": float(probabilities[1]),
                    "confidence": float(max(probabilities)),
                }
            else:
                answers[question_id] = {
                    "probabilities": probabilities.tolist(),
                    "score": float(np.dot(np.arange(options, dtype=float), probabilities)),
                    "confidence": confidence,
                }
        diagnostics = record.get("diagnostics", {})
        predicted.append(
            {
                "id": record.get("id"),
                "symbol": record.get("symbol"),
                "decision_time": record.get("decision_time"),
                "state": record.get("state"),
                "targets": record["targets"],
                "diagnostics": {
                    "long_r": float(diagnostics["long_r"]),
                    "short_r": float(diagnostics["short_r"]),
                    "label_end_time": str(diagnostics["label_end_time"]),
                },
                "answers": answers,
            }
        )
    return predicted


def _load_predictions(checkpoint: Path, path: Path, batch_size: int) -> list[dict]:
    agent = laya.load(str(checkpoint))
    agent.model.eval()
    predictions: list[dict] = []
    for batch in _batches(path, batch_size):
        predictions.extend(_predict_batch(agent, batch))
    return predictions


def _arrays(predictions: list[dict]) -> dict[str, np.ndarray]:
    action_probabilities = np.asarray(
        [row["answers"]["action"]["probabilities"] for row in predictions], dtype=float
    )
    tradeable_probabilities = np.asarray(
        [row["answers"]["tradeable"]["probabilities"] for row in predictions], dtype=float
    )
    edge_probabilities = np.asarray(
        [row["answers"]["edge_quality"]["probabilities"] for row in predictions], dtype=float
    )
    return {
        "action_probabilities": action_probabilities,
        "action_index": action_probabilities.argmax(axis=1),
        "action_confidence": np.asarray(
            [row["answers"]["action"]["confidence"] for row in predictions], dtype=float
        ),
        "tradeable": tradeable_probabilities[:, 1],
        "tradeable_confidence": np.asarray(
            [row["answers"]["tradeable"]["confidence"] for row in predictions], dtype=float
        ),
        "edge_probabilities": edge_probabilities,
        "edge_score": np.asarray(
            [row["answers"]["edge_quality"]["score"] for row in predictions], dtype=float
        ),
        "target_action": np.asarray(
            [row["targets"]["action"] for row in predictions], dtype=float
        ),
        "target_tradeable": np.asarray(
            [row["targets"]["tradeable"] for row in predictions], dtype=float
        ),
        "target_edge": np.asarray(
            [row["targets"]["edge_quality"] for row in predictions], dtype=float
        ),
        "long_r": np.asarray(
            [row["diagnostics"]["long_r"] for row in predictions], dtype=float
        ),
        "short_r": np.asarray(
            [row["diagnostics"]["short_r"] for row in predictions], dtype=float
        ),
    }


def _nll(probabilities: np.ndarray, targets: np.ndarray) -> float:
    return float(-np.mean(np.sum(targets * np.log(np.clip(probabilities, 1e-12, 1.0)), axis=1)))


def _brier(probabilities: np.ndarray, targets: np.ndarray) -> float:
    return float(np.mean(np.sum((probabilities - targets) ** 2, axis=1)))


def _ece(probabilities: np.ndarray, target: np.ndarray, confidence: np.ndarray) -> float:
    predicted = probabilities.argmax(axis=1)
    actual = target.argmax(axis=1)
    correct = (predicted == actual).astype(float)
    bins = np.linspace(0.0, 1.0, 11)
    result = 0.0
    for low, high in pairwise(bins):
        mask = (confidence >= low) & ((confidence < high) if high < 1 else (confidence <= high))
        if mask.any():
            result += float(mask.mean()) * abs(float(correct[mask].mean()) - float(confidence[mask].mean()))
    return result


def _model_metrics(arrays: dict[str, np.ndarray]) -> dict:
    action_probabilities = arrays["action_probabilities"]
    target_action = arrays["target_action"]
    target_tradeable = arrays["target_tradeable"]
    target_edge = arrays["target_edge"]
    actual = target_action.argmax(axis=1)
    predicted = arrays["action_index"]
    confusion = {
        ACTION_KEYS[row]: {
            ACTION_KEYS[column]: int(((actual == row) & (predicted == column)).sum())
            for column in range(3)
        }
        for row in range(3)
    }
    return {
        "action_nll": _nll(action_probabilities, target_action),
        "action_brier": _brier(action_probabilities, target_action),
        "action_agreement_with_target_argmax": float(np.mean(predicted == actual)),
        "action_ece": _ece(
            action_probabilities, target_action, action_probabilities.max(axis=1)
        ),
        "confusion_matrix": confusion,
        "question_nll": {
            "action": _nll(action_probabilities, target_action),
            "tradeable": _nll(
                np.column_stack((1.0 - arrays["tradeable"], arrays["tradeable"])),
                target_tradeable,
            ),
            "edge_quality": _nll(arrays["edge_probabilities"], target_edge),
        },
        "question_brier": {
            "action": _brier(action_probabilities, target_action),
            "tradeable": _brier(
                np.column_stack((1.0 - arrays["tradeable"], arrays["tradeable"])),
                target_tradeable,
            ),
            "edge_quality": _brier(arrays["edge_probabilities"], target_edge),
        },
    }


def _profit_factor(values: np.ndarray) -> float | None:
    losses = float(np.abs(values[values < 0]).sum())
    if losses == 0.0:
        return None
    return float(values[values > 0].sum() / losses)


def _signal_metrics(arrays: dict[str, np.ndarray], mask: np.ndarray) -> dict:
    actions = arrays["action_index"]
    directional = mask & (actions != ACTION_TO_INDEX["FLAT"])
    selected_r = np.where(actions == ACTION_TO_INDEX["LONG"], arrays["long_r"], arrays["short_r"])
    values = selected_r[directional]
    return {
        "samples": len(actions),
        "eligible_signals": int(mask.sum()),
        "trades": int(directional.sum()),
        "LONG": int((directional & (actions == ACTION_TO_INDEX["LONG"])).sum()),
        "SHORT": int((directional & (actions == ACTION_TO_INDEX["SHORT"])).sum()),
        "FLAT": int((mask & (actions == ACTION_TO_INDEX["FLAT"])).sum()),
        "action_counts": {name: int((actions == index).sum()) for name, index in ACTION_TO_INDEX.items()},
        "mean_R": float(values.mean()) if values.size else None,
        "median_R": float(np.median(values)) if values.size else None,
        "win_rate": float(np.mean(values > 0)) if values.size else None,
        "loss_rate": float(np.mean(values < 0)) if values.size else None,
        "profit_factor": _profit_factor(values) if values.size else None,
    }


def _bucket(value: float, edges: tuple[float, ...], labels: tuple[str, ...]) -> str:
    index = int(np.digitize([value], edges, right=False)[0])
    return labels[min(index, len(labels) - 1)]


def _group_metrics(
    predictions: list[dict], arrays: dict[str, np.ndarray], mask: np.ndarray, key: str
) -> dict:
    groups: dict[str, np.ndarray] = {}
    if key == "symbol":
        values = [str(row["symbol"]) for row in predictions]
    elif key == "month":
        values = [str(row["decision_time"])[:7] for row in predictions]
    elif key == "confidence_bucket":
        values = [
            _bucket(
                value,
                (0.4, 0.5, 0.6, 0.7, 0.8),
                ("<0.40", "0.40-0.50", "0.50-0.60", "0.60-0.70", "0.70-0.80", ">=0.80"),
            )
            for value in arrays["action_confidence"]
        ]
    elif key == "tradeable_bucket":
        values = [
            _bucket(
                value,
                (0.5, 0.6, 0.7, 0.8, 0.9),
                ("<0.50", "0.50-0.60", "0.60-0.70", "0.70-0.80", "0.80-0.90", ">=0.90"),
            )
            for value in arrays["tradeable"]
        ]
    elif key == "edge_quality_bucket":
        values = [
            _bucket(value, (1.0, 2.0, 3.0, 4.0), ("<1", "1-2", "2-3", "3-4", "4"))
            for value in arrays["edge_score"]
        ]
    else:
        raise ValueError(f"unknown grouping key: {key}")
    for name in sorted(set(values)):
        groups[name] = mask & np.asarray([value == name for value in values])
    return {name: _signal_metrics(arrays, group_mask) for name, group_mask in groups.items()}


def _majority_action(train_path: Path) -> int:
    counts = Counter()
    for record in _records(train_path):
        counts[int(np.argmax(record["targets"]["action"]))] += 1
    return counts.most_common(1)[0][0]


def _ema_action(row: dict) -> int:
    base = row["state"]["base"]
    upward = {"up", "strong_up", "extreme_up", "slightly_above", "above", "far_above"}
    downward = {"down", "strong_down", "extreme_down", "slightly_below", "below", "far_below"}
    fast = base["price_vs_ema20"]
    slow = base["price_vs_ema200"]
    if fast in upward and slow in upward:
        return ACTION_TO_INDEX["LONG"]
    if fast in downward and slow in downward:
        return ACTION_TO_INDEX["SHORT"]
    return ACTION_TO_INDEX["FLAT"]


def _baseline_reports(
    predictions: list[dict], arrays: dict[str, np.ndarray], taken_mask: np.ndarray, reference_train: Path
) -> dict:
    majority = _majority_action(reference_train)
    majority_mask = np.full(len(predictions), majority != ACTION_TO_INDEX["FLAT"], dtype=bool)
    rng = np.random.default_rng(42)
    random_actions = np.full(len(predictions), ACTION_TO_INDEX["FLAT"], dtype=int)
    trade_count = int((taken_mask & (arrays["action_index"] != ACTION_TO_INDEX["FLAT"])).sum())
    trade_indices = rng.permutation(len(predictions))[:trade_count]
    long_count = int((taken_mask & (arrays["action_index"] == ACTION_TO_INDEX["LONG"])).sum())
    long_indices = set(trade_indices[:long_count].tolist())
    for index in trade_indices:
        random_actions[index] = ACTION_TO_INDEX["LONG"] if index in long_indices else ACTION_TO_INDEX["SHORT"]

    baseline_reports = {"always_flat": _signal_metrics(arrays, np.zeros(len(predictions), dtype=bool))}
    majority_arrays = dict(arrays)
    majority_arrays["action_index"] = np.full(len(predictions), majority, dtype=int)
    baseline_reports["majority_action"] = _signal_metrics(majority_arrays, majority_mask)
    random_arrays = dict(arrays)
    random_arrays["action_index"] = random_actions
    baseline_reports["random_direction_same_trade_frequency"] = _signal_metrics(
        random_arrays, random_actions != ACTION_TO_INDEX["FLAT"]
    )
    ema_actions = np.asarray([_ema_action(row) for row in predictions], dtype=int)
    ema_arrays = dict(arrays)
    ema_arrays["action_index"] = ema_actions
    baseline_reports["ema_trend"] = _signal_metrics(
        ema_arrays, ema_actions != ACTION_TO_INDEX["FLAT"]
    )
    return baseline_reports


def _select_thresholds(
    predictions: list[dict], arrays: dict[str, np.ndarray]
) -> tuple[list[dict], dict]:
    action_probability = arrays["action_probabilities"].max(axis=1)
    grid = []
    for tradeable_min in THRESHOLDS:
        for action_probability_min in ACTION_THRESHOLDS:
            candidate_mask = (
                (arrays["tradeable"] >= tradeable_min)
                & (action_probability >= action_probability_min)
            )
            metrics = _signal_metrics(arrays, candidate_mask)
            gate = _threshold_gate(predictions, arrays, candidate_mask)
            grid.append(
                {
                    "tradeable_min": tradeable_min,
                    "action_probability_min": action_probability_min,
                    **metrics,
                    **gate,
                }
            )
    eligible = [row for row in grid if row["eligible_for_selection"]]
    selected = max(
        eligible,
        key=lambda row: (
            row["nonoverlap_by_symbol"]["mean_R"],
            row["nonoverlap_by_symbol"]["profit_factor"]
            if row["nonoverlap_by_symbol"]["profit_factor"] is not None
            else float("inf"),
            row["nonoverlap_by_symbol"]["trades"],
        ),
        default=None,
    )
    return grid, {
        "minimum_trades": max(100, int(len(action_probability) * 0.005)),
        "minimum_profitable_months": math.ceil(
            len({str(row["decision_time"])[:7] for row in predictions}) * 2 / 3
        ),
        "selected": (
            {
                "tradeable_min": selected["tradeable_min"],
                "action_probability_min": selected["action_probability_min"],
            }
            if selected
            else None
        ),
    }


def _threshold_gate(
    predictions: list[dict], arrays: dict[str, np.ndarray], mask: np.ndarray
) -> dict:
    minimum_trades = max(100, int(len(predictions) * 0.005))
    months = np.asarray([str(row["decision_time"])[:7] for row in predictions])
    all_months = sorted(set(months))
    minimum_profitable_months = math.ceil(len(all_months) * 2 / 3)
    executed_mask = _nonoverlap_mask(predictions, arrays, mask)
    executed = _signal_metrics(arrays, executed_mask)
    profitable_months = sum(
        1
        for month in all_months
        if (monthly := _signal_metrics(arrays, executed_mask & (months == month)))["trades"] > 0
        and monthly["mean_R"] > 0
    )
    enough_trades = executed["trades"] >= minimum_trades
    positive_after_costs = executed["mean_R"] is not None and executed["mean_R"] > 0
    stable_months = profitable_months >= minimum_profitable_months
    return {
        "minimum_trades": minimum_trades,
        "nonoverlap_by_symbol": executed,
        "profitable_months": profitable_months,
        "minimum_profitable_months": minimum_profitable_months,
        "meets_minimum_trades": enough_trades,
        "positive_after_costs": positive_after_costs,
        "stable_months": stable_months,
        "eligible_for_selection": enough_trades and positive_after_costs and stable_months,
    }


def _nonoverlap_mask(
    predictions: list[dict], arrays: dict[str, np.ndarray], mask: np.ndarray
) -> np.ndarray:
    """Conservatively hold each symbol until the full label horizon ends."""
    directional = mask & (arrays["action_index"] != ACTION_TO_INDEX["FLAT"])
    action_probability = arrays["action_probabilities"].max(axis=1)
    ordered = sorted(
        np.flatnonzero(directional),
        key=lambda index: (
            predictions[index]["decision_time"],
            -action_probability[index],
            predictions[index]["symbol"],
        ),
    )
    accepted = np.zeros(len(predictions), dtype=bool)
    last_end: dict[str, str] = {}
    for index in ordered:
        row = predictions[index]
        symbol = str(row["symbol"])
        decision_time = str(row["decision_time"])
        if decision_time >= last_end.get(symbol, ""):
            accepted[index] = True
            last_end[symbol] = str(row["diagnostics"]["label_end_time"])
    return accepted


def evaluate_predictions(
    predictions: list[dict],
    thresholds: dict[str, float],
    reference_train: Path,
    include_threshold_grid: bool,
) -> dict:
    arrays = _arrays(predictions)
    action_probability = arrays["action_probabilities"].max(axis=1)
    taken_mask = (
        (arrays["tradeable"] >= float(thresholds["tradeable_min"]))
        & (action_probability >= float(thresholds["action_probability_min"]))
    )
    signal_mask = taken_mask & (arrays["action_index"] != ACTION_TO_INDEX["FLAT"])
    nonoverlap_mask = _nonoverlap_mask(predictions, arrays, taken_mask)
    report = {
        "samples": len(predictions),
        "thresholds": thresholds,
        "model": _model_metrics(arrays),
        "signal_level_realized_R": _signal_metrics(arrays, taken_mask),
        "nonoverlap_by_symbol_realized_R": _signal_metrics(arrays, nonoverlap_mask),
        "per_symbol": _group_metrics(predictions, arrays, signal_mask, "symbol"),
        "per_month": _group_metrics(predictions, arrays, signal_mask, "month"),
        "confidence_bucket": _group_metrics(predictions, arrays, signal_mask, "confidence_bucket"),
        "tradeable_bucket": _group_metrics(predictions, arrays, signal_mask, "tradeable_bucket"),
        "edge_quality_bucket": _group_metrics(predictions, arrays, signal_mask, "edge_quality_bucket"),
        "baselines": _baseline_reports(predictions, arrays, taken_mask, reference_train),
    }
    if include_threshold_grid:
        grid, selection = _select_thresholds(predictions, arrays)
        report["threshold_grid"] = grid
        report["threshold_selection"] = selection
    return report


def render_markdown(report: dict, title: str) -> str:
    signal = report["signal_level_realized_R"]
    nonoverlap = report["nonoverlap_by_symbol_realized_R"]
    model = report["model"]
    lines = [
        f"# {title}",
        "",
        f"- Samples: **{report['samples']}**",
        f"- Thresholds: `{json.dumps(report['thresholds'], sort_keys=True)}`",
        "",
        "## Model metrics",
        "",
        f"- Action NLL: `{model['action_nll']:.6f}`; Brier: `{model['action_brier']:.6f}`",
        f"- Agreement with target argmax: `{model['action_agreement_with_target_argmax']:.4%}`",
        f"- Action ECE: `{model['action_ece']:.6f}`",
        "",
        "## Signal-level realized R",
        "",
        "These are overlapping, independent signal outcomes after label costs; they are not portfolio PnL.",
        "",
        f"- Eligible signals: `{signal['eligible_signals']}`; trades: `{signal['trades']}`; LONG: `{signal['LONG']}`; SHORT: `{signal['SHORT']}`",
        f"- Mean R: `{signal['mean_R']}`; median R: `{signal['median_R']}`; win rate: `{signal['win_rate']}`; profit factor: `{signal['profit_factor']}`",
        "",
        "## Conservative nonoverlap by symbol",
        "",
        "At most one position per symbol is held through the full label horizon. This is not portfolio PnL.",
        "",
        f"- Trades: `{nonoverlap['trades']}`; mean R: `{nonoverlap['mean_R']}`; profit factor: `{nonoverlap['profit_factor']}`",
        "",
        "## Baselines",
        "",
        "| baseline | trades | mean R | profit factor | win rate |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, metrics in report["baselines"].items():
        lines.append(
            f"| {name} | {metrics['trades']} | {metrics['mean_R']} | {metrics['profit_factor']} | {metrics['win_rate']} |"
        )
    if "threshold_grid" in report:
        lines += [
            "", "## Threshold selection (calibration)", "",
            "```json", json.dumps(report["threshold_selection"], indent=2), "```",
        ]
    if "validation_gate" in report:
        lines += [
            "", "## Fixed-threshold validation gate", "",
            "```json", json.dumps(report["validation_gate"], indent=2), "```",
            f"- Basic gate passed: `{report['thresholds_pass_basic_gate']}`",
        ]
    lines += ["", "## Confusion matrix", "", "```json", json.dumps(model["confusion_matrix"], indent=2), "```", ""]
    return "\n".join(lines)


def _default_title(path: Path) -> str:
    return "Validation Report" if path.stem == "validation" else "Final Test Report"


def _save_selected_thresholds(selected: dict | None, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    if selected is not None:
        temporary.write_text(json.dumps(selected, indent=2), encoding="utf-8")
    if path.exists():
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        archive = path.with_name(f"{path.stem}.stale-{stamp}{path.suffix}")
        sequence = 1
        while archive.exists():
            archive = path.with_name(f"{path.stem}.stale-{stamp}-{sequence}{path.suffix}")
            sequence += 1
        path.replace(archive)
        print(f"archived previous thresholds to {archive}")
    if selected is not None:
        temporary.replace(path)


def _check_selection_order(selection_predictions: list[dict], predictions: list[dict]) -> None:
    if not selection_predictions or not predictions:
        raise ValueError("selection and evaluation datasets must both contain records")
    latest_selection = max(str(row["decision_time"]) for row in selection_predictions)
    earliest_evaluation = min(str(row["decision_time"]) for row in predictions)
    if latest_selection >= earliest_evaluation:
        raise ValueError(
            "selection records must end before the evaluation period begins"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate a Laya trading checkpoint")
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", required=True)
    parser.add_argument("--reference-train", default="data/dataset/train.jsonl")
    parser.add_argument("--thresholds")
    parser.add_argument("--select-thresholds", action="store_true")
    parser.add_argument("--selection-data", help="Calibration JSONL used only for threshold selection")
    parser.add_argument("--threshold-output", default="outputs/thresholds.json")
    parser.add_argument("--batch-size", type=int, default=1)
    args = parser.parse_args(argv)
    if args.select_thresholds and not args.selection_data:
        parser.error("--select-thresholds requires --selection-data (calibration JSONL)")
    if args.selection_data and not args.select_thresholds:
        parser.error("--selection-data requires --select-thresholds")
    if args.select_thresholds and args.thresholds:
        parser.error("--thresholds and --select-thresholds cannot be combined")
    data_path = Path(args.data)
    if args.selection_data and Path(args.selection_data).resolve() == data_path.resolve():
        parser.error("selection data and evaluation data must be different files")
    thresholds = {"tradeable_min": 0.70, "action_probability_min": 0.60}
    if args.thresholds:
        thresholds = json.loads(Path(args.thresholds).read_text(encoding="utf-8"))
    selection_report = None
    if args.select_thresholds:
        selection_predictions = _load_predictions(
            Path(args.checkpoint), Path(args.selection_data), args.batch_size
        )
        selection_report = evaluate_predictions(
            selection_predictions, thresholds, Path(args.reference_train),
            include_threshold_grid=True,
        )
        thresholds = selection_report["threshold_selection"]["selected"] or thresholds
    predictions = _load_predictions(Path(args.checkpoint), data_path, args.batch_size)
    if selection_report is not None:
        _check_selection_order(selection_predictions, predictions)
    report = evaluate_predictions(
        predictions,
        thresholds,
        Path(args.reference_train),
        include_threshold_grid=False,
    )
    if selection_report is not None:
        report["threshold_grid"] = selection_report["threshold_grid"]
        report["threshold_selection"] = selection_report["threshold_selection"]
        report["threshold_selection_data"] = str(args.selection_data)
        arrays = _arrays(predictions)
        action_probability = arrays["action_probabilities"].max(axis=1)
        mask = (
            (arrays["tradeable"] >= thresholds["tradeable_min"])
            & (action_probability >= thresholds["action_probability_min"])
        )
        report["validation_gate"] = _threshold_gate(predictions, arrays, mask)
        report["thresholds_pass_basic_gate"] = bool(
            report["threshold_selection"]["selected"]
            and report["validation_gate"]["eligible_for_selection"]
        )
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    output_md = Path(args.output_md)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(
        render_markdown(report, _default_title(data_path)), encoding="utf-8"
    )
    if args.select_thresholds:
        _save_selected_thresholds(
            report["threshold_selection"]["selected"]
            if report["thresholds_pass_basic_gate"] else None,
            Path(args.threshold_output),
        )
    print(json.dumps(report["signal_level_realized_R"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
