"""Frozen basis convergence comparison, offline and without a trading route."""

import argparse
from datetime import datetime, timezone
import hashlib
import itertools
import json
import os
import platform
import re
import subprocess
import time

from .basis_data import load
from .basis_execution import evaluate
from .basis_features import build_states, canonical
from .basis_policy import BasisPolicy
from .binance_data import HOUR_MS
from .cli import ROOT, RESULTS

CONFIG = {
    "schema_version": 1,
    "periods": {"development": ["2023-04-01T00:00:00+00:00", "2024-01-01T00:00:00+00:00"],
                "later": ["2024-01-01T00:00:00+00:00", "2026-08-31T23:00:00+00:00"]},
    "references": ["fundamental_r0", "median720"], "max_hold_hours": [24, 168],
    "spot_fractions": [.5, .75], "portfolio_trailing": [None, .04],
    "costs": {"base": [.0012, .0007], "stress": [.0024, .0014]},
    "basis_history_hours": 720, "funding_publication_lag_hours": 1,
    "completed_close_execution_delay_hours": 1, "minimum_quote_volume24": 10_000_000,
    "margin_volatility_multiple": 3, "preventive_margin_ratio": .20, "stress_margin_ratio": .10,
    "target_net_cagr_pct": 50, "maximum_drawdown_pct": 10,
    "historical_point_in_time_verified": False,
}
PROTOCOL = ROOT / "docs/basis_protocol_2026-09-26.md"
INPUTS = RESULTS / "basis_inputs.json"
REPORT = RESULTS / "basis_research.json"
CODE = ("basis_data.py", "basis_features.py", "basis_policy.py", "basis_execution.py", "basis_research.py",
        "binance_data.py", "derivatives_data.py", "market_state.py", "strategies.py", "cli.py")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timestamp(value):
    date = datetime.fromisoformat(value)
    if date.utcoffset() is None or date.utcoffset().total_seconds() != 0:
        raise ValueError("explicit UTC dates required")
    return int(date.timestamp()*1000)


def write_new_or_equal(path, value):
    payload = canonical(value)+b"\n"
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError("refusing to replace different frozen artifact: " + str(path))
    else:
        with path.open("xb") as handle:
            handle.write(payload)


def anchors():
    blocks = re.findall(r"```json\s*\n(.*?)\n```", PROTOCOL.read_text(encoding="utf-8"), re.DOTALL)
    if len(blocks) != 1 or json.loads(blocks[0]) != CONFIG:
        raise ValueError("basis protocol configuration differs from code")
    files = [PROTOCOL, ROOT/"docs/basis_sources_2026-09-26.md", ROOT/"docs/basis_data_inventory_2026-09-26.md",
             ROOT/"pyproject.toml", ROOT/"requirements-tree.lock"]
    files += [ROOT/"src/jev_trader"/name for name in CODE]
    files += sorted((ROOT/"tests").glob("test_basis_*.py"))
    return {"files_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in files},
            "python": platform.python_version(), "implementation": platform.python_implementation()}


def verify_calendar(market):
    """Check raw payment/valuation completeness, never select profitable paths."""
    audit = {}
    for symbol in sorted(market["spot"]):
        events = market["funding"][symbol]
        slots = [e.timestamp_ms//HOUR_MS for e in events]
        if (not slots or any(s % 8 for s in slots) or any(b-a != 8 for a, b in zip(slots, slots[1:]))
                or any(e.timestamp_ms % HOUR_MS >= 60_000 or e.interval_hours != 8 for e in events)):
            raise ValueError("incomplete or unsupported funding calendar " + symbol)
        for period, dates in CONFIG["periods"].items():
            start, end = map(timestamp, dates)
            for kind in ("spot", "futures", "mark"):
                if any(t not in market[kind][symbol] for t in range(start, end+1, HOUR_MS)):
                    raise ValueError("incomplete evaluation prices " + symbol + " " + kind)
            expected = set(range(((start//HOUR_MS+7)//8)*8, end//HOUR_MS+1, 8))
            if not expected.issubset(slots):
                raise ValueError("missing evaluation funding " + symbol + " " + period)
        audit[symbol] = {"events": len(events), "first_slot": slots[0], "last_slot": slots[-1],
                         "gap_hours": 8, "maximum_timestamp_offset_ms": max(e.timestamp_ms % HOUR_MS for e in events)}
    return audit


def prepare():
    frozen = anchors()
    market, sources = load()
    calendar = verify_calendar(market)
    print("Offline basis archives verified; building both technical bundles.", flush=True)
    states, features = build_states(market)
    inputs = {"anchors": frozen, "config": CONFIG, "data": sources, "features": features, "calendar": calendar}
    if anchors() != frozen:
        raise ValueError("basis files changed during preparation")
    write_new_or_equal(INPUTS, inputs)
    return market, states, inputs


def compact_scenario(row):
    result = {k: v for k, v in row.items() if k != "metrics"}
    if row["metrics"] is None:
        result["metrics"] = None
        return result
    large = {"hourly_equity", "daily_equity", "wallet_snapshots", "trade_events", "transfer_events",
             "funding_events", "stop_events", "action_decisions"}
    result["metrics"] = {k: v for k, v in row["metrics"].items() if k not in large}
    result["event_counts"] = {k: len(row["metrics"][k]) for k in sorted(large)}
    result["series_sha256"] = {k: hashlib.sha256(canonical(row["metrics"][k])).hexdigest() for k in sorted(large)}
    return result


def run(prepare_only=False):
    RESULTS.mkdir(exist_ok=True)
    lock = RESULTS/"basis_research.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    try:
        started = time.perf_counter()
        if not prepare_only and not INPUTS.exists():
            raise ValueError("prepare and freeze basis inputs before replay")
        if not prepare_only and REPORT.exists():
            raise ValueError("basis report already exists; preserve original experiment")
        market, states, inputs = prepare()
        print("Frozen states:", sum(map(len, states.values())), flush=True)
        if prepare_only:
            return inputs
        scenarios = []
        for reference, hours, fraction, cost_name, trailing, period in itertools.product(
                CONFIG["references"], CONFIG["max_hold_hours"], CONFIG["spot_fractions"], CONFIG["costs"],
                CONFIG["portfolio_trailing"], CONFIG["periods"]):
            cost_s, cost_f = CONFIG["costs"][cost_name]
            start, end = map(timestamp, CONFIG["periods"][period])
            policy = BasisPolicy(reference, cost_s, cost_f, fraction, hours)
            row = {"reference": reference, "max_hold_hours": hours, "spot_fraction": fraction,
                   "cost": cost_name, "portfolio_trailing": trailing, "period": period}
            try:
                metrics = evaluate(market, states, policy, start, end, cost_s, cost_f, fraction, hours, trailing)
            except ValueError as error:
                if not str(error).startswith(("unverified paired execution liquidity", "insolvent", "negative cash",
                                              "nonpositive basis portfolio equity", "nonpositive realized bucket equity")):
                    raise
                row.update(status="invalid_execution", error=str(error), metrics=None,
                           meets_nominal_target=False, meets_target_and_adverse_bound=False)
            else:
                years = (end-start)/(365.25*24*HOUR_MS)
                cagr = 100*((1+metrics["return_pct"]/100)**(1/years)-1)
                nominal = cagr >= 50 and metrics["max_drawdown_pct"] <= 10 and metrics["margin_stress_failures"] == 0
                row.update(status="complete", metrics=metrics, net_cagr_pct=cagr,
                           meets_nominal_target=nominal,
                           meets_target_and_adverse_bound=nominal and metrics["adverse_intrahour_drawdown_bound_pct"] <= 10)
            scenarios.append(row)
            print({k: row.get(k) for k in ("reference", "max_hold_hours", "spot_fraction", "cost",
                  "portfolio_trailing", "period", "status", "net_cagr_pct")}, flush=True)
        if anchors() != inputs["anchors"]:
            raise ValueError("basis frozen sources changed during replay")
        report = {"created_utc": datetime.now(timezone.utc).isoformat(), "elapsed_seconds": time.perf_counter()-started,
                  "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                  "inputs": inputs, "inputs_file_sha256": sha(INPUTS), "scenarios": scenarios,
                  "goal_achieved": False, "deployable": False, "selected_winner": None,
                  "jev_calls": 0, "orders_sent": 0, "new_market_downloads": 0,
                  "limits": ["Reused history is not untouched confirmation.",
                             "Paired hourly trade prices are not synchronized executable bid/ask quotes.",
                             "Historical publication times, margin tiers and account fees are unverified.",
                             "Funding publication lag and fee/slippage values are assumptions.",
                             "Equal-quantity hedge differs from the theoretical lambda hedge.",
                             "Intrahour drawdown bound permits nonsimultaneous extremes and is conservative.",
                             "Trailing and preventive margin checks do not guarantee maximum loss.",
                             "Market technical context contains fields not used as directional entry votes."]}
        write_new_or_equal(REPORT, report)
        summary = {k: v for k, v in report.items() if k != "scenarios"}
        summary.update(full_report_sha256=sha(REPORT), scenarios=[compact_scenario(r) for r in scenarios])
        write_new_or_equal(ROOT/"docs/basis_research_2026-09-26.json", summary)
        print("Completed", len(scenarios), "scenarios; nominal matches:",
              sum(r["meets_nominal_target"] for r in scenarios), flush=True)
        return summary
    finally:
        lock.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    run(parser.parse_args().prepare_only)
