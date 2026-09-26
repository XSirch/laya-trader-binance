"""Describe action-target sharpness and input truncation without model inference."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from laya.common import build_sequence
from transformers import AutoTokenizer

from laya_trader.laya.questions import trading_questions
from laya_trader.laya.records import _internal_question


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/dataset"
REPORT = ROOT / "outputs/laya_target_input_audit.json"
SPLITS = ("train", "calibration")
SAMPLE_STRIDE = 500
MAX_SAMPLES = 200
MAX_LEN = 512
HEAD_MAX_LEN = 192


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def targets_for_split(split: str) -> dict:
    path = DATASET / f"{split}.parquet"
    frame = pd.read_parquet(
        path,
        columns=["target_long", "target_short", "target_flat", "target_trade_true"],
    )
    probabilities = frame[["target_long", "target_short", "target_flat"]].to_numpy(float)
    if not np.isfinite(probabilities).all() or not np.allclose(
        probabilities.sum(axis=1), 1, atol=1e-6
    ):
        raise ValueError(f"{split}: invalid action target probabilities")
    marginal = probabilities.mean(axis=0)
    entropy = -(probabilities * np.log(np.clip(probabilities, 1e-12, 1))).sum(axis=1)
    maximum = probabilities.max(axis=1)
    directional = probabilities.argmax(axis=1) != 2
    return {
        "parquet_sha256": sha256_file(path),
        "rows": len(frame),
        "mean_action_target": marginal.tolist(),
        "constant_marginal_action_nll": float(
            -(probabilities * np.log(marginal)).sum(axis=1).mean()
        ),
        "mean_action_target_entropy": float(entropy.mean()),
        "max_action_target_quantiles_10_50_90_99": np.quantile(
            maximum, [0.1, 0.5, 0.9, 0.99]
        ).tolist(),
        "directional_argmax_fraction": float(directional.mean()),
        "directional_and_tradeable_target_ge_0_5_fraction": float(
            (directional & (frame.target_trade_true.to_numpy() >= 0.5)).mean()
        ),
    }


def input_lengths() -> dict:
    path = DATASET / "train.jsonl"
    tokenizer = AutoTokenizer.from_pretrained(ROOT / "checkpoints/laya-base/tokenizer")
    questions = {
        name: _internal_question(value)
        for name, value in trading_questions().items()
    }
    lengths = {name: [] for name in questions}
    examples = []
    with path.open("r", encoding="utf-8") as stream:
        for index, line in enumerate(stream):
            if index % SAMPLE_STRIDE:
                continue
            record = json.loads(line)
            for name, question in questions.items():
                full_ids, _ = build_sequence(
                    tokenizer, record["state"], question, 10_000, HEAD_MAX_LEN
                )
                lengths[name].append(len(full_ids))
            if len(examples) < 3:
                examples.append(record["id"])
            if len(lengths["action"]) >= MAX_SAMPLES:
                break
    if len(lengths["action"]) != MAX_SAMPLES:
        raise ValueError("too few sampled training records")
    return {
        "jsonl_sha256": sha256_file(path),
        "sampling": f"every {SAMPLE_STRIDE}th training row, first {MAX_SAMPLES}",
        "max_len": MAX_LEN,
        "head_max_len": HEAD_MAX_LEN,
        "example_ids": examples,
        "questions": {
            name: {
                "median_full_tokens": float(np.median(values)),
                "max_full_tokens": int(max(values)),
                "over_max_len": sum(length > MAX_LEN for length in values),
            }
            for name, values in lengths.items()
        },
    }


def main() -> None:
    report = {"purpose": "descriptive audit of the existing generated dataset"}
    for split in SPLITS:
        print("reading targets", split, flush=True)
        report[split] = targets_for_split(split)
        print(split, "rows", report[split]["rows"], flush=True)
    print("measuring fixed-stride input lengths", flush=True)
    report["input_lengths"] = input_lengths()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("saved", REPORT, flush=True)
    print(json.dumps({
        "train_target_max_median": report["train"][
            "max_action_target_quantiles_10_50_90_99"][1],
        "calibration_target_max_median": report["calibration"][
            "max_action_target_quantiles_10_50_90_99"][1],
        "sampled_input_lengths": report["input_lengths"]["questions"],
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
