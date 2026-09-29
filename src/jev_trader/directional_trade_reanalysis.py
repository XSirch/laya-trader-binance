"""Re-aggregate existing daily futures strategy episodes into per-trade metrics."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import directional
from .binance_data import HOUR_MS, utc_ms
from .derivatives_data import load
from .cli import RESULTS

ROOT = Path(__file__).resolve().parents[2]
SOURCE_REPORT = RESULTS / "directional_research.json"
OUTPUT = RESULTS / "directional_trade_reanalysis_20260927.json"
COSTS = {"base": 0.001, "stress": 0.0015}
PERIODS = {"calibration": directional.PERIODS["calibration"],
           "validation": directional.PERIODS["validation"],
           "confirmation": directional.PERIODS["confirmation"],
           "combined": directional.PERIODS["combined"]}


def _simulate_episodes(derivatives, targets, start: str, end: str,
                       side_cost: float) -> tuple[list[dict], dict]:
    start_ms, end_ms = utc_ms(start), utc_ms(end)
    symbols = sorted(targets)
    klines = derivatives["klines"]
    marks = derivatives["markPriceKlines"]
    funding_rates = derivatives["fundingRate"]
    maps = {s: {bar.open_ms: bar for bar in klines[s]} for s in symbols}
    mark_maps = {s: {bar.open_ms: bar for bar in marks[s]} for s in symbols}
    funding = {s: {row.timestamp_ms // HOUR_MS * HOUR_MS: row for row in funding_rates[s]}
               for s in symbols}
    timeline = range(start_ms, end_ms + 1, HOUR_MS)
    equity = {s: 1.0 for s in symbols}
    quantity = {s: 0.0 for s in symbols}
    previous = {s: maps[s][start_ms].open for s in symbols}
    active: dict[str, dict | None] = {s: None for s in symbols}
    episodes = []
    total_fees = total_funding = 0.0
    path = [(start_ms, 1.0)]

    def close_episode(symbol: str, timestamp: int, price: float) -> None:
        row = active[symbol]
        if row is None:
            return
        row["exit_ms"] = timestamp
        row["exit_price"] = price
        row["net_pnl_per_sleeve"] = row["net_pnl"]
        row["net_return_pct_on_entry_notional"] = 100 * row["net_pnl"] / row["entry_notional"]
        row["hold_hours"] = (timestamp - row["entry_ms"]) // HOUR_MS
        episodes.append(row)
        active[symbol] = None

    for timestamp in timeline:
        for symbol in symbols:
            bar = maps[symbol][timestamp]
            mark = mark_maps[symbol][timestamp]
            current_qty = quantity[symbol]

            mark_pnl = current_qty * (bar.open - previous[symbol])
            equity[symbol] += mark_pnl
            if active[symbol] is not None:
                active[symbol]["net_pnl"] += mark_pnl
            previous[symbol] = bar.open

            if current_qty and timestamp in funding[symbol] and funding[symbol][timestamp].timestamp_ms < end_ms:
                payment = -current_qty * mark.open * funding[symbol][timestamp].rate
                equity[symbol] += payment
                total_funding += payment / len(symbols)
                if active[symbol] is not None:
                    active[symbol]["net_pnl"] += payment

            if timestamp not in targets[symbol] and timestamp != end_ms:
                continue
            target = targets[symbol].get(timestamp, 0.0) if timestamp < end_ms else 0.0
            desired_qty = target * equity[symbol] / bar.open
            if current_qty == 0 and desired_qty != 0:
                fee = abs(desired_qty) * bar.open * side_cost
                active[symbol] = {
                    "symbol": symbol, "direction": 1 if desired_qty > 0 else -1,
                    "entry_ms": timestamp, "entry_price": bar.open,
                    "entry_notional": abs(desired_qty) * bar.open,
                    "net_pnl": -fee,
                }
            elif current_qty != 0 and desired_qty == 0:
                fee = abs(current_qty) * bar.open * side_cost
                if active[symbol] is not None:
                    active[symbol]["net_pnl"] -= fee
                close_episode(symbol, timestamp, bar.open)
            elif current_qty * desired_qty < 0:
                close_fee = abs(current_qty) * bar.open * side_cost
                open_fee = abs(desired_qty) * bar.open * side_cost
                if active[symbol] is not None:
                    active[symbol]["net_pnl"] -= close_fee
                close_episode(symbol, timestamp, bar.open)
                active[symbol] = {
                    "symbol": symbol, "direction": 1 if desired_qty > 0 else -1,
                    "entry_ms": timestamp, "entry_price": bar.open,
                    "entry_notional": abs(desired_qty) * bar.open,
                    "net_pnl": -open_fee,
                }
                fee = close_fee + open_fee
            elif current_qty != 0 and desired_qty != 0:
                fee = abs(desired_qty - current_qty) * bar.open * side_cost
                if active[symbol] is not None:
                    active[symbol]["net_pnl"] -= fee
            else:
                fee = 0.0
            equity[symbol] -= fee
            total_fees += fee / len(symbols)
            quantity[symbol] = desired_qty
            if equity[symbol] <= 0:
                raise ValueError(f"insolvent futures sleeve: {symbol} at {timestamp}")
        path.append((timestamp, sum(equity.values()) / len(symbols)))

    for symbol in symbols:
        if active[symbol] is not None:
            close_episode(symbol, end_ms, maps[symbol][end_ms].open)
    peak = 1.0
    max_drawdown = 0.0
    for _, value in path:
        peak = max(peak, value)
        max_drawdown = max(max_drawdown, 100 * (1 - value / peak))
    portfolio = {
        "return_pct": 100 * (sum(equity.values()) / len(symbols) - 1),
        "max_drawdown_pct_hourly": max_drawdown,
        "fees_pct_initial": 100 * total_fees,
        "funding_pct_initial": 100 * total_funding,
    }
    return episodes, portfolio


def _summarize(episodes: list[dict]) -> dict:
    values = [row["net_return_pct_on_entry_notional"] for row in episodes]
    wins = [x for x in values if x > 0]
    losses = [x for x in values if x < 0]
    win_rate = len(wins) / len(values) if values else None
    mean_win = math.fsum(wins) / len(wins) if wins else None
    mean_loss = math.fsum(losses) / len(losses) if losses else None
    payoff = mean_win / abs(mean_loss) if mean_win is not None and mean_loss is not None else None
    return {
        "episodes": len(values), "wins": len(wins), "losses": len(losses),
        "win_rate_pct": None if win_rate is None else 100 * win_rate,
        "mean_win_pct": mean_win, "mean_loss_pct": mean_loss,
        "net_payoff_ratio": payoff,
        "ev_net_pct_per_trade_on_entry_notional": None if not values else math.fsum(values) / len(values),
        "median_hold_hours": (sorted(row["hold_hours"] for row in episodes)[len(episodes) // 2]
                              if episodes else None),
        "episodes_by_symbol": dict(sorted((s, sum(row["symbol"] == s for row in episodes))
                                           for s in sorted({row["symbol"] for row in episodes}))),
    }


def run() -> dict:
    derivatives, manifest = load()
    signals = directional.signals(derivatives["klines"])
    prior = json.loads(SOURCE_REPORT.read_text(encoding="utf-8"))
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "per-trade reaggregation of the pre-existing futures rules; no signal or parameter changes",
        "costs_per_side": COSTS,
        "metric_basis": "net realized episode PnL divided by initial episode notional",
        "prior_report_sha256": hashlib.sha256(SOURCE_REPORT.read_bytes()).hexdigest(),
        "analysis_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "input_manifest_entries": len(manifest),
        "selected_on_2024_in_prior_research": prior.get("selected_on_2024"),
        "periods": {},
        "limits": [
            "historical data were already inspected and are not a clean future holdout",
            "an episode groups same-direction daily rebalances until flat or sign reversal",
            "cash PnL is divided by entry gross notional; episodes can overlap across assets",
            "hourly-open accounting and assumed costs do not prove executable fills",
        ],
    }
    for period, (start, end) in PERIODS.items():
        report["periods"][period] = {}
        for strategy_name, targets in signals.items():
            by_cost = {}
            ledger_by_cost = {}
            for cost_label, side_cost in COSTS.items():
                episodes, portfolio = _simulate_episodes(
                    derivatives, targets, start, end, side_cost)
                metrics = _summarize(episodes)
                metrics["portfolio_replay"] = portfolio
                by_cost[cost_label] = metrics
                ledger_by_cost[cost_label] = episodes
            report["periods"][period][strategy_name] = {
                "by_cost": by_cost, "episode_ledger_by_cost": ledger_by_cost,
            }
    OUTPUT.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n",
                      encoding="utf-8")
    for name in signals:
        m = report["periods"]["combined"][name]["by_cost"]
        print(name, json.dumps({cost: {k: v for k, v in metric.items() if k != "portfolio_replay"}
                                for cost, metric in m.items()}, sort_keys=True))
    return report


if __name__ == "__main__":
    run()
