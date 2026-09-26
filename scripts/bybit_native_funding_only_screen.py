"""Read-only fixed-window Bybit funding-only feasibility screen."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from bybit_native_spread_entry_economics import ROOT, now_utc, read_public


BASES = ("BTC", "ETH", "SOL")
WINDOWS = (
    ("2026-06-27", "2026-07-27"),
    ("2026-07-27", "2026-08-26"),
    ("2026-08-26", "2026-09-25"),
)
REPORT = ROOT / "outputs/bybit_native_funding_only_screen.json"
PROTOCOL_COMMIT = "ce4b882"
ROUND_TRIP_COMBO_FEES = 0.00155
ADVERSE_EXECUTION = 0.0025
CAPITAL_MULTIPLE = 2.025
ANNUAL_CAPITAL_CHARGE = 0.01
MAX_GAP_MS = 8 * 60 * 60 * 1000
MIN_ANNUALIZED_RETURN = 0.04


def utc_ms(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(
        tzinfo=timezone.utc).timestamp() * 1000)


def funding_pages(symbol: str, start_ms: int, end_ms: int) -> tuple[list[dict], list[dict], bool]:
    pages = []
    rows = []
    cursor_end = end_ms - 1
    reached_start = False
    for _ in range(100):
        page = read_public("/v5/market/funding/history", {
            "category": "linear", "symbol": symbol,
            "startTime": start_ms, "endTime": cursor_end, "limit": 200})
        pages.append(page)
        if page["status"] != "ok":
            return pages, rows, False
        batch = page["payload"]["result"].get("list", [])
        if not batch:
            return pages, rows, reached_start
        rows.extend(batch)
        oldest = min(int(row["fundingRateTimestamp"]) for row in batch)
        if oldest <= start_ms + MAX_GAP_MS:
            reached_start = True
            return pages, rows, True
        if len(batch) < 200:
            return pages, rows, False
        if oldest >= cursor_end:
            return pages, rows, False
        cursor_end = oldest - 1
    return pages, rows, False


def evaluate_window(rows: list[dict], start_ms: int, end_ms: int,
                    pagination_complete: bool) -> dict:
    timestamps = [int(row["fundingRateTimestamp"]) for row in rows]
    valid = [row for row in rows
             if start_ms < int(row["fundingRateTimestamp"]) < end_ms]
    ordered = sorted(valid, key=lambda row: int(row["fundingRateTimestamp"]))
    times = [int(row["fundingRateTimestamp"]) for row in ordered]
    gaps = [right - left for left, right in zip(times, times[1:])]
    duplicates = len(timestamps) != len(set(timestamps))
    boundary_covered = bool(times and times[0] - start_ms <= MAX_GAP_MS
                            and end_ms - times[-1] <= MAX_GAP_MS)
    complete = (pagination_complete and not duplicates and boundary_covered
                and all(gap <= MAX_GAP_MS for gap in gaps))
    rates = [float(row["fundingRate"]) for row in ordered]
    days = (end_ms - start_ms) / (1000 * 60 * 60 * 24)
    result = {
        "funding_records_in_window": len(ordered),
        "pagination_complete": pagination_complete,
        "duplicate_timestamps": duplicates,
        "boundary_covered_within_eight_hours": boundary_covered,
        "max_internal_gap_hours": max(gaps, default=0) / (60 * 60 * 1000),
        "complete": complete,
        "funding_sum_on_fixed_reference_notional": sum(rates),
        "negative_funding_count": sum(rate < 0 for rate in rates),
        "min_funding_rate": min(rates, default=None),
        "max_funding_rate": max(rates, default=None),
    }
    if complete:
        capital_charge = ANNUAL_CAPITAL_CHARGE * CAPITAL_MULTIPLE * days / 365
        net = (sum(rates) - ROUND_TRIP_COMBO_FEES - ADVERSE_EXECUTION
               - capital_charge)
        result.update({
            "round_trip_combo_fees": ROUND_TRIP_COMBO_FEES,
            "adverse_execution": ADVERSE_EXECUTION,
            "capital_charge": capital_charge,
            "net_funding_less_configured_costs": net,
            "return_on_reserved_capital": net / CAPITAL_MULTIPLE,
        })
    return result


def main() -> None:
    report = {
        "protocol": "docs/bybit_native_funding_only_protocol.md",
        "protocol_commit": PROTOCOL_COMMIT,
        "started_utc": now_utc(),
        "costs": {
            "round_trip_combo_fees": ROUND_TRIP_COMBO_FEES,
            "adverse_execution": ADVERSE_EXECUTION,
            "annual_capital_charge": ANNUAL_CAPITAL_CHARGE,
            "reserved_capital_multiple": CAPITAL_MULTIPLE,
        },
        "sources": {}, "results": {},
        "limits": "Funding-only fixed-notional approximation; no native spread entry/exit quote, spot-perp basis P&L, mark-notional drift, account fee, collateral, borrowing or fill proof; no orders submitted",
    }
    for base in BASES:
        symbol = f"{base}USDT"
        instrument = read_public("/v5/market/instruments-info", {
            "category": "linear", "symbol": symbol})
        native = read_public("/v5/spread/instrument", {"baseCoin": base, "limit": 500})
        combo = []
        if native["status"] == "ok":
            combo = [item for item in native["payload"]["result"].get("list", [])
                     if item.get("contractType") == "FundingRateArb"
                     and item.get("status") == "Trading"
                     and {leg.get("contractType") for leg in item.get("legs", [])}
                     == {"Spot", "LinearPerpetual"}
                     and all(leg.get("symbol") == symbol
                             for leg in item.get("legs", []))]
        report["sources"][base] = {
            "linear_instrument": instrument, "native_spread_instrument": native,
            "funding_windows": {},
        }
        result = {"symbol": symbol, "active_native_combo_symbols": [
            item["symbol"] for item in combo], "windows": []}
        if instrument["status"] == "ok":
            matches = [item for item in instrument["payload"]["result"].get("list", [])
                       if item.get("symbol") == symbol]
            if len(matches) == 1:
                result["current_funding_interval_minutes"] = matches[0].get(
                    "fundingInterval")
        for start, end in WINDOWS:
            pages, rows, paginated = funding_pages(symbol, utc_ms(start), utc_ms(end))
            report["sources"][base]["funding_windows"][f"{start}/{end}"] = pages
            window = evaluate_window(rows, utc_ms(start), utc_ms(end), paginated)
            window.update({"start_utc": start, "end_utc": end})
            result["windows"].append(window)
            print(base, start, "records", window["funding_records_in_window"],
                  "complete", window["complete"], "net",
                  window.get("net_funding_less_configured_costs"), flush=True)
        complete = bool(combo and "current_funding_interval_minutes" in result
                        and all(window["complete"] for window in result["windows"]))
        result["assessable"] = complete
        result["funding_only_gate_pass"] = False
        if complete:
            returns = [window["return_on_reserved_capital"]
                       for window in result["windows"]]
            annualized = sum(returns) / len(returns) * 365 / 30
            result["mean_monthly_annualized_return_on_reserved_capital"] = annualized
            result["funding_only_gate_pass"] = (all(value > 0 for value in returns)
                                                and annualized >= MIN_ANNUALIZED_RETURN)
        report["results"][base] = result
    report["finished_utc"] = now_utc()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("saved", REPORT, flush=True)


if __name__ == "__main__":
    main()
