# Recent Binance carry inputs: fixed entry-book economics

This read-only follow-up was fixed after the seven-day funding input screen
and before reading entry books for its three qualifying symbols. The input
report at `outputs/binance_recent_funding_20.json` has SHA256
`c438b79c20391ae1cd42c45cac98ef9cf6d917431d3a3fb81d1e63364300fe5e`.
Fix ADAUSDT, NEARUSDT and APTUSDT; do not add a replacement after a failed
read. This is post-selection entry evidence, not independent validation.

- For each symbol, read spot and USD-M perpetual metadata, a 100-level spot
  ask book and 100-level perpetual bid book, plus futures server time. Save
  raw responses, URLs and local request/receive times. Evaluate both intended
  500 and 1,000 USDT spot sizes, rounded down to a common valid lot step.
  Require full visible depth for the rounded spot buy and futures short.
  Require book receive times within five seconds and the futures book `T`
  no more than ten seconds behind the subsequent Binance server clock.
- Consider a **conditional** 30-day holding period with spot and perpetual
  exit prices equal at the entry spot price. Treat the lower of the already
  observed seven- and three-day projected 30-day funding amounts as a
  scenario for future payments on fixed entry spot notional. Future funding
  and basis convergence are unverified. This scenario does not project
  fluctuating perpetual notional or daily margin.
- Charge the displayed spot ask and perpetual bid VWAP, 0.10% spot taker and
  0.05% perpetual taker per side, another 2 bps slippage per side on each of
  the four entries/exits, the older additional 8 bps pair round-trip stress,
  and a further 25 bps of entry spot notional for basis/exit uncertainty.
  Charge 1% annual on 2.025 times spot entry cost as illustrative reserved
  capital. Fees at the future exit are based on entry notional in this
  scenario; actual account rates and exit prices are unknown.
- A symbol warrants a separate repeated-book observation only if **both**
  sizes have timely full displayed depth, positive scenario net cash and at
  least 4% annualized scenario return on reserved capital. Otherwise close
  this branch without changing the assumptions. A passing quote would still
  need account-specific eligibility, fees, hedged fills, realized funding,
  a margin path and a genuinely forward exit. No order is authorized.

Primary sources: [Binance spot API](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md), [USD-M market-data API](https://developers.binance.info/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data), [funding payment convention](https://www.binance.com/en/support/faq/detail/360033525031).
