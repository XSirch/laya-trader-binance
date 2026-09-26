"""Read-only optimistic Kraken inverse basis screen at Tier 1 fees."""

from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal

from binance_dec26_forward_quote import ROOT, read_public, utc_now


FUTURE_API = "https://futures.kraken.com"
SPOT_API = "https://api.kraken.com"
PROTOCOL = "docs/kraken_inverse_retail_top_quote_protocol.md"
REPORT = ROOT / "outputs/kraken_inverse_retail_top_quote.json"
CONTRACTS = ("FI_XBTUSD_261030", "FI_XBTUSD_261225",
             "FI_ETHUSD_261030", "FI_ETHUSD_261225")
TARGETS = (500, 1000)
SPOT_ENTRY_FEE = Decimal("0.008")
SPOT_EXIT_FEE = Decimal("0.008")
FUTURE_ENTRY_FEE = Decimal("0.0005")
MIN_ANNUALIZED_RETURN = Decimal("0.04")


def evaluate(symbol: str, instrument: dict, ticker: dict,
             spot_read: dict, receives: dict) -> dict:
    base = "XBT" if "XBT" in symbol else "ETH"
    result = {"symbol": symbol, "spot_pair": f"{base}USD", "sizes": [],
              "both_sizes_pass_upper_bound": False}
    if (not instrument or not instrument.get("tradeable")
            or instrument.get("type") != "futures_inverse"
            or ticker is None or spot_read.get("status") != "ok"):
        result["status"] = "required metadata or ticker unavailable"
        return result
    if ticker.get("bid") is None:
        result["status"] = "future best bid unavailable"
        result["ticker_open_interest"] = ticker.get("openInterest")
        result["ticker_volume_24h"] = ticker.get("vol24h")
        return result
    payload = spot_read["payload"]
    if payload.get("error") or not payload.get("result"):
        result["status"] = "spot ticker API error"
        return result
    spot_data = next(iter(payload["result"].values()))
    spot_ask = Decimal(spot_data["a"][0])
    future_bid = Decimal(str(ticker["bid"]))
    received = [datetime.fromisoformat(value) for value in receives.values()]
    offset = (max(received) - min(received)).total_seconds()
    days = (datetime.fromisoformat(instrument["lastTradingTime"].replace("Z", "+00:00"))
            - max(received)).total_seconds() / 86400
    timely = offset <= 5
    result.update({"status": "evaluated", "future_bid": float(future_bid),
                   "spot_ask": float(spot_ask), "receive_span_seconds": offset,
                   "timely_under_protocol": timely, "days_to_last_trade": days})
    if min(spot_ask, future_bid) <= 0 or days <= 0:
        result["status"] = "invalid quote or expired future"
        return result
    for size in TARGETS:
        face = Decimal(size)
        coin = face / future_bid
        spot_cost = coin * spot_ask
        charges = (SPOT_ENTRY_FEE * spot_cost + SPOT_EXIT_FEE * face
                   + FUTURE_ENTRY_FEE * face)
        net = face - spot_cost - charges
        annualized = net / spot_cost * Decimal(365) / Decimal(str(days))
        row = {"intended_usd_face": size, "ideal_coin": float(coin),
               "ideal_spot_cost": float(spot_cost),
               "gross_basis_cash": float(face - spot_cost),
               "only_three_fees": float(charges),
               "optimistic_conditional_net_cash": float(net),
               "optimistic_annualized_return": float(annualized),
               "passes_upper_bound": bool(timely and net > 0
                                            and annualized >= MIN_ANNUALIZED_RETURN)}
        result["sizes"].append(row)
    result["both_sizes_pass_upper_bound"] = all(
        row["passes_upper_bound"] for row in result["sizes"])
    return result


def main() -> None:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout.strip()
    report = {"protocol": PROTOCOL, "protocol_commit": commit,
              "started_utc": utc_now(), "contracts": CONTRACTS,
              "targets": TARGETS, "fee_assumptions": {
                  "spot_entry_taker": str(SPOT_ENTRY_FEE),
                  "spot_exit_taker": str(SPOT_EXIT_FEE),
                  "future_entry_taker": str(FUTURE_ENTRY_FEE),
                  "minimum_annualized_return": str(MIN_ANNUALIZED_RETURN),
              }, "sources": {}, "results": {},
              "limits": "Optimistic top quotes, no depth, unlimited best-price quantity, no settlement costs/margin/slippage/taxes, account fee tier unknown; no orders"}
    instruments = read_public(FUTURE_API, "/derivatives/api/v3/instruments")
    with ThreadPoolExecutor(max_workers=3) as pool:
        a = pool.submit(read_public, FUTURE_API, "/derivatives/api/v3/tickers")
        b = pool.submit(read_public, SPOT_API, "/0/public/Ticker", {"pair": "XBTUSD"})
        c = pool.submit(read_public, SPOT_API, "/0/public/Ticker", {"pair": "ETHUSD"})
        future_read, xbt_read, eth_read = a.result(), b.result(), c.result()
    report["sources"] = {"instruments": instruments, "future_tickers": future_read,
                         "spot_tickers": {"XBT": xbt_read, "ETH": eth_read}}
    instrument_rows = (instruments["payload"].get("instruments", [])
                       if instruments.get("status") == "ok" else [])
    ticker_rows = (future_read["payload"].get("tickers", [])
                   if future_read.get("status") == "ok" else [])
    receives = {"future": future_read["received_utc"],
                "xbt_spot": xbt_read["received_utc"],
                "eth_spot": eth_read["received_utc"]}
    for symbol in CONTRACTS:
        instrument = next((row for row in instrument_rows
                           if row.get("symbol") == symbol), {})
        ticker = next((row for row in ticker_rows
                       if row.get("symbol") == symbol), None)
        spot_read = xbt_read if "XBT" in symbol else eth_read
        try:
            row = evaluate(symbol, instrument, ticker, spot_read, receives)
        except (ValueError, TypeError, KeyError, IndexError, ArithmeticError) as error:
            row = {"symbol": symbol, "status": "evaluation error",
                   "reason": str(error), "both_sizes_pass_upper_bound": False}
        report["results"][symbol] = row
        print(symbol, row["status"], [
            case.get("optimistic_annualized_return") for case in row.get("sizes", [])
        ], flush=True)
    report["passing_upper_bound_contracts"] = [
        symbol for symbol, row in report["results"].items()
        if row.get("both_sizes_pass_upper_bound")]
    report["finished_utc"] = utc_now()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("passing upper bound", report["passing_upper_bound_contracts"], flush=True)
    print("saved", REPORT, flush=True)


if __name__ == "__main__":
    main()
