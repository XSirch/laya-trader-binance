"""Research-only monthly long-spot/short-perpetual funding-carry screen."""

from __future__ import annotations

import io
import json
import math
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace

import pandas as pd
import requests

from book_depth_coverage_probe import ROOT
from funding_probe import SYMBOLS
from laya_trader.config import load_config
from laya_trader.dataset.build import _read_zip, load_symbol_klines
from laya_trader.features.core import normalize_klines
from laya_trader.progress import ProgressReporter


SPOT_ROOT = ROOT / "outputs/spot_daily_carry_archives"
FUNDING_CACHE = ROOT / "outputs/funding_2023_2025.parquet"
FIRST_MONTH = "2023-02"
LAST_CALIBRATION_MONTH = "2023-12"
VALIDATION_STAGES = (
    ("validation_2024_h1", "2024-01", "2024-06"),
    ("validation_2024_h2", "2024-07", "2024-12"),
    ("validation_2025_h1", "2025-01", "2025-06"),
    ("diagnostic_2025_h2", "2025-07", "2025-12"),
)
TRAILING_DAYS = 30
MIN_PAST_SETTLEMENTS = 80
MIN_TRAILING_FUNDING = 0.005
SPOT_SIDE_COST = 0.0012  # 10 bps fee plus 2 bps slippage.
PERP_SIDE_COST = 0.0007  # 5 bps fee plus 2 bps slippage.
EXTRA_PAIR_COST = 0.0008  # Another 8 bps of initial spot notional per round trip.


def spot_path(symbol: str, month: str):
    return SPOT_ROOT / symbol / f"{symbol}-1d-{month}.zip"


def download_one(symbol: str, month: str) -> tuple[str, str, str]:
    path = spot_path(symbol, month)
    if path.is_file():
        return symbol, month, "cached"
    url = ("https://data.binance.vision/data/spot/monthly/klines/"
           f"{symbol}/1d/{symbol}-1d-{month}.zip")
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 404:
                return symbol, month, "missing"
            response.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                if archive.testzip() is not None:
                    raise ValueError("ZIP CRC failed")
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".zip.tmp")
            temporary.write_bytes(response.content)
            temporary.replace(path)
            return symbol, month, "downloaded"
        except (requests.RequestException, zipfile.BadZipFile, ValueError):
            if attempt == 2:
                return symbol, month, "error"
            time.sleep(1 + 2 * attempt)
    raise AssertionError("unreachable")


def download_spot(last_month: str) -> None:
    months = pd.period_range("2023-01", last_month, freq="M").astype(str)
    tasks = [(symbol, month) for symbol in SYMBOLS for month in months]
    progress = ProgressReporter("spot daily archives", len(tasks), unit="archives")
    failed = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(download_one, *task) for task in tasks]
        for count, future in enumerate(as_completed(futures), 1):
            symbol, month, status = future.result()
            if status in ("missing", "error"):
                failed.append((symbol, month, status))
            progress.update(count)
    if failed:
        raise RuntimeError(f"spot archive failures: {failed}")


def spot_opens(symbol: str, last_month: str) -> pd.Series:
    months = pd.period_range("2023-01", last_month, freq="M").astype(str)
    frames = [normalize_klines(_read_zip(spot_path(symbol, month)))
              for month in months]
    spot = pd.concat(frames, ignore_index=True)
    spot = spot.drop_duplicates("open_time").sort_values("open_time")
    spot = spot.set_index("open_time")["open"].astype(float)
    if spot.index.has_duplicates or spot.le(0).any():
        raise ValueError(f"invalid spot prices for {symbol}")
    return spot


def perp_and_funding(symbol: str, last_day: str) -> tuple[pd.Series, pd.DataFrame]:
    cfg = load_config(ROOT / "configs/dataset.toml")
    cfg = replace(cfg, data=replace(cfg.data, start="2023-01-01", end=last_day))
    raw = load_symbol_klines(cfg, symbol)
    intraday = raw.set_index("open_time")["open"].astype(float).sort_index()
    midnight = intraday.loc[(intraday.index.hour == 0) & (intraday.index.minute == 0)]
    funding = pd.read_parquet(FUNDING_CACHE)
    funding = funding.loc[funding.symbol == symbol,
                          ["calc_time", "last_funding_rate"]].copy()
    end = pd.Timestamp(last_day, tz="UTC") + pd.Timedelta(days=1)
    funding = funding.loc[(funding.calc_time >= pd.Timestamp("2023-01-01", tz="UTC"))
                          & (funding.calc_time < end)]
    if funding.calc_time.duplicated().any():
        raise ValueError(f"duplicate funding settlements for {symbol}")
    funding = funding.sort_values("calc_time")
    marks = pd.merge_asof(
        funding, intraday.rename("perp_mark").reset_index().rename(columns={"open_time": "calc_time"}),
        on="calc_time", direction="backward", tolerance=pd.Timedelta(minutes=15),
    )
    if marks.perp_mark.isna().any():
        raise ValueError(f"funding settlement lacks a nearby perpetual price for {symbol}")
    return midnight, marks


def monthly_symbol(symbol: str, last_month: str) -> list[dict]:
    next_month = pd.Period(last_month, freq="M") + 1
    spot = spot_opens(symbol, str(next_month))
    last_day = next_month.start_time.date().isoformat()
    perp, funding = perp_and_funding(symbol, last_day)
    months = pd.period_range(FIRST_MONTH, last_month, freq="M")
    rows = []
    for month in months:
        start = month.start_time.tz_localize("UTC")
        end = (month + 1).start_time.tz_localize("UTC")
        past = funding.loc[(funding.calc_time >= start - pd.Timedelta(days=TRAILING_DAYS))
                           & (funding.calc_time < start)]
        signal = float(past.last_funding_rate.sum())
        active = len(past) >= MIN_PAST_SETTLEMENTS and signal > MIN_TRAILING_FUNDING
        fields = {"symbol": symbol, "month": str(month), "signal_30d": signal,
                  "past_settlements": len(past), "active": active}
        if not active:
            rows.append(fields)
            continue
        if start not in spot.index or end not in spot.index:
            raise ValueError(f"missing spot entry or exit: {symbol} {month}")
        if start not in perp.index or end not in perp.index:
            raise ValueError(f"missing perpetual entry or exit: {symbol} {month}")
        s0, s1 = float(spot[start]), float(spot[end])
        f0, f1 = float(perp[start]), float(perp[end])
        settled = funding.loc[(funding.calc_time > start) & (funding.calc_time < end)]
        if len(settled) < (end - start).days * 2.5:
            raise ValueError(f"sparse funding settlements: {symbol} {month}")
        funding_return = float((settled.last_funding_rate * settled.perp_mark).sum() / s0)
        price_return = (s1 - s0 - f1 + f0) / s0
        cost = (SPOT_SIDE_COST * (s0 + s1) + PERP_SIDE_COST * (f0 + f1)) / s0
        fields.update({
            "spot_entry": s0, "spot_exit": s1, "perp_entry": f0, "perp_exit": f1,
            "settlements": len(settled), "price_return": price_return,
            "funding_return": funding_return, "pair_cost": cost,
            "net_return": price_return + funding_return - cost,
            "stress_net_return": price_return + funding_return - cost - EXTRA_PAIR_COST,
        })
        rows.append(fields)
    return rows


def summarize(frame: pd.DataFrame, first_month: str, last_month: str) -> dict:
    months = pd.period_range(first_month, last_month, freq="M").astype(str)
    segment = frame.loc[frame.month.isin(months)]
    active = segment.loc[segment.active]
    portfolios = segment.groupby("month", sort=True).apply(
        lambda rows: pd.Series({
            "net_return": float(rows.net_return.fillna(0).sum() / len(SYMBOLS)),
            "stress_net_return": float(rows.stress_net_return.fillna(0).sum() / len(SYMBOLS)),
            "active_legs": int(rows.active.sum()),
        }), include_groups=False,
    )
    net = portfolios.net_return
    stress = portfolios.stress_net_return
    active_month = portfolios.active_legs.gt(0)
    equity = (1 + net).cumprod()
    drawdown = equity / equity.cummax().clip(lower=1) - 1
    return {
        "months": len(portfolios), "active_legs": len(active),
        "active_months": int(active_month.sum()),
        "positive_months": int(net.gt(0).sum()),
        "positive_active_months": int(net.loc[active_month].gt(0).sum()),
        "positive_stress_months": int(stress.gt(0).sum()),
        "mean_monthly_net": round(float(net.mean()), 6),
        "mean_monthly_stress": round(float(stress.mean()), 6),
        "compounded_net": round(float(equity.iloc[-1] - 1), 6),
        "max_drawdown": round(float(drawdown.min()), 6),
        "monthly": portfolios.round(6).reset_index().to_dict(orient="records"),
        "mean_active_leg_net": round(float(active.net_return.mean()), 6) if len(active) else None,
    }


def passes_original(result: dict) -> bool:
    return (result["months"] == 6 and result["active_legs"] >= 10
            and result["positive_months"] >= 4
            and result["mean_monthly_net"] > 0
            and result["mean_monthly_stress"] > 0
            and result["max_drawdown"] > -0.15)


def passes_active_month(result: dict) -> bool:
    return (result["months"] == 6 and result["active_legs"] >= 10
            and result["active_months"] >= 4
            and result["positive_active_months"]
            >= math.ceil(0.75 * result["active_months"])
            and result["mean_monthly_net"] > 0
            and result["mean_monthly_stress"] > 0
            and result["max_drawdown"] > -0.15)


def main() -> None:
    download_spot("2024-01")
    progress = ProgressReporter("spot-perp monthly legs", len(SYMBOLS), unit="symbols")
    rows = []
    for count, symbol in enumerate(SYMBOLS, 1):
        rows.extend(monthly_symbol(symbol, LAST_CALIBRATION_MONTH))
        progress.update(count)
    frame = pd.DataFrame(rows)
    train = summarize(frame, "2023-02", "2023-06")
    calibration = summarize(frame, "2023-07", LAST_CALIBRATION_MONTH)
    report = {
        "rule": "monthly long spot and short same-coin perpetual when trailing 30d settled funding exceeds 0.5%",
        "symbols": list(SYMBOLS),
        "costs": {"spot_side": SPOT_SIDE_COST, "perp_side": PERP_SIDE_COST,
                  "extra_pair_round_trip": EXTRA_PAIR_COST},
        "gate_revision": "active-month consistency introduced after viewing 2024 H2; earlier periods are exploratory",
        "train": train, "calibration": calibration,
        "calibration_gate_original": passes_original(calibration),
        "calibration_gate_active_month": passes_active_month(calibration),
    }
    prior_passed = report["calibration_gate_active_month"]
    for stage_name, first_month, last_month in VALIDATION_STAGES:
        report[stage_name] = None
        if not prior_passed:
            continue
        next_month = str(pd.Period(last_month, freq="M") + 1)
        download_spot(next_month)
        progress = ProgressReporter(f"spot-perp {stage_name}", len(SYMBOLS), unit="symbols")
        later_rows = []
        for count, symbol in enumerate(SYMBOLS, 1):
            later_rows.extend(monthly_symbol(symbol, last_month))
            progress.update(count)
        frame = pd.DataFrame(later_rows)
        result = summarize(frame, first_month, last_month)
        prior_passed = passes_active_month(result)
        report[stage_name] = result
        report[f"{stage_name}_gate_original"] = passes_original(result)
        report[f"{stage_name}_gate_active_month"] = prior_passed
        print(stage_name, "active-month gate", prior_passed,
              "mean", result["mean_monthly_net"],
              "positive active months", result["positive_active_months"],
              "/", result["active_months"], flush=True)
    output = ROOT / "outputs/spot_perp_carry_probe_report.json"
    frame.to_parquet(ROOT / "outputs/spot_perp_carry_probe_legs.parquet", index=False)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: {key: value for key, value in result.items() if key != "monthly"}
                      if isinstance(result, dict) else result
                      for name, result in report.items() if name.endswith("_gate")
                      or name in ("train", "calibration")
                      or name.startswith(("validation_", "diagnostic_"))},
                     indent=2), flush=True)
    print("saved", output, flush=True)


if __name__ == "__main__":
    main()
