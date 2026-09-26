# Binance-Bybit USDT perpetual funding differential: fixed quote screen

Freeze this exploratory, read-only screen before fetching Bybit funding or
either venue's new perpetual order books. Reuse the Binance seven-day
settlement report `outputs/binance_recent_funding_20.json`, SHA256
`c438b79c20391ae1cd42c45cac98ef9cf6d917431d3a3fb81d1e63364300fe5e`,
with its fixed server-time cutoff and the 20 symbols in `configs/dataset.toml`.
No symbol or side is chosen after seeing the Bybit data. The Binance settled
rates were already inspected, so this is not an untouched out-of-sample test.

- For each symbol, require active USDT-settled linear perpetual metadata at
  both exchanges. Request Bybit settled funding from the Binance report's
  exact seven-day start through its cutoff, paginating backward if necessary.
  Use the Bybit metadata funding interval to require unique timestamps, no
  gap greater than 1.25 times that interval, and first/last settlements
  within 1.25 intervals of window boundaries. Require the same coverage of
  the final three days. Missing or malformed records invalidate the symbol;
  do not impute rates. For each side, project 30 days separately from the
  seven- and three-day sums, and use the **lower** net funding receipt. Evaluate
  both long Binance/short Bybit and long Bybit/short Binance, including
  negative forecasts; do not select the more favorable window after seeing
  it. Fixed entry notional approximates future funding cash.
- Fetch each exchange's official 100-level USDT perpetual order book and then
  each server clock. Preserve raw payloads, URLs, request/receive times and
  errors. For both intended 500 and 1,000 USDT *long-leg* sizes, round the
  base quantity down to a common valid market lot step. Require both venues'
  quantity and notional limits, full displayed long-ask and short-bid depth,
  receive-time offset at most five seconds, and both matching timestamps
  between zero and ten seconds old versus their subsequent server clocks.
- Conditional 30-day scenario: at exit, both perpetual prices equal the
  long-leg entry VWAP, so the current short-bid minus long-ask cash spread is
  captured. Add the lower projected net funding to that spread. Charge
  illustrative regular taker fees of 5 bps Binance and 5.5 bps Bybit **per
  side**; 2 bps extra slippage on each of four executions; another 8 bps
  round-trip pair stress; and 25 bps uncertainty on the entry long notional.
  Reserve 2.05 times the entry long notional across the venues and charge 1%
  annual on it for 30 days. Exit fees are priced at the assumed common exit.
  Actual account fees, collateral requirements and funding notionals may
  differ. Cross-venue USDT transfers and borrow costs are not modeled.
- A symbol/side advances only if **both** sizes have valid timely depth,
  positive conditional net cash, and at least 4% annualized conditional
  return on the illustrative reserved capital. A passing quote requires a
  separately specified forward observation and account/fill/margin proof.
  Do not retune costs, freshness, sizes, horizon or acceptance threshold after
  seeing the data. No order or shadow position is authorized.

Official references: [Binance USD-M market-data API](https://developers.binance.info/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data), [Bybit funding history](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate), [Bybit instrument metadata](https://bybit-exchange.github.io/docs/v5/market/instrument), [Bybit order book](https://bybit-exchange.github.io/docs/v5/market/orderbook), [Bybit fee schedule](https://www.bybit.com/en/help-center/article/Trading-Fee-Structure).
