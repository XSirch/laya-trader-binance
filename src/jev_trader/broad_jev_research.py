"""Fixed all-indicator criterion filter: numeric reference versus JEV adherence."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import os

from .binance_data import HOUR_MS, utc_ms
from .broad_data import CACHE, load as load_daily
from .broad_execution import evaluate
from .broad_extension import extend
from .broad_hourly import load as load_hourly
from .broad_research import DAY_MS, target_weights
from .broad_technical import feature_bundle
from .broad_jev_policy import QUESTIONS, filter_scale, market_state, numeric_adherence, script_accept
from .cli import ROOT, RESULTS
from .jev import MODEL, load_api_key
from .jev_budget import BudgetedJevClient, decision_key
from .target50_research import _offline_inputs, annualized_return, verify_reproduction
from .trailing_stop import TrailingStop
from .trailing_universe import compact


RULE = "blend:low_volatility30+carry30_betahedged"
PERIODS = {"development": ("2022-01-01", "2024-01-01"),
           "combined": ("2024-01-01", "2026-09-26")}
PROTOCOL = ROOT / "docs/broad_jev_protocol_2026-09-26.md"
PRIOR = RESULTS / "jev_multifactor_decisions.jsonl"
REPLIES = RESULTS / "jev_broad_decisions.jsonl"
EVENTS = RESULTS / "broad_jev_events.jsonl"
INPUTS = RESULTS / "broad_jev_inputs.json"
CODE = ("broad_jev_research.py", "broad_jev_policy.py", "jev_budget.py", "jev.py",
        "broad_technical.py", "broad_prediction.py", "broad_research.py", "broad_execution.py",
        "broad_hourly.py", "broad_data.py", "broad_extension.py", "binance_data.py",
        "derivatives_data.py", "market_state.py", "trailing_stop.py", "trailing_universe.py",
        "target50_research.py", "strategies.py", "cli.py")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def anchors():
    freeze_path = ROOT / "docs/broad_candidate_freeze_2026-09-26.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    baseline_path = RESULTS / "trailing_research.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if freeze["rule"] != RULE or baseline["freeze_sha256"] != sha(freeze_path):
        raise ValueError("different base strategy")
    expected = {**freeze["source_code_sha256"], **baseline["source_code_sha256"]}
    for name, expected_hash in expected.items():
        if sha(ROOT / "src/jev_trader" / name) != expected_hash:
            raise ValueError("frozen source changed: " + name)
    return {"protocol_sha256": sha(PROTOCOL), "freeze_sha256": sha(freeze_path),
            "baseline_sha256": sha(baseline_path), "legacy_jev_cache_sha256": sha(PRIOR),
            "code_sha256": {name: sha(ROOT / "src/jev_trader" / name)
                            for name in sorted(set(CODE) | set(expected))},
            "questions_sha256": digest(QUESTIONS),
            "manifest_sha256": {name: sha(CACHE / name) for name in (
                "cohort.json", "manifest.json", "hourly_manifest.json", "training_hourly_manifest.json")}}


def build_events(states, fields):
    """Only closed daily states preceding scheduled weekly execution are used."""
    events, lookup = [], {}
    for day in range(utc_ms(PERIODS["development"][0]), utc_ms(PERIODS["combined"][1]), DAY_MS):
        if datetime.fromtimestamp(day / 1000, timezone.utc).weekday() != 0:
            continue
        current = {symbol: rows[day] for symbol, rows in states.items() if day in rows}
        if any(row["latest_observed_close_ms"] != day for row in current.values()):
            raise ValueError("noncausal or inconsistent feature timestamp")
        weights = target_weights(current, RULE)
        if math.fsum(abs(w) for w in weights.values()) > .5 + 1e-12:
            raise ValueError("base gross exceeds frozen limit")
        for symbol, weight in sorted(weights.items()):
            if not weight:
                continue
            state = market_state(current[symbol], 1 if weight > 0 else -1, fields)
            event = {"symbol": symbol, "signal_close_ms": day, "execution_ms": day + HOUR_MS,
                     "base_weight": weight, "state": state, "key": decision_key(state, QUESTIONS),
                     "numeric_adherence": numeric_adherence(state)}
            events.append(event)
            lookup[(day, symbol)] = event
    if not events:
        raise ValueError("no complete candidate states")
    return events, lookup


def filtered_policy(lookup, mode, active_scale, decisions=None):
    if mode not in ("numeric", "jev"):
        raise ValueError("unknown criterion source")
    def policy(states, rule):
        weights = target_weights(states, rule)
        if not any(weights.values()):
            return {}
        cutoffs = {row["latest_observed_close_ms"] for row in states.values()}
        if len(cutoffs) != 1:
            raise ValueError("mixed decision cutoffs")
        day = cutoffs.pop()
        scores = {}
        for symbol, weight in weights.items():
            if not weight:
                continue
            event = lookup[(day, symbol)]
            if weight != event["base_weight"]:
                raise ValueError("prepared and replayed target weights differ")
            scores[symbol] = (event["numeric_adherence"] if mode == "numeric"
                              else decisions[event["key"]]["adherence"])
        scale, _ = filter_scale(weights, scores, active_scale)
        return {s: w * scale for s, w in weights.items() if w * scale}
    return policy


def acquire(client, events, workers):
    unique = {event["key"]: event for event in events}
    cached = client.cached
    missing = [event for key, event in unique.items() if key not in cached]
    # Submit only one bounded group at a time. Errors leave at most four known
    # reservations; the client never retries an incomplete paid request.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for offset in range(0, len(missing), workers):
            batch = missing[offset:offset + workers]
            futures = [pool.submit(client.decide, event["state"]) for event in batch]
            for future in futures:
                future.result()
            count = min(offset + workers, len(missing))
            if count % 40 == 0 or count == len(missing):
                print(f"JEV {count}/{len(missing)}; cumulative charged/reserved USD {client.spent}", flush=True)


def replay_all(hourly, data, states, lookup, decisions):
    modes = [("reference", None, 1), ("numeric1", "numeric", 1), ("numeric4", "numeric", 4)]
    if decisions is not None:
        modes += [("jev1", "jev", 1), ("jev4", "jev", 4)]
    output = {}
    baseline = json.loads((RESULTS / "trailing_research.json").read_text(encoding="utf-8"))
    for name, mode, scale in modes:
        for trailing in (False, True):
            key = name + ("_trailing4" if trailing else "_none")
            output[key] = {}
            for period, dates in PERIODS.items():
                output[key][period] = {}
                for label, cost in (("stress", .0015), ("double_stress", .003)):
                    policy = None if mode is None else filtered_policy(lookup, mode, scale, decisions)
                    try:
                        row = evaluate(hourly, data["fundingRate"], states, RULE, *dates, cost,
                                       target_policy=policy,
                                       trailing=TrailingStop("portfolio_pct", .04) if trailing else None)
                    except ValueError as exc:
                        if not (str(exc).startswith("unresolved held price") or str(exc).startswith("insolvent")):
                            raise
                        row = {"status": "invalid_execution", "error": str(exc), "meets_50_10": False}
                    else:
                        days = (utc_ms(dates[1]) - utc_ms(dates[0])) / DAY_MS
                        row["status"] = "complete"
                        row["net_cagr_pct"] = annualized_return(row["return_pct"], days)
                        row["meets_50_10"] = (row["net_cagr_pct"] >= 50 and row["max_drawdown_pct"] <= 10
                                                and row["margin_stress_failures"] == 0)
                        row["also_adverse_bound_within_10"] = row["meets_50_10"] and row["adverse_intrahour_drawdown_bound_pct"] <= 10
                        row["active_rebalance_count"] = sum(any(a["target_weights"].values()) for a in row["execution_audit"])
                        if mode is None and period == "combined":
                            original = "portfolio_pct_4pct" if trailing else "none"
                            row["baseline_reproduction"] = verify_reproduction(row, baseline["results"][original]["combined"][label])
                    output[key][period][label] = row
            values = output[key]["combined"]["stress"]
            print(key, {k: values.get(k) for k in ("status", "net_cagr_pct", "max_drawdown_pct", "active_rebalance_count")}, flush=True)
    return output


def run(paid=False, workers=4, prepare_only=False):
    if workers not in (1, 2, 3, 4) or paid and prepare_only:
        raise ValueError("invalid run mode")
    lock = RESULTS / "broad_jev_research.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(descriptor)
    try:
        frozen = anchors()
        print("Loading verified offline market inputs and all 60 daily fields.", flush=True)
        with _offline_inputs():
            data, daily_sources, _ = load_daily()
            hourly, hourly_sources = load_hourly(data)
            training, training_sources = load_hourly(data, "training_hourly_manifest.json")
            for kind in hourly:
                for symbol in hourly[kind]:
                    hourly[kind][symbol].update(training[kind][symbol])
            rest_sources, overlap, _ = extend(data, hourly)
        states, fields, quality = feature_bundle(data)
        if len(fields) != 60:
            raise ValueError("expected the full 60-field schema")
        events, lookup = build_events(states, fields)
        encoded = ("".join(json.dumps(event, sort_keys=True, allow_nan=False) + "\n" for event in events)).encode()
        if EVENTS.exists() and EVENTS.read_bytes() != encoded:
            raise ValueError("prepared decision states changed; explicit new experiment required")
        if not EVENTS.exists():
            EVENTS.write_bytes(encoded)
        sources = {label: {"count": len(rows), "manifest_sha256": digest([
                       {k: v for k, v in row.items() if k != "path"} for row in rows])}
                   for label, rows in (("daily", daily_sources), ("hourly", hourly_sources),
                                       ("training_hourly", training_sources), ("rest", rest_sources))}
        inputs = {"anchors": frozen, "events_sha256": sha(EVENTS), "scheduled_asset_decisions": len(events),
                  "unique_state_keys": len({e["key"] for e in events}), "fields": fields,
                  "feature_quality": quality, "sources": sources, "overlap": overlap,
                  "script_thresholds": {"risk": .75, "supporting": .65, "supporting_count": 2,
                                        "portfolio_accepted_fraction": .60, "active_scales": [1, 4]},
                  "questions": QUESTIONS, "model": MODEL}
        if INPUTS.exists() and json.loads(INPUTS.read_text(encoding="utf-8")) != json.loads(json.dumps(inputs)):
            raise ValueError("fixed experiment inputs or code changed")
        if not INPUTS.exists():
            INPUTS.write_text(json.dumps(inputs, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Prepared {len(events)} asset/time decisions; every request carries 60 fields and five questions.", flush=True)
        if frozen != anchors():
            raise ValueError("sources changed during preparation")
        key = load_api_key(ROOT / ".env") if paid else None
        with BudgetedJevClient(path=REPLIES, prior_path=PRIOR, questions=QUESTIONS,
                               api_key=key, budget_usd=Decimal("2")) as client:
            if paid:
                acquire(client, events, workers)
            cached = client.cached
            complete = all(e["key"] in cached for e in events)
            decisions = cached if complete and not prepare_only else None
            results = replay_all(hourly, data, states, lookup, decisions)
            rows = [cached[e["key"]] for e in events if e["key"] in cached]
            latency = sorted(row["latency_seconds"] for row in rows)
            diagnostics = None
            if complete:
                diagnostics = {"criterion_errors_at_half": {name: sum(
                    (cached[e["key"]]["adherence"][name] >= .5) != bool(e["numeric_adherence"][name])
                    for e in events) for name in QUESTIONS},
                    "asset_acceptance_disagreements": sum(script_accept(cached[e["key"]]["adherence"])
                        != script_accept(e["numeric_adherence"]) for e in events)}
            report = {"created_utc": datetime.now(timezone.utc).isoformat(), "inputs": inputs,
                      "inputs_file_sha256": sha(INPUTS), "results": results, "jev_complete": complete,
                      "cached_decisions": len(rows), "diagnostics": diagnostics,
                      "authorized_cumulative_budget_usd": "2", "cumulative_charged_or_reserved_usd": str(client.spent),
                      "response_cache_sha256": sha(REPLIES) if REPLIES.exists() else None,
                      "latency_seconds": {"median": latency[len(latency)//2],
                          "p95": latency[min(len(latency)-1, int(.95*len(latency)))], "max": max(latency)} if latency else None,
                      "deployable": False, "selected_winner": None, "live_changes": False,
                      "limits": ["Known historical periods; no independent prospective proof.",
                                 "JEV scores criterion adherence only; the script owns all decisions and keeps basket ratios.",
                                 "Historical model knowledge cannot be excluded despite omitting symbol/calendar from request.",
                                 "API charges are research expenses reported separately from normalized trading returns.",
                                 "Gross exposure and margin flags do not model real account liquidation or fills.",
                                 "Missing JEV responses never become numeric fallback or a cash signal."]}
        if frozen != anchors():
            raise ValueError("protocol or source code changed during experiment")
        tag = "prepare" if decisions is None else "research"
        full = RESULTS / f"broad_jev_{tag}.json"
        full.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        summary = compact(report)
        summary["full_report_sha256"] = sha(full)
        (ROOT / f"docs/broad_jev_{tag}_2026-09-26.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        print(f"Report {full.name}: JEV complete={complete}, cumulative USD {report['cumulative_charged_or_reserved_usd']}", flush=True)
        return summary
    finally:
        lock.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paid", action="store_true", help="Use only the existing cumulative USD2 authorization")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--workers", type=int, choices=(1, 2, 3, 4), default=4)
    args = parser.parse_args()
    run(args.paid, args.workers, args.prepare_only)
