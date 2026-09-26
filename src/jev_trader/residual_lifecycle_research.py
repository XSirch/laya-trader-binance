"""Preserve R1; correct only announced contract eligibility in a separate replay."""

from datetime import datetime, timezone
import hashlib
import itertools
import json
import os
import time

from .binance_data import utc_ms
from .broad_data import load as load_daily
from .broad_extension import extend
from .broad_hourly import load as load_hourly
from .broad_technical import feature_bundle
from .cli import ROOT, RESULTS
from .residual_lifecycle import LifecyclePolicy
from .residual_policy import enrich_states
from .residual_research import CONFIG, anchors as original_anchors, canonical, compact, sha, verified_bounds
from .scheduled_execution import evaluate
from .target50_research import _offline_inputs, annualized_return
from .trailing_stop import TrailingStop


PROTOCOL = ROOT / "docs/residual_lifecycle_protocol_2026-09-26.md"
PREVIOUS = RESULTS / "residual_research.json"


def anchors():
    previous = json.loads(PREVIOUS.read_text(encoding="utf-8"))
    if original_anchors() != previous["inputs"]["anchors"]:
        raise ValueError("R1 frozen sources changed")
    summary = json.loads((ROOT / "docs/residual_research_2026-09-26.json").read_text(encoding="utf-8"))
    if summary["full_report_sha256"] != sha(PREVIOUS):
        raise ValueError("R1 report differs from preserved evidence")
    return {"protocol_sha256": sha(PROTOCOL), "previous_report_sha256": sha(PREVIOUS),
            "original_anchors": original_anchors(), "code_sha256": {
                name: sha(ROOT / "src/jev_trader" / name)
                for name in ("residual_lifecycle.py", "residual_lifecycle_research.py")}}


def run():
    lock = RESULTS / "residual_lifecycle_research.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(descriptor)
    try:
        start = time.perf_counter()
        frozen = anchors()
        previous = json.loads(PREVIOUS.read_text(encoding="utf-8"))
        lifecycle = json.loads((ROOT / "docs/contract_lifecycle_sources_2026-09-26.json").read_text(encoding="utf-8"))
        print("R1 evidence preserved; loading exactly the same offline inputs.", flush=True)
        with _offline_inputs():
            data, daily_sources, _ = load_daily()
            hourly, hourly_sources = load_hourly(data)
            training, training_sources = load_hourly(data, "training_hourly_manifest.json")
            for kind in hourly:
                for symbol in hourly[kind]:
                    hourly[kind][symbol].update(training[kind][symbol])
            rest_sources, _, _ = extend(data, hourly)
            bounds, _ = verified_bounds()
        base, fields, _ = feature_bundle(data)
        states, _ = enrich_states(data, base)
        state_hash = hashlib.sha256()
        for symbol, rows in sorted(states.items()):
            for cutoff, row in sorted(rows.items()):
                state_hash.update(canonical({"symbol": symbol, "cutoff_ms": cutoff, "state": row})+b"\n")
        if state_hash.hexdigest() != previous["inputs"]["model_state_sha256"]:
            raise ValueError("model states differ from R1")
        for label, rows in (("daily", daily_sources), ("hourly", hourly_sources),
                            ("training_hourly", training_sources), ("rest", rest_sources)):
            actual = {"count": len(rows), "manifest_sha256": hashlib.sha256(canonical([
                {k: v for k, v in row.items() if k != "path"} for row in rows])).hexdigest()}
            if actual != previous["inputs"]["sources"][label]:
                raise ValueError("market sources differ from R1: " + label)
        if list(fields) != previous["inputs"]["fields"] or anchors() != frozen:
            raise ValueError("R1 schema or code changed")
        inputs = {"anchors": frozen, "config": CONFIG, "model_state_sha256": state_hash.hexdigest(),
                  "lifecycle": lifecycle, "same_sources_as_r1": True}
        input_path = RESULTS / "residual_lifecycle_inputs.json"
        if input_path.exists() and json.loads(input_path.read_text(encoding="utf-8")) != inputs:
            raise ValueError("R2 inputs changed; explicit new revision required")
        if not input_path.exists():
            input_path.write_text(json.dumps(inputs, indent=2, sort_keys=True)+"\n", encoding="utf-8")
        results = []
        for period, risk_scale, trailing, cost in itertools.product(
                CONFIG["periods"], CONFIG["risk_scales"], CONFIG["portfolio_trailing"], CONFIG["side_costs"]):
            dates = CONFIG["periods"][period]
            policy = LifecyclePolicy(lifecycle["events"], risk_scale=risk_scale, delay_hours=CONFIG["delay_hours"])
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
                cagr = annualized_return(metrics["return_pct"], (utc_ms(dates[1])-utc_ms(dates[0]))/86_400_000)
                meets = cagr >= 50 and metrics["max_drawdown_pct"] <= 10 and metrics["margin_stress_failures"] == 0
                scenario.update(status="complete", metrics=metrics, net_cagr_pct=cagr,
                                meets_nominal_target=meets,
                                meets_target_and_adverse_bound=meets and metrics["adverse_intrahour_drawdown_bound_pct"] <= 10,
                                relies_on_bounded_settlements=bool(metrics["bounded_settlements"]),
                                active_decision_days=sum(bool(a["target_weights"]) for a in policy.audit),
                                stop_tick_count=len({e["timestamp_ms"] for e in metrics["stop_events"]}))
            scenario["policy_audit"] = policy.audit
            scenario["lifecycle_audit"] = policy.lifecycle_audit
            if period == "development":
                reference = next(r for r in previous["scenarios"] if all(
                    r[name] == scenario[name] for name in ("period", "risk_scale", "portfolio_trailing", "side_cost")))
                if scenario["metrics"] != reference["metrics"] or policy.audit != reference["policy_audit"]:
                    raise ValueError("operational fix changed pre-lifecycle development replay")
                scenario["r1_development_reproduced_exactly"] = True
            results.append(scenario)
            print({k: scenario.get(k) for k in ("period", "risk_scale", "portfolio_trailing", "side_cost",
                  "status", "net_cagr_pct")}, flush=True)
        if anchors() != frozen:
            raise ValueError("R1 or R2 sources changed during replay")
        report = {"created_utc": datetime.now(timezone.utc).isoformat(), "elapsed_seconds": time.perf_counter()-start,
                  "inputs": inputs, "inputs_file_sha256": sha(input_path), "scenarios": results,
                  "deployable": False, "goal_achieved": False, "selected_winner": None, "jev_calls": 0,
                  "orders_sent": 0, "limits": previous["limits"] + lifecycle["limits"] + [
                      "R2 is a disclosed operational correction after R1; no new untouched sample."]}
        full = RESULTS / "residual_lifecycle_research.json"
        full.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+"\n", encoding="utf-8")
        summary = compact(report)
        for row in summary["scenarios"]:
            row["restricted_decision_days"] = sum(bool(a["excluded_symbols"]) for a in row.pop("lifecycle_audit"))
        summary["full_report_sha256"] = sha(full)
        (ROOT / "docs/residual_lifecycle_research_2026-09-26.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True, allow_nan=False)+"\n", encoding="utf-8")
        print(f"R2 completed {len(results)} scenarios; target matches={sum(r['meets_nominal_target'] for r in results)}.", flush=True)
        return summary
    finally:
        lock.unlink()


if __name__ == "__main__":
    run()
