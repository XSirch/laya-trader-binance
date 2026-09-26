"""Isolated fixed tree experiment; offline market inputs, no order/JEV route."""

from datetime import datetime, timezone
import hashlib
import importlib.metadata
import itertools
import json
import os
import platform
import re
import time

from .binance_data import utc_ms
from .broad_data import CACHE, load as load_daily
from .broad_extension import extend
from .broad_hourly import load as load_hourly
from .broad_prediction import summarize_errors
from .broad_technical import feature_bundle
from .cli import ROOT, RESULTS
from .residual_research import verified_bounds
from .scheduled_execution import evaluate
from .target50_research import _offline_inputs, annualized_return
from .trailing_stop import TrailingStop
from .tree_policy import TreePolicy
from .tree_prediction import build_forecasts


CONFIG = {"schema_version": 1, "periods": {"development": ["2023-01-01", "2024-01-01"],
          "combined": ["2024-01-01", "2026-09-26"]}, "gross_limits": [1.0, 2.0],
          "portfolio_trailing": [None, .04], "side_costs": [.0015, .003], "delay_hours": 1,
          "cadence": "weekly", "target_net_cagr_pct": 50, "maximum_drawdown_pct": 10}
PROTOCOL = ROOT / "docs/tree_prediction_protocol_2026-09-26.md"
INPUTS = RESULTS / "tree_prediction_inputs.json"
CODE = ("tree_prediction.py", "tree_policy.py", "tree_research.py", "scheduled_execution.py",
        "broad_technical.py", "broad_prediction.py", "broad_research.py", "broad_execution.py",
        "broad_data.py", "broad_hourly.py", "broad_extension.py", "binance_data.py", "derivatives_data.py",
        "market_state.py", "strategies.py", "trailing_stop.py", "target50_research.py", "settlement_bounds.py",
        "residual_research.py", "residual_policy.py", "cli.py", "statistics.py", "extended.py")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest_states(states):
    digest = hashlib.sha256()
    for symbol, rows in sorted(states.items()):
        for cutoff, row in sorted(rows.items()):
            digest.update(canonical({"symbol": symbol, "cutoff_ms": cutoff, "state": row}) + b"\n")
    return digest.hexdigest()


def anchors():
    blocks = re.findall(r"```json\s*\n(.*?)\n```", PROTOCOL.read_text(encoding="utf-8"), re.DOTALL)
    if len(blocks) != 1 or json.loads(blocks[0]) != CONFIG:
        raise ValueError("tree protocol and runner differ")
    lock = ROOT / "requirements-tree.lock"
    versions = dict(re.findall(r"^([a-zA-Z0-9_-]+)==([^\s]+)", lock.read_text(encoding="utf-8"), re.MULTILINE))
    if not versions or any(importlib.metadata.version(name) != version for name, version in versions.items()):
        raise ValueError("tree dependencies differ from locked environment")
    freeze_path = ROOT / "docs/broad_candidate_freeze_2026-09-26.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    for name, expected in freeze["source_code_sha256"].items():
        if sha(ROOT / "src/jev_trader" / name) != expected:
            raise ValueError("frozen source changed: " + name)
    return {"protocol_sha256": sha(PROTOCOL), "freeze_sha256": sha(freeze_path),
            "code_sha256": {name: sha(ROOT / "src/jev_trader" / name) for name in CODE},
            "dependency_lock_sha256": sha(lock), "package_versions": versions,
            "project_manifest_sha256": sha(ROOT / "pyproject.toml"),
            "method_sources_sha256": sha(ROOT / "docs/tree_prediction_sources_2026-09-26.md"),
            "python_version": platform.python_version(),
            "settlement_sha256": sha(ROOT / "docs/settlement_bounds_2026-09-26.json"),
            "lifecycle_sha256": sha(ROOT / "docs/contract_lifecycle_sources_2026-09-26.json"),
            "manifest_sha256": {name: sha(CACHE / name) for name in (
                "cohort.json", "manifest.json", "hourly_manifest.json", "training_hourly_manifest.json")}}


def compact(value):
    if isinstance(value, dict):
        omitted = ("daily_equity", "execution_audit", "policy_audit", "fit_audits", "prediction_audits",
                   "prediction_errors", "stop_events", "signals")
        return {key: compact(item) for key, item in value.items() if key not in omitted}
    if isinstance(value, list):
        return [compact(item) for item in value]
    return value


def run():
    lock = RESULTS / "tree_research.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(descriptor)
    try:
        started = time.perf_counter()
        frozen = anchors()
        print("Fixed tree protocol; verifying preserved market data offline.", flush=True)
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
        if len(fields) != 60:
            raise ValueError("expected all sixty fields")
        expected_cohort = json.loads((ROOT / "docs/broad_candidate_freeze_2026-09-26.json").read_text(encoding="utf-8"))["cohort"]
        if cohort["selected"] != expected_cohort:
            raise ValueError("historical cohort changed")
        lifecycle = json.loads((ROOT / "docs/contract_lifecycle_sources_2026-09-26.json").read_text(encoding="utf-8"))
        sources = {label: {"count": len(rows), "manifest_sha256": hashlib.sha256(canonical([
                       {k: v for k, v in row.items() if k != "path"} for row in rows])).hexdigest()}
                   for label, rows in (("daily", daily_sources), ("hourly", hourly_sources),
                                       ("training_hourly", training_sources), ("rest", rest_sources))}
        inputs = {"anchors": frozen, "config": CONFIG, "cohort": expected_cohort, "fields": fields,
                  "feature_quality": quality, "state_sha256": digest_states(states), "sources": sources,
                  "overlap": overlap, "settlement_evidence": settlement_evidence}
        if INPUTS.exists() and json.loads(INPUTS.read_text(encoding="utf-8")) != json.loads(json.dumps(inputs)):
            raise ValueError("tree input evidence changed; explicit new revision required")
        if not INPUTS.exists():
            INPUTS.write_text(json.dumps(inputs, indent=2, sort_keys=True)+"\n", encoding="utf-8")
        if anchors() != frozen:
            raise ValueError("sources changed during preparation")
        print("Inputs frozen; fitting monthly trees on completed past labels only.", flush=True)
        prediction = build_forecasts(hourly, states, fields, lifecycle["events"])
        signals = prediction["signals"]
        prediction["signal_sha256"] = digest_states(signals)
        prediction["fit_count"] = len(prediction["fit_audits"])
        prediction["forecast_count"] = len(prediction["prediction_audits"])
        score_periods = {**CONFIG["periods"], "year_2024": ["2024-01-01", "2025-01-01"],
                         "year_2025": ["2025-01-01", "2026-01-01"], "year_2026": ["2026-01-01", "2026-09-26"]}
        prediction["scores"] = {p: summarize_errors(prediction["prediction_errors"], *dates)
                                for p, dates in score_periods.items()}
        print("Causal fits:", prediction["fit_count"], "forecast weeks:", prediction["forecast_count"], flush=True)
        scenarios = []
        for period, gross, trailing, cost in itertools.product(
                CONFIG["periods"], CONFIG["gross_limits"], CONFIG["portfolio_trailing"], CONFIG["side_costs"]):
            dates = CONFIG["periods"][period]
            policy = TreePolicy(lifecycle["events"], gross_limit=gross)
            row = {"period": period, "gross_limit": gross, "portfolio_trailing": trailing, "side_cost": cost}
            try:
                metrics = evaluate(hourly, data["fundingRate"], signals, "tree", *dates, cost,
                                   target_policy=policy, settlement_bounds=bounds,
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
            print({k: row.get(k) for k in ("period", "gross_limit", "portfolio_trailing", "side_cost",
                   "status", "net_cagr_pct")}, flush=True)
        if anchors() != frozen:
            raise ValueError("frozen experiment changed during replay")
        report = {"created_utc": datetime.now(timezone.utc).isoformat(), "elapsed_seconds": time.perf_counter()-started,
                  "inputs": inputs, "inputs_file_sha256": sha(INPUTS), "prediction": prediction, "scenarios": scenarios,
                  "goal_achieved": False, "deployable": False, "jev_calls": 0, "orders_sent": 0,
                  "new_market_downloads": 0, "selected_winner": None,
                  "limits": ["Retrospective after prior searches; no untouched confirmation.",
                             "Weekly gross relative-price labels exclude funding and trading costs; policy hurdle is an estimate.",
                             "BTC beta hedge can leave nonzero net dollar exposure; relative alpha omits the unknown common return on that exposure.",
                             "Whole weeks with unavailable labels are omitted, including lifecycle interruptions.",
                             "Hourly marks and adverse settlement bounds do not establish realized fills or account margin.",
                             "Nominal historical target matches alone cannot validate consistent future profitability."]}
        full = RESULTS / "tree_prediction_research.json"
        full.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+"\n", encoding="utf-8")
        summary = compact(report)
        summary["full_report_sha256"] = sha(full)
        (ROOT / "docs/tree_prediction_research_2026-09-26.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True, allow_nan=False)+"\n", encoding="utf-8")
        print("Completed sixteen fixed tree scenarios; nominal target matches:",
              sum(row["meets_nominal_target"] for row in scenarios), flush=True)
        return summary
    finally:
        lock.unlink()


if __name__ == "__main__":
    run()
