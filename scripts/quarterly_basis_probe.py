"""Research screen of BTC/ETH spot versus USD-M quarterly delivery futures."""

from __future__ import annotations

import argparse
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
from spot_perp_carry_probe import (
    EXTRA_PAIR_COST, PERP_SIDE_COST, ROOT, SPOT_SIDE_COST,
    download_spot, spot_opens,
)


SYMBOLS = ("BTCUSDT", "ETHUSDT")
ARCHIVES = ROOT / "outputs/quarterly_basis_archives"
SPOT_ALLOCATION_PER_SYMBOL = 0.5
SPOT_CASH = 1.05
FUTURES_MARGIN = 2.0
MAINTENANCE_ASSUMPTION = 0.05
EXTRA_MARK_SHOCK = 0.10
EXTRA_SIDE_COST = EXTRA_PAIR_COST / 4


def contract_dates(quarter: pd.Period) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    first = quarter.start_time.tz_localize("UTC")
    last_calendar_day = quarter.end_time.normalize()
    last_friday = last_calendar_day - pd.Timedelta(days=(last_calendar_day.weekday() - 4) % 7)
    expiry = last_friday.tz_localize("UTC")
    exit_time = expiry - pd.Timedelta(days=2)
    return first, exit_time, expiry


def contract_name(symbol: str, expiry: pd.Timestamp) -> str:
    return f"{symbol}_{expiry.strftime('%y%m%d')}"


def archive_path(contract: str, month: str) -> Path:
    return ARCHIVES / contract / f"{contract}-1d-{month}.zip"


def download_one(contract: str, month: str) -> tuple[str, str, str]:
    path = archive_path(contract, month)
    if path.is_file():
        return contract, month, "cached"
    url = ("https://data.binance.vision/data/futures/um/monthly/klines/"
           f"{contract}/1d/{contract}-1d-{month}.zip")
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 404:
                return contract, month, "missing"
            response.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                if archive.testzip() is not None:
                    raise ValueError("ZIP CRC failed")
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".zip.tmp")
            temporary.write_bytes(response.content)
            temporary.replace(path)
            return contract, month, "downloaded"
        except (requests.RequestException, zipfile.BadZipFile, ValueError):
            if attempt == 2:
                return contract, month, "error"
            time.sleep(1 + 2 * attempt)
    raise AssertionError("unreachable")


def load_quarter(quarter: pd.Period) -> dict[str, pd.DataFrame]:
    _, _, expiry = contract_dates(quarter)
    months = pd.period_range(quarter.start_time, quarter.end_time, freq="M").astype(str)
    tasks = [(contract_name(symbol, expiry), month) for symbol in SYMBOLS for month in months]
    statuses = {}
    progress = ProgressReporter(f"quarterly archives {quarter}", len(tasks), unit="archives")
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(download_one, *task) for task in tasks]
        for count, future in enumerate(as_completed(futures), 1):
            contract, month, status = future.result()
            statuses[(contract, month)] = status
            progress.update(count)
    failed = [(contract, month, statuses[(contract, month)]) for contract, month in tasks
              if statuses[(contract, month)] not in ("cached", "downloaded")]
    if failed:
        raise ValueError(f"quarterly archives unavailable: {failed}")
    result = {}
    for symbol in SYMBOLS:
        contract = contract_name(symbol, expiry)
        pieces = [normalize_klines(_read_zip(archive_path(contract, month))) for month in months]
        raw = pd.concat(pieces, ignore_index=True)
        raw = raw.drop_duplicates("open_time").sort_values("open_time")
        result[symbol] = raw.set_index("open_time")[["open", "high"]].astype(float)
    return result


def quarter_result(quarter: pd.Period, spot: dict[str, pd.Series]) -> tuple[dict, list[dict]]:
    first, exit_time, expiry = contract_dates(quarter)
    futures = load_quarter(quarter)
    days = pd.date_range(first, exit_time, freq="D")
    legs = []
    margin_cushions = []
    for symbol in SYMBOLS:
        future = futures[symbol]
        if future.reindex(days).isna().any().any() or spot[symbol].reindex(days).isna().any():
            raise ValueError(f"missing daily prices: {symbol} {quarter}")
        s0, s1 = float(spot[symbol][first]), float(spot[symbol][exit_time])
        f0, f1 = float(future.loc[first, "open"]), float(future.loc[exit_time, "open"])
        q = SPOT_ALLOCATION_PER_SYMBOL / s0
        price_cash = q * (s1 - s0 - f1 + f0)
        entry_fee = q * (SPOT_SIDE_COST * s0 + PERP_SIDE_COST * f0)
        exit_fee = q * (SPOT_SIDE_COST * s1 + PERP_SIDE_COST * f1)
        stress_fee = q * EXTRA_SIDE_COST * (s0 + f0 + s1 + f1)
        legs.append({
            "quarter": str(quarter), "symbol": symbol,
            "contract": contract_name(symbol, expiry),
            "entry": first, "exit": exit_time,
            "spot_entry": s0, "spot_exit": s1,
            "future_entry": f0, "future_exit": f1,
            "entry_basis": f0 / s0 - 1,
            "exit_basis": f1 / s1 - 1,
            "quantity": q, "price_cash": price_cash,
            "entry_fee": entry_fee, "exit_fee": exit_fee,
            "stress_extra_fee": stress_fee,
            "net_cash": price_cash - entry_fee - exit_fee,
            "stress_net_cash": price_cash - entry_fee - exit_fee - stress_fee,
        })
    for day in days:
        futures_equity = FUTURES_MARGIN
        maintenance = 0.0
        for leg in legs:
            symbol = leg["symbol"]
            stressed_mark = float(futures[symbol].loc[day, "high"]) * (1 + EXTRA_MARK_SHOCK)
            futures_equity -= leg["quantity"] * leg["future_entry"] * PERP_SIDE_COST
            futures_equity += leg["quantity"] * (leg["future_entry"] - stressed_mark)
            maintenance += leg["quantity"] * stressed_mark * MAINTENANCE_ASSUMPTION
        margin_cushions.append(futures_equity - maintenance)
    total_capital = SPOT_CASH + FUTURES_MARGIN
    net_cash = sum(leg["net_cash"] for leg in legs)
    stress_cash = sum(leg["stress_net_cash"] for leg in legs)
    result = {
        "quarter": str(quarter), "entry": first.isoformat(), "exit": exit_time.isoformat(),
        "contracts": [leg["contract"] for leg in legs],
        "mean_entry_basis": round(sum(leg["entry_basis"] for leg in legs) / len(legs), 6),
        "mean_exit_basis": round(sum(leg["exit_basis"] for leg in legs) / len(legs), 6),
        "net_on_capital": round(net_cash / total_capital, 6),
        "stress_on_capital": round(stress_cash / total_capital, 6),
        "minimum_margin_shock_cushion": round(min(margin_cushions), 6),
    }
    return result, legs


def annual_summary(rows: list[dict]) -> dict:
    return {
        "quarters": len(rows),
        "positive_stress_quarters": sum(row["stress_on_capital"] > 0 for row in rows),
        "net_on_capital": round(sum(row["net_on_capital"] for row in rows), 6),
        "stress_on_capital": round(sum(row["stress_on_capital"] for row in rows), 6),
        "minimum_margin_shock_cushion": min(row["minimum_margin_shock_cushion"] for row in rows),
        "quarterly": rows,
    }


def passes(summary: dict) -> bool:
    return (summary["quarters"] == 4 and summary["positive_stress_quarters"] >= 3
            and summary["stress_on_capital"] >= 0.02
            and summary["minimum_margin_shock_cushion"] > 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnostic-all", action="store_true",
                        help="inspect later years even when the 2023 selection gate failed")
    args = parser.parse_args()
    download_spot("2026-01")
    spot = {symbol: spot_opens(symbol, "2026-01") for symbol in SYMBOLS}
    report = {
        "hypothesis": "buy spot and short current USD-M quarterly contract on quarter open; close two days before expiry",
        "symbols": list(SYMBOLS),
        "capital": {"spot_cash": SPOT_CASH, "futures_margin": FUTURES_MARGIN,
                    "spot_allocation_per_symbol": SPOT_ALLOCATION_PER_SYMBOL},
        "costs": {"spot_side": SPOT_SIDE_COST, "quarterly_future_side": PERP_SIDE_COST,
                  "extra_pair_round_trip": EXTRA_PAIR_COST},
        "margin_screen": {"maintenance_assumption": MAINTENANCE_ASSUMPTION,
                          "daily_high_extra_mark_shock": EXTRA_MARK_SHOCK},
        "diagnostic_all": args.diagnostic_all,
    }
    all_legs = []
    for year, stage in ((2023, "selection"), (2024, "calibration"),
                        (2025, "validation")):
        if year > 2023 and not args.diagnostic_all and not report.get(f"{year - 1}_gate", False):
            report[str(year)] = None
            continue
        quarters = pd.period_range(f"{year}Q1", f"{year}Q4", freq="Q")
        rows = []
        for quarter in quarters:
            result, legs = quarter_result(quarter, spot)
            rows.append(result)
            all_legs.extend(legs)
            print(stage, quarter, "stress", result["stress_on_capital"],
                  "margin", result["minimum_margin_shock_cushion"], flush=True)
        summary = annual_summary(rows)
        report[str(year)] = summary
        report[f"{year}_gate"] = passes(summary)
        print(stage, year, "gate", report[f"{year}_gate"], flush=True)
    suffix = "_diagnostic" if args.diagnostic_all else ""
    output = ROOT / f"outputs/quarterly_basis{suffix}_report.json"
    if all_legs:
        pd.DataFrame(all_legs).to_parquet(
            ROOT / f"outputs/quarterly_basis{suffix}_legs.parquet", index=False)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: {name: value for name, value in section.items()
                            if name != "quarterly"} if isinstance(section, dict) else section
                      for key, section in report.items() if key in ("2023", "2024", "2025")
                      or key.endswith("_gate")}, indent=2), flush=True)
    print("saved", output, flush=True)


if __name__ == "__main__":
    main()
