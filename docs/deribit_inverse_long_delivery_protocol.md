# Deribit inverse delivery: longer-maturity exploratory screen

Frozen after the shorter-maturity BTC/ETH Deribit inverse screen and after
public instrument discovery, before reading any June or September 2027 book.
This is **post-selection exploration** of longer maturities, not an
independent holdout. Fix exactly four live inverse contracts: BTC-25JUN27,
ETH-25JUN27, BTC-24SEP27 and ETH-24SEP27. Use matching BTC_USDC and ETH_USDC
spot books. Failed, missing or stale reads remain failures; do not substitute
another maturity or relax the gate.

For both 500 and 1,000 USDC intended sizes, reuse the unchanged
`deribit_inverse_delivery_universe_screen.evaluate` function and all its
predeclared lot, inverse hedge, 100-level displayed-depth, clock-freshness,
fee, index, USDC, uncertainty, capital and 4%-annualized both-size rules.
Record complete metadata, raw books, clock reads, URLs, local request/receive
times and the protocol commit. The eight previously inspected shorter-maturity
inverse futures are not re-evaluated here.

A passing single snapshot requires a newly frozen repeated forward
observation and account-specific review. It does not prove executable
two-leg fills, safe coin collateral, convergence, fees or realized after-cost
profit. No order, transfer or shadow position is authorized.

Primary sources: [Deribit inverse futures](https://support.deribit.com/hc/en-us/articles/31424938981533-Inverse-Futures),
[production API](https://docs.deribit.com/).
