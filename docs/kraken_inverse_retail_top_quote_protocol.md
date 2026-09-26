# Kraken inverse futures: retail top-quote upper-bound screen

Freeze before the first spot/future ticker read. Public futures metadata lists
four active inverse contracts to screen: FI_XBTUSD_261030,
FI_XBTUSD_261225, FI_ETHUSD_261030 and FI_ETHUSD_261225. Pair each with
Kraken XBTUSD or ETHUSD spot. Read all four, including any failed response.

This is only an **optimistic top-quote upper bound** for the published Tier 1
retail fee schedule, not a depth or execution screen. Read futures tickers
and both spot tickers concurrently; require their local receive timestamps
to be within five seconds. Require active public instrument metadata and
positive future best bid and spot best ask. For hypothetical 500 and 1,000
USD futures face, value the matching coin purchase at the single best spot
ask and the inverse short at the single best future bid. This assumes
unlimited quantity at both best prices, instant fills and perfect settlement
convergence, deliberately favoring the candidate.

Charge only the publicly listed Tier 1 0.80% spot taker on entry, 0.80% spot
taker on exit, and 0.05% future taker on entry. Assign zero settlement fee,
slippage, mismatch, extra uncertainty, financing cost and margin reserve in
this first upper bound. Calculate annualized conditional return on spot cost
through each contract's last trading time. If even this optimistic result is
below the same 4% research gate at both sizes, stop: adding depth and costs
cannot rescue this snapshot under Tier 1 fees. If it passes, freeze a full
book/cost/margin screen before any further price read. Actual account fee
tier, access and order fillability remain unknown. No order is authorized.

Primary sources: [Kraken inverse contract specifications](https://support.kraken.com/en-br/articles/360022632172-Fixed-Maturity-Futures-Contract-specifications),
[July 2026 fee tiers](https://support.kraken.com/in/articles/cross-platform-fee-tier-changes),
[futures ticker API](https://docs-legacy.kraken.com/api/docs/futures-api/trading/get-tickers/),
[spot ticker API](https://support.kraken.com/articles/360000919986-public-endpoint-examples-you-can-try-them-directly-in-a-web-browser-).
