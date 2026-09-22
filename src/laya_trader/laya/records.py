from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from torch.utils.data import Dataset

from laya.common import QTYPES, build_sequence, render_options

from laya_trader.laya.questions import trading_questions


def _internal_question(qdef: dict[str, Any]) -> dict[str, Any]:
    t = qdef["type"]
    crit = qdef.get("criteria")
    if t == "choice" and isinstance(crit, list):
        crit = {c: None for c in crit}
    return {"t": t, "ins": qdef["instructions"], "crit": crit}


def record_to_items(record: dict, tokenizer, max_len: int, head_max_len: int) -> list[dict]:
    questions = trading_questions()
    items: list[dict] = []
    for qid, qdef in questions.items():
        q = _internal_question(qdef)
        ids, markers = build_sequence(tokenizer, record["state"], q, max_len, head_max_len)
        expected = len(render_options(q))
        if len(markers) != expected:
            raise ValueError(f"{qid}: {expected} options do not fit head_max_len={head_max_len}")
        target = [float(v) for v in record["targets"][qid]]
        if len(target) != expected:
            raise ValueError(
                f"{record.get('id')}: {qid} target has {len(target)} values, expected {expected}"
            )
        total = sum(target)
        if total <= 0:
            raise ValueError(f"{record.get('id')}: {qid} target sums to zero")
        target = [max(0.0, v) / total for v in target]
        items.append(
            {
                "ids": ids,
                "markers": markers,
                "qtype": QTYPES[q["t"]],
                "target": target,
                "label": max(range(len(target)), key=target.__getitem__),
                "record_id": record.get("id", ""),
                "question_id": qid,
            }
        )
    return items


class JsonlDecisionDataset(Dataset):
    """Random-access JSONL dataset without loading every state into RAM."""

    def __init__(self, path: str | Path, tokenizer, max_len: int = 512, head_max_len: int = 192):
        self.path = Path(path)
        self.tokenizer = tokenizer
        self.max_len = int(max_len)
        self.head_max_len = int(head_max_len)
        self.offsets: list[int] = []
        with self.path.open("rb") as fh:
            while True:
                offset = fh.tell()
                line = fh.readline()
                if not line:
                    break
                if line.strip():
                    self.offsets.append(offset)
        self._fh = None
        self._pid = None

    def __len__(self) -> int:
        return len(self.offsets)

    def _handle(self):
        pid = os.getpid()
        if self._fh is None or self._pid != pid:
            if self._fh is not None:
                self._fh.close()
            self._fh = self.path.open("rb")
            self._pid = pid
        return self._fh

    def __getitem__(self, index: int) -> list[dict]:
        fh = self._handle()
        fh.seek(self.offsets[index])
        record = json.loads(fh.readline())
        return record_to_items(record, self.tokenizer, self.max_len, self.head_max_len)
