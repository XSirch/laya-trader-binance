"""Read-only BTC quarterly settlement-index versus spot-sale range audit."""

from __future__ import annotations

import calendar
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from decimal import Decimal

from binance_coinm_delivery_universe_screen import COIN_API
from binance_dec26_forward_quote import ROOT, SPOT_API, read_public, utc_now


REPORT = ROOT / "outputs/binance_coinm_settlement_mismatch_audit.json"
PROTOCOL = "docs/binance_coinm_settlement_mismatch_audit_protocol.md"
QUARTER_MONTHS = (3, 6, 9, 12)
MINUTE_MS = 60_000
MISMATCH_CHARGE = Decimal("0.001")


def expiries() -> list[datetime]:
    result = []
    for year in range(2023, 2027):
        for month in QUARTER_MONTHS:
            if year == 2026 and month > 9:
                continue
            last_day = calendar.monthrange(year, month)[1]
            last_friday = last_day - (
                datetime(year, month, last_day).weekday() - 4) % 7
            result.append(datetime(year, month, last_friday, 8,
                                   tzinfo=timezone.utc))
    return result


def utc_ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def checked_candles(rows: list, expected: list[int],
                    *, require_volume: bool) -> list[dict]:
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise ValueError("missing or extra minute candles")
    ordered = sorted(rows, key=lambda row: int(row[0]))
    if [int(row[0]) for row in ordered] != expected:
        raise ValueError("minute timestamps do not match the fixed window")
    parsed = []
    for row in ordered:
        if len(row) < 7 or int(row[6]) != int(row[0]) + MINUTE_MS - 1:
            raise ValueError("invalid candle schema or close time")
        opening, high, low, close = (Decimal(str(row[index]))
                                     for index in (1, 2, 3, 4))
        if (not all(value.is_finite() and value > 0
                    for value in (opening, high, low, close))
                or low > min(opening, close)
                or high < max(opening, close)):
            raise ValueError("invalid positive OHLC range")
        if require_volume:
            volume = Decimal(str(row[5]))
            if not volume.is_finite() or volume <= 0:
                raise ValueError("spot minute has no positive traded volume")
        parsed.append({
            "open_ms": int(row[0]),
            "open": opening, "high": high, "low": low, "close": close,
        })
    return parsed


def evaluate(expiry: datetime, index_read: dict, spot_read: dict) -> dict:
    result = {"expiry_utc": expiry.isoformat(), "status": "unassessable"}
    if index_read["status"] != "ok" or spot_read["status"] != "ok":
        result["status"] = "required API read failed"
        return result
    settle_ms = utc_ms(expiry)
    index_expected = [settle_ms - 30 * MINUTE_MS + i * MINUTE_MS
                      for i in range(30)]
    spot_expected = [settle_ms + i * MINUTE_MS for i in range(5)]
    index = checked_candles(index_read["payload"], index_expected,
                            require_volume=False)
    spot = checked_candles(spot_read["payload"], spot_expected,
                           require_volume=True)
    index_high_mean = sum(row["high"] for row in index) / len(index)
    index_low_mean = sum(row["low"] for row in index) / len(index)
    spot_low = min(row["low"] for row in spot)
    spot_high = max(row["high"] for row in spot)
    adverse = Decimal(1) - spot_low / index_high_mean
    favorable = spot_high / index_low_mean - Decimal(1)
    result.update({
        "status": "evaluated", "index_minutes": len(index),
        "spot_minutes": len(spot),
        "index_minute_high_mean": float(index_high_mean),
        "index_minute_low_mean": float(index_low_mean),
        "spot_0800_open": float(spot[0]["open"]),
        "spot_0800_0804_low": float(spot_low),
        "spot_0800_0804_high": float(spot_high),
        "adverse_spot_low_vs_index_high_mean": float(adverse),
        "favorable_spot_high_vs_index_low_mean": float(favorable),
        "adverse_exceeds_existing_10bps_charge": adverse > MISMATCH_CHARGE,
    })
    return result


def main() -> None:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    report = {
        "protocol": PROTOCOL, "protocol_commit": commit,
        "started_utc": utc_now(),
        "expected_expiries": [date.isoformat() for date in expiries()],
        "mismatch_charge": str(MISMATCH_CHARGE),
        "sources": {}, "results": {},
        "limits": "Minute OHLC ranges are not the official second-wise settlement value or executable exit bids",
    }
    for expiry in expiries():
        key = expiry.date().isoformat()
        settle_ms = utc_ms(expiry)
        index_read = read_public(COIN_API, "/dapi/v1/indexPriceKlines", {
            "pair": "BTCUSD", "interval": "1m",
            "startTime": settle_ms - 30 * MINUTE_MS,
            "endTime": settle_ms - 1, "limit": 30,
        })
        spot_read = read_public(SPOT_API, "/api/v3/klines", {
            "symbol": "BTCUSDT", "interval": "1m",
            "startTime": settle_ms,
            "endTime": settle_ms + 5 * MINUTE_MS - 1, "limit": 5,
        })
        report["sources"][key] = {
            "index_candles": index_read, "spot_candles": spot_read,
        }
        try:
            result = evaluate(expiry, index_read, spot_read)
        except (ValueError, TypeError, KeyError, IndexError,
                ArithmeticError) as error:
            result = {"expiry_utc": expiry.isoformat(),
                      "status": "evaluation error", "reason": str(error)}
        report["results"][key] = result
        print(key, result["status"], "adverse",
              result.get("adverse_spot_low_vs_index_high_mean"),
              "exceeds_10bps",
              result.get("adverse_exceeds_existing_10bps_charge"), flush=True)
    results = list(report["results"].values())
    report["assessable_dates"] = sum(
        row["status"] == "evaluated" for row in results)
    report["exceeding_dates"] = [
        key for key, row in report["results"].items()
        if row.get("adverse_exceeds_existing_10bps_charge", False)
    ]
    report["finished_utc"] = utc_now()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    digest = hashlib.sha256(REPORT.read_bytes()).hexdigest()
    print("assessable", report["assessable_dates"], "/", len(results),
          "exceeding", len(report["exceeding_dates"]),
          "report_sha256", digest, flush=True)
    print("saved", REPORT, flush=True)


if __name__ == "__main__":
    main()
