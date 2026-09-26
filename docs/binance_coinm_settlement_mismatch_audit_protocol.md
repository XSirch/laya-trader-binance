# BTC COIN-M settlement index versus spot-sale range

Freeze this separate risk audit before fetching the historical index and spot
minute candles. The live BTCUSD_270326 quote screen and its 12-sample forward
watch already use a fixed 10 bps spot/index mismatch charge. Do not change
their cost or acceptance gate as a result of this audit. Its purpose is to
check whether that charge even covers a simple adverse historical candle
range around prior quarterly settlement times.

- Use every scheduled BTC quarter expiry from 2023 Q1 through 2026 Q3, 15
  dates total, calculated as the last Friday of March, June, September and
  December. Do not select dates based on observed prices. Binance states that
  delivery uses the average index price each second from 07:30 through 08:00
  UTC and settles at 08:00 UTC. For each date request exactly 30 official
  BTCUSD COIN-M index-price one-minute candles (07:30-07:59 UTC) and five
  BTCUSDT spot one-minute candles (08:00-08:04 UTC). Save every first-party
  response, URL and request/receive time, including failures.
- Require exactly the specified minute timestamps, valid positive OHLC
  ranges and positive spot traded volume. A missing minute makes that date
  unassessable; do not substitute another day or widen its time window.
  Compute the mean of 30 index-minute highs and of 30 index-minute lows.
  The true 1,800-second settlement average should lie inside those broad
  OHLC bounds if the minute data represent the same index. Use the **lowest**
  spot traded price in the five post-settlement minutes against the mean
  index-minute highs for an adverse scenario: `1 - spot_low/index_high_mean`.
  This is a range stress, not a simultaneous executable spot bid. Also
  report the opposite range and the 08:00 spot open for context.
- Flag each assessable date whose adverse mismatch exceeds the existing
  10 bps charge. Report full coverage, the date-level values and the report
  SHA256. Even a positive flag does not prove the actual spot sale would have
  realized that low; no flag does not prove safe settlement. The 2026 Q3
  observation is recent but it is still historical. Do not infer a future
  fill, liquidation safety or robust after-cost profit from this audit.

Sources: [Binance delivery and settlement method](https://www.binance.com/en-AE/support/faq/detail/a3401595e1734084959c61491bc0dbe3), [COIN-M index-price klines](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-coin-m-futures/api/rest-api/market-data), [Binance spot klines](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md).
