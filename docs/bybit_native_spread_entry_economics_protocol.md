# Bybit native carry spread: fixed public-quote economics screen

Specified after the initial 2026-09-26 native spread snapshot and ten-sample freshness watch, but before this screen's new API reads. This is a post-observation feasibility diagnostic, not a historical holdout, fill, account return or trading instruction. No orders may be placed by this script.

## Sample and size

- Read one contemporaneous public 25-level native spread book for each of `BTCUSDT-25DEC26_BTC/USDT` and `ETHUSDT-25DEC26_ETH/USDT`, one ordinary spot book for each corresponding `BTCUSDT` and `ETHUSDT`, and each native combination's instrument metadata. Preserve the raw response fields, request/response UTC times, source URLs and errors in an ignored JSON report. Do not replace failed or stale calls.
- Evaluate both fixed intended spot notionals, 500 and 1,000 USDT, for both coins. Compute quantity as the floor of intended notional divided by the ordinary spot best ask, in whole `lotSize` steps. Reject quantity below `minSize`. For selling the carry combo, walk displayed native spread **bid** levels best-first until the whole rounded quantity is covered; otherwise report insufficient visible depth. The volume-weighted bid spread is conditional quote revenue per coin, not a fill.
- Report `ts - cts` for native and ordinary books. Flag a quote as current for this conservative screen only when both books have positive sides, both `ts - cts` ages are in [0, 10] seconds, and their response `ts` values are at most five seconds apart. An older unchanged quote may still be executable; this flag is an evidence requirement.

## Conditional hold-to-expiry arithmetic

For each covered size, use `q` times the bid VWAP spread as entry premium, and the ordinary spot best ask `S` as the reference leg price. The implied future entry reference is `S + spread`. Hold the short USDT future until its metadata `deliveryTime`, then sell the remaining spot. The following **illustrative**, adverse costs are fixed before the read:

- Entry combo trading fees: half of published VIP 0 spot taker 0.1000% times `q*S`, plus half of published VIP 0 future taker 0.0550% times `q*(S+spread)`.
- Future settlement fee: 0.0500% of `q*S`. This conservatively follows Bybit's 2026-09-10 USDT expiry FAQ; an older Bybit fees page says no USDT futures settlement fee, so the actual account and product treatment must be verified.
- Exit spot taker fee: 0.1000% of `q*S`. Add 0.1000% of `q*S` for adverse spot sale slippage and 0.1000% for settlement-index versus realizable spot-price mismatch. Future spot level at expiry and path risk remain unknown; these fixed amounts are stresses, not upper bounds.
- Capital: reserve `2.025*q*S` as an illustrative unlevered account allocation, consistent with half of the earlier 4.05-unit two-coin basis account. Charge 1.00% annual on that allocation through delivery, using actual days/365. Actual UTA collateral, borrowing, opportunity cost, liquidation path and tax remain unverified.

Calculate conditional net cash and return on reserved capital. Do not aggregate BTC and ETH as a realized portfolio or call a positive quote profitable. A positive estimate at both intended sizes with current books justifies longer forward observation and account-specific fee/collateral verification. A missing book, insufficient depth, stale-book flag or nonpositive estimate does not satisfy that gate. Record all outcomes, including failures, without retuning size, cost or freshness after reading data.

Sources: [Bybit spread order book](https://bybit-exchange.github.io/docs/v5/spread/market/orderbook), [instrument metadata](https://bybit-exchange.github.io/docs/v5/spread/market/instrument), [ordinary spot book](https://bybit-exchange.github.io/docs/v5/market/orderbook), [spread fees and matched legs](https://www.bybit.com/en/help-center/article/FAQ-Spread-Trading), [VIP fee schedule](https://www.bybit.com/en/help-center/article/Trading-Fee-Structure), [USDT expiry FAQ](https://www.bybit.com/en/help-center/article/FAQ-USDT-Perpetual-and-Expiry-Contracts).
