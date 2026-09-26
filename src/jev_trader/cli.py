"""Research commands. No order execution or exchange credentials are used."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .backtest import evaluate_window
from .binance_data import load_cached_range, load_range, utc_ms
from .jev import DecisionCache, JevClient, load_api_key
from .strategies import CANDIDATES, causal_state, make_signals

ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "data" / "binance" / "spot" / "1h"
RESULTS = ROOT / "results"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]
FIRST, LAST = "2023-01", "2026-08"
BASE_COST = 0.0015  # 10 bps fee + 5 bps assumed adverse execution, each side.
STRESS_COST = 0.0025
WINDOWS = {
    "development": ("2023-04-01", "2025-01-01"),
    "calibration": ("2025-01-01", "2025-07-01"),
    "validation": ("2025-07-01", "2026-01-01"),
    "confirmation": ("2026-01-01", "2026-08-01"),
}
JEV_MATCH_MIN = 0.70


def _save_report(name: str, report: dict) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / name
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _window_metrics(frames, signals, name: str) -> dict:
    start, end = WINDOWS[name]
    return {
        "base": asdict(evaluate_window(frames, signals, start, end, BASE_COST)),
        "stress": asdict(evaluate_window(frames, signals, start, end, STRESS_COST)),
    }


def _passes(metrics: dict) -> bool:
    base, stress = metrics["base"], metrics["stress"]
    required_months = (2 * base["months"] + 2) // 3
    return (base["trades"] >= 12 and base["return_pct"] > 0
            and stress["return_pct"] > 0
            and base["positive_months"] >= required_months
            and stress["max_drawdown_pct"] <= 25)


def _fingerprint(manifest: list[dict]) -> str:
    records = [{"symbol": row["symbol"], "month": row["month"],
                "sha256": row["sha256"]} for row in manifest]
    records.sort(key=lambda row: (row["symbol"], row["month"]))
    return hashlib.sha256(json.dumps(records, sort_keys=True).encode("utf-8")).hexdigest()


def research(download: bool = True) -> dict:
    if download:
        frames, manifest = load_range(SYMBOLS, FIRST, LAST, DATA_ROOT)
    else:
        frames, manifest = load_cached_range(SYMBOLS, FIRST, LAST, DATA_ROOT)
    signals = {candidate.name: {symbol: make_signals(bars, candidate)
                                for symbol, bars in frames.items()}
               for candidate in CANDIDATES}
    candidates = {}
    for candidate in CANDIDATES:
        candidate_signals = signals[candidate.name]
        candidates[candidate.name] = {
            "development": _window_metrics(frames, candidate_signals, "development"),
            "calibration": _window_metrics(frames, candidate_signals, "calibration"),
        }
        print(f"evaluated {candidate.name} on development and calibration", flush=True)
    ranked = sorted((candidate for candidate in CANDIDATES if candidate.name != "hold"),
                    key=lambda candidate: (
                        _passes(candidates[candidate.name]["calibration"]),
                        candidates[candidate.name]["calibration"]["stress"]["return_pct"],
                        -candidates[candidate.name]["calibration"]["stress"]["max_drawdown_pct"]),
                    reverse=True)
    selected = ranked[0].name
    eligible = _passes(candidates[selected]["calibration"])
    for name in (selected, "hold"):
        candidates[name]["validation"] = _window_metrics(frames, signals[name], "validation")
        candidates[name]["confirmation"] = _window_metrics(frames, signals[name], "confirmation")
    val_pass = _passes(candidates[selected]["validation"])
    confirm_pass = _passes(candidates[selected]["confirmation"])
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source": "Binance spot monthly 1h first-party ZIP + CHECKSUM",
        "source_manifest_sha256": _fingerprint(manifest),
        "symbols": SYMBOLS, "first_month": FIRST, "last_month": LAST,
        "windows": WINDOWS,
        "costs": {"base_per_side": BASE_COST, "stress_per_side": STRESS_COST,
                  "base_detail": "10 bps fee + 5 bps adverse execution per side"},
        "selection": {"selected": selected,
                      "calibration_gate_passed": eligible,
                      "validation_gate_passed": val_pass,
                      "confirmation_gate_passed": confirm_pass,
                      "deployable": eligible and val_pass and confirm_pass,
                      "rule": "Select one non-hold rule using calibration stress return and gates; then evaluate later windows once."},
        "candidates": candidates,
        "limits": ["Spot long or flat only; no live orders.",
                   "Kline opens are proxies for executable fills; slippage is assumed.",
                   "Earlier project work inspected some 2025-2026 periods, so these are not pristine holdouts.",
                   "API fees and actual fills depend on the account and order type."],
    }
    path = _save_report("research.json", report)
    print(f"research report: {path}", flush=True)
    print(f"selected diagnostic rule: {selected}; deployable={report['selection']['deployable']}",
          flush=True)
    return report


def _entry_events(frames, base_signals, window_name: str):
    start_ms, end_ms = (utc_ms(day) for day in WINDOWS[window_name])
    events = []
    for symbol, bars in frames.items():
        signal = base_signals[symbol]
        first_index = next(i for i, bar in enumerate(bars) if bar.open_ms == start_ms)
        last_index = next(i for i, bar in enumerate(bars) if bar.open_ms == end_ms)
        in_episode = False
        for i in range(first_index, last_index):
            desired = signal[i - 1]
            if desired and not in_episode:
                events.append((symbol, i, causal_state(bars, i - 1, symbol,
                                                       "base_rule_entry_gate")))
            in_episode = desired
    return events


def _gated_signals(frames, base_signals, window_name: str,
                   decisions: dict[tuple[str, int], bool]):
    start_ms, end_ms = (utc_ms(day) for day in WINDOWS[window_name])
    gated = {symbol: [False] * len(bars) for symbol, bars in frames.items()}
    for symbol, bars in frames.items():
        signal = base_signals[symbol]
        first_index = next(i for i, bar in enumerate(bars) if bar.open_ms == start_ms)
        last_index = next(i for i, bar in enumerate(bars) if bar.open_ms == end_ms)
        in_episode = False
        allowed = False
        for i in range(first_index, last_index):
            desired = signal[i - 1]
            if desired and not in_episode:
                allowed = decisions[(symbol, i)]
            if not desired:
                allowed = False
            gated[symbol][i - 1] = desired and allowed
            in_episode = desired
    return gated


def _entry_checklist(state: dict) -> bool:
    ret24 = state["returns_percent"]["24"]
    ret1 = state["returns_percent"]["1"]
    return (state["rsi_14"] <= 30
            and state["distance_from_sma_200_percent"] > 0
            and -5 <= ret24 <= 0
            and state["range_24h_percent"] <= 8
            and ret1 > -1.5)


def jev_replay() -> dict:
    path = RESULTS / "research.json"
    if not path.exists():
        raise FileNotFoundError("run research before Jev replay")
    research_report = json.loads(path.read_text(encoding="utf-8"))
    frames, manifest = load_cached_range(SYMBOLS, FIRST, LAST, DATA_ROOT)
    if _fingerprint(manifest) != research_report["source_manifest_sha256"]:
        raise ValueError("source manifest differs from research report")
    selected = research_report["selection"]["selected"]
    candidate = next(item for item in CANDIDATES if item.name == selected)
    base_signals = {symbol: make_signals(bars, candidate)
                    for symbol, bars in frames.items()}
    client = JevClient(load_api_key(ROOT / ".env"))
    cache = DecisionCache(RESULTS / "jev_checklist_single_decisions.jsonl")
    replay = {"model": "typesafe/jev-1.13", "base_rule": selected,
              "checklist_probability_threshold": JEV_MATCH_MIN,
              "entry_checklist": ["RSI14 <= 30", "close > SMA200",
                                  "24h return between -5% and 0%",
                                  "24h range <= 8%", "1h return > -1.5%"],
              "exit_rule": "Close when RSI14 >= 55 or close < SMA200; force-close at split end.",
              "windows": {}, "total_api_cost_usd": 0.0}
    for window in ("calibration", "validation", "confirmation"):
        events = _entry_events(frames, base_signals, window)
        answers = cache.decide([item[2] for item in events], client)
        approvals = {(symbol, index): (_entry_checklist(state)
                                         and answer.matches_probability >= JEV_MATCH_MIN)
                     for (symbol, index, state), answer in zip(events, answers)}
        gated = _gated_signals(frames, base_signals, window, approvals)
        replay["windows"][window] = {
            "candidate_entries": len(events),
            "checklist_matches": sum(_entry_checklist(state) for _, _, state in events),
            "approved_entries": sum(approvals.values()),
            "model_snapshots": sorted({answer.model for answer in answers}),
            "base_rule": _window_metrics(frames, base_signals, window),
            "jev_gated": _window_metrics(frames, gated, window),
        }
        print(f"{window}: Jev approved {sum(approvals.values())}/{len(events)} entries",
              flush=True)
    replay["calibration_gate_passed"] = _passes(replay["windows"]["calibration"]["jev_gated"])
    replay["validation_gate_passed"] = _passes(replay["windows"]["validation"]["jev_gated"])
    replay["confirmation_gate_passed"] = _passes(replay["windows"]["confirmation"]["jev_gated"])
    replay["deployable"] = all(replay[key] for key in
                               ("calibration_gate_passed", "validation_gate_passed",
                                "confirmation_gate_passed"))
    replay["total_api_cost_usd"] = sum(answer.cost_usd for answer in cache.items.values())
    _save_report("jev_replay.json", replay)
    return replay


def jev_smoke() -> None:
    frames, _ = load_cached_range(["BTCUSDT"], FIRST, LAST, DATA_ROOT)
    bars = frames["BTCUSDT"]
    state = causal_state(bars, len(bars) - 1, "BTCUSDT", "integration_smoke")
    response = JevClient(load_api_key(ROOT / ".env")).decide_many({"probe": state})["probe"]
    print(json.dumps(asdict(response), indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("research", "research-cached", "jev-smoke", "jev-replay"))
    args = parser.parse_args()
    if args.command == "research":
        research(download=True)
    elif args.command == "research-cached":
        research(download=False)
    elif args.command == "jev-smoke":
        jev_smoke()
    else:
        jev_replay()


if __name__ == "__main__":
    main()
