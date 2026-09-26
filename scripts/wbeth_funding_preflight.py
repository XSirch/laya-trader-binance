"""Archive fixed public WBETH/ETH and ETHUSDT funding input windows."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

from binance_dec26_forward_quote import FUTURE_API, ROOT, SPOT_API, read_public, utc_now


REPORT = ROOT / "outputs/wbeth_funding_preflight.json"


def epoch_ms(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() * 1000)


def main() -> None:
    # This window was selected after an exploratory preview, not before it.
    funding_start = epoch_ms("2026-08-27T16:00:00")
    funding_end = epoch_ms("2026-09-26T08:00:01")
    candle_start = epoch_ms("2026-08-26T00:00:00")
    candle_end = epoch_ms("2026-09-26T00:00:00")
    report = {"status": "exploratory, post-selection input check",
              "started_utc": utc_now(), "sources": {}, "summary": {},
              "limits": "Historical close prices and settled funding are not executable hedge PnL, forward funding or a realized trade."}
    report["sources"]["wbeth_eth_daily"] = read_public(
        SPOT_API, "/api/v3/klines",
        {"symbol": "WBETHETH", "interval": "1d", "startTime": candle_start,
         "endTime": candle_end, "limit": 32})
    print("WBETHETH candles fetched", flush=True)
    report["sources"]["ethusdt_funding"] = read_public(
        FUTURE_API, "/fapi/v1/fundingRate",
        {"symbol": "ETHUSDT", "startTime": funding_start,
         "endTime": funding_end, "limit": 100})
    print("ETHUSDT funding fetched", flush=True)
    try:
        candle_read = report["sources"]["wbeth_eth_daily"]
        funding_read = report["sources"]["ethusdt_funding"]
        if candle_read["status"] != "ok" or funding_read["status"] != "ok":
            raise ValueError("public request failed")
        candles = candle_read["payload"]
        funding = funding_read["payload"]
        if len(candles) != 32 or len(funding) != 90:
            raise ValueError(f"unexpected row counts: {len(candles)} candles, {len(funding)} funding")
        # Daily closes from Aug 26 and Sep 25, exactly 30 calendar days apart.
        first_close = Decimal(str(candles[0][4]))
        last_close = Decimal(str(candles[30][4]))
        first_close_time = int(candles[0][6])
        last_close_time = int(candles[30][6])
        if (first_close <= 0 or last_close <= 0
                or first_close_time != epoch_ms("2026-08-27T00:00:00") - 1
                or last_close_time != epoch_ms("2026-09-26T00:00:00") - 1):
            raise ValueError("unexpected close times or prices")
        times = [int(row["fundingTime"]) for row in funding]
        if (times[0] < funding_start or times[-1] > funding_end
                or any(b <= a for a, b in zip(times, times[1:]))
                or any(row["symbol"] != "ETHUSDT" for row in funding)):
            raise ValueError("invalid funding sequence")
        funding_sum = sum((Decimal(str(row["fundingRate"])) for row in funding), Decimal(0))
        wbeth_change = last_close / first_close - 1
        # An input-only indication: no perp basis move, no entry/exit spread,
        # no fees, no slippage, no WBETH redemption delay or collateral loss.
        gross_input = wbeth_change + funding_sum
        annual_on_double_capital = gross_input * Decimal(365) / Decimal(30) / Decimal(2)
        report["summary"] = {
            "first_wbeth_eth_close": str(first_close),
            "last_wbeth_eth_close": str(last_close),
            "wbeth_eth_30d_change": str(wbeth_change),
            "funding_rows": len(funding),
            "first_funding_utc": datetime.fromtimestamp(times[0] / 1000, timezone.utc).isoformat(),
            "last_funding_utc": datetime.fromtimestamp(times[-1] / 1000, timezone.utc).isoformat(),
            "settled_funding_rate_sum": str(funding_sum),
            "indicative_gross_input_30d": str(gross_input),
            "indicative_annualized_on_double_capital_before_costs": str(annual_on_double_capital),
        }
    except (ValueError, TypeError, KeyError, IndexError, ArithmeticError) as error:
        report["summary"] = {"status": "unusable", "reason": str(error)}
    report["finished_utc"] = utc_now()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("summary", report["summary"], flush=True)
    print("saved", REPORT, flush=True)


if __name__ == "__main__":
    main()
