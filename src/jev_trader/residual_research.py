"""Fixed, offline, daily residual-reversion experiment with hourly accounting."""

from datetime import datetime, timezone
import csv
import hashlib
import io
import itertools
import json
import os
from pathlib import Path
import re
import time
import zipfile

from .binance_data import utc_ms
from .broad_data import CACHE, load as load_daily
from .broad_extension import extend
from .broad_hourly import load as load_hourly
from .broad_technical import feature_bundle
from .cli import ROOT, RESULTS
from .derivatives_data import fetch
from .residual_policy import ResidualPolicy, enrich_states
from .scheduled_execution import evaluate
from .settlement_bounds import bound
from .target50_research import _offline_inputs, annualized_return, verify_reproduction
from .trailing_stop import TrailingStop


CONFIG = {"schema_version": 1, "periods": {"development": ["2022-01-01", "2024-01-01"],
          "combined": ["2024-01-01", "2026-09-26"]}, "risk_scales": [1, 2],
          "portfolio_trailing": [None, .04], "side_costs": [.0015, .003], "delay_hours": 1,
          "cadence": "daily", "factor_window": 60, "residual_window": 60, "entry_z": 1.25,
          "exit_z": .5, "maximum_signal_days": 10, "hurdle_side_cost": .0015,
          "target_net_cagr_pct": 50, "maximum_drawdown_pct": 10}
PROTOCOL = ROOT / "docs/residual_protocol_2026-09-26.md"
INPUTS = RESULTS / "residual_inputs.json"
CODE = ("residual_research.py", "residual_policy.py", "scheduled_execution.py", "broad_technical.py",
        "broad_prediction.py", "broad_research.py", "broad_execution.py", "broad_data.py",
        "broad_hourly.py", "broad_extension.py", "binance_data.py", "derivatives_data.py",
        "market_state.py", "strategies.py", "trailing_stop.py", "target50_research.py",
        "settlement_bounds.py", "cli.py", "statistics.py")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def anchors():
    blocks = re.findall(r"```json\s*\n(.*?)\n```", PROTOCOL.read_text(encoding="utf-8"), re.DOTALL)
    if len(blocks) != 1 or json.loads(blocks[0]) != CONFIG:
        raise ValueError("protocol and runner differ")
    freeze_path = ROOT / "docs/broad_candidate_freeze_2026-09-26.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    baseline_path = RESULTS / "trailing_research.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if baseline["freeze_sha256"] != sha(freeze_path):
        raise ValueError("baseline differs from frozen candidate")
    for name, expected in {**freeze["source_code_sha256"], **baseline["source_code_sha256"]}.items():
        if sha(ROOT / "src/jev_trader" / name) != expected:
            raise ValueError("existing frozen source changed: " + name)
    return {"protocol_sha256": sha(PROTOCOL), "freeze_sha256": sha(freeze_path),
            "baseline_sha256": sha(baseline_path),
            "code_sha256": {name: sha(ROOT / "src/jev_trader" / name) for name in CODE},
            "settlement_sha256": sha(ROOT / "docs/settlement_bounds_2026-09-26.json"),
            "lifecycle_sha256": sha(ROOT / "docs/contract_lifecycle_sources_2026-09-26.json"),
            "manifest_sha256": {name: sha(CACHE / name) for name in (
                "cohort.json", "manifest.json", "hourly_manifest.json", "training_hourly_manifest.json")}}


def verified_bounds():
    """Recheck known adverse bounds without rewriting the existing evidence."""
    report = json.loads((ROOT / "docs/settlement_bounds_2026-09-26.json").read_text(encoding="utf-8"))
    lifecycle = json.loads((ROOT / "docs/contract_lifecycle_sources_2026-09-26.json").read_text(encoding="utf-8"))
    expected = {(event["symbol"], utc_ms(event["automatic_settlement_utc"])): event["source_url"]
                for event in lifecycle["events"]}
    observed = {(event["symbol"], event["settlement_ms"]): event["event_url"] for event in report["events"]}
    if len(expected) != 2 or len(report["events"]) != 2 or observed != expected:
        raise ValueError("settlement bounds differ from the two documented lifecycle events")
    output = {}
    for event in report["events"]:
        source = event["source"]
        if source["symbol"] != event["symbol"]:
            raise ValueError("settlement source symbol differs")
        record = fetch(source["kind"], source["symbol"], source["month"], source["frequency"], source["interval"])
        if record["sha256"] != source["sha256"] or sha(Path(record["path"])) != source["sha256"]:
            raise ValueError("settlement source differs")
        with zipfile.ZipFile(Path(record["path"])) as archive:
            if len(archive.namelist()) != 1:
                raise ValueError("unexpected settlement ZIP")
            computed = bound(csv.reader(io.StringIO(archive.read(archive.namelist()[0]).decode("utf-8-sig"))),
                             event["settlement_ms"])
        if any(computed[name] != event[name] for name in computed):
            raise ValueError("settlement bound reproduction failed")
        output[event["symbol"], event["settlement_ms"]] = computed
    return output, report


def verify_weekly(hourly, funding, states):
    baseline = json.loads((RESULTS / "trailing_research.json").read_text(encoding="utf-8"))
    output = {}
    for trailing, (label, cost) in itertools.product((False, True), (("stress", .0015), ("double_stress", .003))):
        name = "portfolio_pct_4pct" if trailing else "none"
        actual = evaluate(hourly, funding, states, baseline["rule"], *CONFIG["periods"]["combined"], cost,
                          trailing=TrailingStop("portfolio_pct", .04) if trailing else None, cadence="weekly")
        expected = baseline["results"][name]["combined"][label]
        checks = verify_reproduction(actual, expected)
        for field in ("daily_equity", "execution_audit", "stop_events"):
            if actual[field] != expected[field]:
                raise ValueError("weekly baseline path differs: " + field)
        output[name + "/" + label] = {**checks, "daily_path_and_orders_equal": True}
    return output


def compact(value):
    if isinstance(value, dict):
        return {k: compact(v) for k, v in value.items()
                if k not in ("daily_equity", "execution_audit", "stop_events", "policy_audit")}
    if isinstance(value, list):
        return [compact(v) for v in value]
    return value


def run():
    lock = RESULTS / "residual_research.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(descriptor)
    try:
        start = time.perf_counter()
        frozen = anchors()
        print("Fixed residual protocol verified; loading cached market sources.", flush=True)
        with _offline_inputs():
            data, daily_sources, _ = load_daily()
            hourly, hourly_sources = load_hourly(data)
            training, training_sources = load_hourly(data, "training_hourly_manifest.json")
            for kind in hourly:
                for symbol in hourly[kind]:
                    hourly[kind][symbol].update(training[kind][symbol])
            rest_sources, overlap, _ = extend(data, hourly)
            bounds, settlement_evidence = verified_bounds()
        base, fields, feature_quality = feature_bundle(data)
        if len(fields) != 60:
            raise ValueError("expected all 60 existing daily fields")
        states, model_quality = enrich_states(data, base)
        state_hash = hashlib.sha256()
        for symbol, rows in sorted(states.items()):
            for cutoff, row in sorted(rows.items()):
                state_hash.update(canonical({"symbol": symbol, "cutoff_ms": cutoff, "state": row}) + b"\n")
        sources = {label: {"count": len(rows), "manifest_sha256": hashlib.sha256(canonical([
                       {k: v for k, v in row.items() if k != "path"} for row in rows])).hexdigest()}
                   for label, rows in (("daily", daily_sources), ("hourly", hourly_sources),
                                       ("training_hourly", training_sources), ("rest", rest_sources))}
        inputs = {"config": CONFIG, "anchors": frozen, "fields": fields, "sources": sources,
                  "feature_quality": feature_quality, "model_quality": model_quality,
                  "model_state_sha256": state_hash.hexdigest(), "overlap": overlap,
                  "settlement_evidence": settlement_evidence}
        if INPUTS.exists() and json.loads(INPUTS.read_text(encoding="utf-8")) != json.loads(json.dumps(inputs)):
            raise ValueError("fixed inputs changed; new experiment revision required")
        if not INPUTS.exists():
            INPUTS.write_text(json.dumps(inputs, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if anchors() != frozen:
            raise ValueError("sources changed while building model states")
        reproduction = verify_weekly(hourly, data["fundingRate"], base)
        print("All four weekly reference paths, costs, and orders reproduced exactly.", flush=True)
        results = []
        for period, risk_scale, trailing, cost in itertools.product(
                CONFIG["periods"], CONFIG["risk_scales"], CONFIG["portfolio_trailing"], CONFIG["side_costs"]):
            dates = CONFIG["periods"][period]
            policy = ResidualPolicy(risk_scale)
            scenario = {"period": period, "risk_scale": risk_scale, "portfolio_trailing": trailing,
                        "side_cost": cost, "start": dates[0], "end": dates[1]}
            try:
                metrics = evaluate(hourly, data["fundingRate"], states, "residual_ou", *dates, cost,
                                   target_policy=policy, settlement_bounds=bounds,
                                   trailing=TrailingStop("portfolio_pct", trailing) if trailing else None,
                                   cadence=CONFIG["cadence"], delay_hours=CONFIG["delay_hours"])
            except ValueError as exc:
                if not str(exc).startswith(("insolvent", "unresolved held price", "unverified execution liquidity")):
                    raise
                scenario.update(status="invalid_execution", error=str(exc), metrics=None,
                                meets_nominal_target=False, meets_target_and_adverse_bound=False)
            else:
                days = (utc_ms(dates[1])-utc_ms(dates[0]))/86_400_000
                cagr = annualized_return(metrics["return_pct"], days)
                meets = cagr >= 50 and metrics["max_drawdown_pct"] <= 10 and metrics["margin_stress_failures"] == 0
                scenario.update(status="complete", metrics=metrics, net_cagr_pct=cagr,
                                meets_nominal_target=meets,
                                meets_target_and_adverse_bound=meets and metrics["adverse_intrahour_drawdown_bound_pct"] <= 10,
                                relies_on_bounded_settlements=bool(metrics["bounded_settlements"]),
                                active_decision_days=sum(bool(a["target_weights"]) for a in policy.audit),
                                stop_tick_count=len({e["timestamp_ms"] for e in metrics["stop_events"]}))
            scenario["policy_audit"] = policy.audit
            results.append(scenario)
            print({k: scenario.get(k) for k in ("period", "risk_scale", "portfolio_trailing", "side_cost",
                  "status", "net_cagr_pct", "active_decision_days")}, flush=True)
        if anchors() != frozen:
            raise ValueError("protocol or sources changed during replay")
        report = {"created_utc": datetime.now(timezone.utc).isoformat(), "elapsed_seconds": time.perf_counter()-start,
                  "inputs": inputs, "inputs_file_sha256": sha(INPUTS), "weekly_reproduction": reproduction,
                  "scenarios": results, "deployable": False, "goal_achieved": False, "selected_winner": None,
                  "jev_calls": 0, "orders_sent": 0,
                  "limits": ["Previously researched history; not an independent prospective trial.",
                             "BTC/ETH neutrality and volatility are estimated, not guaranteed future exposure limits.",
                             "Model factor and residual windows are disjoint, but OU stationarity is not proven.",
                             "Entry hurdle excludes favorable drift/carry and does not cover every daily turnover cost.",
                             "Signal episode lifespan can differ from actual exposure after trailing stops.",
                             "Any contract settlement bound is an adverse accounting scenario, not an exact fill.",
                             "Hourly portfolio stops and margin heuristics do not reproduce exchange liquidation.",
                             "Returns exclude taxes and real account-specific execution/operating expenses."]}
        full = RESULTS / "residual_research.json"
        full.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+"\n", encoding="utf-8")
        summary = compact(report)
        summary["full_report_sha256"] = sha(full)
        (ROOT / "docs/residual_research_2026-09-26.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True, allow_nan=False)+"\n", encoding="utf-8")
        print(f"Completed {len(results)} scenarios; target matches={sum(r['meets_nominal_target'] for r in results)}.", flush=True)
        return summary
    finally:
        lock.unlink()


if __name__ == "__main__":
    run()
