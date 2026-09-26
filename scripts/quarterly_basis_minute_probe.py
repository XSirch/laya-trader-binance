"""Adverse synchronized one-minute execution screen for quarterly basis pairs."""

from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

from laya_trader.dataset.build import _read_zip
from laya_trader.features.core import normalize_klines
from laya_trader.progress import ProgressReporter
from quarterly_basis_probe import FUTURES_MARGIN, SPOT_CASH
from spot_perp_carry_probe import PERP_SIDE_COST, ROOT, SPOT_SIDE_COST


ARCHIVES = ROOT / "outputs/quarterly_minute_archives"
EXTRA_SIDE_COST = 0.0002  # 8 bps per pair round trip, across four sides.
FURTHER_SPOT_SIDE_COST = 0.0005
FURTHER_FUTURES_SIDE_COST = 0.0010
MAX_DELAY_MINUTES = 5
EXAMPLE_ACCOUNT_USDT = 1000.0


def archive_path(market: str, name: str, day: str) -> Path:
    return ARCHIVES / market / name / f"{name}-1m-{day}.zip"


def archive_url(market: str, name: str, day: str) -> str:
    path = ("spot" if market == "spot" else "futures/um")
    return (f"https://data.binance.vision/data/{path}/daily/klines/"
            f"{name}/1m/{name}-1m-{day}.zip")


def fetch_one(market: str, name: str, day: str) -> tuple[str, str, str, str]:
    path = archive_path(market, name, day)
    if path.is_file():
        return market, name, day, "cached"
    url = archive_url(market, name, day)
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 404:
                return market, name, day, "missing"
            response.raise_for_status()
            checksum = requests.get(url + ".CHECKSUM", timeout=20)
            checksum.raise_for_status()
            expected = checksum.text.split()[0].lower()
            if hashlib.sha256(response.content).hexdigest() != expected:
                raise ValueError(f"SHA256 mismatch: {market} {name} {day}")
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                if archive.testzip() is not None:
                    raise ValueError(f"ZIP CRC failed: {market} {name} {day}")
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".zip.tmp")
            temporary.write_bytes(response.content)
            temporary.replace(path)
            return market, name, day, "downloaded"
        except (requests.RequestException, zipfile.BadZipFile, ValueError, IndexError):
            if attempt == 2:
                return market, name, day, "error"
            time.sleep(1 + 2 * attempt)
    raise AssertionError("unreachable")


def first_minutes(market: str, name: str, day: str) -> pd.DataFrame:
    frame = normalize_klines(_read_zip(archive_path(market, name, day)))
    start = pd.Timestamp(day, tz="UTC")
    end = start + pd.Timedelta(minutes=MAX_DELAY_MINUTES)
    result = frame.loc[(frame.open_time >= start) & (frame.open_time < end),
                       ["open_time", "open", "high", "low", "volume", "quote_volume"]]
    if result.empty:
        raise ValueError(f"no trades in first {MAX_DELAY_MINUTES} minutes: {market} {name} {day}")
    return result.set_index("open_time")


def leg_result(leg, bars: dict) -> dict:
    quarter, symbol, contract = leg.quarter, leg.symbol, leg.contract
    observations = {}
    for side, instant in (("entry", leg.entry), ("exit", leg.exit)):
        day = pd.Timestamp(instant).strftime("%Y-%m-%d")
        spot = bars[("spot", symbol, day)]
        future = bars[("future", contract, day)]
        common = spot.index.intersection(future.index).sort_values()
        if common.empty:
            raise ValueError(f"no common traded minute: {contract} {day}")
        moment = common[0]
        observations[side] = (moment, spot.loc[moment], future.loc[moment])
    entry_time, entry_spot, entry_future = observations["entry"]
    exit_time, exit_spot, exit_future = observations["exit"]
    s0, f0 = float(entry_spot.high), float(entry_future.low)
    s1, f1 = float(exit_spot.low), float(exit_future.high)
    if min(s0, f0, s1, f1) <= 0:
        raise ValueError(f"nonpositive minute price: {contract} {quarter}")
    q = 0.5 / s0
    price_cash = q * (s1 - s0 - f1 + f0)
    trade_cost = q * (SPOT_SIDE_COST * (s0 + s1)
                      + PERP_SIDE_COST * (f0 + f1))
    stress_cost = q * EXTRA_SIDE_COST * (s0 + s1 + f0 + f1)
    further_cost = q * (FURTHER_SPOT_SIDE_COST * (s0 + s1)
                        + FURTHER_FUTURES_SIDE_COST * (f0 + f1))
    account_scale = EXAMPLE_ACCOUNT_USDT / (SPOT_CASH + FUTURES_MARGIN)
    return {
        "quarter": quarter, "symbol": symbol, "contract": contract,
        "entry_time": entry_time, "exit_time": exit_time,
        "entry_delay_min": int((entry_time - pd.Timestamp(leg.entry)).total_seconds() / 60),
        "exit_delay_min": int((exit_time - pd.Timestamp(leg.exit)).total_seconds() / 60),
        "spot_entry_adverse": s0, "future_entry_adverse": f0,
        "spot_exit_adverse": s1, "future_exit_adverse": f1,
        "entry_future_volume": float(entry_future.volume),
        "exit_future_volume": float(exit_future.volume),
        "entry_spot_volume": float(entry_spot.volume),
        "exit_spot_volume": float(exit_spot.volume),
        "hypothetical_quantity_at_1000_usdt": q * account_scale,
        "net_cash": price_cash - trade_cost,
        "stress_cash": price_cash - trade_cost - stress_cost,
        "further_stress_cash": price_cash - trade_cost - stress_cost - further_cost,
    }


def main() -> None:
    legs_path = ROOT / "outputs/quarterly_basis_diagnostic_legs.parquet"
    if not legs_path.is_file():
        raise FileNotFoundError("run quarterly_basis_probe.py --diagnostic-all first")
    legs = pd.read_parquet(legs_path)
    tasks = sorted({task for leg in legs.itertuples() for task in (
        ("spot", leg.symbol, pd.Timestamp(leg.entry).strftime("%Y-%m-%d")),
        ("spot", leg.symbol, pd.Timestamp(leg.exit).strftime("%Y-%m-%d")),
        ("future", leg.contract, pd.Timestamp(leg.entry).strftime("%Y-%m-%d")),
        ("future", leg.contract, pd.Timestamp(leg.exit).strftime("%Y-%m-%d")),
    )})
    progress = ProgressReporter("quarterly 1m archives", len(tasks), unit="archives")
    failures = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(fetch_one, *task) for task in tasks]
        for count, future in enumerate(as_completed(futures), 1):
            market, name, day, status = future.result()
            if status in ("missing", "error"):
                failures.append((market, name, day, status))
            progress.update(count)
    if failures:
        raise RuntimeError(f"1m archive failures: {failures}")
    bars = {}
    progress = ProgressReporter("quarterly first 1m bars", len(tasks), unit="archives")
    for count, (market, name, day) in enumerate(tasks, 1):
        bars[(market, name, day)] = first_minutes(market, name, day)
        progress.update(count)
    rows = [leg_result(leg, bars) for leg in legs.itertuples()]
    frame = pd.DataFrame(rows)
    frame["minute_volume_covers_1000_usdt"] = (
        frame[["entry_future_volume", "exit_future_volume",
               "entry_spot_volume", "exit_spot_volume"]].min(axis=1)
        >= frame.hypothetical_quantity_at_1000_usdt
    )
    annual = frame.groupby(frame.quarter.str[:4]).agg(
        legs=("symbol", "size"),
        positive_stress_legs=("stress_cash", lambda values: int(values.gt(0).sum())),
        positive_further_stress_legs=("further_stress_cash", lambda values: int(values.gt(0).sum())),
        net_cash=("net_cash", "sum"),
        stress_cash=("stress_cash", "sum"),
        further_stress_cash=("further_stress_cash", "sum"),
        volume_covered_1000_usdt=("minute_volume_covers_1000_usdt", "sum"),
    )
    for name in ("net", "stress", "further_stress"):
        annual[f"{name}_on_initial_capital"] = annual[f"{name}_cash"] / (SPOT_CASH + FUTURES_MARGIN)
    report = {
        "source": "official daily 1m spot and USD-M delivery-future ZIPs, SHA256 and ZIP CRC checked",
        "method": "first common traded minute within five minutes of UTC decision; spot high/future low at entry, spot low/future high at exit",
        "example_account_usdt": EXAMPLE_ACCOUNT_USDT,
        "archives": len(tasks), "legs": len(frame),
        "max_entry_delay_min": int(frame.entry_delay_min.max()),
        "max_exit_delay_min": int(frame.exit_delay_min.max()),
        "minute_volume_covered_1000_usdt_legs": int(frame.minute_volume_covers_1000_usdt.sum()),
        "further_stress": {"extra_spot_bps_per_side": FURTHER_SPOT_SIDE_COST * 10_000,
                           "extra_future_bps_per_side": FURTHER_FUTURES_SIDE_COST * 10_000},
        "annual": annual.round(6).reset_index().to_dict(orient="records"),
    }
    frame.to_parquet(ROOT / "outputs/quarterly_basis_minute_legs.parquet", index=False)
    output = ROOT / "outputs/quarterly_basis_minute_report.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    print("saved", output, flush=True)


if __name__ == "__main__":
    main()
