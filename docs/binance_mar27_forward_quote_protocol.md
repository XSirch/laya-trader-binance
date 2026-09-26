# Binance March 2027 delivery basis: prospective quote gate

Fixed after a read of current Binance exchange metadata and before any March
2027 book read for this study. The metadata exposed BTCUSDT_270326 and
ETHUSDT_270326 as active `NEXT_QUARTER` USDT-margined contracts with matching
BTCUSDT and ETHUSDT spot markets. December 2026 quotes were previously
inspected and are not reused as an untouched result.

- Read the official Binance spot and USD-M futures exchange metadata, a
  100-level spot ask book and 100-level March 2027 future bid book for BTC and
  ETH, plus the futures server clock. Preserve complete source responses,
  request/receive timestamps, URLs and errors. Do not replace a failed read.
- Evaluate intended 500 and 1,000 USDT spot buys for each coin, rounded down
  to a quantity valid on both venues. Require the whole intended position to
  fit the displayed ask/bid books. Require spot and future receive times to
  differ by at most five seconds and the futures book matching timestamp to
  be no more than ten seconds behind the server clock. This cannot prove
  atomic hedged fills or spot-book persistence.
- Reuse the December 2026 evaluator's fixed illustrative rates, without
  adjustment after seeing the March books: 0.10% spot entry taker, 0.05%
  future entry taker, 0.05% future settlement stress, 0.10% spot exit taker,
  0.10% spot exit slippage, 0.10% adverse index/spot mismatch, an additional
  0.25% uncertainty stress, and 1.00% annual charge on 2.025 times entry
  spot notional reserved through delivery. The actual account fee tier,
  margin path and future exit remain unknown.
- A **coin** becomes a candidate for longer read-only observation only if
  both sizes have valid depth/timing, positive conditional net cash and at
  least 4% annualized conditional return on illustrative reserved capital
  after every configured cost. Either BTC or ETH may pass independently.
  If neither passes, stop this candidate and report the result. If one does,
  freeze a separate repeated-observation protocol before additional reads.
  No order is authorized by this screen; even a passing quote is not a
  realized profit.

Primary API sources: [Binance spot REST API](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md), [Binance USD-M futures market data](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data).
