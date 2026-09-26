# Deribit USDC delivery: fixed public-book universe screen

Frozen after official instrument metadata and product documentation were read,
before any Deribit book read for this study. The active linear USDC delivery
futures with matching USDC spot instruments and 30-180 days to expiry are
AVAX, BTC, ETH, SOL and XRP on 2026-10-30 and 2026-12-25, plus BTC and ETH
on 2026-11-27: exactly 12 contracts. Screen every named contract, including
missing or stale books. Exclude perpetuals, DVOL, options, shorter-dated
expiries and underlyings without a matching USDC spot book. Do not replace a
failed contract or change the costs or gate after the first book read.

- For each intended 500 and 1,000 USDC spot size, round future base-coin
  quantity down to the contract lot step so its best-ask spot value is no
  greater than the target. Round the spot purchase up to its lot step and
  assign zero terminal value to any extra coin. Require valid instrument
  status, minimum sizes and full displayed depth through 100 order-book
  levels. Walk spot asks and future bids in base-coin units.
- Fetch spot and future books concurrently for each contract, then Deribit
  server time. Require both book timestamps to be 0-10 seconds old at that
  clock read and the books' local receive times to differ by at most five
  seconds. Any failed or stale read fails the case. Preserve complete public
  responses, URLs, timestamps, errors and the frozen protocol commit.
- Model cash settlement of the short USDC linear future against a USDC spot
  sale only as a **conditional** terminal-cash scenario. Charge 0.15% spot
  entry taker, 0.05% future entry taker, 0.05% expiry fee stress, 0.15% spot
  exit taker, 0.10% exit slippage, 0.10% adverse index/spot mismatch, 0.25%
  USDC/index valuation stress, another 0.25% uncertainty stress, and a 1.00%
  annual capital charge on 2.025 times spot acquisition cost reserved until
  expiry. These are illustrative costs and stresses, not maximum losses.
  The actual spot routing, fees, account margin, two-leg fills, final exit,
  taxes and regional eligibility are not known.
- A contract passes the preliminary screen only if both sizes have valid,
  timely and fully displayed entry books, positive after-cost conditional
  cash and at least 4% annualized conditional return on reserved capital.
  A pass requires a separately frozen forward observation and account review.
  No order, transfer or shadow position is authorized. One quote is not
  evidence of robust realized profit.

Primary sources: [Deribit production API](https://docs.deribit.com/),
[linear futures](https://support.deribit.com/hc/en-us/articles/31424954805405-Linear-Futures),
[spot instruments](https://support.deribit.com/hc/en-us/articles/31424969480093-Spot-Instruments),
[fees](https://support.deribit.com/hc/en-us/articles/25944746248989-Fees).
