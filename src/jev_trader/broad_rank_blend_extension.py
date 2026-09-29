"""Frozen chronological extension of the existing rank_blend futures rule."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from . import broad_extension
from .binance_data import Bar, utc_ms
from .broad_data import load as load_daily
from .broad_hourly import load as load_hourly
from .broad_research import evaluate as evaluate_portfolio, features
from .broad_trade_reanalysis import RECONCILE_FIELDS, _simulate_episodes, _summarize
from .cli import ROOT
from .target50_research import _offline_inputs

START, END = "2026-08-01", "2026-09-26"
RULE = "rank_blend"
COSTS = {"base": 0.001, "prior_stress": 0.0015, "doubled": 0.002, "severe": 0.003}
PROTOCOL = ROOT / "research/docs/CICLO11_RANK_BLEND_EXTENSION_PROTOCOLO.md"
OUTPUT_DIR = ROOT / "research/results/cycle11_rank_blend_extension_2026-09-28"


def _source_hashes() -> dict[str, str]:
    paths = {
        "protocol": PROTOCOL,
        "script": Path(__file__),
        "factor_code": ROOT / "src/jev_trader/broad_research.py",
        "extension_code": ROOT / "src/jev_trader/broad_extension.py",
        "episode_accounting": ROOT / "src/jev_trader/broad_trade_reanalysis.py",
    }
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}


def _terminal_marker(data: dict, hourly: dict) -> None:
    """Provide an execution-only 00:00 terminal mark, excluded from signals."""
    timestamp = utc_ms(END)
    for kind in ("klines", "markPriceKlines"):
        for symbol, rows in data[kind].items():
            hourly_bar = hourly[kind].get(symbol, {}).get(timestamp)
            if hourly_bar is None:
                continue
            if rows and rows[-1].open_ms >= timestamp:
                raise ValueError(f"unexpected terminal daily candle: {symbol} {kind}")
            rows.append(Bar(timestamp, hourly_bar.open, hourly_bar.high, hourly_bar.low, hourly_bar.close,
                            hourly_bar.volume, hourly_bar.quote_volume, hourly_bar.trades,
                            hourly_bar.taker_buy_base))


def _summarize_with_gates(episodes: list[dict], portfolio: dict) -> dict:
    metrics = _summarize(episodes)
    active_weeks = sorted({
        datetime.fromtimestamp(row["entry_ms"] / 1000, timezone.utc).strftime("%G-W%V")
        for row in episodes
    })
    values = [row["net_return_pct_on_entry_notional"] for row in episodes]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    profit_factor = sum(wins) / abs(sum(losses)) if losses else None
    metrics.update({
        "active_weeks": len(active_weeks),
        "active_week_ids": active_weeks,
        "profit_factor": profit_factor,
        "portfolio_replay": portfolio,
    })
    return metrics


def run() -> dict:
    if OUTPUT_DIR.exists():
        raise FileExistsError(f"refusing to overwrite prior result: {OUTPUT_DIR}")
    if not PROTOCOL.is_file():
        raise FileNotFoundError(PROTOCOL)

    with _offline_inputs():
        data, daily_manifest, cohort = load_daily()
        hourly, hourly_sources = load_hourly(data)
        extension_sources, overlap, exact_marks = broad_extension.extend(data, hourly)

    _terminal_marker(data, hourly)
    states = features(data)
    period_results: dict[str, dict] = {}
    ledger: list[dict] = []
    for cost_name, side_cost in COSTS.items():
        episodes, episode_portfolio = _simulate_episodes(data, states, RULE, START, END, side_cost)
        portfolio = evaluate_portfolio(data, states, RULE, START, END, side_cost)
        for ours, theirs in RECONCILE_FIELDS.items():
            difference = abs(episode_portfolio[ours] - portfolio[theirs])
            if difference > 1e-8:
                raise ValueError(f"accounting did not reconcile for {cost_name}/{ours}: {difference}")
        metrics = _summarize_with_gates(episodes, episode_portfolio)
        period_results[cost_name] = metrics
        for row in episodes:
            ledger.append({
                "cost_case": cost_name,
                "symbol": row["symbol"],
                "direction": row["direction"],
                "entry_ms": row["entry_ms"],
                "exit_ms": row["exit_ms"],
                "entry_notional": row["entry_notional"],
                "hold_days": row["hold_days"],
                "price_pnl": row["price_pnl"],
                "funding_pnl": row["funding_pnl"],
                "fees": row["fees"],
                "net_pnl": row["net_pnl"],
                "net_return_pct_on_entry_notional": row["net_return_pct_on_entry_notional"],
                "unresolved_proxy_exit": row["unresolved_proxy_exit"],
            })

    source_manifest = {
        "daily": daily_manifest,
        "hourly": hourly_sources,
        "extension": [{key: value for key, value in row.items() if key != "path"}
                      for row in extension_sources],
        "overlap": overlap,
        "exact_funding_marks": len(exact_marks),
    }
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "rule": RULE,
        "market": "Binance USD-M perpetual futures",
        "window_utc": {"start_inclusive": START, "end_terminal_inclusive": END},
        "costs_per_side": COSTS,
        "cohort": cohort["selected"],
        "source_hashes": _source_hashes(),
        "source_manifest_sha256": hashlib.sha256(
            json.dumps(source_manifest, sort_keys=True).encode("utf-8")).hexdigest(),
        "source_counts": {
            "daily_manifest_entries": len(daily_manifest),
            "hourly_archives_and_supplements": len(hourly_sources),
            "extension_rest_snapshots": len(extension_sources),
            "extension_overlap": overlap,
        },
        "accounting_reconciled": True,
        "results": period_results,
        "limits": [
            "Exploratory chronological extension; this window was previously examined for another rule.",
            "The candidate was selected after reviewing earlier historical results, so this is not an untouched holdout.",
            "Daily open episode accounting and simulated fees, slippage, and funding are not executable fills.",
            "EV is net return on initial gross episode notional; portfolio return and drawdown use portfolio equity.",
            "An adverse listing-exit proxy is reported and is not a verified fill.",
            "No strategy or model training was changed in this cycle; no real orders were sent.",
        ],
    }

    OUTPUT_DIR.mkdir(parents=True)
    json_path = OUTPUT_DIR / "research.json"
    csv_path = OUTPUT_DIR / "trades.csv"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ledger[0]) if ledger else [
            "cost_case", "symbol", "direction", "entry_ms", "exit_ms", "entry_notional",
            "hold_days", "price_pnl", "funding_pnl", "fees", "net_pnl",
            "net_return_pct_on_entry_notional", "unresolved_proxy_exit",
        ])
        writer.writeheader()
        writer.writerows(ledger)
    report["output_hashes"] = {
        "research.json": hashlib.sha256(json_path.read_bytes()).hexdigest(),
        "trades.csv": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return report


if __name__ == "__main__":
    run()
