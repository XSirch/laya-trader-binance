"""Pinned Jev decision calls, validated responses, and replayable local cache."""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

MODEL = "typesafe/jev-1.13"
ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
INSTRUCTIONS = (
    "For the market record with the exact id below, does the completed-bar state meet "
    "ALL of this predefined RSI pullback entry checklist: RSI(14) at or below 30; "
    "last close above its 200-hour simple moving average; 24-hour return between "
    "-5% and 0%; 24-hour high/low range at or below 8%; and last one-hour return "
    "above -1.5%? Judge only whether the observed numbers meet the checklist. "
    "Do not estimate future price direction or profitability. Record id: "
)


def load_api_key(env_path: Path) -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key and env_path.exists():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if not key:
        raise RuntimeError(f"set OPENROUTER_API_KEY in {env_path} before calling Jev")
    return key


@dataclass(frozen=True)
class Decision:
    matches_probability: float
    model: str
    request_id: str
    cost_usd: float


class JevClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def decide_many(self, states: dict[str, dict]) -> dict[str, Decision]:
        if len(states) != 1:
            raise ValueError("send one market record per Jev request")
        questions = {
            key: {"type": "noul", "instructions": INSTRUCTIONS + key}
            for key in states
        }
        body = {"model": MODEL,
                "state": {"records": [{"id": key, "market": value}
                                      for key, value in states.items()]},
                "questions": questions}
        request = urllib.request.Request(
            ENDPOINT, data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"}, method="POST")
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    result = json.load(response)
                break
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise RuntimeError(f"OpenRouter Decisions API HTTP {exc.code}") from exc
                time.sleep(2 ** attempt)
        answers = result.get("answers", {})
        if set(answers) != set(states):
            raise ValueError("Jev answer IDs do not match requested IDs")
        usage = result.get("usage", {})
        cost = float(usage.get("cost", 0.0)) / len(states)
        output = {}
        for key, answer in answers.items():
            if answer.get("type") != "noul":
                raise ValueError(f"invalid Jev answer type for {key}")
            probability = float(answer["noul"])
            if not 0 <= probability <= 1:
                raise ValueError(f"invalid Jev probability for {key}")
            output[key] = Decision(probability, str(result.get("model", "")),
                                   str(result.get("id", "")), cost)
        return output


def _cache_key(state: dict) -> str:
    payload = {"model": MODEL, "instructions": INSTRUCTIONS, "state": state}
    return hashlib.sha256(json.dumps(payload, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


class DecisionCache:
    def __init__(self, path: Path):
        self.path = path
        self.items: dict[str, Decision] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                self.items[row["key"]] = Decision(**row["decision"])

    def decide(self, states: list[dict], client: JevClient) -> list[Decision]:
        missing = [(index, state, _cache_key(state)) for index, state in enumerate(states)
                   if _cache_key(state) not in self.items]
        # Separate requests avoid cross-record contamination in checklist judgments.
        for offset in range(len(missing)):
            group = missing[offset:offset + 1]
            batch = {f"record_{index:06d}": state for index, state, _ in group}
            answers = client.decide_many(batch)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                for index, _, key in group:
                    decision = answers[f"record_{index:06d}"]
                    self.items[key] = decision
                    stream.write(json.dumps({"key": key, "decision": decision.__dict__}) + "\n")
            if (offset + 1) % 10 == 0 or offset + 1 == len(missing):
                print(f"Jev decisions {offset + 1}/{len(missing)}", flush=True)
        return [self.items[_cache_key(state)] for state in states]
