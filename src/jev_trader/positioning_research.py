"""Offline, matched-universe comparison of sixty versus sixty-eight fields."""

import argparse
from datetime import datetime, timezone
import hashlib
import itertools
import json
import os
import re
import time

from .binance_data import utc_ms
from .broad_data import load as load_daily
from .broad_extension import extend
from .broad_hourly import load as load_hourly
from .broad_prediction import summarize_errors
from .broad_technical import feature_bundle
from .cli import ROOT, RESULTS
from .positioning_acquire import CACHE, prepare as acquisition_plan
from .positioning_dataset import load_verified
from .positioning_features import augment
from .positioning_prediction import build_forecasts
from .residual_research import verified_bounds
from .scheduled_execution import evaluate
from .target50_research import _offline_inputs, annualized_return
from .trailing_stop import TrailingStop
from .tree_policy import TreePolicy
from .tree_research import anchors as tree_anchors, canonical, digest_states, sha


CONFIG = {"schema_version": 1, "models": ["control60", "augmented68"],
          "periods": {"development": ["2023-01-01", "2024-01-01"],
                      "combined": ["2024-01-01", "2026-09-26"]},
          "gross_limits": [1.0, 2.0], "portfolio_trailing": [None, .04],
          "side_costs": [.0015, .003], "delay_hours": 1, "cadence": "weekly",
          "target_net_cagr_pct": 50, "maximum_drawdown_pct": 10,
          "historical_point_in_time_verified": False}
PROTOCOL = ROOT / "docs/positioning_prediction_protocol_2026-09-26.md"
INPUTS = RESULTS / "positioning_prediction_inputs.json"
BASELINE_INPUTS = RESULTS / "tree_prediction_inputs.json"
BASELINE_INPUTS_SHA256 = "d13b5e1b0f4d348c681b85ea788a1e0eadb675fc84472e85ec779fcde50f7483"
CODE = ("positioning_research.py", "positioning_prediction.py", "positioning_dataset.py",
        "positioning_features.py", "positioning_acquire.py", "positioning_metrics.py",
        "metrics_catalog.py", "metrics_fetch.py")


def anchors():
    blocks = re.findall(r"```json\s*\n(.*?)\n```", PROTOCOL.read_text(encoding="utf-8"), re.DOTALL)
    if len(blocks) != 1 or json.loads(blocks[0]) != CONFIG:
        raise ValueError("positioning comparison protocol differs from fixed configuration")
    if sha(BASELINE_INPUTS) != BASELINE_INPUTS_SHA256:
        raise ValueError("preserved sixty-field baseline inputs changed")
    return {"tree_anchors": tree_anchors(), "protocol_sha256": sha(PROTOCOL),
            "code_sha256": {name: sha(ROOT / "src/jev_trader" / name) for name in CODE},
            "baseline_inputs_sha256": BASELINE_INPUTS_SHA256,
            "acquisition_plan_sha256": sha(CACHE / "acquisition_plan.json")}


def compact(value):
    omitted = {"daily_equity", "execution_audit", "policy_audit", "fit_audits",
               "prediction_audits", "prediction_errors", "stop_events", "signals",
               "manifest", "unavailable_observations"}
    if isinstance(value, dict):
        return {key: compact(item) for key, item in value.items() if key not in omitted}
    if isinstance(value, list):
        return [compact(item) for item in value]
    return value


def write_json(path, value):
    payload = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    temporary = path.with_name(path.name + ".part")
    temporary.write_bytes(payload)
    temporary.replace(path)


def prepare_inputs(frozen):
    plan = acquisition_plan()
    snapshots, dataset_audit = load_verified(plan, CACHE)
    print("All positioning records verified offline; rebuilding preserved sixty fields.", flush=True)
    with _offline_inputs():
        data, daily_sources, cohort = load_daily()
        hourly, hourly_sources = load_hourly(data)
        training, training_sources = load_hourly(data, "training_hourly_manifest.json")
        for kind in hourly:
            for symbol in hourly[kind]:
                hourly[kind][symbol].update(training[kind][symbol])
        rest_sources, overlap, _ = extend(data, hourly)
        bounds, settlement_evidence = verified_bounds()
    states, fields, quality = feature_bundle(data)
    sources = {label: {"count": len(rows), "manifest_sha256": hashlib.sha256(canonical([
                   {key: value for key, value in row.items() if key != "path"} for row in rows])).hexdigest()}
               for label, rows in (("daily", daily_sources), ("hourly", hourly_sources),
                                   ("training_hourly", training_sources), ("rest", rest_sources))}
    baseline = json.loads(BASELINE_INPUTS.read_text(encoding="utf-8"))
    comparison = {"anchors": frozen["tree_anchors"], "cohort": cohort["selected"],
                  "fields": list(fields), "feature_quality": quality, "state_sha256": digest_states(states),
                  "sources": sources, "overlap": overlap, "settlement_evidence": settlement_evidence}
    for name, value in comparison.items():
        if json.loads(json.dumps(value)) != baseline[name]:
            raise ValueError("preserved baseline mismatch: " + name)
    augmented, all_fields, positioning_quality = augment(states, fields, snapshots)
    # Both models receive this same filtered state map. The control's predictor
    # vectors select only base fields, while portfolio/accounting metadata stays equal.
    inputs = {"anchors": frozen, "config": CONFIG, "cohort": cohort["selected"],
              "base_fields": list(fields), "augmented_fields": list(all_fields),
              "baseline_state_sha256": comparison["state_sha256"],
              "matched_state_sha256": digest_states(augmented), "sources": sources,
              "positioning_dataset": dataset_audit, "positioning_quality": positioning_quality,
              "settlement_evidence": settlement_evidence,
              "historical_point_in_time_verified": False}
    if anchors() != frozen:
        raise ValueError("comparison sources changed during preparation")
    if INPUTS.exists():
        if json.loads(INPUTS.read_text(encoding="utf-8")) != json.loads(json.dumps(inputs)):
            raise ValueError("positioning comparison inputs changed; explicit new revision required")
    else:
        write_json(INPUTS, inputs)
    return data, hourly, bounds, augmented, fields, inputs


def run(prepare_only=False):
    lock = RESULTS / "positioning_research.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(descriptor)
    try:
        started = time.perf_counter()
        frozen = anchors()
        data, hourly, bounds, states, fields, inputs = prepare_inputs(frozen)
        print("Matched inputs frozen; observations:", sum(map(len, states.values())), flush=True)
        if prepare_only:
            return compact(inputs)
        events = json.loads((ROOT / "docs/contract_lifecycle_sources_2026-09-26.json").read_text(
            encoding="utf-8"))["events"]
        prediction = build_forecasts(hourly, states, fields, events)
        score_periods = {**CONFIG["periods"], "year_2024": ["2024-01-01", "2025-01-01"],
                         "year_2025": ["2025-01-01", "2026-01-01"],
                         "year_2026": ["2026-01-01", "2026-09-26"]}
        scenarios = []
        for model_name in CONFIG["models"]:
            model = prediction[model_name]
            model.update(signal_sha256=digest_states(model["signals"]), fit_count=len(model["fit_audits"]),
                         forecast_count=len(model["prediction_audits"]))
            model["scores"] = {period: summarize_errors(model["prediction_errors"], *dates)
                               for period, dates in score_periods.items()}
            print(model_name, "fits", model["fit_count"], "forecast weeks", model["forecast_count"], flush=True)
            for period, gross, trailing, cost in itertools.product(
                    CONFIG["periods"], CONFIG["gross_limits"], CONFIG["portfolio_trailing"], CONFIG["side_costs"]):
                dates = CONFIG["periods"][period]
                policy = TreePolicy(events, gross_limit=gross)
                row = {"model": model_name, "period": period, "gross_limit": gross,
                       "portfolio_trailing": trailing, "side_cost": cost}
                try:
                    metrics = evaluate(hourly, data["fundingRate"], model["signals"], model_name,
                                       *dates, cost, target_policy=policy, settlement_bounds=bounds,
                                       trailing=TrailingStop("portfolio_pct", trailing) if trailing else None,
                                       cadence=CONFIG["cadence"], delay_hours=CONFIG["delay_hours"])
                except ValueError as exc:
                    if not str(exc).startswith(("insolvent", "unresolved held price", "unverified execution liquidity")):
                        raise
                    row.update(status="invalid_execution", error=str(exc), metrics=None,
                               meets_nominal_target=False, meets_target_and_adverse_bound=False)
                else:
                    cagr = annualized_return(metrics["return_pct"], (utc_ms(dates[1])-utc_ms(dates[0]))/86_400_000)
                    meets = cagr >= 50 and metrics["max_drawdown_pct"] <= 10 and metrics["margin_stress_failures"] == 0
                    row.update(status="complete", metrics=metrics, net_cagr_pct=cagr,
                               meets_nominal_target=meets,
                               meets_target_and_adverse_bound=meets and metrics["adverse_intrahour_drawdown_bound_pct"] <= 10,
                               relies_on_bounded_settlements=bool(metrics["bounded_settlements"]))
                row["policy_audit"] = policy.audit
                scenarios.append(row)
                print({key: row.get(key) for key in ("model", "period", "gross_limit", "portfolio_trailing",
                                                   "side_cost", "status", "net_cagr_pct")}, flush=True)
        if anchors() != frozen:
            raise ValueError("frozen positioning comparison changed during replay")
        report = {"created_utc": datetime.now(timezone.utc).isoformat(),
                  "elapsed_seconds": time.perf_counter()-started, "inputs": inputs,
                  "inputs_file_sha256": sha(INPUTS), "prediction": prediction, "scenarios": scenarios,
                  "goal_achieved": False, "deployable": False, "selected_winner": None,
                  "jev_calls": 0, "orders_sent": 0, "new_market_downloads": 0,
                  "historical_point_in_time_verified": False,
                  "limits": ["Current archive versions and assumed publication timing permit historical revision bias.",
                             "Retrospective research after prior searches; no untouched confirmation period.",
                             "Both models share the positioning-available universe; this control differs from the prior full-universe model.",
                             "Weekly gross relative-price labels exclude funding and costs; the policy hurdle estimates them.",
                             "The BTC beta hedge can leave net dollar exposure with unknown common price return.",
                             "Unavailable weekly labels exclude the whole eligible cross-section from training.",
                             "Hourly prices, assumed costs and margin heuristics do not prove realized fills or account margin.",
                             "A nominal historical target match cannot establish consistent future profitability."]}
        full = RESULTS / "positioning_prediction_research.json"
        write_json(full, report)
        summary = compact(report)
        summary["full_report_sha256"] = sha(full)
        write_json(ROOT / "docs/positioning_prediction_research_2026-09-26.json", summary)
        print("Completed thirty-two matched scenarios; nominal target matches:",
              sum(row["meets_nominal_target"] for row in scenarios), flush=True)
        return summary
    finally:
        lock.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    run(parser.parse_args().prepare_only)
