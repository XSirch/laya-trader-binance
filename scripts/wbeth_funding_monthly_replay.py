"""Exploratory monthly WBETH/ETH versus ETH perpetual carry replay."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from binance_dec26_forward_quote import FUTURE_API, ROOT, SPOT_API, read_public, utc_now


PROTOCOL = "docs/wbeth_funding_monthly_replay_protocol.md"
REPORT = ROOT / "outputs/wbeth_funding_monthly_replay.json"
START = datetime(2024, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 9, 1, tzinfo=timezone.utc)
SPOT_TAKER = Decimal("0.001")
FUTURE_TAKER = Decimal("0.0005")
SPOT_SLIPPAGE = Decimal("0.0005")
FUTURE_SLIPPAGE = Decimal("0.0002")
WBETH_EXIT_STRESS = Decimal("0.005")
ANNUAL_CAPITAL_CHARGE = Decimal("0.01")
CAPITAL_MULTIPLE = Decimal("2.05")
INITIAL_SPOT_USDT = Decimal("1000")
MIN_ANNUALIZED_RETURN = Decimal("0.04")
MIN_POSITIVE_MONTHS = 24
MAX_FUNDING_GAP_MS = int(8.5 * 3_600_000)


def ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def months():
    current = START
    while current < END:
        year, month = current.year, current.month
        following = datetime(year + (month == 12), month % 12 + 1, 1,
                             tzinfo=timezone.utc)
        yield current, following
        current = following


def prices(read: dict, name: str) -> dict[int, Decimal]:
    if read.get("status") != "ok" or not isinstance(read.get("payload"), list):
        raise ValueError(f"{name} daily kline request failed")
    out = {}
    for row in read["payload"]:
        start_ms, close_ms = int(row[0]), int(row[6])
        value = Decimal(str(row[4]))
        if value <= 0 or close_ms != start_ms + 86_400_000 - 1 or start_ms in out:
            raise ValueError(f"invalid {name} daily candle")
        out[start_ms] = value
    return out


def funding_rows(reads: list[dict]) -> list[dict]:
    rows = []
    for page in reads:
        if page.get("status") != "ok" or not isinstance(page.get("payload"), list):
            raise ValueError("funding history request failed")
        rows.extend(page["payload"])
    times = [int(row["fundingTime"]) for row in rows]
    if (not rows or any(row.get("symbol") != "ETHUSDT" for row in rows)
            or any(b <= a for a, b in zip(times, times[1:]))
            or times[0] < ms(START) or times[-1] >= ms(END)):
        raise ValueError("funding history sequence invalid")
    for row in rows:
        if not Decimal(str(row["markPrice"])).is_finite():
            raise ValueError("nonfinite funding mark price")
        if Decimal(str(row["markPrice"])) <= 0:
            raise ValueError("nonpositive funding mark price")
        if not Decimal(str(row["fundingRate"])).is_finite():
            raise ValueError("nonfinite funding rate")
    return rows


def evaluate_month(start: datetime, end: datetime,
                   wbeth: dict[int, Decimal], spot: dict[int, Decimal],
                   future: dict[int, Decimal], funding: list[dict]) -> dict:
    row = {"month": start.strftime("%Y-%m"), "status": "unavailable",
           "passes_month": False}
    start_day = ms(start - timedelta(days=1))
    end_day = ms(end - timedelta(days=1))
    if any(day not in series for series in (wbeth, spot, future)
           for day in (start_day, end_day)):
        row["reason"] = "entry or exit daily close missing"
        return row
    window = [item for item in funding if ms(start) < int(item["fundingTime"]) < ms(end)]
    times = [ms(start)] + [int(item["fundingTime"]) for item in window] + [ms(end)]
    if not window or any(b - a > MAX_FUNDING_GAP_MS for a, b in zip(times, times[1:])):
        row["reason"] = "funding settlement coverage gap"
        return row
    wb0, wb1 = wbeth[start_day], wbeth[end_day]
    sp0, sp1 = spot[start_day], spot[end_day]
    fu0, fu1 = future[start_day], future[end_day]
    wbeth_coin = INITIAL_SPOT_USDT / (wb0 * sp0)
    hedge_eth = wbeth_coin * wb0
    end_spot_usdt = wbeth_coin * wb1 * sp1
    spot_pnl = end_spot_usdt - INITIAL_SPOT_USDT
    future_pnl = hedge_eth * (fu0 - fu1)
    funding_cash = hedge_eth * sum(
        (Decimal(str(item["markPrice"])) * Decimal(str(item["fundingRate"]))
         for item in window), Decimal(0))
    gross = spot_pnl + future_pnl + funding_cash
    spot_cost = (INITIAL_SPOT_USDT + end_spot_usdt) * 2 * (SPOT_TAKER + SPOT_SLIPPAGE)
    future_cost = hedge_eth * (fu0 + fu1) * (FUTURE_TAKER + FUTURE_SLIPPAGE)
    depeg_stress = INITIAL_SPOT_USDT * WBETH_EXIT_STRESS
    capital = INITIAL_SPOT_USDT * CAPITAL_MULTIPLE
    days = Decimal((end - start).days)
    capital_charge = capital * ANNUAL_CAPITAL_CHARGE * days / 365
    net = gross - spot_cost - future_cost - depeg_stress - capital_charge
    annualized = net / capital * 365 / days
    row.update({"status": "historical close-price proxy only",
                "days": int(days), "funding_events": len(window),
                "wbeth_eth_entry": str(wb0), "wbeth_eth_exit": str(wb1),
                "eth_spot_entry": str(sp0), "eth_spot_exit": str(sp1),
                "eth_future_entry": str(fu0), "eth_future_exit": str(fu1),
                "wbeth_quantity": str(wbeth_coin), "future_short_eth": str(hedge_eth),
                "spot_pnl": str(spot_pnl), "future_pnl": str(future_pnl),
                "funding_cash": str(funding_cash), "gross_cash": str(gross),
                "spot_cost": str(spot_cost), "future_cost": str(future_cost),
                "depeg_stress": str(depeg_stress), "capital_charge": str(capital_charge),
                "reserved_capital": str(capital), "stressed_net_cash": str(net),
                "annualized_on_reserved_capital": str(annualized),
                "passes_month": net > 0})
    return row


def main() -> None:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout.strip()
    report = {"protocol": PROTOCOL, "protocol_commit": commit,
              "status": "exploratory post-selection replay", "started_utc": utc_now(),
              "months": "2024-01 through 2026-08 inclusive", "sources": {},
              "assumptions": {"initial_spot_usdt": str(INITIAL_SPOT_USDT),
                              "spot_taker": str(SPOT_TAKER),
                              "future_taker": str(FUTURE_TAKER),
                              "spot_slippage_per_leg": str(SPOT_SLIPPAGE),
                              "future_slippage_per_side": str(FUTURE_SLIPPAGE),
                              "wbeth_exit_stress": str(WBETH_EXIT_STRESS),
                              "annual_capital_charge": str(ANNUAL_CAPITAL_CHARGE),
                              "capital_multiple": str(CAPITAL_MULTIPLE)},
              "results": [], "gate": {}}
    candle_start = ms(START - timedelta(days=1))
    candle_end = ms(END) - 1
    sources = {
        "wbeth_eth_spot": (SPOT_API, "/api/v3/klines", "WBETHETH"),
        "eth_usdt_spot": (SPOT_API, "/api/v3/klines", "ETHUSDT"),
        "eth_usdt_future": (FUTURE_API, "/fapi/v1/klines", "ETHUSDT"),
    }
    for name, (api, path, symbol) in sources.items():
        read = read_public(api, path, {"symbol": symbol, "interval": "1d",
                                       "startTime": candle_start, "endTime": candle_end,
                                       "limit": 1000})
        report["sources"][name] = read
        print(name, "daily rows", len(read.get("payload", [])), flush=True)
    report["sources"]["funding_pages"] = []
    cursor = ms(START)
    for page_number in range(6):
        if cursor >= ms(END):
            break
        read = read_public(FUTURE_API, "/fapi/v1/fundingRate",
                           {"symbol": "ETHUSDT", "startTime": cursor,
                            "endTime": ms(END) - 1, "limit": 1000})
        report["sources"]["funding_pages"].append(read)
        rows = read.get("payload", [])
        print("funding page", page_number + 1, "rows", len(rows), flush=True)
        if read.get("status") != "ok" or not rows:
            break
        next_cursor = int(rows[-1]["fundingTime"]) + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor
    try:
        wbeth = prices(report["sources"]["wbeth_eth_spot"], "WBETHETH")
        spot = prices(report["sources"]["eth_usdt_spot"], "ETHUSDT spot")
        future = prices(report["sources"]["eth_usdt_future"], "ETHUSDT future")
        funding = funding_rows(report["sources"]["funding_pages"])
        report["source_counts"] = {"wbeth_days": len(wbeth), "spot_days": len(spot),
                                   "future_days": len(future), "funding_events": len(funding)}
        for start, end in months():
            row = evaluate_month(start, end, wbeth, spot, future, funding)
            report["results"].append(row)
            print(row["month"], row["status"], row.get("stressed_net_cash"), flush=True)
        yearly = {}
        for year in (2024, 2025, 2026):
            rows = [row for row in report["results"] if row["month"].startswith(str(year))]
            if all(row["status"] == "historical close-price proxy only" for row in rows):
                total = sum((Decimal(row["stressed_net_cash"]) for row in rows), Decimal(0))
                capital_years = sum((Decimal(row["reserved_capital"]) * Decimal(row["days"]) / 365
                                     for row in rows), Decimal(0))
                yearly[str(year)] = {"months": len(rows), "total_stressed_cash": str(total),
                                     "annualized_on_reserved_capital": str(total / capital_years)}
            else:
                yearly[str(year)] = {"status": "incomplete"}
        positive = sum(bool(row["passes_month"]) for row in report["results"])
        complete = len(report["results"]) == 32 and all(
            row["status"] == "historical close-price proxy only" for row in report["results"])
        passes = (complete and positive >= MIN_POSITIVE_MONTHS
                  and all(Decimal(yearly[str(year)]["annualized_on_reserved_capital"])
                          >= MIN_ANNUALIZED_RETURN for year in (2024, 2025, 2026)))
        report["gate"] = {"complete": complete, "positive_months": positive,
                          "required_positive_months": MIN_POSITIVE_MONTHS,
                          "yearly": yearly, "passes_preliminary_economics": passes}
    except (ValueError, TypeError, KeyError, IndexError, ArithmeticError) as error:
        report["gate"] = {"complete": False, "passes_preliminary_economics": False,
                          "error": str(error)}
    report["finished_utc"] = utc_now()
    report["limits"] = ("Close-price proxy, not historical fillable bid/ask, redemption, "
                        "account margin or realized profit; no orders")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("gate", report["gate"], flush=True)
    print("saved", REPORT, flush=True)


if __name__ == "__main__":
    main()
