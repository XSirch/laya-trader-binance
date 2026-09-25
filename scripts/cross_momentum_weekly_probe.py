"""Research-only weekly cross-sectional momentum with realized funding."""

from __future__ import annotations

import json
from datetime import timedelta

import numpy as np
import pandas as pd

from cross_basis_daily_probe import (
    FUNDING_CACHE,
    ROOT,
    ROUND_TRIP_COST,
    SYMBOLS,
    load_daily_prices,
    market_history,
)
from laya_trader.progress import ProgressReporter


LOOKBACK_DAYS = 30
HOLD_DAYS = 7
RANK_SIZE = 5
EXTRA_COST = 0.0004


def available_signal(bars: pd.DataFrame, start: pd.Timestamp) -> float | None:
    old = start - timedelta(days=LOOKBACK_DAYS + 1)
    recent = start - timedelta(days=1)
    if old not in bars.index or recent not in bars.index or start not in bars.index:
        return None
    first, last = bars.index.get_indexer([old, recent])
    if last - first != LOOKBACK_DAYS or bars.iloc[first].segment != bars.iloc[last].segment:
        return None
    old_open, recent_open = float(bars.at[old, "open"]), float(bars.at[recent, "open"])
    if old_open <= 0 or recent_open <= 0:
        return None
    return recent_open / old_open - 1


def leg_return(
    symbol: str,
    direction: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    prices: dict[str, pd.DataFrame],
    funding: dict[str, pd.DataFrame],
) -> tuple[float, float] | None:
    bars = prices[symbol]
    if start not in bars.index or end not in bars.index:
        return None
    first, last = bars.index.get_indexer([start, end])
    if last - first != HOLD_DAYS or bars.iloc[first].segment != bars.iloc[last].segment:
        return None
    entry, exit_ = float(bars.iloc[first].open), float(bars.iloc[last].open)
    if entry <= 0 or exit_ <= 0:
        return None
    settled = funding[symbol].loc[
        (funding[symbol].calc_time > start) & (funding[symbol].calc_time < end)
    ]
    if settled.empty:
        return None
    side = 1 if direction == "long" else -1
    price_return = side * (exit_ / entry - 1)
    funding_return = -side * float(settled.last_funding_rate.sum())
    return price_return, funding_return


def portfolios(first_start: str, last_start: str) -> pd.DataFrame:
    if not FUNDING_CACHE.is_file():
        market_history()
    funding = pd.read_parquet(FUNDING_CACHE)
    funding = {
        symbol: funding.loc[funding.symbol == symbol].sort_values("calc_time")
        for symbol in SYMBOLS
    }
    prices = load_daily_prices()
    starts = pd.date_range(first_start, last_start, freq="W-MON", tz="UTC")
    progress = ProgressReporter("momentum portfolios", len(starts), unit="weeks")
    rows = []
    for count, start in enumerate(starts, 1):
        end = start + timedelta(days=HOLD_DAYS)
        signals = {
            symbol: value
            for symbol in SYMBOLS
            if (value := available_signal(prices[symbol], start)) is not None
        }
        if len(signals) < 2 * RANK_SIZE:
            progress.update(count)
            continue
        ranked = sorted(signals, key=lambda symbol: (signals[symbol], symbol))
        longs, shorts = ranked[-RANK_SIZE:], ranked[:RANK_SIZE]
        legs = [leg_return(symbol, "long", start, end, prices, funding) for symbol in longs]
        legs += [leg_return(symbol, "short", start, end, prices, funding) for symbol in shorts]
        if any(leg is None for leg in legs):
            progress.update(count)
            continue
        rows.append({
            "start": start,
            "end": end,
            "eligible_symbols": len(signals),
            "long_symbols": ",".join(longs),
            "short_symbols": ",".join(shorts),
            "price_return": float(np.mean([leg[0] for leg in legs])),
            "funding_return": float(np.mean([leg[1] for leg in legs])),
            "net_return": float(np.mean([leg[0] + leg[1] for leg in legs]) - ROUND_TRIP_COST),
        })
        progress.update(count)
    print("complete weekly portfolios", len(rows), flush=True)
    return pd.DataFrame(rows)


def metrics(frame: pd.DataFrame) -> dict:
    net = frame.net_return.to_numpy()
    equity = np.cumprod(1 + net)
    drawdown = equity / np.maximum.accumulate(np.r_[1.0, equity])[1:] - 1
    months = frame.groupby(frame.start.dt.strftime("%Y-%m")).net_return.sum()
    return {
        "weeks": len(frame),
        "mean_weekly_return": round(float(net.mean()), 7),
        "total_compounded_return": round(float(equity[-1] - 1), 5),
        "mean_price_return": round(float(frame.price_return.mean()), 7),
        "mean_funding_return": round(float(frame.funding_return.mean()), 7),
        "mean_with_extra_4bps": round(float(net.mean() - EXTRA_COST), 7),
        "positive_months": int((months > 0).sum()),
        "months": len(months),
        "max_drawdown": round(float(drawdown.min()), 5),
        "monthly_return": months.round(5).to_dict(),
    }


def optimistic_turnover_metrics(frame: pd.DataFrame) -> dict:
    """Lower-bound fees: retained names incur no resizing cost between weeks."""
    ordered = frame.sort_values("start").copy()
    previous: set[tuple[str, str]] = set()
    fees = []
    stress_fees = []
    for row in ordered.itertuples():
        current = {("long", symbol) for symbol in row.long_symbols.split(",")}
        current |= {("short", symbol) for symbol in row.short_symbols.split(",")}
        turnover = 0.1 * len(current.symmetric_difference(previous))
        fees.append(0.0007 * turnover)
        stress_fees.append(0.0002 * turnover)
        previous = current
    fees[-1] += 0.0007
    stress_fees[-1] += 0.0002
    gross = ordered.price_return.to_numpy() + ordered.funding_return.to_numpy()
    net = gross - np.asarray(fees)
    equity = np.cumprod(1 + net)
    drawdown = equity / np.maximum.accumulate(np.r_[1.0, equity])[1:] - 1
    monthly = pd.Series(net, index=ordered.start.dt.strftime("%Y-%m")).groupby(level=0).sum()
    gross_monthly = pd.Series(gross, index=ordered.start.dt.strftime("%Y-%m")).groupby(level=0).sum()
    return {
        "mean_weekly_return": round(float(net.mean()), 7),
        "total_compounded_return": round(float(equity[-1] - 1), 5),
        "mean_fee": round(float(np.mean(fees)), 7),
        "mean_with_extra_4bps": round(float((net - stress_fees).mean()), 7),
        "positive_months": int((monthly > 0).sum()),
        "zero_fee_positive_months": int((gross_monthly > 0).sum()),
        "months": len(monthly),
        "max_drawdown": round(float(drawdown.min()), 5),
        "monthly_return": monthly.round(5).to_dict(),
    }


def main() -> None:
    early = portfolios("2023-02-06", "2025-06-23")
    train = early.loc[early.end <= pd.Timestamp("2025-01-01", tz="UTC")]
    calibration = early.loc[
        (early.start >= pd.Timestamp("2025-01-01", tz="UTC"))
        & (early.end <= pd.Timestamp("2025-07-01", tz="UTC"))
    ]
    report = {
        "hypothesis": "weekly long top five and short bottom five trailing 30-day returns, one-day signal lag, equal gross weights, realized funding, 14 bps round trip per leg",
        "train": metrics(train),
        "calibration": metrics(calibration),
        "optimistic_turnover_train": optimistic_turnover_metrics(train),
        "optimistic_turnover_calibration": optimistic_turnover_metrics(calibration),
    }
    cal = report["calibration"]
    passes = (
        cal["weeks"] >= 20
        and cal["mean_weekly_return"] > 0
        and cal["mean_with_extra_4bps"] > 0
        and cal["positive_months"] >= 4
        and cal["max_drawdown"] > -0.25
    )
    report["calibration_gate"] = passes
    if passes:
        later = portfolios("2025-07-07", "2025-12-22")
        report["validation"] = metrics(later)
        early = pd.concat([early, later], ignore_index=True)
    else:
        report["validation"] = None
    early.to_parquet(ROOT / "outputs/cross_momentum_weekly_portfolios.parquet", index=False)
    output = ROOT / "outputs/cross_momentum_weekly_report.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    print("saved", output, flush=True)


if __name__ == "__main__":
    main()
