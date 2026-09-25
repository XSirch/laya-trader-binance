"""Exploratory weekly long/short premium carry with historical funding cash flow."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from laya_trader.config import load_config
from laya_trader.dataset.build import load_symbol_klines
from laya_trader.features.core import _aggregate_ohlcv


ROOT = Path(__file__).resolve().parents[1]
SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")
HOLD_DAYS = 7
ROUND_TRIP_COST = 0.0014
PREMIUM_MAX_AGE = pd.Timedelta(hours=3)


def load_caches() -> tuple[pd.DataFrame, pd.DataFrame]:
    premium_path = ROOT / "outputs/premium_2023_2025.parquet"
    funding_path = ROOT / "outputs/funding_2023_2025.parquet"
    if not premium_path.exists():
        from premium_probe import premium_history

        premium_history()
    if not funding_path.exists():
        from funding_probe import funding_history

        funding_history()
    premium = pd.read_parquet(premium_path)
    funding = pd.read_parquet(funding_path)
    assert set(SYMBOLS).issubset(set(premium.symbol.unique()))
    assert set(SYMBOLS).issubset(set(funding.symbol.unique()))
    return premium, funding


def load_hourly_prices() -> dict[str, pd.DataFrame]:
    cfg = load_config(ROOT / "configs/dataset.toml")
    prices = {}
    for symbol in SYMBOLS:
        raw = load_symbol_klines(cfg, symbol)
        raw = raw.loc[
            (raw.timestamp >= pd.Timestamp("2023-01-01", tz="UTC"))
            & (raw.timestamp < pd.Timestamp("2026-01-01", tz="UTC"))
        ].copy()
        complete = raw.groupby(raw.timestamp.dt.floor("1h")).size().eq(4)
        hourly = _aggregate_ohlcv(raw, "1h")
        hourly = hourly.loc[hourly.timestamp.dt.floor("1h").map(complete)].copy()
        hourly = hourly.sort_values("timestamp").reset_index(drop=True)
        hourly["bar_start"] = hourly.timestamp.dt.floor("1h")
        hourly["segment"] = hourly.bar_start.diff().dt.total_seconds().ne(3600).cumsum()
        prices[symbol] = hourly.set_index("bar_start")
        print("price bars", symbol, len(hourly), flush=True)
    return prices


def premium_at(history: pd.DataFrame, start: pd.Timestamp) -> float | None:
    cutoff = start - pd.Timedelta(hours=1)
    pos = history.close_time.searchsorted(cutoff, side="right") - 1
    if pos < 0 or cutoff - history.iloc[pos].close_time > PREMIUM_MAX_AGE:
        return None
    value = float(history.iloc[pos].premium_8h_mean)
    return value if np.isfinite(value) else None


def week_return(
    symbol: str, direction: str, start: pd.Timestamp, end: pd.Timestamp,
    prices: dict[str, pd.DataFrame], funding: dict[str, pd.DataFrame],
) -> dict | None:
    bars = prices[symbol]
    if start not in bars.index or end not in bars.index:
        return None
    first, last = bars.index.get_indexer([start, end])
    if last - first != 24 * HOLD_DAYS:
        return None
    if bars.iloc[first].segment != bars.iloc[last].segment:
        return None
    entry, exit_ = float(bars.iloc[first].open), float(bars.iloc[last].open)
    if entry <= 0 or exit_ <= 0:
        return None
    events = funding[symbol]
    settled = events.loc[(events.calc_time > start) & (events.calc_time < end)]
    if len(settled) < 15:
        return None
    price_return = (exit_ / entry - 1) * (1 if direction == "long" else -1)
    funding_return = float(settled.last_funding_rate.sum()) * (-1 if direction == "long" else 1)
    return {
        "symbol": symbol, "direction": direction,
        "price_return": price_return, "funding_return": funding_return,
        "funding_events": len(settled),
        "net_return": price_return + funding_return - ROUND_TRIP_COST,
    }


def build_weeks() -> pd.DataFrame:
    premium, funding = load_caches()
    prices = load_hourly_prices()
    premium_by_symbol = {
        symbol: premium.loc[premium.symbol == symbol].sort_values("close_time")
        for symbol in SYMBOLS
    }
    funding_by_symbol = {
        symbol: funding.loc[funding.symbol == symbol].sort_values("calc_time")
        for symbol in SYMBOLS
    }
    weeks = []
    starts = pd.date_range("2023-01-02", "2025-12-22", freq="W-MON", tz="UTC")
    for start in starts:
        end = start + pd.Timedelta(days=HOLD_DAYS)
        spread = {symbol: premium_at(premium_by_symbol[symbol], start) for symbol in SYMBOLS}
        if any(value is None for value in spread.values()):
            continue
        long_symbol = min(spread, key=spread.get)
        short_symbol = max(spread, key=spread.get)
        if long_symbol == short_symbol:
            continue
        long = week_return(long_symbol, "long", start, end, prices, funding_by_symbol)
        short = week_return(short_symbol, "short", start, end, prices, funding_by_symbol)
        if long is None or short is None:
            continue
        weeks.append({
            "start": start, "end": end,
            "long_symbol": long_symbol, "short_symbol": short_symbol,
            "premium_spread": spread[short_symbol] - spread[long_symbol],
            "price_return": (long["price_return"] + short["price_return"]) / 2,
            "funding_return": (long["funding_return"] + short["funding_return"]) / 2,
            "net_return": (long["net_return"] + short["net_return"]) / 2,
            "funding_events_long": long["funding_events"],
            "funding_events_short": short["funding_events"],
        })
    result = pd.DataFrame(weeks)
    print("complete weekly portfolios", len(result), flush=True)
    return result


def metrics(frame: pd.DataFrame) -> dict:
    monthly = frame.groupby(frame.start.dt.strftime("%Y-%m")).net_return.sum()
    net = frame.net_return.to_numpy()
    equity = np.cumprod(1 + net)
    drawdown = equity / np.maximum.accumulate(np.r_[1.0, equity])[1:] - 1
    return {
        "weeks": len(frame),
        "mean_weekly_return": round(float(net.mean()), 6),
        "total_compounded_return": round(float(equity[-1] - 1), 5),
        "mean_price_return": round(float(frame.price_return.mean()), 6),
        "mean_funding_return": round(float(frame.funding_return.mean()), 6),
        "mean_with_extra_4bps": round(float((net - 0.0004).mean()), 6),
        "positive_months": int((monthly > 0).sum()),
        "months": len(monthly),
        "max_drawdown": round(float(drawdown.min()), 5),
        "monthly_return": monthly.round(5).to_dict(),
    }


def main() -> None:
    weeks = build_weeks()
    cutoffs = {
        "train": ("2023-01-01", "2024-12-31"),
        "calibration": ("2025-01-01", "2025-06-30"),
        "validation": ("2025-07-01", "2025-12-31"),
    }
    splits = {}
    for name, (begin, last_day) in cutoffs.items():
        begin_ts = pd.Timestamp(begin, tz="UTC")
        end_ts = pd.Timestamp(last_day, tz="UTC") + pd.Timedelta(days=1)
        splits[name] = weeks.loc[(weeks.start >= begin_ts) & (weeks.end <= end_ts)].copy()
    report = {
        "hypothesis": "Monday UTC, long lowest and short highest lagged 8h premium among five majors, hold seven days, include realized funding, 14 bps round trip per leg",
        "train": metrics(splits["train"]),
        "calibration": metrics(splits["calibration"]),
    }
    cal = report["calibration"]
    eligible = (
        cal["weeks"] >= 20 and cal["mean_weekly_return"] > 0
        and cal["mean_with_extra_4bps"] > 0 and cal["positive_months"] >= 4
    )
    report["calibration_gate"] = eligible
    report["validation"] = metrics(splits["validation"]) if eligible else None
    weeks.to_parquet(ROOT / "outputs/carry_probe_weeks.parquet", index=False)
    output = ROOT / "outputs/carry_probe_report.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    print("saved", output, flush=True)


if __name__ == "__main__":
    main()
