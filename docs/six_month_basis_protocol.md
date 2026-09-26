# Six-month BTC/ETH delivery-basis research protocol

Frozen before reading exit prices for this six-month rule. Entry-only adverse one-minute premia for the six January/July starts from 2024 through 2026 were already inspected. The earlier three-month delivery-basis research also revealed the broad market periods, so these are exploratory historical comparisons, not pristine independent holdouts.

## Fixed position and execution rule

- On January 1 and July 1 at 00:00 UTC, buy BTCUSDT and ETHUSDT spot and short the matching USD-M delivery future expiring on the last Friday of June or December. Binance's [2024 December-contract announcement](https://www.binance.com/en/support/announcement/detail/41d6514883444ea39b7324859e937c31) confirms the next-quarter listing after the June expiry; the required entry archive files exist for every studied half-year.
- Exit both legs at 00:00 UTC two calendar days before expiry, without using delivery settlement. Entry and exit each use the first common traded minute within five minutes of the target. Buy spot at that minute's high, short the future at its low, sell spot at its low, and cover the future at its high. A common traded minute and aggregate volume do not prove fills.
- Set each spot quantity to 0.5 normalized USDT divided by its adverse entry spot price. Short exactly that base-asset quantity on the future. Do not resize while open.
- Charge the frozen final quarterly-basis stress of 19 basis points per side on spot and 19 basis points per side on futures, including fee and additional slippage. Idle USDT earns zero; no funding is paid on a delivery future.

## Wallet and risk rule

- Begin with 1.05 normalized USDT in spot cash and 3.00 in separate futures cash, total 4.05. Pay spot and future entry costs from their respective wallets. After closing both legs, transfer USDT to restore 3.00 futures cash before the next entry; fail if spot cash becomes negative.
- For every UTC day while a pair is open, mark both short futures at that day's future high plus a simultaneous 10% shock. Require futures equity above an assumed 5% maintenance charge on stressed notional. Value account liquidation at daily spot and future opens after estimated exit fees, and record peak-to-trough drawdown.
- An illustrative 1,000 USDT account's base-asset quantity must be compared with first-minute traded volume at entry and exit, but volume is not order-book depth or a fill guarantee.

## Chronology and interpretation

Replay the five completed January/July entries from January 2024 through January 2026, in one continuous account. The July 2026 position is still open as of this protocol and must not be assigned a completed return. Report 2024, 2025 and 2026 H1 separately, as well as the account total. Do not retune the entry or exit rule after seeing exits.

The research gate requires all five completed half-years to have positive stressed cash profit, at least 1% return on initial capital in each complete calendar year (2024 and 2025), minimum modeled margin cushion of 0.50 units, no spot-wallet shortfall, and maximum modeled daily liquidation drawdown less than 5%. Passing would make this a candidate for prospective and exchange-specific execution work, not evidence of live executable profit or permission to trade. Live depth, actual fee tier, contract lot sizes, account eligibility, exact mark-price/liquidation rules, financing opportunity cost, taxes and transfer timing remain unverified.
