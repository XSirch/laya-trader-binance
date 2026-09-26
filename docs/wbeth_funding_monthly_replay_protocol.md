# Exploratory WBETH plus ETH perpetual monthly replay

This is **post-selection exploration**: an August-September 2026 WBETHETH
close-price and ETHUSDT funding preview was already inspected. Do not call
the following months an untouched holdout. Before requesting older history,
fix every complete calendar month from January 2024 through August 2026,
inclusive (32 windows). Never drop a losing or unavailable month. Any pass
requires an independently frozen future observation before account review.

Use official Binance public daily klines for WBETHETH spot, ETHUSDT spot and
ETHUSDT USDT-M perpetual, plus every settled ETHUSDT USDT-M funding record.
For each month, enter at 00:00 UTC on day one and exit at 00:00 UTC on the
next month using the immediately previous daily close as an *unfillable*
price proxy. Include funding events strictly inside the month and require
no gap over 8.5 hours, including the entry and exit boundaries. At a 1,000
USDT illustrative WBETH acquisition, set WBETH quantity to
`1000 / (WBETHETH_entry * ETHUSDT_spot_entry)` and fix the short perpetual
ETH quantity to `WBETH_quantity * WBETHETH_entry` for the month. Do not
rebalance. Convert final WBETH to ETH and then USDT at the corresponding
spot closes. The short perpetual receives its entry-to-exit close P&L and
the actual settled funding rates times their reported mark-price notionals.

Charge 0.10% spot taker fee on each of four conversions (ETH buy, WBETH buy,
WBETH sale, ETH sale), 0.05% future taker fee on opening and closing the
hedge, 0.05% slippage on each spot conversion, 0.02% on each future side,
0.50% adverse WBETH/ETH exit-price stress on initial spot notional and 1%
annual capital charge on 2.05 times initial spot notional. These are fixed
illustrative stresses, not historical account fees or risk bounds. Require
each of 2024, 2025 and January-August 2026 to exceed 4% annualized stressed
return on reserved capital and at least 24 of 32 months to have positive
stressed cash, with no missing data, for a preliminary research pass.

Even a pass does not establish fillability, WBETH redemption ratio, future
funding, account eligibility, margin or liquidation safety. Historical daily
closes omit bid/ask depth and order timing, and WBETH can trade below its
redemption value. No order or shadow position is authorized.

Primary sources: [Binance spot market data](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md),
[USDT-M funding history](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History),
[ETH staking](https://www.binance.com/en/earn/ethereum-staking),
[fees](https://www.binance.com/en/fee/trading),
[WBETH depeg incident](https://www.binance.com/en/support/announcement/detail/0989d6c7f32545bfb019e3249eaabc3f).
