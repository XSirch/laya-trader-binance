# OKX USD-margined delivery: fixed public-book universe screen

Frozen after public instrument metadata and official product documentation were
read, before any order-book read for this study. The live, normal-expiry linear
`USD_UM` universe with a matching `BASE-USDC` spot market is BTC, ETH and SOL,
each expiring 2026-10-30, 2026-11-27, 2026-12-25 and 2027-03-26: exactly 12
contracts. Exclude XAU (no matching spot instrument), inverse coin contracts,
and `XPERP` products. Evaluate every named contract, even if a required API
read fails; do not substitute another contract or change the gate afterward.

- For 500 and 1,000 USDC intended spot notionals, round the future contract
  count down to the exchange lot step, so its base-coin exposure at the best
  spot ask does not exceed the intended size. Round the matching spot buy up
  to the spot lot step, and assign zero terminal value to any excess coin.
  Require both entry legs to fit 100 displayed book levels and exchange
  size limits, including market-order limits. Compute the future's bid-side proceeds and spot's ask-side cost
  by walking the books in their native units.
- Fetch the two books concurrently for each contract, then the OKX server
  clock. Require each book's generation timestamp to be 0-10 seconds old at
  the server-clock read and the two local receive times to differ by no more
  than five seconds. A failed or stale read fails that case. Preserve full
  public responses, URLs, errors, request/receive times and protocol commit.
- Assume the USD-quoted short future converges with a USDC spot exit only for
  a **conditional** terminal-cash scenario. Charge 0.10% spot entry taker,
  0.05% future entry taker, 0.05% expiry fee stress, 0.10% spot exit taker,
  0.10% spot exit slippage, 0.10% adverse index/spot mismatch, 0.25% USD/USDC
  conversion stress, another 0.25% uncertainty stress, and 1.00% annual
  capital charge on 2.025 times entry spot cost held until expiry. These are
  illustrative stresses, not a cap on losses. The USD settlement currency
  selected by the user's account, actual fees, collateral path, margin call,
  two-leg fills, final exit, taxes and regional access are unknown.
- A contract passes the preliminary screen only if both sizes have valid
  metadata, timely books, displayed depth and positive conditional cash, with
  at least 4% annualized conditional return on reserved capital after every
  configured charge. A passing contract requires a new frozen forward
  observation and account review. No order, transfer or shadow position is
  authorized. One quote is not robust profit.

Primary references: [OKX public API](https://www.okx.com/docs-v5/en/),
[USD-margined futures FAQ](https://www.okx.com/en-eu/help/faq-on-usd-margined-futures),
[expiry futures](https://www.okx.com/en-gb/help/expiry-futures),
[fee rules](https://www.okx.com/en-us/help/trading-fee-rules-faq-eea).
