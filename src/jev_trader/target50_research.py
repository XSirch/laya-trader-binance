"""Fixed retrospective exposure/stop feasibility grid; no selection or live changes."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import time

from . import binance_data, broad_data, broad_extension, derivatives_data
from .binance_data import utc_ms
from .broad_data import CACHE, load as load_daily
from .broad_execution import evaluate
from .broad_extension import extend
from .broad_hourly import load as load_hourly
from .broad_research import DAY_MS, features, target_weights
from .cli import ROOT, RESULTS
from .trailing_stop import TrailingStop


GRID = {"schema_version": 1, "multipliers": [.5, 1, 2, 3, 4, 6],
        "portfolio_stops": [None, .01, .02, .04], "side_costs": [.0015, .003],
        "start": "2024-01-01", "end": "2026-09-26", "days": 999,
        "minimum_net_cagr_pct": 50, "maximum_drawdown_pct": 10}
PROTOCOL = ROOT / "docs/target50_protocol_2026-09-26.md"
FREEZE = ROOT / "docs/broad_candidate_freeze_2026-09-26.json"
BASELINE = RESULTS / "trailing_research.json"
CODE = ("target50_research.py", "broad_data.py", "broad_hourly.py", "broad_execution.py",
        "broad_extension.py", "broad_research.py", "binance_data.py", "derivatives_data.py",
        "trailing_stop.py", "market_state.py", "cli.py")
REPRODUCTION_METRICS = ("return_pct", "max_drawdown_pct", "fees_pct_initial", "stop_count")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("invalid " + name)
    return float(value)


class ScaledTargets:
    """Scale freshly computed factor weights, never a previously computed return."""

    def __init__(self, multiplier):
        self.multiplier = _number(multiplier, "research exposure multiplier")
        if not 0 < self.multiplier <= 6:
            raise ValueError("research exposure multiplier must be in (0, 6]")
        self.max_unscaled_gross = self.max_scaled_gross = 0.0

    def __call__(self, states, rule):
        base = target_weights(states, rule)
        gross = math.fsum(abs(_number(weight, "base target weight")) for weight in base.values())
        if gross > .5 + 1e-12:
            raise ValueError("unscaled target gross exceeds frozen 0.5 limit")
        scaled = {symbol: weight * self.multiplier for symbol, weight in base.items()}
        scaled_gross = math.fsum(abs(weight) for weight in scaled.values())
        if scaled_gross > 3 + 1e-12:
            raise ValueError("scaled target gross exceeds research 3.0 limit")
        self.max_unscaled_gross = max(self.max_unscaled_gross, gross)
        self.max_scaled_gross = max(self.max_scaled_gross, scaled_gross)
        return scaled


def annualized_return(total_return_pct, days):
    total = _number(total_return_pct, "total return")
    days = _number(days, "elapsed days")
    if total <= -100 or days <= 0:
        raise ValueError("annualization requires positive terminal equity and elapsed time")
    return 100 * math.expm1(math.log1p(total / 100) * 365 / days)


def classify(metrics, days=GRID["days"]):
    cagr = annualized_return(metrics["return_pct"], days)
    hourly = _number(metrics["max_drawdown_pct"], "hourly drawdown")
    adverse = _number(metrics["adverse_intrahour_drawdown_bound_pct"], "adverse drawdown bound")
    failures = metrics["margin_stress_failures"]
    if hourly < 0 or adverse < 0 or type(failures) is not int or failures < 0:
        raise ValueError("invalid risk metrics")
    nominal = cagr >= GRID["minimum_net_cagr_pct"] and hourly <= GRID["maximum_drawdown_pct"] and failures == 0
    return {"net_cagr_pct": cagr, "meets_nominal_target": nominal,
            "meets_target_and_adverse_bound": nominal and adverse <= GRID["maximum_drawdown_pct"]}


def verify_reproduction(metrics, expected):
    differences = {key: metrics[key] - expected[key] for key in REPRODUCTION_METRICS}
    if any(not math.isfinite(value) or abs(value) > 1e-9 for value in differences.values()):
        raise ValueError("scale-one baseline reproduction failed: " + json.dumps(differences, sort_keys=True))
    return {"passed": True, "absolute_tolerance": 1e-9, "differences": differences}


def _anchors():
    protocol_bytes = PROTOCOL.read_bytes()
    blocks = re.findall(r"```json\s*\n(.*?)\n```", protocol_bytes.decode("utf-8"), re.DOTALL)
    if len(blocks) != 1 or _digest(json.loads(blocks[0])) != _digest(GRID):
        raise ValueError("protocol must contain the exact single fixed-grid JSON schema")
    if (utc_ms(GRID["end"]) - utc_ms(GRID["start"])) / DAY_MS != GRID["days"]:
        raise ValueError("fixed-grid elapsed days mismatch")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    if baseline["freeze_sha256"] != _sha(FREEZE) or baseline["rule"] != freeze["rule"]:
        raise ValueError("baseline and fixed candidate differ")
    expected = dict(freeze["source_code_sha256"])
    for name, sha in baseline["source_code_sha256"].items():
        if name in expected and expected[name] != sha:
            raise ValueError("conflicting frozen source hashes")
        expected[name] = sha
    for name, sha in expected.items():
        if Path(name).name != name or _sha(ROOT / "src/jev_trader" / name) != sha:
            raise ValueError("frozen source changed: " + name)
    anchors = {"protocol_sha256": hashlib.sha256(protocol_bytes).hexdigest(),
               "freeze_sha256": _sha(FREEZE), "baseline_report_sha256": _sha(BASELINE),
               "code_sha256": {name: _sha(ROOT / "src/jev_trader" / name)
                               for name in sorted(set(CODE) | expected.keys())},
               "input_manifest_file_sha256": {name: _sha(CACHE / name)
                                               for name in ("cohort.json", "manifest.json", "hourly_manifest.json")}}
    return anchors, freeze, baseline


@contextmanager
def _offline_inputs():
    # Imported loaders can fetch a missing supplement. Fail rather than silently
    # acquiring data after this fixed retrospective protocol was recorded.
    modules = (binance_data, broad_data, broad_extension, derivatives_data)
    original = {module: module._read_url for module in modules}

    def reject(*args, **kwargs):
        raise ValueError("offline research requires all verified inputs in the local cache")

    try:
        for module in modules:
            module._read_url = reject
        yield
    finally:
        for module, reader in original.items():
            module._read_url = reader


def _sources(records):
    cleaned = [{key: value for key, value in row.items() if key != "path"} for row in records]
    return {"count": len(cleaned), "manifest_sha256": _digest(cleaned), "sources": cleaned}


def _summary(scenario):
    result = {key: value for key, value in scenario.items() if key != "metrics"}
    metrics = scenario["metrics"]
    if metrics is not None:
        result.update({key: metrics[key] for key in (
            "return_pct", "max_drawdown_pct", "adverse_intrahour_drawdown_bound_pct", "fees_pct_initial",
            "funding_pct_initial", "margin_stress_failures", "cash_hours", "observed_hours", "cash_time_pct",
            "stop_count", "entries", "rebalances", "traded_notional_multiple_initial", "order_changes")})
        result["stop_tick_count"] = len({row["timestamp_ms"] for row in metrics["stop_events"]})
        result["max_executed_target_gross"] = max((math.fsum(abs(weight) for weight in row["target_weights"].values())
                                                   for row in metrics["execution_audit"]), default=0.0)
    return result


def run():
    started = datetime.now(timezone.utc).isoformat()
    elapsed_start = time.perf_counter()
    anchors, freeze, baseline = _anchors()
    print("Fixed 48-scenario protocol and frozen source hashes verified; loading offline data.", flush=True)
    with _offline_inputs():
        data, daily_sources, cohort = load_daily()
        hourly, hourly_sources = load_hourly(data)
        rest_sources, overlap, _ = extend(data, hourly)
    if cohort["selected"] != freeze["cohort"]:
        raise ValueError("cohort changed from frozen candidate")
    if [row["sha256"] for row in rest_sources] != baseline["rest_source_hashes"]:
        raise ValueError("REST sources differ from reproduced baseline")
    states = features(data)
    load_seconds = time.perf_counter() - elapsed_start
    print(f"Verified data and features loaded in {load_seconds:.2f}s; starting fixed grid.", flush=True)
    scenarios, reproduction_count = [], 0
    for index, (multiplier, distance, cost) in enumerate(itertools.product(
            GRID["multipliers"], GRID["portfolio_stops"], GRID["side_costs"]), 1):
        key = f"scale{multiplier:g}_stop{'none' if distance is None else format(distance, 'g')}_cost{cost:g}"
        policy = ScaledTargets(multiplier)
        stop = TrailingStop("portfolio_pct", distance) if distance is not None else None
        start_clock = time.perf_counter()
        scenario = {"id": key, "multiplier": multiplier, "portfolio_stop": distance, "side_cost": cost,
                    "status": "completed", "error": None, "metrics": None,
                    "net_cagr_pct": None, "meets_nominal_target": False, "meets_target_and_adverse_bound": False}
        try:
            metrics = evaluate(hourly, data["fundingRate"], states, freeze["rule"],
                               GRID["start"], GRID["end"], cost, target_policy=policy, trailing=stop)
        except ValueError as exc:
            if str(exc) not in ("insolvent before decision", "insolvent hourly portfolio"):
                raise
            scenario.update({"status": "failed_insolvency", "error": str(exc)})
        else:
            scenario.update({"metrics": metrics, **classify(metrics)})
            if multiplier == 1 and distance in (None, .04):
                old_name = "none" if distance is None else "portfolio_pct_4pct"
                old_cost = "stress" if cost == .0015 else "double_stress"
                scenario["baseline_reproduction"] = verify_reproduction(
                    metrics, baseline["results"][old_name]["combined"][old_cost])
                reproduction_count += 1
        scenario.update({"elapsed_seconds": time.perf_counter() - start_clock,
                         "max_unscaled_target_gross": policy.max_unscaled_gross,
                         "max_proposed_target_gross": policy.max_scaled_gross})
        scenarios.append(scenario)
        if scenario["metrics"] is None:
            detail = scenario["status"]
        else:
            detail = (f"CAGR={scenario['net_cagr_pct']:.4f}% hourlyDD={metrics['max_drawdown_pct']:.4f}% "
                      f"adverseBound={metrics['adverse_intrahour_drawdown_bound_pct']:.4f}%")
        print(f"{index}/48 {key}: {detail}; {scenario['elapsed_seconds']:.3f}s", flush=True)
        if index == 1:
            print(f"First replay runtime {scenario['elapsed_seconds']:.3f}s; rough remaining grid estimate "
                  f"{47 * scenario['elapsed_seconds']:.1f}s, excluding final validation/output.", flush=True)
    if reproduction_count != 4:
        raise ValueError("four scale-one baseline checks were not completed")
    final_anchors, _, _ = _anchors()
    if anchors != final_anchors:
        raise ValueError("protocol, frozen code, baseline or input manifest changed during grid")
    summaries = [_summary(row) for row in scenarios]
    paired = []
    for multiplier, distance in itertools.product(GRID["multipliers"], GRID["portfolio_stops"]):
        rows = [row for row in summaries if row["multiplier"] == multiplier and row["portfolio_stop"] == distance]
        paired.append({"multiplier": multiplier, "portfolio_stop": distance,
                       "meets_nominal_target_both_costs": all(row["meets_nominal_target"] for row in rows),
                       "meets_target_and_adverse_bound_both_costs": all(row["meets_target_and_adverse_bound"] for row in rows)})
    report = {"schema_version": 1, "started_utc": started, "created_utc": datetime.now(timezone.utc).isoformat(),
              "elapsed_seconds": time.perf_counter() - elapsed_start, "data_load_seconds": load_seconds,
              "grid": GRID, "rule": freeze["rule"], "anchors_start": anchors, "anchors_end": final_anchors,
              "source_data": {"daily": _sources(daily_sources), "hourly": _sources(hourly_sources),
                              "rest": _sources(rest_sources)}, "overlap": overlap,
              "baseline_reproduction_count": reproduction_count, "scenarios": scenarios, "paired_cost_checks": paired,
              "nominal_target_count": sum(row["meets_nominal_target"] for row in summaries),
              "adverse_bound_target_count": sum(row["meets_target_and_adverse_bound"] for row in summaries),
              "failed_scenario_count": sum(row["status"] != "completed" for row in summaries),
              "selected_winner": None, "deployable": False, "live_changes": False, "jev_calls": 0,
              "limits": ["Fixed retrospective feasibility grid on previously inspected history; no independent out-of-sample or prospective validation.",
                         "Net CAGR includes modeled side costs and funding, but excludes taxes and account-specific financing or liquidation mechanics.",
                         "Exposure multipliers apply before every full replay; gross can drift after targeting and the replay does not implement exchange liquidation.",
                         "The 10% notional margin stress flag is a heuristic, not actual maintenance margin or liquidation accounting.",
                         "Adverse simultaneous intrahour mark extremes form a stress bound, not a reconstructed tradable portfolio path.",
                         "The stop is a trigger, not a guarantee of a maximum loss; gaps, costs and repeated stops can exceed it.",
                         "No grid winner is selected and the active forward simulation is unchanged."]}
    full_path = RESULTS / "target50_research.json"
    full_path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    compact = {key: value for key, value in report.items() if key not in ("scenarios", "source_data")}
    compact["source_data"] = {kind: {key: value for key, value in row.items() if key != "sources"}
                              for kind, row in report["source_data"].items()}
    compact.update({"scenarios": summaries, "full_report_sha256": _sha(full_path),
                    "full_report_path": "results/target50_research.json"})
    (ROOT / "docs/target50_research_2026-09-26.json").write_text(
        json.dumps(compact, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Fixed grid completed: nominal={report['nominal_target_count']}/48; "
          f"also adverse bound={report['adverse_bound_target_count']}/48; failures={report['failed_scenario_count']}.", flush=True)
    return compact


if __name__ == "__main__":
    run()
