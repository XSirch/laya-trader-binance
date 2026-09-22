from __future__ import annotations

import argparse
import json
from pathlib import Path

import laya

from laya_trader.laya.questions import trading_questions


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run a trained Laya trading checkpoint")
    p.add_argument("--checkpoint", default="checkpoints/laya-trader-v0.1")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--state-file")
    group.add_argument("--state-json")
    args = p.parse_args(argv)

    if args.state_file:
        state = json.loads(Path(args.state_file).read_text(encoding="utf-8"))
    else:
        state = json.loads(args.state_json)

    agent = laya.load(args.checkpoint)
    result = agent.predict(state, trading_questions())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
