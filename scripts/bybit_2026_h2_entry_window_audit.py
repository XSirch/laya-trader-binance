"""Reproduce the observed Bybit December-2026 futures entry-window absence."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
from datetime import datetime, timezone

import requests

from spot_perp_carry_probe import ROOT


DAY = "2026-07-01"
START = datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp()
END = START + 5 * 60
SYMBOLS = ("BTCUSDT-25DEC26", "ETHUSDT-25DEC26")
ARCHIVES = ROOT / "outputs/bybit_2026_h2_entry_archives"
REPORT = ROOT / "outputs/bybit_2026_h2_entry_window_audit.json"


def audit(symbol: str) -> dict:
    name = f"{symbol}{DAY}.csv.gz"
    url = f"https://public.bybit.com/trading/{symbol}/{name}"
    path = ARCHIVES / name
    if path.is_file():
        payload = path.read_bytes()
    else:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        payload = response.content
    digest = hashlib.sha256(payload).hexdigest()
    total = 0
    window = 0
    first = float("inf")
    try:
        with gzip.open(io.BytesIO(payload), "rt", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            expected = ["timestamp", "symbol", "side", "size", "price",
                        "tickDirection", "trdMatchID", "grossValue",
                        "homeNotional", "foreignNotional", "RPI"]
            if reader.fieldnames != expected:
                raise ValueError(f"unexpected CSV header: {symbol}")
            for row in reader:
                stamp = float(row["timestamp"])
                if (row["symbol"] != symbol or not math.isfinite(stamp)
                        or float(row["price"]) <= 0 or float(row["size"]) <= 0):
                    raise ValueError(f"invalid trade row: {symbol}")
                total += 1
                first = min(first, stamp)
                if START <= stamp < END:
                    window += 1
    except (OSError, UnicodeError, csv.Error) as error:
        raise ValueError(f"gzip/CSV integrity failed: {symbol}: {error}") from error
    if total == 0:
        raise ValueError(f"empty trade archive: {symbol}")
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".gz.tmp")
        temporary.write_bytes(payload)
        temporary.replace(path)
    return {
        "symbol": symbol, "url": url, "sha256": digest,
        "compressed_bytes": len(payload), "full_day_trade_count": total,
        "entry_window_start_utc": "2026-07-01T00:00:00+00:00",
        "entry_window_end_exclusive_utc": "2026-07-01T00:05:00+00:00",
        "entry_window_trade_count": window,
        "first_trade_timestamp": first,
        "first_trade_utc": datetime.fromtimestamp(first, timezone.utc).isoformat(),
    }


def main() -> None:
    results = [audit(symbol) for symbol in SYMBOLS]
    report = {
        "method": "post-observation reproduction of exact five-minute UTC trade-window availability",
        "source": "Bybit first-party public dated-future trade gzip files; local SHA256 and full gzip stream read",
        "results": results,
        "both_future_entry_windows_have_trades": all(
            row["entry_window_trade_count"] > 0 for row in results),
        "limits": "Trade absence in this window does not evaluate later entry times, spot execution, fees, margin, account eligibility or a different strategy",
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    print("saved", REPORT, flush=True)


if __name__ == "__main__":
    main()
