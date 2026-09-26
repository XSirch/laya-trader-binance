# Independent-venue 2022-2023 six-month basis price screen

Specified before reading OKX spot or dated-future prices for these periods. The target contract IDs and archive existence were checked first. This is an independent-venue historical *price screen*, not a completed risk or executable-fill replay.

## Fixed sample and source

- Include every January and July start in 2022 and 2023 for BTC-USDT and ETH-USDT spot paired with the matching OKX USDT-settled June or December expiry future: 220624, 221230, 230630 and 231229. Exit at 00:00 UTC two calendar days before each expiry. Do not skip a symbol or replace a date or contract if a window is missing.
- Download the first-party daily OKX trade ZIP for each spot and `futureschain` market on all eight entry/exit dates. The ZIP filename is partitioned in UTC+8, so explicitly filter `created_time` epoch milliseconds for 00:00-00:04:59.999 UTC on the specified date. Reject malformed/nonpositive prices, wrong spot instrument, wrong delivery contract or empty required window. Verify ZIP CRC and record each downloaded file's SHA256; OKX does not provide a published checksum in this path.
- For each entry window use the maximum observed spot trade price and the minimum observed future trade price. For each exit window use the minimum observed spot trade price and the maximum observed future trade price. These extreme traded prices are deliberately adverse but do not prove the pair could fill simultaneously or at the modeled size.

## Fixed cash calculation and decision

- Use the same continuous, normalized position as the Binance six-month research rule: 0.5 normalized USDT of spot per symbol divided by its adverse entry spot price; short the same base quantity of the dated future. Charge 19 basis points per side on each market. Divide combined cash profit by the same 4.05 normalized initial account capital. Report both symbol legs, each half-year, all four half-years together and simple annualized break-even capital charge by holding days.
- Report whether all four half-years have positive modeled cash profit. A negative half-year weakens the cross-venue hypothesis; positive cash profit only justifies further work. This screen deliberately does not claim a fee-tier match, contract-size feasibility, same-direction traded-volume capacity, wallet or margin safety, funding/opportunity cost, tax treatment, historical bid/ask depth or a live executable edge. Do not assign a completed strategy verdict from this price screen.

Record exact archive URLs and local hashes for reproducibility. No live orders are authorized.
