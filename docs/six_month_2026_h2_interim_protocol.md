# Interim shadow observation for the frozen 2026 H2 basis position

Specified after the July 2026 entry premia and September 2026 December-future screen were already inspected. This is a post-result risk observation, not an untouched prospective holdout or a completed strategy return.

- Apply the frozen BTC/ETH spot versus USDT-margined December 25, 2026 delivery-future rule to the July 1, 2026 00:00 UTC entry. Use the five-minute same-direction taker-volume completion rule for a 1,000 USDT illustrative account, adverse spot high/future low through the common entry deadline, 0.5 normalized spot allocation per leg, 1.05 spot cash, 3.00 futures cash and 19 bps per side in both markets.
- Observe every UTC daily bar from July 1 through September 24, 2026 inclusive. Require SHA256 and ZIP CRC verification for the spot and future 1-minute entry archives and every 1-day archive. Use monthly files for July and August and daily files for September 1-24; fail closed if any required archive or day is missing.
- For each day, compute the existing risk proxy: short-future equity using that day's future high plus a simultaneous 10% mark shock, less assumed 5% maintenance. Also calculate hypothetical account liquidation value at that day's spot and future opens, subtracting estimated spot and future exit costs. These traded daily ranges are not executable bid/ask quotes or Binance's liquidation engine.
- Report entry prices/quantities, source hashes, minimum modeled margin cushion, first modeled breach if any, latest hypothetical liquidation value at September 24 00:00 UTC, and maximum daily drawdown. Do not assign an exit profit or treat a positive interim mark as a completed return. The frozen exit remains two calendar days before delivery.

Actual fees, account eligibility, borrow/opportunity cost, order-book depth, transfers and future outcome are outside this observation. No live order is authorized.
