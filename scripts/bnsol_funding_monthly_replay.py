"""Exploratory BNSOL/SOL versus SOL perpetual replay with fixed economics."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from decimal import Decimal

from binance_dec26_forward_quote import FUTURE_API, ROOT, SPOT_API, read_public, utc_now
from wbeth_funding_monthly_replay import (
    MAX_FUNDING_GAP_MS, MIN_ANNUALIZED_RETURN, evaluate_month, ms, prices,
)


PROTOCOL = "docs/bnsol_funding_monthly_replay_protocol.md"
REPORT = ROOT / "outputs/bnsol_funding_monthly_replay.json"
START = datetime(2024, 11, 1, tzinfo=timezone.utc)
END = datetime(2026, 9, 1, tzinfo=timezone.utc)
MIN_POSITIVE_MONTHS = 17


def months():
    current = START
    while current < END:
        following = datetime(current.year + (current.month == 12),
                             current.month % 12 + 1, 1, tzinfo=timezone.utc)
        yield current, following
        current = following


def sol_funding(reads: list[dict]) -> list[dict]:
    rows = []
    for page in reads:
        if page.get("status") != "ok" or not isinstance(page.get("payload"), list):
            raise ValueError("SOL funding history request failed")
        rows.extend(page["payload"])
    times = [int(row["fundingTime"]) for row in rows]
    if (not rows or any(row.get("symbol") != "SOLUSDT" for row in rows)
            or any(b <= a for a, b in zip(times, times[1:]))
            or times[0] < ms(START) or times[-1] >= ms(END)):
        raise ValueError("SOL funding sequence invalid")
    for row in rows:
        mark = Decimal(str(row["markPrice"]))
        rate = Decimal(str(row["fundingRate"]))
        if not mark.is_finite() or mark <= 0 or not rate.is_finite():
            raise ValueError("invalid SOL funding rate or mark")
    return rows


def main() -> None:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout.strip()
    report = {"protocol": PROTOCOL, "protocol_commit": commit,
              "economic_evaluator_commit": "5088847", "status": "exploratory post-selection replay",
              "started_utc": utc_now(), "months": "2024-11 through 2026-08 inclusive",
              "funding_max_gap_ms": MAX_FUNDING_GAP_MS,
              "sources": {}, "results": [], "gate": {}}
    sources = {
        "bnsol_sol_spot": (SPOT_API, "/api/v3/klines", "BNSOLSOL"),
        "sol_usdt_spot": (SPOT_API, "/api/v3/klines", "SOLUSDT"),
        "sol_usdt_future": (FUTURE_API, "/fapi/v1/klines", "SOLUSDT"),
    }
    for name, (api, path, symbol) in sources.items():
        read = read_public(api, path, {"symbol": symbol, "interval": "1d",
                                       "startTime": ms(datetime(2024, 10, 31, tzinfo=timezone.utc)),
                                       "endTime": ms(END) - 1, "limit": 1000})
        report["sources"][name] = read
        print(name, "daily rows", len(read.get("payload", [])), flush=True)
    report["sources"]["funding_pages"] = []
    cursor = ms(START)
    for page_number in range(5):
        if cursor >= ms(END):
            break
        read = read_public(FUTURE_API, "/fapi/v1/fundingRate",
                           {"symbol": "SOLUSDT", "startTime": cursor,
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
        bnsol = prices(report["sources"]["bnsol_sol_spot"], "BNSOLSOL")
        spot = prices(report["sources"]["sol_usdt_spot"], "SOLUSDT spot")
        future = prices(report["sources"]["sol_usdt_future"], "SOLUSDT future")
        funding = sol_funding(report["sources"]["funding_pages"])
        report["source_counts"] = {"bnsol_days": len(bnsol), "spot_days": len(spot),
                                   "future_days": len(future), "funding_events": len(funding)}
        for start, end in months():
            row = evaluate_month(start, end, bnsol, spot, future, funding)
            for old, new in (("wbeth_eth_entry", "bnsol_sol_entry"),
                             ("wbeth_eth_exit", "bnsol_sol_exit"),
                             ("wbeth_quantity", "bnsol_quantity")):
                if old in row:
                    row[new] = row.pop(old)
            report["results"].append(row)
            print(row["month"], row["status"], row.get("stressed_net_cash"), flush=True)
        yearly = {}
        for year in (2024, 2025, 2026):
            rows = [row for row in report["results"] if row["month"].startswith(str(year))]
            if rows and all(row["status"] == "historical close-price proxy only" for row in rows):
                total = sum((Decimal(row["stressed_net_cash"]) for row in rows), Decimal(0))
                capital_years = sum((Decimal(row["reserved_capital"]) * Decimal(row["days"]) / 365
                                     for row in rows), Decimal(0))
                yearly[str(year)] = {"months": len(rows), "total_stressed_cash": str(total),
                                     "annualized_on_reserved_capital": str(total / capital_years)}
            else:
                yearly[str(year)] = {"status": "incomplete"}
        positive = sum(bool(row["passes_month"]) for row in report["results"])
        complete = len(report["results"]) == 22 and all(
            row["status"] == "historical close-price proxy only" for row in report["results"])
        passes = (complete and positive >= MIN_POSITIVE_MONTHS
                  and all(Decimal(yearly[str(year)]["annualized_on_reserved_capital"])
                          >= MIN_ANNUALIZED_RETURN for year in (2025, 2026)))
        report["gate"] = {"complete": complete, "positive_months": positive,
                          "required_positive_months": MIN_POSITIVE_MONTHS,
                          "yearly": yearly, "passes_preliminary_economics": passes}
    except (ValueError, TypeError, KeyError, IndexError, ArithmeticError) as error:
        report["gate"] = {"complete": False, "passes_preliminary_economics": False,
                          "error": str(error)}
    report["finished_utc"] = utc_now()
    report["limits"] = ("Daily closes and assumed costs only; no historical executable bid/ask, "
                        "redemption, account margin, intraday depeg or realized profit; no orders")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("gate", report["gate"], flush=True)
    print("saved", REPORT, flush=True)


if __name__ == "__main__":
    main()
