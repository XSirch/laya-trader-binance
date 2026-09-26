"""Replay BTC/ETH quarterly basis pairs with separate spot and futures wallets."""

from __future__ import annotations

import json

import pandas as pd

from laya_trader.dataset.build import _read_zip
from laya_trader.features.core import normalize_klines
from laya_trader.progress import ProgressReporter
from quarterly_basis_probe import (
    EXTRA_MARK_SHOCK, EXTRA_SIDE_COST, FUTURES_MARGIN, MAINTENANCE_ASSUMPTION,
    SPOT_CASH, SYMBOLS, archive_path, contract_dates,
)
from spot_perp_carry_probe import PERP_SIDE_COST, ROOT, SPOT_SIDE_COST, spot_opens


INITIAL_CAPITAL = SPOT_CASH + FUTURES_MARGIN


def contract_prices(contract: str, entry: pd.Timestamp, exit_time: pd.Timestamp) -> pd.DataFrame:
    months = pd.period_range(entry.tz_localize(None), exit_time.tz_localize(None), freq="M").astype(str)
    frames = [normalize_klines(_read_zip(archive_path(contract, month))) for month in months]
    result = pd.concat(frames, ignore_index=True)
    result = result.drop_duplicates("open_time").sort_values("open_time")
    prices = result.set_index("open_time")[["open", "high"]].astype(float)
    expected = pd.date_range(entry, exit_time, freq="D")
    if prices.reindex(expected).isna().any().any():
        raise ValueError(f"incomplete delivery-future prices: {contract}")
    return prices


def liquidating_equity(
    day: pd.Timestamp, legs: list[dict], spot_cash: float, futures_cash: float,
    spot: dict[str, pd.Series], futures: dict[str, pd.DataFrame],
    extra_paid: float,
) -> tuple[float, float]:
    value = spot_cash + futures_cash
    reserve = 0.0
    extra_reserve = 0.0
    for leg in legs:
        symbol, contract, q = leg["symbol"], leg["contract"], leg["quantity"]
        s = float(spot[symbol][day])
        f = float(futures[contract].loc[day, "open"])
        value += q * (s + leg["future_entry"] - f)
        reserve += q * (SPOT_SIDE_COST * s + PERP_SIDE_COST * f)
        extra_reserve += q * EXTRA_SIDE_COST * (s + f)
    return value - reserve, value - reserve - extra_paid - extra_reserve


def main() -> None:
    input_path = ROOT / "outputs/quarterly_basis_diagnostic_legs.parquet"
    if not input_path.is_file():
        raise FileNotFoundError("run quarterly_basis_probe.py --diagnostic-all first")
    legs_frame = pd.read_parquet(input_path)
    quarters = pd.period_range("2023Q1", "2025Q4", freq="Q")
    spot = {symbol: spot_opens(symbol, "2026-01") for symbol in SYMBOLS}
    spot_cash, futures_cash, extra_paid = SPOT_CASH, FUTURES_MARGIN, 0.0
    records = []
    daily = []
    progress = ProgressReporter("quarterly account replay", len(quarters), unit="quarters")
    for count, quarter in enumerate(quarters, 1):
        entry, exit_time, _ = contract_dates(quarter)
        source = legs_frame.loc[legs_frame.quarter == str(quarter)]
        if set(source.symbol) != set(SYMBOLS):
            raise ValueError(f"incomplete quarter legs: {quarter}")
        legs = source.to_dict(orient="records")
        futures = {leg["contract"]: contract_prices(leg["contract"], entry, exit_time)
                   for leg in legs}
        before_capital = spot_cash + futures_cash
        before_stress = before_capital - extra_paid
        for leg in legs:
            q, s, f = leg["quantity"], leg["spot_entry"], leg["future_entry"]
            spot_cash -= q * s * (1 + SPOT_SIDE_COST)
            futures_cash -= q * f * PERP_SIDE_COST
            extra_paid += q * EXTRA_SIDE_COST * (s + f)
        if spot_cash < 0:
            raise ValueError(f"spot cash insufficient at {quarter} entry")
        margin_min = float("inf")
        for day in pd.date_range(entry, exit_time - pd.Timedelta(days=1), freq="D"):
            margin_equity = futures_cash
            maintenance = 0.0
            for leg in legs:
                mark = float(futures[leg["contract"]].loc[day, "high"]) * (1 + EXTRA_MARK_SHOCK)
                margin_equity += leg["quantity"] * (leg["future_entry"] - mark)
                maintenance += leg["quantity"] * mark * MAINTENANCE_ASSUMPTION
            cushion = margin_equity - maintenance
            margin_min = min(margin_min, cushion)
            value, stressed = liquidating_equity(
                day, legs, spot_cash, futures_cash, spot, futures, extra_paid)
            daily.append({"day": day, "quarter": str(quarter),
                          "liquidating_equity": value,
                          "stress_liquidating_equity": stressed,
                          "margin_shock_cushion": cushion,
                          "spot_cash": spot_cash, "futures_cash": futures_cash})
        for leg in legs:
            q, s, f = leg["quantity"], leg["spot_exit"], leg["future_exit"]
            spot_cash += q * s * (1 - SPOT_SIDE_COST)
            futures_cash += q * (leg["future_entry"] - f) - q * f * PERP_SIDE_COST
            extra_paid += q * EXTRA_SIDE_COST * (s + f)
        transfer_to_futures = FUTURES_MARGIN - futures_cash
        spot_cash -= transfer_to_futures
        futures_cash += transfer_to_futures
        if spot_cash < 0:
            raise ValueError(f"spot proceeds cannot restore futures margin after {quarter}")
        after_capital = spot_cash + futures_cash
        after_stress = after_capital - extra_paid
        records.append({
            "quarter": str(quarter), "entry": entry, "exit": exit_time,
            "net_cash": after_capital - before_capital,
            "stress_cash": after_stress - before_stress,
            "account_equity": after_capital,
            "stress_account_equity": after_stress,
            "spot_cash_after_transfer": spot_cash,
            "futures_cash_after_transfer": futures_cash,
            "transfer_to_futures": transfer_to_futures,
            "minimum_margin_shock_cushion": margin_min,
        })
        progress.update(count)
    results = pd.DataFrame(records)
    path = pd.DataFrame(daily)
    peak = path.liquidating_equity.cummax().clip(lower=INITIAL_CAPITAL)
    drawdown = path.liquidating_equity / peak - 1
    by_year = results.groupby(results.quarter.str[:4]).agg(
        quarters=("quarter", "size"),
        positive_stress_quarters=("stress_cash", lambda values: int(values.gt(0).sum())),
        net_cash=("net_cash", "sum"),
        stress_cash=("stress_cash", "sum"),
        minimum_margin_shock_cushion=("minimum_margin_shock_cushion", "min"),
    )
    by_year["stress_on_initial_capital"] = by_year.stress_cash / INITIAL_CAPITAL
    report = {
        "initial_capital": INITIAL_CAPITAL,
        "spot_wallet_initial": SPOT_CASH,
        "futures_wallet_target_between_quarters": FUTURES_MARGIN,
        "interwallet_transfer": "costless only after both legs close; no transfer while positions are open",
        "minimum_spot_cash_after_transfer": round(float(results.spot_cash_after_transfer.min()), 6),
        "minimum_margin_shock_cushion": round(float(results.minimum_margin_shock_cushion.min()), 6),
        "maximum_daily_liquidation_drawdown": round(float(drawdown.min()), 6),
        "net_total_on_initial_capital": round(float(results.net_cash.sum() / INITIAL_CAPITAL), 6),
        "stress_total_on_initial_capital": round(float(results.stress_cash.sum() / INITIAL_CAPITAL), 6),
        "years": by_year.round(6).reset_index().to_dict(orient="records"),
        "quarters": results.assign(entry=results.entry.astype(str),
                                   exit=results.exit.astype(str)).round(6).to_dict(orient="records"),
    }
    results.to_parquet(ROOT / "outputs/quarterly_basis_account_quarters.parquet", index=False)
    path.to_parquet(ROOT / "outputs/quarterly_basis_account_daily.parquet", index=False)
    output = ROOT / "outputs/quarterly_basis_account_report.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "quarters"},
                     indent=2), flush=True)
    print("saved", output, flush=True)


if __name__ == "__main__":
    main()
