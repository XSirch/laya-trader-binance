"""Re-aggregate the frozen daily RSI2 ledger into the user's per-trade metrics."""

from __future__ import annotations

import hashlib
import json
import math
import csv
from pathlib import Path
from datetime import datetime, timezone

from .binance_data import load_cached_range, utc_ms
from .cli import DATA_ROOT, FIRST, LAST, SYMBOLS
from .extended import PERIODS, daily_bars
from .strategies import Candidate, make_signals

ROOT = Path(__file__).resolve().parents[2]
SOURCE_REPORT = ROOT / "results" / "extended_research.json"
OUTPUT = ROOT / "results" / "daily_rsi2_trade_reanalysis_20260927.json"
OUTPUT_CSV = ROOT / "results" / "daily_rsi2_trade_ledger_20260927.csv"
BASE_COST = 0.0015
STRESS_COST = 0.0025
RULE = Candidate("daily_rsi2", "rsi", 2, 10)
PER_TRADE_WINDOWS = {
    "development": PERIODS["development"],
    "calibration": PERIODS["calibration"],
    "validation": PERIODS["validation"],
    "confirmation": PERIODS["confirmation"],
    "combined": ("2025-01-01", "2026-08-01"),
}


def _trades_for_symbol(bars, signals, start_ms: int, end_ms: int, side_cost: float,
                       symbol: str) -> list[dict]:
    trades = []
    active = False
    factor = 1.0
    entry_ms = entry_price = None
    last_return_ms = start_ms
    for index, bar in enumerate(bars[:-1]):
        if not start_ms <= bar.open_ms < end_ms:
            continue
        desired = signals[index - 1]
        next_bar = bars[index + 1]
        if desired and not active:
            active = True
            factor = 1.0 - side_cost
            entry_ms = bar.open_ms
            entry_price = bar.open
        if active and desired:
            factor *= next_bar.open / bar.open
            last_return_ms = next_bar.open_ms
        elif active and not desired:
            factor *= 1.0 - side_cost
            trades.append({"symbol": symbol, "entry_ms": entry_ms, "exit_ms": bar.open_ms,
                           "entry_price": entry_price, "exit_price": bar.open,
                           "hold_days": (bar.open_ms - entry_ms) // 86_400_000,
                           "net_return_pct": 100 * (factor - 1.0)})
            active, factor, entry_ms, entry_price = False, 1.0, None, None
    if active:
        final_bar = next(bar for bar in bars if bar.open_ms == last_return_ms)
        factor *= 1.0 - side_cost
        trades.append({"symbol": symbol, "entry_ms": entry_ms, "exit_ms": end_ms,
                       "entry_price": entry_price, "exit_price": final_bar.open,
                       "hold_days": (end_ms - entry_ms) // 86_400_000,
                       "net_return_pct": 100 * (factor - 1.0)})
    return trades


def _wilson_interval(wins: int, count: int) -> list[float] | None:
    if count == 0:
        return None
    z = 1.959963984540054
    p = wins / count
    denominator = 1 + z * z / count
    center = (p + z * z / (2 * count)) / denominator
    radius = z * math.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / denominator
    return [100 * max(0.0, center - radius), 100 * min(1.0, center + radius)]


def _summarize(trades: list[dict]) -> dict:
    values = [row["net_return_pct"] for row in trades]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    win_rate = len(wins) / len(values) if values else None
    mean_win = math.fsum(wins) / len(wins) if wins else None
    mean_loss = math.fsum(losses) / len(losses) if losses else None
    payoff = mean_win / abs(mean_loss) if mean_win is not None and mean_loss is not None else None
    return {
        "closed_trades": len(values), "wins": len(wins), "losses": len(losses),
        "win_rate_pct": None if win_rate is None else 100 * win_rate,
        "win_rate_wilson_95_pct": _wilson_interval(len(wins), len(values)),
        "mean_win_pct": mean_win, "mean_loss_pct": mean_loss,
        "net_payoff_ratio": payoff,
        "ev_net_pct_per_trade_on_committed_notional": (
            None if not values else math.fsum(values) / len(values)),
        "median_hold_days": (sorted(row["hold_days"] for row in trades)[len(trades) // 2]
                             if trades else None),
    }


def run() -> dict:
    hourly, manifest = load_cached_range(SYMBOLS, FIRST, LAST, DATA_ROOT)
    frames = {symbol: daily_bars(bars) for symbol, bars in hourly.items()}
    signals = {symbol: make_signals(bars, RULE) for symbol, bars in frames.items()}
    prior = json.loads(SOURCE_REPORT.read_text(encoding="utf-8"))
    result = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "strategy": "daily_rsi2, selected on calibration under the prior portfolio gate",
        "rule": {"entry": "Wilder RSI2 <=10 and close > SMA200",
                 "exit": "Wilder RSI2 >=60 or close < SMA200",
                 "execution": "next daily open", "universe": SYMBOLS},
        "costs_per_side": {"base": BASE_COST, "stress": STRESS_COST},
        "metric_basis": "net trade return divided by committed notional; entry/exit side costs included",
        "prior_research_sha256": hashlib.sha256(SOURCE_REPORT.read_bytes()).hexdigest(),
        "analysis_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "prior_source_code_sha256": prior.get("source_code_sha256"),
        "source_manifest_sha256": prior.get("source_manifest_sha256"),
        "verified_hourly_archives": len(manifest),
        "windows": {},
        "goal_passed": False,
        "historical_not_pristine_holdout": True,
    }
    csv_rows = []
    for name, (start, end) in PER_TRADE_WINDOWS.items():
        start_ms, end_ms = utc_ms(start), utc_ms(end)
        by_cost = {}
        ledger_by_cost = {}
        for label, side_cost in (("base", BASE_COST), ("stress", STRESS_COST)):
            trades = []
            for symbol, bars in frames.items():
                trades.extend(_trades_for_symbol(bars, signals[symbol], start_ms, end_ms,
                                                 side_cost, symbol))
            trades.sort(key=lambda row: (row["entry_ms"], row["symbol"]))
            portfolio_metrics = prior["candidates"]["daily_rsi2"][
                "combined" if name == "combined" else name][label]
            summary = _summarize(trades)
            summary["portfolio_return_pct_existing_replay"] = portfolio_metrics["return_pct"]
            summary["portfolio_max_drawdown_pct_existing_replay"] = portfolio_metrics["max_drawdown_pct"]
            by_cost[label] = summary
            ledger_by_cost[label] = trades
            csv_rows.extend({"window": name, "cost": label, **trade} for trade in trades)
        target_checks = {}
        for label, metric in by_cost.items():
            target_checks[label] = {
                "win_rate_at_least_70_pct": metric["win_rate_pct"] is not None
                    and metric["win_rate_pct"] >= 70,
                "payoff_at_least_1_to_1": metric["net_payoff_ratio"] is not None
                    and metric["net_payoff_ratio"] >= 1,
                "ev_above_1_2_pct": metric["ev_net_pct_per_trade_on_committed_notional"] is not None
                    and metric["ev_net_pct_per_trade_on_committed_notional"] > 1.2,
                "max_drawdown_at_most_10_pct": metric["portfolio_max_drawdown_pct_existing_replay"] <= 10,
            }
        result["windows"][name] = {
            "start": start, "end": end,
            "by_cost": by_cost,
            "target_checks": target_checks,
            "all_user_target_gates_both_costs": all(all(row.values()) for row in target_checks.values()),
            "at_least_100_trades_both_costs": all(
                metric["closed_trades"] >= 100 for metric in by_cost.values()),
            "trade_ledger_by_cost": ledger_by_cost,
        }
    result["goal_passed"] = all(
        result["windows"][name]["all_user_target_gates_both_costs"]
        and result["windows"][name]["at_least_100_trades_both_costs"]
        for name in ("validation", "confirmation"))
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
                      encoding="utf-8")
    if csv_rows:
        fields = ["window", "cost", "symbol", "entry_ms", "exit_ms", "entry_price",
                  "exit_price", "hold_days", "net_return_pct"]
        with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(csv_rows)
    return result


if __name__ == "__main__":
    report = run()
    for name, window in report["windows"].items():
        print(name, json.dumps(window["by_cost"], sort_keys=True))
