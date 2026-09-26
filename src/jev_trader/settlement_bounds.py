"""Price-index bounds for the published 30-minute delisting settlement rule."""

import csv
import io
import json
import math
import zipfile
from pathlib import Path

from .binance_data import utc_ms
from .cli import ROOT
from .derivatives_data import fetch

RULE = "https://www.binance.com/en-AU/support/announcement/detail/4bcabddf0e81423ebca242e185bf157d"


def bound(rows, end):
    wanted = set(range(end - 30 * 60_000, end, 60_000))
    selected = {}
    for row in rows:
        if not row or row[0].lower() == "open_time":
            continue
        timestamp = int(row[0])
        if timestamp not in wanted:
            continue
        high, low = float(row[2]), float(row[3])
        if timestamp in selected or not math.isfinite(low) or not math.isfinite(high) or not 0 < low <= high:
            raise ValueError("invalid minute price-index candle")
        selected[timestamp] = (low, high)
    if set(selected) != wanted:
        raise ValueError("incomplete settlement index window")
    # Each minute contains 60 equally weighted seconds. Its unknown secondwise
    # mean is bounded by that minute's low/high; so is the 30-minute mean.
    return {"lower": sum(v[0] for v in selected.values()) / 30,
            "upper": sum(v[1] for v in selected.values()) / 30, "minute_count": 30}


def load():
    lifecycle = json.loads((ROOT / "docs/contract_lifecycle_sources_2026-09-26.json").read_text(encoding="utf-8"))
    records, bounds = [], {}
    for event in lifecycle["events"]:
        end = utc_ms(event["automatic_settlement_utc"])
        record = fetch("indexPriceKlines", event["symbol"], event["automatic_settlement_utc"][:10], "daily", "1m")
        with zipfile.ZipFile(Path(record["path"])) as archive:
            names = archive.namelist()
            if len(names) != 1:
                raise ValueError("expected one price-index CSV")
            interval = bound(csv.reader(io.StringIO(archive.read(names[0]).decode("utf-8-sig"))), end)
        bounds[event["symbol"], end] = interval
        records.append({"symbol": event["symbol"], "settlement_ms": end, **interval,
                        "rule_url": RULE, "event_url": event["source_url"],
                        "source": {k: v for k, v in record.items() if k != "path"}})
    report = {"events": records, "exact_settlement_prices_verified": False,
              "method": "Bounds on equally weighted 1800-second index average from 30 one-minute OHLC ranges.",
              "limits": ["Assumes the published general settlement rule applied without an exceptional override.",
                         "Index candle extrema must cover the settlement rule's secondwise samples.",
                         "A bounded accounting scenario is not an observed settlement transaction."]}
    (ROOT / "docs/settlement_bounds_2026-09-26.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return bounds, report


if __name__ == "__main__":
    print(json.dumps(load()[1], indent=2))
