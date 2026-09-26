"""Frozen matched 24-hour post-funding experiment, using offline inputs only."""

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
from .funding_event_execution import evaluate
from .funding_event_features import build_states
from .funding_event_policy import EventPolicy
from .funding_event_prediction import build_forecasts
from .positioning_acquire import CACHE, prepare as acquisition_plan
from .positioning_dataset import load_verified
from .positioning_features import FEATURES, augment
from .positioning_research import anchors as positioning_anchors, compact, write_json
from .residual_research import verified_bounds
from .target50_research import _offline_inputs, annualized_return
from .trailing_stop import TrailingStop
from .tree_research import canonical, digest_states, sha


CONFIG = {"schema_version": 1, "models": ["control75", "augmented80"],
          "periods": {"development": ["2023-01-01", "2024-01-01"],
                      "combined": ["2024-01-01", "2026-09-26"]},
          "gross_limits": [1.0, 2.0], "portfolio_trailing": [None, .04],
          "side_costs": [.0015, .003], "funding_slot_utc_hour": 0,
          "decision_utc_hour": 1, "execution_utc_hour": 2, "label_hours": 24,
          "minimum_training_days": 365, "maximum_pairs": 3,
          "target_net_cagr_pct": 50, "maximum_drawdown_pct": 10,
          "historical_point_in_time_verified": False}
PROTOCOL = ROOT / "docs/funding_event_protocol_2026-09-26.md"
SOURCES = ROOT / "docs/funding_event_sources_2026-09-26.md"
INPUTS = RESULTS / "funding_event_inputs.json"
BASELINE = RESULTS / "tree_prediction_inputs.json"
BASELINE_SHA = "d13b5e1b0f4d348c681b85ea788a1e0eadb675fc84472e85ec779fcde50f7483"
CODE = ("funding_event_research.py", "funding_event_features.py", "funding_event_prediction.py",
        "funding_event_policy.py", "funding_event_execution.py")


def anchors():
    blocks = re.findall(r"```json\s*\n(.*?)\n```", PROTOCOL.read_text(encoding="utf-8"), re.DOTALL)
    if len(blocks) != 1 or json.loads(blocks[0]) != CONFIG:
        raise ValueError("funding event protocol differs from fixed configuration")
    if sha(BASELINE) != BASELINE_SHA:
        raise ValueError("preserved baseline changed")
    return {"positioning_anchors": positioning_anchors(), "protocol_sha256": sha(PROTOCOL),
            "method_sources_sha256": sha(SOURCES), "baseline_inputs_sha256": BASELINE_SHA,
            "code_sha256": {name: sha(ROOT / "src/jev_trader" / name) for name in CODE}}


def funding_inventory(funding):
    """Timing-only check: no event-return calculation or future eligibility."""
    result = {}
    for symbol, rows in sorted(funding.items()):
        ordered = sorted(rows, key=lambda row: row.timestamp_ms)
        times = [row.timestamp_ms for row in ordered]
        gaps = {(b//3_600_000-a//3_600_000) for a, b in zip(times, times[1:])}
        if len(times) != len(set(times)) or gaps != {8}:
            raise ValueError("frozen three-payment assumption requires observed eight-hour history")
        if any(t//3_600_000 % 24 not in (0, 8, 16) or t % 3_600_000 >= 60_000 for t in times):
            raise ValueError("funding timestamps differ from predeclared schedule")
        result[symbol] = {"events": len(times), "nominal_gap_hours": sorted(gaps),
                          "first_timestamp_ms": times[0], "last_timestamp_ms": times[-1],
                          "largest_slot_offset_ms": max(t % 3_600_000 for t in times)}
    return result


def prepare_inputs(frozen):
    snapshots, dataset_audit = load_verified(acquisition_plan(), CACHE)
    print("Positioning archives verified; loading preserved hourly and daily inputs offline.", flush=True)
    with _offline_inputs():
        data, daily_sources, cohort = load_daily()
        hourly, hourly_sources = load_hourly(data)
        training, training_sources = load_hourly(data, "training_hourly_manifest.json")
        for kind in hourly:
            for symbol in hourly[kind]:
                hourly[kind][symbol].update(training[kind][symbol])
        rest_sources, overlap, exact_marks = extend(data, hourly)
        bounds, settlement_evidence = verified_bounds()
    base, fields, quality = feature_bundle(data)
    sources = {label: {"count": len(rows), "manifest_sha256": hashlib.sha256(canonical([
        {key: value for key, value in row.items() if key != "path"} for row in rows])).hexdigest()}
        for label, rows in (("daily", daily_sources), ("hourly", hourly_sources),
                            ("training_hourly", training_sources), ("rest", rest_sources))}
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    reproduction = {"anchors": frozen["positioning_anchors"]["tree_anchors"],
                    "cohort": cohort["selected"], "fields": list(fields), "feature_quality": quality,
                    "state_sha256": digest_states(base), "sources": sources,
                    "overlap": overlap, "settlement_evidence": settlement_evidence}
    for key, value in reproduction.items():
        if json.loads(json.dumps(value)) != baseline[key]:
            raise ValueError("preserved baseline mismatch: " + key)
    positioning, _, positioning_quality = augment(base, fields, snapshots)
    states, control_fields, event_fields, state_audit = build_states(
        data, hourly, base, fields, positioning, FEATURES)
    inputs = {"anchors": frozen, "config": CONFIG, "cohort": cohort["selected"],
              "control_fields": list(control_fields), "event_fields": list(event_fields),
              "baseline_state_sha256": reproduction["state_sha256"],
              "event_state_sha256": digest_states(states), "sources": sources,
              "funding_inventory": funding_inventory(data["fundingRate"]),
              "positioning_dataset": dataset_audit, "positioning_quality": positioning_quality,
              "event_feature_quality": state_audit, "settlement_evidence": settlement_evidence,
              "exact_funding_marks_sha256": hashlib.sha256(canonical(
                  [[s, t, mark] for (s, t), mark in sorted(exact_marks.items())])).hexdigest(),
              "historical_point_in_time_verified": False}
    if anchors() != frozen:
        raise ValueError("sources changed during input preparation")
    if INPUTS.exists():
        if json.loads(INPUTS.read_text(encoding="utf-8")) != json.loads(json.dumps(inputs)):
            raise ValueError("funding event inputs changed; explicit new revision required")
    else:
        write_json(INPUTS, inputs)
    return data, hourly, bounds, exact_marks, states, control_fields, event_fields, inputs


def run(prepare_only=False):
    lock = RESULTS / "funding_event_research.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(descriptor)
    try:
        started = time.perf_counter()
        frozen = anchors()
        data, hourly, bounds, exact_marks, states, control_fields, event_fields, inputs = prepare_inputs(frozen)
        print("Event states frozen:", sum(map(len, states.values())), "asset/days.", flush=True)
        if prepare_only:
            return compact(inputs)
        events = json.loads((ROOT / "docs/contract_lifecycle_sources_2026-09-26.json").read_text(
            encoding="utf-8"))["events"]
        prediction = build_forecasts(hourly, states, control_fields, event_fields, events,
                                     progress=lambda record: print("Matched monthly fit:", record, flush=True))
        score_periods = {**CONFIG["periods"], "year_2024": ["2024-01-01", "2025-01-01"],
                         "year_2025": ["2025-01-01", "2026-01-01"],
                         "year_2026": ["2026-01-01", "2026-09-26"]}
        scenarios = []
        for name in CONFIG["models"]:
            model = prediction[name]
            model.update(signal_sha256=digest_states(model["signals"]), fit_count=len(model["fit_audits"]),
                         forecast_count=len(model["prediction_audits"]))
            model["scores"] = {period: summarize_errors(model["prediction_errors"], *dates)
                               for period, dates in score_periods.items()}
            print(name, "fits", model["fit_count"], "forecast days", model["forecast_count"], flush=True)
            for period, gross, trailing, cost in itertools.product(
                    CONFIG["periods"], CONFIG["gross_limits"], CONFIG["portfolio_trailing"], CONFIG["side_costs"]):
                dates = CONFIG["periods"][period]
                policy = EventPolicy(events, gross_limit=gross, side_cost=cost, end_ms=utc_ms(dates[1]))
                row = {"model": name, "period": period, "gross_limit": gross,
                       "portfolio_trailing": trailing, "side_cost": cost}
                try:
                    metrics = evaluate(hourly, data["fundingRate"], model["signals"], name,
                                       *dates, cost, target_policy=policy, settlement_bounds=bounds,
                                       exact_funding_marks=exact_marks,
                                       trailing=TrailingStop("portfolio_pct", trailing) if trailing else None)
                except ValueError as error:
                    if not str(error).startswith(("insolvent", "unresolved held price", "unverified execution liquidity")):
                        raise
                    row.update(status="invalid_execution", error=str(error), metrics=None,
                               meets_nominal_target=False, meets_target_and_adverse_bound=False)
                else:
                    days = (utc_ms(dates[1])-utc_ms(dates[0]))/86_400_000
                    cagr = annualized_return(metrics["return_pct"], days)
                    meets = cagr >= 50 and metrics["max_drawdown_pct"] <= 10 and metrics["margin_stress_failures"] == 0
                    row.update(status="complete", metrics=metrics, net_cagr_pct=cagr,
                               meets_nominal_target=meets,
                               meets_target_and_adverse_bound=meets and metrics["adverse_intrahour_drawdown_bound_pct"] <= 10)
                row["policy_audit"] = policy.audit
                scenarios.append(row)
                print({key: row.get(key) for key in ("model", "period", "gross_limit", "portfolio_trailing",
                                                   "side_cost", "status", "net_cagr_pct")}, flush=True)
        if anchors() != frozen:
            raise ValueError("frozen funding event sources changed during replay")
        report = {"created_utc": datetime.now(timezone.utc).isoformat(),
                  "elapsed_seconds": time.perf_counter()-started, "inputs": inputs,
                  "inputs_file_sha256": sha(INPUTS), "prediction": prediction, "scenarios": scenarios,
                  "goal_achieved": False, "deployable": False, "selected_winner": None,
                  "jev_calls": 0, "orders_sent": 0, "new_market_downloads": 0,
                  "historical_point_in_time_verified": False,
                  "limits": ["Funding publication by 01:00 and positioning publication are retrospective assumptions.",
                             "Archive revisions can differ from historically available information.",
                             "Only midnight funding events and a 02:00-to-02:00 holding horizon are tested.",
                             "Reused history and repeated experiments do not constitute untouched confirmation.",
                             "Forecast labels are gross beta-hedged price returns, not calibrated net profit or probabilities.",
                             "A three-payment adverse funding hurdle is an estimate; actual future funding is accounted separately.",
                             "Missing future labels exclude whole training dates but do not suppress current forecasts.",
                             "Hourly fills, cost assumptions and margin heuristics cannot prove executable account outcomes.",
                             "A portfolio trailing rule cannot guarantee a ten-percent maximum drawdown."]}
        full = RESULTS / "funding_event_research.json"
        write_json(full, report)
        summary = compact(report)
        summary["full_report_sha256"] = sha(full)
        write_json(ROOT / "docs/funding_event_research_2026-09-26.json", summary)
        print("Completed 32 scenarios; nominal target matches:",
              sum(row["meets_nominal_target"] for row in scenarios), flush=True)
        return summary
    finally:
        lock.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    run(parser.parse_args().prepare_only)
