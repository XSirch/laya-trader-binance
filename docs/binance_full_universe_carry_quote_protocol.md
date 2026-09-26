# Binance spot/perpetual carry: full-universe entry quote screen

Freeze this read-only screen before fetching new order books. The 20-symbol
settled-funding report at `outputs/binance_recent_funding_20.json` is fixed by
SHA256 `c438b79c20391ae1cd42c45cac98ef9cf6d917431d3a3fb81d1e63364300fe5e`.
Its prior 0.8% funding-only input gate selected three symbols; this distinct
screen assesses whether **entry basis plus funding** can cover costs for any
of the original 20. This is a post-result exploratory quote read, not an
independent performance test. Do not narrow the universe after seeing books.

- Evaluate every symbol in `configs/dataset.toml` in config order, including
  symbols with negative funding projections. Require an `evaluated` funding
  row with complete seven- and three-day settlement coverage. Use the lower
  of those two 30-day projections as a conditional future funding amount;
  do not clip negative values to zero.
- For each symbol, fetch official spot and USD-M perpetual metadata, 100-level
  spot asks, 100-level perpetual bids and a later futures server clock. Save
  raw responses, URLs and local request/receive timestamps. The quote must
  show both markets `TRADING`, full displayed VWAP depth for both a 500 and a
  1,000 USDT intended spot purchase rounded down to a common valid lot step,
  receive-time offset no more than five seconds, and futures book `T` age
  between zero and ten seconds against the subsequent server clock.
- Reuse `binance_recent_carry_entry_quote.evaluate` without changing its
  economics: 30 days held; future exit spot and perpetual prices both equal
  entry spot VWAP; 10 bps spot and 5 bps perpetual taker per side; 2 bps extra
  slippage per side for four legs; 8 bps pair stress; another 25 bps entry
  notional uncertainty; and 1% annual charge on 2.025 times entry spot cash.
  Funding cash equals the lower projection times fixed entry spot notional.
  Negative funding reduces return. These are illustrative VIP 0 fees, not
  verified account rates.
- A symbol proceeds to a separately frozen forward observation only if **both**
  sizes pass all book and quantity checks and each has positive conditional
  net cash and at least 4% annualized on illustrative reserved capital. Do
  not relax fees, sizes, freshness, holding period or gate after observing
  results. Even a pass would not prove executable or realized profit: exit
  basis, future funding, two-leg fills, margin and account eligibility are
  unknown. No order or shadow position is authorized by this screen.

Primary sources: [Binance spot API](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md), [USD-M market-data API](https://developers.binance.info/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data), [funding convention](https://www.binance.com/en/support/faq/detail/360033525031).
