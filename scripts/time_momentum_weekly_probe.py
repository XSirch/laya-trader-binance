"""Research-only weekly time-series momentum across configured perpetuals."""

from __future__ import annotations

import json
import sys
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
from cross_momentum_weekly_probe import available_signal, leg_return, metrics
from laya_trader.progress import ProgressReporter


EXTRA_COST = 0.0004
INVERSE_VOL = "--inverse-vol" in sys.argv


def trailing_volatility(bars: pd.DataFrame, start: pd.Timestamp) -> float | None:
    old = start - timedelta(days=31)
    recent = start - timedelta(days=1)
    history = bars.loc[old:recent, "open"].to_numpy(dtype=float)
    if len(history) != 31 or not np.isfinite(history).all() or (history <= 0).any():
        return None
    volatility = float(np.diff(np.log(history)).std(ddof=1))
    return volatility if volatility > 0 else None


def portfolios(first_start: str, last_start: str) -> pd.DataFrame:
    if not FUNDING_CACHE.is_file():
        market_history()
    all_funding = pd.read_parquet(FUNDING_CACHE)
    funding = {
        symbol: all_funding.loc[all_funding.symbol == symbol].sort_values("calc_time")
        for symbol in SYMBOLS
    }
    prices = load_daily_prices()
    starts = pd.date_range(first_start, last_start, freq="W-MON", tz="UTC")
    task = "inverse-vol momentum" if INVERSE_VOL else "time momentum portfolios"
    progress = ProgressReporter(task, len(starts), unit="weeks")
    rows = []
    for count, start in enumerate(starts, 1):
        end = start + timedelta(days=7)
        signals = {
            symbol: value
            for symbol in SYMBOLS
            if (value := available_signal(prices[symbol], start)) is not None
        }
        if INVERSE_VOL:
            volatilities = {
                symbol: value
                for symbol in signals
                if (value := trailing_volatility(prices[symbol], start)) is not None
            }
            signals = {symbol: signal for symbol, signal in signals.items()
                       if symbol in volatilities}
        if len(signals) < 10:
            progress.update(count)
            continue
        if INVERSE_VOL:
            inverse_vol = {symbol: 1 / volatilities[symbol] for symbol in signals}
            scale = sum(inverse_vol.values())
            weights = {symbol: value / scale for symbol, value in inverse_vol.items()}
        else:
            weights = {symbol: 1 / len(signals) for symbol in signals}
        sides = {symbol: ("long" if value > 0 else "short") for symbol, value in signals.items()}
        legs = {
            symbol: leg_return(symbol, side, start, end, prices, funding)
            for symbol, side in sides.items()
        }
        if any(leg is None for leg in legs.values()):
            progress.update(count)
            continue
        rows.append({
            "start": start,
            "end": end,
            "symbols": len(sides),
            "long_symbols": ",".join(symbol for symbol, side in sides.items() if side == "long"),
            "short_symbols": ",".join(symbol for symbol, side in sides.items() if side == "short"),
            "max_weight": max(weights.values()),
            "price_return": float(sum(weights[symbol] * leg[0] for symbol, leg in legs.items())),
            "funding_return": float(sum(weights[symbol] * leg[1] for symbol, leg in legs.items())),
            "net_return": float(sum(weights[symbol] * sum(leg)
                                    for symbol, leg in legs.items()) - ROUND_TRIP_COST),
        })
        progress.update(count)
    print("complete weekly portfolios", len(rows), flush=True)
    return pd.DataFrame(rows)


def summary(frame: pd.DataFrame) -> dict:
    result = metrics(frame)
    weekly = frame.net_return.to_numpy()
    block = 4
    rng = np.random.default_rng(42)
    starts = rng.integers(0, len(weekly), size=(10_000, (len(weekly) + block - 1) // block))
    samples = weekly[(starts[:, :, None] + np.arange(block)) % len(weekly)]
    means = samples.reshape(10_000, -1)[:, :len(weekly)].mean(axis=1)
    result["four_week_block_ci_95_mean"] = np.quantile(means, [0.025, 0.975]).round(7).tolist()
    gross = frame.price_return + frame.funding_return
    monthly = gross.groupby(frame.start.dt.strftime("%Y-%m")).sum()
    result["zero_fee_positive_months"] = int((monthly > 0).sum())
    result["yearly_compounded_return"] = frame.groupby(
        frame.start.dt.strftime("%Y")
    ).net_return.agg(lambda values: float(np.prod(1 + values) - 1)).round(5).to_dict()
    result["mean_max_weight"] = round(float(frame.max_weight.mean()), 5)
    return result


def main() -> None:
    early = portfolios("2023-02-06", "2025-06-23")
    train = early.loc[early.end <= pd.Timestamp("2025-01-01", tz="UTC")]
    calibration = early.loc[
        (early.start >= pd.Timestamp("2025-01-01", tz="UTC"))
        & (early.end <= pd.Timestamp("2025-07-01", tz="UTC"))
    ]
    report = {
        "hypothesis": "weekly sign of each symbol's lagged 30-day return, one-day lag, realized funding, 14 bps round trip per leg",
        "weighting": "inverse trailing 30-day daily volatility" if INVERSE_VOL else "equal gross weights",
        "train": summary(train),
        "calibration": summary(calibration),
    }
    cal = report["calibration"]
    passes = (
        cal["weeks"] >= 20
        and cal["mean_weekly_return"] > 0
        and cal["mean_with_extra_4bps"] > 0
        and cal["four_week_block_ci_95_mean"][0] > 0
        and cal["positive_months"] >= 4
        and cal["max_drawdown"] > -0.25
    )
    report["calibration_gate"] = passes
    if passes:
        validation = portfolios("2025-07-07", "2025-12-22")
        report["validation"] = summary(validation)
        early = pd.concat([early, validation], ignore_index=True)
    else:
        report["validation"] = None
    name = "time_momentum_inverse_vol_weekly" if INVERSE_VOL else "time_momentum_weekly"
    early.to_parquet(ROOT / f"outputs/{name}_portfolios.parquet", index=False)
    output = ROOT / f"outputs/{name}_report.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    print("saved", output, flush=True)


if __name__ == "__main__":
    main()
