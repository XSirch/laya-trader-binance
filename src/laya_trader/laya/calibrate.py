from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import laya
import numpy as np
import torch
from laya.common import collate_items, temp_bucket
from scipy.optimize import minimize_scalar
from torch.utils.data import DataLoader, SequentialSampler

from laya_trader.laya.records import JsonlDecisionDataset


def _soft_nll(logits: np.ndarray, target: np.ndarray, temperature: float) -> float:
    z = logits / float(temperature)
    z = z - z.max(axis=1, keepdims=True)
    logp = z - np.log(np.exp(z).sum(axis=1, keepdims=True))
    return float(-(target * logp).sum(axis=1).mean())


def calibrate(
    checkpoint: Path, calibration_jsonl: Path, batch_size: int = 32
) -> dict[str, float]:
    agent = laya.load(str(checkpoint))
    device = agent.device
    dataset = JsonlDecisionDataset(
        calibration_jsonl,
        agent.tok,
        int(agent.cfg.get("max_len", 512)),
        int(agent.cfg.get("head_max_len", 192)),
    )
    loader = DataLoader(
        dataset,
        batch_size=batch_size,
        sampler=SequentialSampler(dataset),
        num_workers=0,
        collate_fn=lambda batch: collate_items(batch, agent.tok.pad_token_id),
    )

    buckets: dict[str, list[tuple[np.ndarray, np.ndarray]]] = defaultdict(list)
    agent.model.eval()
    with torch.no_grad():
        for batch in loader:
            if batch is None:
                continue
            tensors = {
                k: v.to(device)
                for k, v in batch.items()
                if torch.is_tensor(v)
            }
            logits, _ = agent.model(
                tensors["input_ids"],
                tensors["attention_mask"],
                tensors["marker_pos"],
                tensors["marker_mask"],
                tensors["qtype"],
            )
            logits = logits.float().cpu().numpy()
            targets = batch["target"].numpy()
            qtypes = batch["qtype"].numpy()
            masks = batch["marker_mask"].numpy()
            for i in range(len(qtypes)):
                k = int(masks[i].sum())
                key = temp_bucket(int(qtypes[i]), k)
                buckets[key].append((logits[i, :k].copy(), targets[i, :k].copy()))

    fitted: dict[str, float] = {}
    report: dict[str, dict] = {}
    for key, rows in sorted(buckets.items()):
        logits = np.stack([x for x, _ in rows])
        targets = np.stack([y for _, y in rows])
        before = _soft_nll(logits, targets, 1.0)
        result = minimize_scalar(
            lambda t, logits=logits, targets=targets: _soft_nll(logits, targets, t),
            bounds=(0.5, 5.0),
            method="bounded",
        )
        temp = float(result.x)
        fitted[key] = temp
        report[key] = {
            "n": len(rows),
            "temperature": round(temp, 6),
            "nll_before": round(before, 6),
            "nll_after": round(_soft_nll(logits, targets, temp), 6),
        }

    cfg_path = checkpoint / "rl_agent_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["temperature_by_options"] = fitted
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    (checkpoint / "calibration_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return fitted


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Fit Laya temperature calibration on held-out data"
    )
    p.add_argument("--checkpoint", default="checkpoints/laya-trader-v0.1")
    p.add_argument("--calibration", default="data/dataset/calibration.jsonl")
    p.add_argument("--batch-size", type=int, default=32)
    args = p.parse_args(argv)
    fitted = calibrate(Path(args.checkpoint), Path(args.calibration), args.batch_size)
    print(json.dumps(fitted, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
