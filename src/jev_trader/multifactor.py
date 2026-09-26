"""Single-call Jev adherence scores; local script decides exposure."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from .binance_data import HOUR_MS, load_cached_range, utc_ms
from .cli import DATA_ROOT, FIRST, LAST, RESULTS, ROOT, SYMBOLS, _fingerprint, _passes
from .extended import DAY_MS, PERIODS, daily_bars, metrics, robustness
from .jev import ENDPOINT, MODEL, load_api_key
from .market_state import aggregate, composite_votes, rounded, states

CRITERIA = {
    "trend": "At least THREE of these five conditions hold: daily distance_sma_pct.200 > 0; daily sma50_slope_5bars_pct > 0; daily plus_di14 > minus_di14; four_hour distance_ema_pct.50 > 0; daily adx14 >= 20.",
    "timing": "At least THREE of these five conditions hold: daily macd_histogram_pct >= 0; four_hour macd_histogram_pct > 0; daily rsi14 between 40 and 70 inclusive; daily stochastic_k14 between 20 and 85 inclusive; daily return_pct.7 > 0.",
    "participation": "At least THREE of these five conditions hold: daily obv_change20_over_volume > 0; daily taker_buy_fraction20 >= 0.50; daily relative_volume20 >= 0.8; daily distance_vwap20_pct >= 0; cross_asset return30_minus_btc_pct >= 0. Missing fields do not satisfy conditions.",
    "structure": "At least ONE of these alternatives holds: (A) daily structure.fibonacci.60.high_after_low is true, its retracement_fraction is between 0.236 and 0.618 inclusive, and daily close_position_in_bar >= 0.5; (B) daily distance_prior_high20_pct is between 0 and 2 inclusive and daily relative_volume20 >= 1.2; (C) daily distance_sma_pct.50 is between -1 and 2 inclusive, daily sma50_slope_5bars_pct > 0, and four_hour macd_histogram_pct > 0.",
    "risk": "ALL these conditions hold: daily atr14_pct <= 6; daily bollinger_position <= 1.1; daily return_pct.1 >= -5; daily realized20_per_bar_pct <= 5; daily drawdown_from_high60_pct >= -25.",
}
QUESTIONS = {name: {"type": "noul", "instructions": (
    "Evaluate only whether the supplied observed indicators satisfy this criterion. "
    "Return the probability of CRITERION ADHERENCE, not probability of profit or future direction. "
    "Never choose buy, sell or hold; the calling script owns all trading decisions. "
    "All indicators for both timeframes are in this single state. Periods are bars; "
    "return/distance fields are percentages, fraction fields are fractions. "
    "Use no outside facts and no unavailable data. Criterion: " + criterion)}
    for name, criterion in CRITERIA.items()}
THRESHOLDS = {"trend": 0.70, "risk": 0.75, "supporting": 0.65, "supporting_count": 2}
RESERVATION_USD = 0.01  # Conservative per-call reserve; unknown charges retain it.


def decision_key(state):
    return hashlib.sha256(json.dumps({"model": MODEL, "questions": QUESTIONS, "state": state},
                                     sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class BudgetedDecisions:
    """Persistent in-flight reservations, cache and audit; no automatic retries."""
    def __init__(self, path: Path, budget: float, api_key: str | None):
        if not math.isfinite(budget) or budget < 0:
            raise ValueError("budget must be finite and nonnegative")
        self.path, self.budget, self.api_key = path, budget, api_key
        self.lock = threading.Lock()
        self.cached = {}
        self.ledger = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                self.ledger[row["key"]] = row
                if row["status"] == "complete":
                    self.cached[row["key"]] = row

    @property
    def spent(self):
        return sum(row["charged_or_reserved_usd"] for row in self.ledger.values())

    def write(self, row):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
        self.ledger[row["key"]] = row

    def decide(self, state):
        key = decision_key(state)
        body = json.dumps({"model": MODEL, "state": state, "questions": QUESTIONS},
                          separators=(",", ":")).encode("utf-8")
        if len(body) > 24000:
            raise ValueError("request exceeds bounded input size")
        with self.lock:
            if key in self.cached:
                return self.cached[key]
            if not self.api_key:
                raise RuntimeError("cached decision absent; paid replay not enabled")
            if key in self.ledger:
                raise RuntimeError("prior incomplete request requires charge reconciliation before retry")
            if self.spent + RESERVATION_USD > self.budget:
                raise RuntimeError("authorized API budget exhausted")
            self.write({"key": key, "status": "reserved", "charged_or_reserved_usd": RESERVATION_USD})
        request = urllib.request.Request(ENDPOINT, data=body,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}, method="POST")
        started = time.perf_counter()
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.load(response)
        latency = time.perf_counter() - started
        answers = payload.get("answers", {})
        if set(answers) != set(QUESTIONS):
            raise ValueError("criterion response IDs differ; reserved charge retained")
        adherence = {}
        for name, answer in answers.items():
            value = answer.get("noul")
            if (answer.get("type") != "noul" or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError("invalid criterion adherence response")
            adherence[name] = value
        if not str(payload.get("model", "")).startswith(MODEL):
            raise ValueError("unexpected returned model")
        cost = payload.get("usage", {}).get("cost")
        if cost is None or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0:
            raise ValueError("missing or invalid usage cost; reserved charge retained")
        row = {"key": key, "status": "complete", "charged_or_reserved_usd": cost,
               "request_id": payload.get("id"), "model": payload["model"],
               "adherence": adherence, "usage": payload.get("usage"),
               "latency_seconds": latency, "request_bytes": len(body)}
        with self.lock:
            self.write(row)
            self.cached[key] = row
        if cost > RESERVATION_USD:
            raise RuntimeError("unexpected API charge exceeds reserve; stop replay")
        return row


def numeric_adherence(state):
    """Exact numeric reference for auditing the model's criterion adherence."""
    d, h = state["daily"], state["four_hour"]
    t, m, p, st, v = (d[k] for k in ("trend", "momentum", "participation", "structure", "volatility"))
    fib = st["fibonacci"]["60"]
    return {
        "trend": float(sum((t["distance_sma_pct"]["200"] > 0, t["sma50_slope_5bars_pct"] > 0,
                      t["plus_di14"] > t["minus_di14"], h["trend"]["distance_ema_pct"]["50"] > 0,
                      t["adx14"] >= 20)) >= 3),
        "timing": float(sum((m["macd_histogram_pct"] >= 0, h["momentum"]["macd_histogram_pct"] > 0,
                       40 <= m["rsi14"] <= 70, 20 <= m["stochastic_k14"] <= 85,
                       m["return_pct"]["7"] > 0)) >= 3),
        "participation": float(sum((p["obv_change20_over_volume"] > 0,
                    p["taker_buy_fraction20"] is not None and p["taker_buy_fraction20"] >= .50,
                    p["relative_volume20"] >= .8,
                    p["distance_vwap20_pct"] is not None and p["distance_vwap20_pct"] >= 0,
                    state["cross_asset"]["return30_minus_btc_pct"] >= 0)) >= 3),
        "structure": float((fib["high_after_low"] and .236 <= fib["retracement_fraction"] <= .618
                            and st["close_position_in_bar"] >= .5)
                           or (0 <= st["distance_prior_high20_pct"] <= 2 and p["relative_volume20"] >= 1.2)
                           or (-1 <= t["distance_sma_pct"]["50"] <= 2 and t["sma50_slope_5bars_pct"] > 0
                               and h["momentum"]["macd_histogram_pct"] > 0)),
        "risk": float(v["atr14_pct"] <= 6 and v["bollinger_position"] <= 1.1
                      and m["return_pct"]["1"] >= -5 and v["realized20_per_bar_pct"] <= 5
                      and v["drawdown_from_high60_pct"] >= -25),
    }


def script_target(adherence):
    """Only the local script converts criterion scores into target exposure."""
    if set(adherence) != set(CRITERIA) or any(not isinstance(v, (int, float))
            or not math.isfinite(v) or not 0 <= v <= 1 for v in adherence.values()):
        raise ValueError("invalid criterion scores")
    return (adherence["trend"] >= THRESHOLDS["trend"]
            and adherence["risk"] >= THRESHOLDS["risk"]
            and sum(adherence[k] >= THRESHOLDS["supporting"]
                    for k in ("timing", "participation", "structure")) >= THRESHOLDS["supporting_count"])


def build_events(hourly):
    daily = {s: daily_bars(bars) for s, bars in hourly.items()}
    daily_states = {s: states(bars) for s, bars in daily.items()}
    four_hour = {s: aggregate([bar for bar in bars if bar.open_ms >= utc_ms("2023-04-01")], 4)
                 for s, bars in hourly.items()}
    four_states = {s: {b.open_ms: value for b, value in zip(bars, states(bars))}
                   for s, bars in four_hour.items()}
    events = []
    for s, bars in daily.items():
        for i, bar in enumerate(bars):
            if not utc_ms("2024-12-29") <= bar.open_ms < utc_ms("2026-08-01"):
                continue
            if datetime.fromtimestamp(bar.open_ms / 1000, timezone.utc).weekday() != 6:
                continue
            d = daily_states[s][i]
            btc = daily_states["BTCUSDT"][i]
            h = four_states[s][bar.open_ms + 20 * HOUR_MS]
            state = rounded({
                "daily": d, "four_hour": h,
                "cross_asset": {"return30_minus_btc_pct": d["momentum"]["return_pct"]["30"] - btc["momentum"]["return_pct"]["30"],
                                "btc_distance_sma200_pct": btc["trend"]["distance_sma_pct"]["200"],
                                "universe_above_sma200_fraction": sum(values[i]["trend"]["distance_sma_pct"]["200"] > 0
                                    for values in daily_states.values()) / len(daily_states)},
                "horizon_days": 7, "cost_per_side_pct": 0.25,
                "unavailable": ["order_book", "spread", "open_interest", "funding", "news", "on_chain"],
            })
            # Symbol and calendar date are audit metadata, not hints to a model
            # that might have encountered these historical episodes in training.
            events.append({"symbol": s, "signal_index": i,
                           "signal_close_ms": bar.open_ms + DAY_MS,
                           "latest_four_hour_close_ms": bar.open_ms + 24 * HOUR_MS,
                           "state": state, "key": decision_key(state)})
    events.sort(key=lambda row: (row["signal_close_ms"], row["symbol"]))
    return daily, events


def build_signals(daily, events, decisions=None):
    names = list(composite_votes(events[0]["state"])) + ["numeric_multifactor"]
    if decisions is not None:
        names.append("jev_multifactor")
    output = {name: {s: [False] * len(bars) for s, bars in daily.items()} for name in names}
    for event in events:
        choices = composite_votes(event["state"])
        choices["numeric_multifactor"] = script_target(numeric_adherence(event["state"]))
        if decisions is not None:
            choices["jev_multifactor"] = script_target(decisions[event["key"]]["adherence"])
        s, i = event["symbol"], event["signal_index"]
        for name, long in choices.items():
            for j in range(i, min(i + 7, len(daily[s]))):
                output[name][s][j] = long
    return output


def run(budget=0.0, workers=4):
    hourly, manifest = load_cached_range(SYMBOLS, FIRST, LAST, DATA_ROOT)
    daily, events = build_events(hourly)
    cache = BudgetedDecisions(RESULTS / "jev_multifactor_decisions.jsonl", budget,
                              load_api_key(ROOT / ".env") if budget > 0 else None)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "multifactor_events.jsonl").write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events), encoding="utf-8")
    print(f"prepared {len(events)} decisions; each includes all daily and 4h indicators", flush=True)
    missing = [event for event in events if event["key"] not in cache.cached]
    if budget > 0 and missing:
        # At most four independent asset/time decisions in flight. No call per indicator.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(cache.decide, event["state"]): event for event in missing}
            try:
                for count, future in enumerate(as_completed(futures), start=1):
                    future.result()
                    if count % 10 == 0 or count == len(missing):
                        print(f"Jev {count}/{len(missing)}; charged/reserved ${cache.spent:.6f}", flush=True)
            except Exception:
                for future in futures:
                    future.cancel()
                raise
    complete = all(event["key"] in cache.cached for event in events)
    signals = build_signals(daily, events, cache.cached if complete else None)
    result = {}
    for name, signal in signals.items():
        windows = {p: metrics(daily, signal, *PERIODS[p]) for p in ("calibration", "validation", "confirmation")}
        windows["combined"] = metrics(daily, signal, "2025-01-01", "2026-08-01")
        windows["all_three_gates"] = all(_passes(windows[p]) for p in ("calibration", "validation", "confirmation"))
        result[name] = windows
        print(f"{name}: stress {windows['combined']['stress']['return_pct']:.2f}%", flush=True)
    rows = [cache.cached[event["key"]] for event in events if event["key"] in cache.cached]
    latency = sorted(row["latency_seconds"] for row in rows)
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_manifest_sha256": _fingerprint(manifest),
        "source_code_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                               for name in ("multifactor.py", "market_state.py", "binance_data.py", "backtest.py", "extended.py")},
        "events_sha256": hashlib.sha256((RESULTS / "multifactor_events.jsonl").read_bytes()).hexdigest(),
        "response_cache_sha256": hashlib.sha256(cache.path.read_bytes()).hexdigest() if cache.path.exists() else None,
        "questions": QUESTIONS, "script_thresholds": THRESHOLDS,
        "scheduled_decisions": len(events), "cached_decisions": len(rows),
        "jev_complete": complete, "charged_or_reserved_usd": cache.spent,
        "authorized_budget_this_replay_usd": budget,
        "one_call_contains_all_indicators": True,
        "latency_seconds": {"median": latency[len(latency) // 2], "p95": latency[min(len(latency) - 1, int(len(latency) * .95))],
                            "max": max(latency)} if latency else None,
        "model_snapshots": sorted({row["model"] for row in rows}),
        "script_long_targets": sum(script_target(row["adherence"]) for row in rows),
        "candidates": result, "deployable": False,
        "limits": ["Exploratory reuse of history; no pristine holdout.",
                   "Indicators describe past markets, not independently established sources of alpha.",
                   "Historical model knowledge cannot be excluded despite omitting symbol/date from inputs.",
                   "One weekly decision per asset; this does not establish intraday trading profitability.",
                   "Measured latency includes network and provider time at up to four concurrent calls.",
                   "Jev scores criterion adherence only; the script decides all target exposure.",
                   "Criterion adherence probabilities are not probabilities of financial profit.",
                   "Unavailable order book, spread, open interest, funding, news and on-chain data are explicitly marked."],
    }
    if complete:
        report["jev_robustness"] = robustness(hourly, daily, signals["jev_multifactor"])
        report["script_target_disagreements_vs_numeric"] = sum(
            script_target(cache.cached[e["key"]]["adherence"]) != script_target(numeric_adherence(e["state"]))
            for e in events)
        report["criterion_classification_errors_at_half"] = {
            name: sum((cache.cached[e["key"]]["adherence"][name] >= .5) != bool(numeric_adherence(e["state"])[name])
                      for e in events) for name in CRITERIA}
        report["decision_audit"] = [
            {"symbol": e["symbol"], "signal_close_ms": e["signal_close_ms"],
             "latest_four_hour_close_ms": e["latest_four_hour_close_ms"],
             "state_and_prompt_key": e["key"],
             "request_id": cache.cached[e["key"]]["request_id"],
             "adherence": cache.cached[e["key"]]["adherence"],
             "numeric_adherence": numeric_adherence(e["state"]),
             "script_target_long": script_target(cache.cached[e["key"]]["adherence"]),
             "cost_usd": cache.cached[e["key"]]["charged_or_reserved_usd"],
             "latency_seconds": cache.cached[e["key"]]["latency_seconds"]}
            for e in events]
    path = RESULTS / "multifactor_research.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"report: {path}; Jev complete={complete}", flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget-usd", type=float, default=0)
    parser.add_argument("--workers", type=int, choices=(1, 2, 3, 4), default=4)
    args = parser.parse_args()
    run(args.budget_usd, args.workers)
