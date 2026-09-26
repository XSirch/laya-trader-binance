"""Check archived future top-of-book coverage for the six-month basis replay."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests

from laya_trader.progress import ProgressReporter

from quarterly_basis_execution_probe import BASE_URL
from six_month_basis_replay import PERIODS, SYMBOLS
from spot_perp_carry_probe import ROOT


OUTPUT = ROOT / "outputs/six_month_bookticker_coverage.json"


def check(task: tuple[str, str, str, str]) -> dict:
    period, symbol, contract, day = task
    name = f"{contract}-bookTicker-{day}.zip"
    url = f"{BASE_URL}/{contract}/{name}"
    response = requests.head(url, timeout=20)
    if response.status_code not in (200, 404):
        raise RuntimeError(f"Unexpected archive response {response.status_code}: {url}")
    return {"period": period, "symbol": symbol, "contract": contract,
            "day": day, "available": response.status_code == 200,
            "content_length": response.headers.get("Content-Length")}


def main() -> None:
    tasks = []
    for period in PERIODS:
        for symbol in SYMBOLS:
            contract = f"{symbol}_{period.contract_suffix}"
            tasks.append((period.name, symbol, contract, period.entry))
            tasks.append((period.name, symbol, contract,
                          period.exit.strftime("%Y-%m-%d")))
    progress = ProgressReporter("six-month bookTicker coverage", len(tasks),
                                unit="archive dates")
    rows = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(check, task) for task in tasks]
        for count, future in enumerate(as_completed(futures), 1):
            rows.append(future.result())
            progress.update(count)
    rows.sort(key=lambda row: (row["period"], row["symbol"], row["day"]))
    complete_legs = sum(all(row["available"] for row in rows
                            if row["period"] == period.name
                            and row["symbol"] == symbol)
                        for period in PERIODS for symbol in SYMBOLS)
    report = {"checked_at_utc": datetime.now(timezone.utc).isoformat(),
              "source": BASE_URL,
              "required_archive_dates": len(rows),
              "available_archive_dates": sum(row["available"] for row in rows),
              "legs_with_both_entry_and_exit_archives": complete_legs,
              "limits": "HEAD availability only; no bid/ask price, quantity, fill or account eligibility established",
              "archives": rows}
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items()
                      if key != "archives"}, indent=2), flush=True)
    print("saved", OUTPUT, flush=True)


if __name__ == "__main__":
    main()
