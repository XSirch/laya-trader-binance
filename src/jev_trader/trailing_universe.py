"""Fixed-rule leave-one-asset-out execution diagnostics."""

import hashlib
import json
from datetime import datetime, timezone

from .broad_data import load as load_daily
from .broad_execution import evaluate
from .broad_extension import extend
from .broad_hourly import load as load_hourly
from .broad_research import features, target_weights
from .cli import ROOT, RESULTS
from .trailing_stop import TrailingStop


def exclusion_policy(excluded):
    def policy(states, rule):
        return target_weights({s: v for s, v in states.items() if s != excluded}, rule)
    return policy


def compact(value):
    if isinstance(value, dict):
        return {k: compact(v) for k, v in value.items()
                if k not in ("daily_equity", "execution_audit", "stop_events")}
    if isinstance(value, list):
        return [compact(v) for v in value]
    return value


def run():
    freeze_path = ROOT / "docs/trailing_candidate_freeze_2026-09-26.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    for name, expected in freeze["source_code_sha256"].items():
        if hashlib.sha256((ROOT / "src/jev_trader" / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"frozen code changed: {name}")
    data, _, _ = load_daily()
    hourly, _ = load_hourly(data)
    extend(data, hourly)
    states = features(data)
    periods = {"combined": ("2024-01-01", "2026-09-26"),
               "recent": ("2026-08-01", "2026-09-26")}
    results = {}
    for excluded in [None] + sorted(states):
        key = excluded or "full_universe"
        results[key] = {}
        for trailing in (False, True):
            mode = "trailing4" if trailing else "none"
            results[key][mode] = {}
            for period, dates in periods.items():
                try:
                    row = evaluate(hourly, data["fundingRate"], states, freeze["base_rule"],
                                   *dates, .0015, target_policy=exclusion_policy(excluded),
                                   trailing=TrailingStop("portfolio_pct", .04) if trailing else None)
                except ValueError as exc:
                    if not str(exc).startswith("unresolved held price"):
                        raise
                    row = {"status": "unresolved", "error": str(exc)}
                else:
                    row["status"] = "complete"
                    if excluded and any(excluded in a["target_weights"] for a in row["execution_audit"]):
                        raise AssertionError("excluded asset traded")
                results[key][mode][period] = row
            row = results[key][mode]["combined"]
            print(key, mode, row.get("return_pct", row.get("error")), flush=True)
    prior = json.loads((RESULTS / "trailing_research.json").read_text(encoding="utf-8"))
    for mode, original in (("none", "none"), ("trailing4", "portfolio_pct_4pct")):
        for period, original_period in (("combined", "combined"), ("recent", "2026_aug_sep")):
            for metric in ("return_pct", "max_drawdown_pct", "fees_pct_initial"):
                if abs(results["full_universe"][mode][period][metric] -
                       prior["results"][original][original_period]["stress"][metric]) > 1e-10:
                    raise AssertionError("full universe no longer reproduces frozen result")
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "results": results,
              "freeze_sha256": hashlib.sha256(freeze_path.read_bytes()).hexdigest(),
              "source_sha256": hashlib.sha256((ROOT / "src/jev_trader/trailing_universe.py").read_bytes()).hexdigest(),
              "protocol_sha256": hashlib.sha256((ROOT / "docs/trailing_universe_protocol_2026-09-26.md").read_bytes()).hexdigest(),
              "deployable": False, "full_universe_reproduction_verified": True,
              "limits": ["Previously inspected retrospective history; no new asset selection authorized.",
                         "BTC removal disables the carry hedge sleeve under existing rules.",
                         "Feature history remains unchanged; only tradable universe is filtered.",
                         "Missing held prices remain unresolved; no settlement proxy."]}
    path = RESULTS / "trailing_universe.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = compact(report)
    summary["full_report_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (ROOT / "docs/trailing_universe_2026-09-26.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    run()
