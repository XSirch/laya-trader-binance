"""Long-only five-coin spot market trend screen with causal 28-day ranking."""

from __future__ import annotations

import json
from datetime import timedelta

import numpy as np
import pandas as pd

from spot_perp_carry_probe import ROOT, SPOT_SIDE_COST, spot_opens


SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")
OUT = ROOT / "outputs/market_trend_28_5_report.json"
ANCHOR = pd.Timestamp("2023-04-01", tz="UTC")
LOOKBACK_DAYS = 28
HOLD_DAYS = 5
HISTORY_DAYS = 365
MIN_HISTORY = 60
EXTRA_SIDE_COST = 0.0002  # Four additional basis points per round trip.


def market_data(last_month: str) -> tuple[pd.DataFrame, pd.Series]:
    prices = pd.concat(
        {symbol: spot_opens(symbol, last_month) for symbol in SYMBOLS}, axis=1
    ).sort_index()
    prices = prices.loc[(prices.index >= pd.Timestamp("2023-01-01", tz="UTC"))]
    if prices.isna().any().any() or prices.le(0).any().any():
        raise ValueError("Missing or nonpositive spot daily open")
    expected = pd.date_range(prices.index[0], prices.index[-1], freq="D")
    if not prices.index.equals(expected):
        raise ValueError("Spot daily archive has a date gap")
    equal_weight_return = prices.pct_change().mean(axis=1).fillna(0)
    market_index = (1 + equal_weight_return).cumprod()
    lookback = market_index / market_index.shift(LOOKBACK_DAYS) - 1
    return prices, lookback


def windows(prices: pd.DataFrame, lookback: pd.Series,
            first: str, last: str) -> pd.DataFrame:
    first_day = pd.Timestamp(first, tz="UTC")
    last_day = pd.Timestamp(last, tz="UTC")
    if first_day < ANCHOR:
        raise ValueError("Start precedes fixed five-day anchor")
    candidates = pd.date_range(ANCHOR, last_day, freq=f"{HOLD_DAYS}D")
    rows = []
    for start in candidates:
        end = start + timedelta(days=HOLD_DAYS)
        if start < first_day or end > last_day:
            continue
        current_day = start - timedelta(days=1)
        prior_day = current_day - timedelta(days=1)
        past = lookback.loc[:prior_day].dropna().tail(HISTORY_DAYS)
        if len(past) < MIN_HISTORY:
            continue
        current = float(lookback.loc[current_day])
        threshold = float(past.quantile(2 / 3))
        days = pd.date_range(start, end, freq="D")
        if not days.isin(prices.index).all():
            raise ValueError(f"Incomplete tradable spot window: {start}")
        active = current > threshold
        gross_factor = float((prices.loc[end] / prices.loc[start]).mean())
        net_factor = (gross_factor * (1 - SPOT_SIDE_COST)
                      / (1 + SPOT_SIDE_COST)) if active else 1.0
        stress_side_cost = SPOT_SIDE_COST + EXTRA_SIDE_COST
        stress_factor = (gross_factor * (1 - stress_side_cost)
                         / (1 + stress_side_cost)) if active else 1.0
        rows.append({"start": start, "end": end, "active": active,
                     "signal_return_28d": current, "past_top_third": threshold,
                     "gross_factor": gross_factor if active else 1.0,
                     "net_factor": net_factor, "stress_factor": stress_factor})
    return pd.DataFrame(rows)


def stage_summary(frame: pd.DataFrame, prices: pd.DataFrame) -> dict:
    if frame.empty:
        raise ValueError("No five-day windows in stage")
    active = frame.loc[frame.active]
    capital = 1.0
    daily_values = [1.0]
    for row in frame.itertuples():
        if row.active:
            days = pd.date_range(row.start, row.end, freq="D")
            for day in days:
                factor = float((prices.loc[day] / prices.loc[row.start]).mean())
                daily_values.append(capital * factor * (1 - SPOT_SIDE_COST)
                                    / (1 + SPOT_SIDE_COST))
        else:
            daily_values.extend([capital] * (HOLD_DAYS + 1))
        capital *= row.net_factor
    daily = pd.Series(daily_values)
    drawdown = float((daily / daily.cummax() - 1).min())
    month_returns = {month: 0.0 for month in pd.period_range(
        frame.start.min().tz_localize(None).to_period("M"),
        frame.end.max().tz_localize(None).to_period("M"), freq="M")}
    for row in frame.itertuples():
        month = row.end.tz_localize(None).to_period("M")
        month_returns[month] = ((1 + month_returns[month]) * row.net_factor - 1)
    returns = frame.net_factor.to_numpy() - 1
    rng = np.random.default_rng(42)
    block = 4
    sample_starts = rng.integers(0, len(returns), size=(10_000, (len(returns) + 3) // 4))
    sampled = returns[(sample_starts[:, :, None] + np.arange(block)) % len(returns)]
    means = sampled.reshape(10_000, -1)[:, :len(returns)].mean(axis=1)
    first = frame.start.iloc[0]
    end = frame.end.iloc[-1]
    buy_hold = float((prices.loc[end] / prices.loc[first]).mean()
                     * (1 - SPOT_SIDE_COST) / (1 + SPOT_SIDE_COST) - 1)
    result = {
        "windows": len(frame), "invested_windows": len(active),
        "net_compounded_return": float(np.prod(frame.net_factor) - 1),
        "stress_compounded_return": float(np.prod(frame.stress_factor) - 1),
        "buy_hold_return_same_dates": buy_hold,
        "positive_months": sum(value > 0 for value in month_returns.values()),
        "calendar_months": len(month_returns),
        "month_return_by_exit": {str(key): round(value, 6)
                                 for key, value in month_returns.items()},
        "maximum_daily_liquidation_drawdown": drawdown,
        "four_window_block_ci_95_mean": np.quantile(means, [0.025, 0.975]).tolist(),
    }
    return result


def passes(stage: dict) -> bool:
    return (stage["invested_windows"] >= 12
            and stage["calendar_months"] == 6
            and stage["stress_compounded_return"] > 0
            and stage["positive_months"] >= 4
            and stage["maximum_daily_liquidation_drawdown"] > -0.25
            and stage["four_window_block_ci_95_mean"][0] > 0)


def main() -> None:
    prices, lookback = market_data("2025-07")
    development = windows(prices, lookback, "2023-04-01", "2024-12-31")
    calibration = windows(prices, lookback, "2025-01-01", "2025-06-30")
    report = {
        "hypothesis": "long-only equal-weight five-coin spot basket when lagged 28-day equal-weight market return is above prior rolling 365-day upper tercile; five-day holds",
        "causal_signal": "current return through previous daily open; percentile uses only earlier 28-day returns",
        "per_side_cost": SPOT_SIDE_COST,
        "extra_per_side_stress": EXTRA_SIDE_COST,
        "source": "cached Binance public monthly spot 1d archives",
        "development": stage_summary(development, prices),
        "calibration": stage_summary(calibration, prices),
    }
    report["calibration_gate"] = passes(report["calibration"])
    ledgers = [development.assign(stage="development"),
               calibration.assign(stage="calibration")]
    print("development", json.dumps(report["development"], indent=2), flush=True)
    print("calibration", json.dumps(report["calibration"], indent=2), flush=True)
    print("calibration gate", report["calibration_gate"], flush=True)
    if report["calibration_gate"]:
        prices, lookback = market_data("2026-01")
        validation = windows(prices, lookback, "2025-07-01", "2025-12-31")
        report["validation"] = stage_summary(validation, prices)
        report["validation_gate"] = passes(report["validation"])
        ledgers.append(validation.assign(stage="validation"))
        print("validation", json.dumps(report["validation"], indent=2), flush=True)
        print("validation gate", report["validation_gate"], flush=True)
    else:
        report["validation"] = None
        report["validation_gate"] = None
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    pd.concat(ledgers, ignore_index=True).to_parquet(
        ROOT / "outputs/market_trend_28_5_windows.parquet", index=False)
    print("saved", OUT, flush=True)


if __name__ == "__main__":
    main()
