# Deribit inverse delivery: fixed public-book universe screen

Frozen after official instrument metadata and inverse-future documentation,
before any Deribit inverse-future book read for this study. Screen exactly
eight active contracts: BTC and ETH each expiring 2026-10-30, 2026-11-27,
2026-12-25 and 2027-03-26. Each has a matching `BASE_USDC` spot market.
Exclude nearer expiries, June/September 2027, perpetuals, options and linear
USDC futures. Preserve failed contracts; do not replace symbols, costs or the
gate after the first book read.

- For each intended 500 and 1,000 USDC spot size, round the inverse future's
  USD face down to its `contract_size` multiple. Deribit book amount is also
  USD face; walk future bids and sum `matched_USD / bid_price` to find the
  exact base-coin collateral hedge. Round the spot purchase up to its lot
  step and write off any excess coin at the terminal calculation. Require
  minimum sizes, both 100-level books' full entry depth and valid active
  instruments. Do not infer two-leg fillability from displayed depth.
- Fetch spot and future books concurrently for each contract, then Deribit
  server time. Each book's timestamp must be 0-10 seconds old at that clock
  read and the two local receive times at most five seconds apart. Preserve
  raw responses, URLs, times, errors and the frozen protocol commit. Failed
  or stale reads fail the case.
- Assume coin collateral plus the inverse short settles to the USD future
  face at expiry, with its coin proceeds sold into USDC, only for a
  **conditional** terminal-cash scenario. Charge 0.15% spot entry taker;
  0.05% future entry taker in coin, valued at twice the entry spot price as
  a stress; 0.05% expiry fee on USD face; 0.15% spot exit taker; 0.10% spot
  exit slippage; 0.10% adverse index/spot mismatch; 0.25% USD/USDC index
  valuation stress; 0.25% extra uncertainty; and 1.00% annual capital charge
  on 1.025 times entry spot cost reserved until delivery. These are
  illustrative costs, not a bound on possible loss. Account margin,
  liquidation, spot routing, actual fees, transfer availability, final exit,
  taxes and regional access are unknown.
- A preliminary pass requires both sizes to have valid, timely, fully
  displayed books, positive conditional after-cost cash and at least 4%
  annualized conditional return on illustrative reserved capital. A pass
  requires a newly frozen forward observation and account-specific review.
  No order, transfer or shadow position is authorized. One quote is not
  evidence of robust realized profit.

Primary sources: [Deribit inverse futures](https://support.deribit.com/hc/en-us/articles/31424938981533-Inverse-Futures),
[spot instruments](https://support.deribit.com/hc/en-us/articles/31424969480093-Spot-Instruments),
[fees](https://support.deribit.com/hc/en-us/articles/25944746248989-Fees),
[production API](https://docs.deribit.com/).
