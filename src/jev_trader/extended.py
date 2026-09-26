"""Exploratory daily rules and purged weekly forecasts using verified local data.

All parameters below are fixed before this run. Later windows are diagnostic:
the same market history was already inspected by earlier project experiments.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .backtest import evaluate_window
from .binance_data import Bar, HOUR_MS, load_cached_range, utc_ms
from .cli import (BASE_COST, STRESS_COST, DATA_ROOT, FIRST, LAST, RESULTS,
                  SYMBOLS, _fingerprint, _passes, _entry_events, _gated_signals,
                  _entry_checklist, WINDOWS)
from .jev import DecisionCache, _cache_key
from .strategies import Candidate, make_signals, sma

DAY_MS = 24 * HOUR_MS
DAILY_RULES = (
    Candidate("daily_trend_10_50", "trend", 10, 50),
    Candidate("daily_trend_20_100", "trend", 20, 100),
    Candidate("daily_trend_50_200", "trend", 50, 200),
    Candidate("daily_breakout_20_10", "breakout", 20, 10),
    Candidate("daily_breakout_55_20", "breakout", 55, 20),
    Candidate("daily_rsi2", "rsi", 2, 10),
    Candidate("daily_rsi14", "rsi", 14, 30),
    Candidate("daily_momentum_30", "momentum", 30, 200),
    Candidate("daily_momentum_90", "momentum", 90, 200),
    Candidate("daily_momentum_180", "momentum", 180, 200),
)
MODEL_NAMES = ("ridge_1", "ridge_10", "analog_50", "regime_mean", "historical_mean")
PERIODS = {
    "development": ("2024-01-01", "2025-01-01"),
    "calibration": WINDOWS["calibration"],
    "validation": WINDOWS["validation"],
    "confirmation": WINDOWS["confirmation"],
}


def daily_bars(bars: list[Bar]) -> list[Bar]:
    """Use April 2023 onward; reject incomplete UTC days rather than fill gaps."""
    groups: dict[int, list[Bar]] = {}
    for bar in bars:
        if bar.open_ms >= utc_ms("2023-04-01"):
            groups.setdefault(bar.open_ms // DAY_MS * DAY_MS, []).append(bar)
    result = []
    for day, group in sorted(groups.items()):
        if [bar.open_ms for bar in group] != [day + i * HOUR_MS for i in range(24)]:
            raise ValueError(f"incomplete UTC day: {day}")
        result.append(Bar(day, group[0].open, max(b.high for b in group),
                          min(b.low for b in group), group[-1].close,
                          sum(b.volume for b in group),
                          *[sum(getattr(b, field) for b in group)
                            if all(getattr(b, field) is not None for b in group) else None
                            for field in ("quote_volume", "trades", "taker_buy_base")]))
    if any(b.open_ms - a.open_ms != DAY_MS for a, b in zip(result, result[1:])):
        raise ValueError("missing UTC day")
    return result


def features(bars: list[Bar], i: int) -> list[float]:
    """Fixed scaling, no normalization fitted on future observations."""
    close = bars[i].close
    returns = [bars[j].close / bars[j - 1].close - 1 for j in range(i - 13, i + 1)]
    average = sum(returns) / 14
    vol = math.sqrt(sum((r - average) ** 2 for r in returns) / 14)
    return [1.0] + [10 * (close / bars[i - lag].close - 1) for lag in (1, 7, 30)] + [
        10 * (close / (sum(b.close for b in bars[i - 59:i + 1]) / 60) - 1),
        10 * vol,
    ]


def solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Partial-pivot Gaussian elimination for a small regularized system."""
    rows = [list(row) + [value] for row, value in zip(matrix, vector)]
    n = len(rows)
    for i in range(n):
        pivot = max(range(i, n), key=lambda j: abs(rows[j][i]))
        rows[i], rows[pivot] = rows[pivot], rows[i]
        scale = rows[i][i]
        if abs(scale) < 1e-12:
            raise ValueError("singular regression")
        rows[i] = [value / scale for value in rows[i]]
        for j in range(n):
            if j != i:
                scale = rows[j][i]
                rows[j] = [a - scale * b for a, b in zip(rows[j], rows[i])]
    return [row[-1] for row in rows]


def train_rows(frames, vectors, signal_index: int, horizon: int = 7):
    # A feature at j enters at j+1 open and exits at j+1+horizon open.
    # Endpoint must be <= signal_index (already observed before today's close).
    earliest = max(60, signal_index - 730)
    latest = signal_index - horizon - 1
    indices = [j for j in range(earliest, latest + 1) if j % horizon == 0]
    return [(vectors[symbol][j], bars[j + horizon + 1].open / bars[j + 1].open - 1)
            for symbol, bars in frames.items() for j in indices]


def forecast_signals(frames):
    count = len(next(iter(frames.values())))
    vectors = {s: [features(bars, i) if i >= 60 else None for i in range(count)]
               for s, bars in frames.items()}
    output = {name: {s: [False] * count for s in frames} for name in MODEL_NAMES}
    audits = []
    prediction_errors = {name: [] for name in MODEL_NAMES}
    # Weekly decisions at Sunday close, held unchanged until next Sunday close.
    for i in range(210, count):
        if datetime.fromtimestamp(next(iter(frames.values()))[i].open_ms / 1000,
                                  timezone.utc).weekday() != 6:
            for name in MODEL_NAMES:
                for s in frames:
                    output[name][s][i] = output[name][s][i - 1]
            continue
        rows = train_rows(frames, vectors, i)
        x, y = zip(*rows)
        n = len(x[0])
        gram = [[sum(row[a] * row[b] for row in x) for b in range(n)] for a in range(n)]
        rhs = [sum(row[a] * target for row, target in rows) for a in range(n)]
        weights = {}
        for penalty in (1, 10):
            matrix = [[value + (penalty if a == b and a > 0 else 0)
                       for b, value in enumerate(row)] for a, row in enumerate(gram)]
            weights[f"ridge_{penalty}"] = solve(matrix, rhs)
        audits.append({"signal_open_ms": next(iter(frames.values()))[i].open_ms,
                       "max_training_label_open_ms": max(
                           bars[j + 8].open_ms for bars in frames.values()
                           for j in range(max(60, i - 730), i - 7) if j % 7 == 0),
                       "samples": len(rows)})
        for s, bars in frames.items():
            current = vectors[s][i]
            predictions = {name: sum(a * b for a, b in zip(weight, current))
                           for name, weight in weights.items()}
            nearest = sorted(rows, key=lambda row: sum((a - b) ** 2 for a, b in
                             zip(row[0][1:], current[1:])))[:50]
            regime = [target for row, target in rows
                      if (row[3] > 0) == (current[3] > 0)
                      and (row[4] > 0) == (current[4] > 0)]
            predictions["analog_50"] = sum(target for _, target in nearest) / len(nearest)
            predictions["regime_mean"] = sum(regime) / len(regime) if regime else 0
            predictions["historical_mean"] = sum(y) / len(y)
            for name, value in predictions.items():
                # Fixed 50bps hurdle = stress round-trip approximation.
                output[name][s][i] = value > 0.005
                if (i + 8 < count and bars[i].open_ms >= utc_ms("2025-01-01")
                        and bars[i + 8].open_ms <= utc_ms("2026-08-01")):
                    actual = bars[i + 8].open / bars[i + 1].open - 1
                    prediction_errors[name].append((value, actual))
    scores = {name: {"n": len(values),
                    "mae": sum(abs(p - y) for p, y in values) / len(values),
                    "zero_forecast_mae": sum(abs(y) for _, y in values) / len(values),
                    "direction_accuracy": sum((p > 0) == (y > 0) for p, y in values) / len(values)}
              for name, values in prediction_errors.items() if values}
    return output, audits, scores


def metrics(frames, signal, start, end):
    return {name: asdict(evaluate_window(frames, signal, start, end, cost))
            for name, cost in (("base", BASE_COST), ("stress", STRESS_COST))}


def block_interval(monthly: dict[str, float], seed: int = 417):
    """Descriptive 3-month circular block bootstrap; not selection-adjusted."""
    values = [math.log1p(value / 100) for value in monthly.values()]
    rng = random.Random(seed)
    draws = []
    for _ in range(2000):
        sample = []
        while len(sample) < len(values):
            start = rng.randrange(len(values))
            sample.extend(values[(start + k) % len(values)] for k in range(3))
        draws.append(100 * math.expm1(sum(sample[:len(values)]) / len(values)))
    draws.sort()
    return {"mean_monthly_geometric_pct_95_interval": [draws[50], draws[1949]],
            "block_months": 3, "draws": 2000, "selection_adjusted": False}


def quarterly_selector(frames, signals):
    """Choose using preceding 12 months only; hold cash when no candidate passes."""
    output = {s: [False] * len(bars) for s, bars in frames.items()}
    choices = []
    boundaries = ["2025-01-01", "2025-04-01", "2025-07-01", "2025-10-01",
                  "2026-01-01", "2026-04-01", "2026-07-01", "2026-08-01"]
    for start, end in zip(boundaries, boundaries[1:]):
        prior = f"{int(start[:4]) - 1}{start[4:]}"
        # Selection is made before the quarter's first executable open.
        known_end = (datetime.fromisoformat(start) - timedelta(days=1)).date().isoformat()
        ranked = []
        for name, signal in signals.items():
            if name in ("hold", "cash"):
                continue
            score = metrics(frames, signal, prior, known_end)
            if _passes(score):
                ranked.append((score["stress"]["return_pct"], name))
        selected = max(ranked)[1] if ranked else "cash"
        choices.append({"start": start, "end": end, "training_start": prior,
                        "training_end": known_end, "selected": selected,
                        "eligible": len(ranked)})
        for s, bars in frames.items():
            for i in range(len(bars) - 1):
                if utc_ms(start) <= bars[i + 1].open_ms < utc_ms(end):
                    output[s][i] = signals[selected][s][i]
    return output, choices


def jev_ablation(hourly):
    """Read-only cached replay; fail closed if any cached decision is absent."""
    cache = DecisionCache(RESULTS / "jev_checklist_single_decisions.jsonl")
    base = {s: make_signals(bars, Candidate("rsi14_30_55", "rsi", 14, 30))
            for s, bars in hourly.items()}
    result = {}
    for window in ("calibration", "validation", "confirmation"):
        events = _entry_events(hourly, base, window)
        missing = [state for _, _, state in events if _cache_key(state) not in cache.items]
        if missing:
            result[window] = {"status": "missing_cache", "missing": len(missing)}
            continue
        checklist = {(s, i): _entry_checklist(state) for s, i, state in events}
        jev = {(s, i): checklist[(s, i)] and
               cache.items[_cache_key(state)].matches_probability >= 0.70
               for s, i, state in events}
        result[window] = {
            "checklist_entries": sum(checklist.values()), "jev_entries": sum(jev.values()),
            "baseline": metrics(hourly, base, *WINDOWS[window]),
            "checklist": metrics(hourly, _gated_signals(hourly, base, window, checklist), *WINDOWS[window]),
            "jev": metrics(hourly, _gated_signals(hourly, base, window, jev), *WINDOWS[window]),
        }
    return result


def robustness(hourly, daily, signal):
    """Fixed diagnostics for the calibration-selected rule, not new candidates."""
    expanded = {}
    for s, bars in hourly.items():
        daily_lookup = {bar.open_ms: value for bar, value in zip(daily[s], signal[s])}
        # A daily candle is known only at the END of its last hourly candle.
        expanded[s] = [daily_lookup.get(
            (bar.open_ms + HOUR_MS) // DAY_MS * DAY_MS - DAY_MS, False) for bar in bars]
    start, end = "2025-01-01", "2026-08-01"
    return {
        "hourly_marked": metrics(hourly, expanded, start, end),
        "double_stress_cost": asdict(evaluate_window(daily, signal, start, end, 0.005)),
        "one_day_delay": metrics(daily, {s: [False] + values[:-1] for s, values in signal.items()}, start, end),
        "leave_one_asset_out": {excluded: metrics(
            {s: bars for s, bars in daily.items() if s != excluded},
            {s: values for s, values in signal.items() if s != excluded}, start, end)
            for excluded in daily},
    }


def run():
    hourly, manifest = load_cached_range(SYMBOLS, FIRST, LAST, DATA_ROOT)
    frames = {s: daily_bars(bars) for s, bars in hourly.items()}
    if len({tuple(b.open_ms for b in bars) for bars in frames.values()}) != 1:
        raise ValueError("daily symbol calendars differ")
    signals = {rule.name: {s: make_signals(bars, rule) for s, bars in frames.items()}
               for rule in DAILY_RULES}
    signals["daily_ensemble"] = {s: [sum(signals[name][s][i] for name in
        ("daily_trend_10_50", "daily_trend_20_100", "daily_momentum_90")) >= 2
        for i in range(len(bars))] for s, bars in frames.items()}
    signals["cash"] = {s: [False] * len(bars) for s, bars in frames.items()}
    signals["hold"] = {s: [True] * len(bars) for s, bars in frames.items()}
    models, audits, scores = forecast_signals(frames)
    signals.update(models)
    print("daily rules and weekly statistical forecasts ready", flush=True)
    selector, choices = quarterly_selector(frames, signals)
    signals["quarterly_selector"] = selector
    results = {}
    for name, signal in signals.items():
        results[name] = {period: metrics(frames, signal, *dates) for period, dates in PERIODS.items()}
        full = metrics(frames, signal, "2025-01-01", "2026-08-01")
        results[name]["combined"] = full
        results[name]["monthly_interval"] = block_interval(full["stress"]["monthly_returns_pct"])
        results[name]["all_three_gates"] = all(_passes(results[name][p])
            for p in ("calibration", "validation", "confirmation"))
        print(f"{name}: stress={full['stress']['return_pct']:.2f}% "
              f"gates={results[name]['all_three_gates']}", flush=True)
    selected = max((name for name in signals if name not in ("cash", "hold", "quarterly_selector")),
                   key=lambda name: (_passes(results[name]["calibration"]),
                                     results[name]["calibration"]["stress"]["return_pct"]))
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_manifest_sha256": _fingerprint(manifest),
        "source_code_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                               for name in ("extended.py", "backtest.py", "strategies.py", "cli.py", "jev.py")},
        "jev_cache_sha256": hashlib.sha256(
            (RESULTS / "jev_checklist_single_decisions.jsonl").read_bytes()).hexdigest()
            if (RESULTS / "jev_checklist_single_decisions.jsonl").exists() else None,
        "design": {"periods": PERIODS, "base_per_side": BASE_COST,
                   "stress_per_side": STRESS_COST, "daily_rules": [asdict(c) for c in DAILY_RULES],
                   "models": MODEL_NAMES, "horizon_days": 7, "training_days": 730,
                   "min_signal_index": 210, "rebalance": "Sunday close -> Monday open",
                   "execution": "next UTC day open, equal initial capital sleeves",
                   "candidate_count_including_benchmarks_and_selector": len(signals)},
        "selected_on_calibration": selected,
        "historically_passes": [name for name, value in results.items() if value["all_three_gates"]],
        "deployable": False,
        "limitations": ["Exploratory reuse of previously inspected history; no pristine holdout.",
                        "Daily drawdown sampled at opens; intraday losses may be larger.",
                        "Fixed four-asset universe has selection/survivorship bias.",
                        "No executable quotes, taxes, interest on cash, or actual account fees.",
                        "Monthly bootstrap is descriptive and not adjusted for multiple trials.",
                        "Forecast metrics pool correlated assets; they are not independent samples.",
                        "No live orders or fresh paid Jev requests."],
        "candidates": results, "forecast_metrics": scores,
        "training_audit": audits, "quarterly_choices": choices,
        "jev_ablation": jev_ablation(hourly),
        "selected_robustness": robustness(hourly, frames, signals[selected]),
    }
    RESULTS.mkdir(exist_ok=True)
    target = RESULTS / "extended_research.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"report: {target}; calibration selection: {selected}", flush=True)
    return report


if __name__ == "__main__":
    run()
