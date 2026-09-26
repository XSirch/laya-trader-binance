"""Fixed monthly BTC/ETH long-only spot trend screen."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta

import numpy as np
import pandas as pd

from laya_trader.progress import ProgressReporter

from spot_perp_carry_probe import ROOT, SPOT_SIDE_COST, download_one, spot_opens


SYMBOLS = ("BTCUSDT", "ETHUSDT")
START = pd.Timestamp("2024-02-01", tz="UTC")
CALIBRATION_END = pd.Timestamp("2025-07-01", tz="UTC")
SIGNAL_DAYS = 365
ALLOCATION_PER_COIN = 0.495
EXTRA_SIDE_COST = 0.0002
REPORT = ROOT / "outputs/slow_spot_trend_report.json"


def load_prices(last_month: str) -> pd.DataFrame:
    months = pd.period_range("2023-01", last_month, freq="M").astype(str)
    tasks = [(symbol, month) for symbol in SYMBOLS for month in months]
    progress = ProgressReporter("slow spot daily archives", len(tasks), unit="archives")
    failures = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(download_one, *task) for task in tasks]
        for count, future in enumerate(as_completed(futures), 1):
            symbol, month, status = future.result()
            if status in ("missing", "error"):
                failures.append((symbol, month, status))
            progress.update(count)
    if failures:
        raise RuntimeError(f"Incomplete spot archive coverage: {failures}")
    prices = pd.concat({symbol: spot_opens(symbol, last_month)
                        for symbol in SYMBOLS}, axis=1).sort_index()
    expected = pd.date_range("2023-01-01", prices.index[-1], tz="UTC", freq="D")
    if not prices.index.equals(expected) or prices.isna().any().any():
        raise ValueError("Spot daily opens have a date gap")
    if not np.isfinite(prices.to_numpy()).all() or prices.le(0).any().any():
        raise ValueError("Spot daily opens must be finite and positive")
    return prices


def replay(prices: pd.DataFrame, first: pd.Timestamp,
           stop: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    months = pd.date_range(first, stop - timedelta(days=1), freq="MS")
    rows = []
    daily_rows = []
    for start in months:
        end = start + pd.offsets.MonthBegin(1)
        signal_day = start - timedelta(days=1)
        past_day = signal_day - timedelta(days=SIGNAL_DAYS)
        days = pd.date_range(start, end, freq="D")
        if not days.isin(prices.index).all() or past_day not in prices.index:
            raise ValueError(f"Incomplete month or signal history: {start}")
        eligible = prices.loc[signal_day] > prices.loc[past_day]
        weights = eligible.astype(float) * ALLOCATION_PER_COIN
        invested = float(weights.sum())
        paths = prices.loc[days].div(prices.loc[start])
        month = {"month": start.strftime("%Y-%m"), "active_coins": int(eligible.sum()),
                 "btc_active": bool(eligible["BTCUSDT"]),
                 "eth_active": bool(eligible["ETHUSDT"]),
                 "btc_signal_365d": float(prices.loc[signal_day, "BTCUSDT"]
                                          / prices.loc[past_day, "BTCUSDT"] - 1),
                 "eth_signal_365d": float(prices.loc[signal_day, "ETHUSDT"]
                                          / prices.loc[past_day, "ETHUSDT"] - 1)}
        for label, side_cost in (("base", SPOT_SIDE_COST),
                                 ("stress", SPOT_SIDE_COST + EXTRA_SIDE_COST)):
            liquidatable = (1 - invested + paths.mul(weights).sum(axis=1)
                            * (1 - side_cost) / (1 + side_cost))
            month[f"{label}_factor"] = float(liquidatable.loc[end])
            for day, value in liquidatable.items():
                daily_rows.append({"day": day, "month": month["month"],
                                   "case": label, "month_factor": float(value)})
        rows.append(month)
    return pd.DataFrame(rows), pd.DataFrame(daily_rows)


def summarize(months: pd.DataFrame, daily: pd.DataFrame) -> dict:
    if months.empty:
        raise ValueError("No monthly positions")
    returns = months.base_factor.to_numpy() - 1
    stressed_returns = months.stress_factor.to_numpy() - 1
    rng = np.random.default_rng(20260926)
    starts = rng.integers(0, len(returns), size=(10_000, (len(returns) + 1) // 2))
    samples = stressed_returns[(starts[:, :, None] + np.arange(2)) % len(returns)]
    means = samples.reshape(10_000, -1)[:, :len(returns)].mean(axis=1)
    stressed = daily.loc[daily.case == "stress"].copy()
    opening_capital = dict(zip(months.month, np.r_[1.0, months.stress_factor
                               .to_numpy()[:-1].cumprod()]))
    stressed["equity"] = stressed.month.map(opening_capital) * stressed.month_factor
    path = stressed.sort_values(["day", "month"]).equity.to_numpy()
    drawdown = float((path / np.maximum.accumulate(np.r_[1.0, path])[1:] - 1).min())
    return {"months": len(months),
            "active_months": int(months.active_coins.gt(0).sum()),
            "active_coin_months": int(months.active_coins.sum()),
            "positive_months": int((returns > 0).sum()),
            "base_compounded": float(np.prod(months.base_factor) - 1),
            "stress_compounded": float(np.prod(months.stress_factor) - 1),
            "maximum_stress_daily_drawdown": drawdown,
            "two_month_block_ci_95_stress_mean": np.quantile(means, [0.025, 0.975]).tolist(),
            "monthly": months.round(8).to_dict(orient="records")}


def gate(summary: dict) -> bool:
    return (summary["months"] == 6 and summary["active_months"] >= 4
            and summary["active_coin_months"] >= 6
            and summary["positive_months"] >= 4
            and summary["stress_compounded"] > 0
            and summary["maximum_stress_daily_drawdown"] > -0.25
            and summary["two_month_block_ci_95_stress_mean"][0] > 0)


def main() -> None:
    prices = load_prices("2025-07")
    months, daily = replay(prices, START, CALIBRATION_END)
    development_mask = months.month.lt("2025-01")
    report = {"rule": "monthly BTC/ETH spot long if own 365-day lagged return is positive",
              "source": "Binance public monthly 1d spot klines",
              "assumptions": {"allocation_per_coin": ALLOCATION_PER_COIN,
                              "base_side_cost": SPOT_SIDE_COST,
                              "stress_side_cost": SPOT_SIDE_COST + EXTRA_SIDE_COST,
                              "idle_usdt_yield": 0},
              "development_2024": summarize(months.loc[development_mask],
                                            daily.loc[daily.month.lt("2025-01")]),
              "calibration_2025_h1": summarize(months.loc[~development_mask],
                                               daily.loc[daily.month.ge("2025-01")])}
    report["calibration_gate"] = gate(report["calibration_2025_h1"])
    report["later_periods_evaluated"] = False
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    months.to_parquet(ROOT / "outputs/slow_spot_trend_months.parquet", index=False)
    daily.to_parquet(ROOT / "outputs/slow_spot_trend_daily.parquet", index=False)
    print(json.dumps(report, indent=2), flush=True)
    print("saved", REPORT, flush=True)


if __name__ == "__main__":
    main()
