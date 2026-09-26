# Current Binance funding: fixed 20-symbol signal screen

Frozen before querying the recent USD-M settled funding records. This is a
current, read-only input check of the existing seven-day carry signal, not a
new backtest or a profit calculation. The earlier January-June 2025
twenty-symbol funding-only cohort failed its cost screen. Do not change the
universe or thresholds after observing the current rates.

- Use the 20 symbols in `configs/dataset.toml`, only if both USDT spot and
  USD-M perpetual metadata report `TRADING`. Obtain one Binance USD-M server
  time and request each symbol's official funding settlements from exactly
  seven days before that time through that time. Preserve raw API responses,
  URLs, parameters and request/receive timestamps, including failures.
- Accept a window only if times are unique and increasing, no gap exceeds
  8.5 hours, the first settlement is within 8.5 hours of the window start,
  and the last is within 8.5 hours of the server-time cutoff. Require at
  least 18 settlements in seven days and at least eight in the final three
  days. Project a 30-day amount as `sum(settled rates) * 30 / observed days`
  separately for the seven-day and final three-day windows. Positive rates
  are receipts for a perpetual short under the published funding convention.
- A symbol passes this **input** screen only if both projections exceed
  0.8% for 30 days, the previously specified carry-entry threshold. A
  passing input still needs contemporaneous spot/perpetual entry and exit
  books, funding persistence, account-specific fees, collateral and margin
  analysis. It is not an after-cost return or an order authorization. If
  none pass, stop this current-rate branch at the input stage.

Primary sources: [Binance USD-M funding-rate API](https://developers.binance.info/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data), [funding payment convention](https://www.binance.com/en/support/faq/detail/360033525031).
