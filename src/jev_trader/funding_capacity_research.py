"""Offline income-component screening, explicitly not a spot/perp portfolio replay."""

from datetime import datetime, timezone
import hashlib
import itertools
import json
import os
import re
import time

from .broad_data import CACHE, load as load_daily
from .broad_extension import extend
from .broad_hourly import load as load_hourly
from .broad_technical import feature_bundle
from .cli import ROOT, RESULTS
from .funding_capacity import evaluate
from .target50_research import _offline_inputs


CONFIG = {"schema_version": 1, "rules": ["top5_30", "top5_persistent", "top1_30"],
          "notional_ratios": [.5, 1.0], "periods": {"development": ["2022-01-01", "2024-01-01"],
          "combined": ["2024-01-01", "2026-09-26"]}, "execution_delay_hours": 1,
          "weekly_rebalance_day": 0, "fees": 0, "goal_target_cagr_pct": 50,
          "portfolio_drawdown_validated": False}
PROTOCOL = ROOT / "docs/funding_capacity_protocol_2026-09-26.md"
INPUTS = RESULTS / "funding_capacity_inputs.json"
CODE = ("funding_capacity.py", "funding_capacity_research.py", "broad_technical.py", "broad_prediction.py",
        "broad_research.py", "broad_data.py", "broad_hourly.py", "broad_extension.py", "binance_data.py",
        "derivatives_data.py", "market_state.py", "strategies.py", "statistics.py", "target50_research.py",
        "broad_execution.py", "trailing_stop.py", "cli.py")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def anchors():
    blocks = re.findall(r"```json\s*\n(.*?)\n```", PROTOCOL.read_text(encoding="utf-8"), re.DOTALL)
    if len(blocks) != 1 or json.loads(blocks[0]) != CONFIG:
        raise ValueError("funding capacity protocol differs from fixed configuration")
    freeze_path = ROOT / "docs/broad_candidate_freeze_2026-09-26.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    for name, expected in freeze["source_code_sha256"].items():
        if sha(ROOT / "src/jev_trader" / name) != expected:
            raise ValueError("frozen source changed: " + name)
    return {"protocol_sha256": sha(PROTOCOL), "freeze_sha256": sha(freeze_path),
            "code_sha256": {name: sha(ROOT / "src/jev_trader" / name) for name in CODE},
            "lifecycle_sha256": sha(ROOT / "docs/contract_lifecycle_sources_2026-09-26.json"),
            "manifest_sha256": {name: sha(CACHE / name) for name in ("cohort.json", "manifest.json", "hourly_manifest.json")}}


def compact(value):
    if isinstance(value, dict):
        return {k: compact(v) for k, v in value.items() if k not in ("weekly_audit", "daily_index")}
    if isinstance(value, list):
        return [compact(v) for v in value]
    return value


def run():
    lock = RESULTS / "funding_capacity_research.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(descriptor)
    try:
        started = time.perf_counter()
        frozen = anchors()
        print("Fixed funding-income-only protocol; verifying offline inputs.", flush=True)
        with _offline_inputs():
            data, daily_sources, cohort = load_daily()
            hourly, hourly_sources = load_hourly(data)
            rest_sources, overlap, _ = extend(data, hourly)
        states, fields, quality = feature_bundle(data)
        if len(fields) != 60:
            raise ValueError("expected full daily bundle")
        expected_cohort = json.loads((ROOT / "docs/broad_candidate_freeze_2026-09-26.json").read_text(encoding="utf-8"))["cohort"]
        if cohort["selected"] != expected_cohort:
            raise ValueError("historical cohort changed")
        state_hash = hashlib.sha256()
        for symbol, rows in sorted(states.items()):
            for cutoff, row in sorted(rows.items()):
                state_hash.update(canonical({"symbol": symbol, "cutoff_ms": cutoff, "state": row})+b"\n")
        funding_hash = hashlib.sha256()
        for symbol, rows in sorted(data["fundingRate"].items()):
            for row in rows:
                funding_hash.update(canonical({"symbol": symbol, **row.__dict__})+b"\n")
        sources = {label: {"count": len(rows), "manifest_sha256": hashlib.sha256(canonical([
                       {k: v for k, v in row.items() if k != "path"} for row in rows])).hexdigest()}
                   for label, rows in (("daily", daily_sources), ("hourly", hourly_sources), ("rest", rest_sources))}
        lifecycle = json.loads((ROOT / "docs/contract_lifecycle_sources_2026-09-26.json").read_text(encoding="utf-8"))
        inputs = {"anchors": frozen, "config": CONFIG, "cohort": expected_cohort, "fields": fields,
                  "feature_quality": quality, "state_sha256": state_hash.hexdigest(),
                  "funding_events_sha256": funding_hash.hexdigest(), "sources": sources, "overlap": overlap,
                  "funding_event_counts": {s: len(rows) for s, rows in data["fundingRate"].items()},
                  "observed_interval_hours": sorted({r.interval_hours for rows in data["fundingRate"].values() for r in rows})}
        if INPUTS.exists() and json.loads(INPUTS.read_text(encoding="utf-8")) != json.loads(json.dumps(inputs)):
            raise ValueError("fixed funding screen inputs changed")
        if not INPUTS.exists():
            INPUTS.write_text(json.dumps(inputs, indent=2, sort_keys=True)+"\n", encoding="utf-8")
        if anchors() != frozen:
            raise ValueError("sources changed during preparation")
        scenarios = []
        for period, rule, ratio in itertools.product(CONFIG["periods"], CONFIG["rules"], CONFIG["notional_ratios"]):
            metrics = evaluate(data["fundingRate"], states, rule, *CONFIG["periods"][period], ratio, lifecycle["events"])
            row = {"period": period, "rule": rule, "notional_ratio": ratio, "metrics": metrics,
                   "income_component_reaches_50pct": metrics["funding_index_cagr_pct"] >= 50,
                   "portfolio_goal_validated": False}
            scenarios.append(row)
            print(period, rule, ratio, {k: metrics[k] for k in ("funding_index_cagr_pct", "funding_index_return_pct")}, flush=True)
        if anchors() != frozen:
            raise ValueError("sources or protocol changed during income diagnostic")
        report = {"created_utc": datetime.now(timezone.utc).isoformat(), "elapsed_seconds": time.perf_counter()-started,
                  "inputs": inputs, "inputs_file_sha256": sha(INPUTS), "scenarios": scenarios,
                  "goal_achieved": False, "deployable": False, "jev_calls": 0, "orders_sent": 0,
                  "new_market_downloads": 0, "selected_winner": None,
                  "limits": ["Funding-income index only; not net trading P&L or portfolio risk.",
                             "Assumes free constant notional resets, ideal price hedge and unlimited margin.",
                             "No spot/basis data, trading costs, financing, taxes, slippage or liquidation.",
                             "Ratio one leaves no separate cash reserve for futures collateral.",
                             "Not a mathematical upper bound on all spot/perp strategy returns.",
                             "Known historical periods and current announcement pages do not establish prospective evidence."]}
        full = RESULTS / "funding_capacity_research.json"
        full.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+"\n", encoding="utf-8")
        summary = compact(report)
        summary["full_report_sha256"] = sha(full)
        (ROOT / "docs/funding_capacity_research_2026-09-26.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True, allow_nan=False)+"\n", encoding="utf-8")
        print("Completed 12 income-component screens; portfolio goal remains unvalidated.", flush=True)
        return summary
    finally:
        lock.unlink()


if __name__ == "__main__":
    run()
