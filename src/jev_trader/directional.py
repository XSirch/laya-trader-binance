"""Fixed long/short futures hypotheses with causal daily volatility scaling."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from .binance_data import HOUR_MS, utc_ms
from .cli import RESULTS
from .derivatives_data import load
from .extended import daily_bars
from .market_state import ema, states
from .strategies import sma

DAY_MS = HOUR_MS * 24
NAMES = ("ema_8_32", "ema_16_64", "ema_32_128", "sma_20_100",
         "channel_20_10", "channel_55_20", "momentum_30", "ema_ensemble",
         "multifactor_direction", "cross_section_30")
PERIODS = {"development": ("2024-01-01", "2025-01-01"),
           "calibration": ("2025-01-01", "2025-07-01"),
           "validation": ("2025-07-01", "2026-01-01"),
           "confirmation": ("2026-01-01", "2026-08-01"),
           "combined": ("2025-01-01", "2026-08-01")}


def sign(value):
    return 1 if value > 0 else -1 if value < 0 else 0


def signals(frames):
    daily = {s: daily_bars(bars) for s, bars in frames.items()}
    if len({tuple(b.open_ms for b in bars) for bars in daily.values()}) != 1:
        raise ValueError("futures daily calendars differ")
    output = {name: {s: [0.0] * len(bars) for s, bars in daily.items()} for name in NAMES}
    scales, returns30 = {}, {}
    for s, bars in daily.items():
        closes = [b.close for b in bars]
        exponential = {n: ema(closes, n) for n in (8, 16, 32, 64, 128)}
        fast, slow = sma(closes, 20), sma(closes, 100)
        market = states(bars)
        scales[s], returns30[s] = [0.0] * len(bars), [0.0] * len(bars)
        channel_state = {20: 0, 55: 0}
        for i in range(200, len(bars)):
            changes = [math.log(closes[j] / closes[j - 1]) for j in range(i - 29, i + 1)]
            average = sum(changes) / len(changes)
            vol = math.sqrt(sum((x - average) ** 2 for x in changes) / len(changes) * 365)
            scale = min(.5, .20 / max(vol, .05))
            scales[s][i] = scale
            for a, b in ((8, 32), (16, 64), (32, 128)):
                output[f"ema_{a}_{b}"][s][i] = sign(exponential[a][i] - exponential[b][i]) * scale
            output["sma_20_100"][s][i] = sign(fast[i] - slow[i]) * scale
            for entry, exit in ((20, 10), (55, 20)):
                if closes[i] > max(b.high for b in bars[i - entry:i]):
                    channel_state[entry] = 1
                elif closes[i] < min(b.low for b in bars[i - entry:i]):
                    channel_state[entry] = -1
                elif (channel_state[entry] == 1 and closes[i] < min(b.low for b in bars[i - exit:i])
                      or channel_state[entry] == -1 and closes[i] > max(b.high for b in bars[i - exit:i])):
                    channel_state[entry] = 0
                output[f"channel_{entry}_{exit}"][s][i] = channel_state[entry] * scale
            momentum = closes[i] / closes[i - 30] - 1
            returns30[s][i] = momentum
            output["momentum_30"][s][i] = sign(momentum) * scale if abs(momentum) > .02 else 0
            output["ema_ensemble"][s][i] = sum(output[name][s][i] for name in
                                             ("ema_8_32", "ema_16_64", "ema_32_128")) / 3
            state = market[i]
            t, m, p = state["trend"], state["momentum"], state["participation"]
            score = sum((sign(t["distance_sma_pct"]["200"]), sign(t["sma50_slope_5bars_pct"]),
                         sign(m["macd_histogram_pct"]), sign(p["obv_change20_over_volume"])))
            output["multifactor_direction"][s][i] = sign(score) * scale if abs(score) >= 3 and t["adx14"] >= 20 else 0
    symbols = sorted(daily)
    for i in range(200, len(daily[symbols[0]])):
        ranked = sorted(symbols, key=lambda s: (returns30[s][i], s))
        # Same notional on each side: no net directional bet introduced by scaling.
        scale = min(scales[ranked[0]][i], scales[ranked[-1]][i])
        output["cross_section_30"][ranked[0]][i] = -scale
        output["cross_section_30"][ranked[-1]][i] = scale
    # Decision is made at the prior daily close and executed at 01:00 UTC,
    # avoiding the usual 00:00 funding event and adding a full hour of delay.
    timed = {name: {s: {bar.open_ms + DAY_MS + HOUR_MS: value
                        for bar, value in zip(daily[s], values)} for s, values in symbols.items()}
             for name, symbols in output.items()}
    return timed


def evaluate(derivatives, targets, start, end, side_cost):
    start_ms, end_ms = utc_ms(start), utc_ms(end)
    symbols = sorted(targets)
    maps = {s: {b.open_ms: b for b in derivatives["klines"][s]} for s in symbols}
    marks = {s: {b.open_ms: b for b in derivatives["markPriceKlines"][s]} for s in symbols}
    funding = {s: {r.timestamp_ms // HOUR_MS * HOUR_MS: r for r in derivatives["fundingRate"][s]} for s in symbols}
    timeline = range(start_ms, end_ms + 1, HOUR_MS)
    equity, quantity = {s: 1.0 for s in symbols}, {s: 0.0 for s in symbols}
    previous = {s: maps[s][start_ms].open for s in symbols}
    path = [(start_ms, 1.0)]
    fees = funding_pnl = 0.0
    entries = margin_breaches = 0
    for timestamp in timeline:
        for s in symbols:
            bar, mark = maps[s][timestamp], marks[s][timestamp]
            q = quantity[s]
            equity[s] += q * (bar.open - previous[s])
            previous[s] = bar.open
            if q and timestamp in funding[s] and funding[s][timestamp].timestamp_ms < end_ms:
                payment = -q * mark.open * funding[s][timestamp].rate
                equity[s] += payment
                funding_pnl += payment / len(symbols)
            if timestamp in targets[s] or timestamp == end_ms:
                target = targets[s].get(timestamp, 0) if timestamp < end_ms else 0
                desired = target * equity[s] / bar.open
                charge = abs(desired - q) * bar.open * side_cost
                fees += charge / len(symbols)
                equity[s] -= charge
                if desired and sign(desired) != sign(q):
                    entries += 1
                quantity[s] = q = desired
            if q and timestamp < end_ms:
                adverse = mark.low if q > 0 else mark.high
                margin_breaches += equity[s] + q * (adverse - bar.open) < .10 * abs(q) * adverse
            if equity[s] <= 0:
                raise ValueError("insolvent futures sleeve")
        path.append((timestamp, sum(equity.values()) / len(symbols)))
    peak = 1.0
    drawdown = 0.0
    for _, value in path:
        peak = max(peak, value)
        drawdown = max(drawdown, 1 - value / peak)
    monthly, prior = {}, 1.0
    for i in range(1, len(path)):
        month = datetime.fromtimestamp(path[i - 1][0] / 1000, timezone.utc).strftime("%Y-%m")
        after = datetime.fromtimestamp(path[i][0] / 1000, timezone.utc).strftime("%Y-%m")
        if month != after or i == len(path) - 1:
            monthly[month] = 100 * (path[i][1] / prior - 1)
            prior = path[i][1]
    return {"return_pct": 100 * (path[-1][1] - 1), "max_drawdown_pct": 100 * drawdown,
            "daily_equity": {str(t): value for t, value in path if t % DAY_MS == 0},
            "monthly_returns_pct": monthly, "positive_months": sum(v > 0 for v in monthly.values()),
            "months": len(monthly), "entries": entries, "fees_pct_initial": 100 * fees,
            "funding_pct_initial": 100 * funding_pnl, "hours_below_10pct_margin": margin_breaches,
            "symbol_returns_pct": {s: 100 * (value - 1) for s, value in equity.items()}}


def passed(m):
    return (m["return_pct"] > 0 and m["positive_months"] >= math.ceil(2 * m["months"] / 3)
            and m["max_drawdown_pct"] <= 15 and m["entries"] >= 12 and m["hours_below_10pct_margin"] == 0)


def run():
    derivatives, manifest = load()
    all_signals = signals(derivatives["klines"])
    result = {}
    for name in NAMES:
        result[name] = {"development": {cost: evaluate(derivatives, all_signals[name], *PERIODS["development"], value)
                         for cost, value in (("base", .001), ("stress", .0015))}}
    selected = max(NAMES, key=lambda name: (passed(result[name]["development"]["stress"]),
                                           result[name]["development"]["stress"]["return_pct"]))
    for name in NAMES:
        for period, dates in PERIODS.items():
            if period != "development":
                result[name][period] = {cost: evaluate(derivatives, all_signals[name], *dates, value)
                                       for cost, value in (("base", .001), ("stress", .0015))}
        result[name]["all_later_gates"] = all(passed(result[name][p]["stress"])
                                             for p in ("calibration", "validation", "confirmation"))
        m = result[name]["combined"]["stress"]
        print(f"{name}: return={m['return_pct']:.2f}% drawdown={m['max_drawdown_pct']:.2f}% "
              f"months={m['positive_months']}/{m['months']} gates={result[name]['all_later_gates']}", flush=True)
    report = {"created_utc": datetime.now(timezone.utc).isoformat(),
              "selected_on_2024": selected, "candidates": result, "deployable": False,
              "source_code_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                     for name in ("directional.py", "derivatives_data.py", "binance_data.py", "market_state.py")},
              "derivatives_sources_sha256": hashlib.sha256(json.dumps(
                  [{k: row[k] for k in ("kind", "symbol", "month", "sha256")} for row in manifest],
                  sort_keys=True).encode()).hexdigest(),
              "design": {"names": NAMES, "periods": PERIODS, "max_abs_exposure_per_sleeve": .5,
                         "volatility_target_annual": .20, "volatility_lookback_days": 30,
                         "execution": "daily 01:00 UTC, signals from prior completed UTC daily candle",
                         "base_side_cost": .001, "stress_side_cost": .0015},
              "limits": ["Exploratory reused history, not prospective proof.",
                         "All fees and slippage assumed; marks approximate funding settlement prices.",
                         "10% maintenance stress is not actual exchange liquidation accounting.",
                         "Daily realized volatility and hourly marks do not bound jump risk."]}
    (RESULTS / "directional_research.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"selected on development: {selected}", flush=True)
    return report


if __name__ == "__main__":
    run()
