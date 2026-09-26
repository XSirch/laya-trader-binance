# Quarterly basis, 2026 final evaluation protocol

Frozen before reading complete 2026 outcomes on 2026-09-26. The 2023-2025 development evidence and its limitations are in `docs/validation_diagnosis_2026-09-25.md`. Only the first three completed 2026 quarters will be evaluated. Archive URL existence was checked; 2026 prices and returns were not inspected while writing this protocol.

## Fixed position rule

- Markets: BTCUSDT and ETHUSDT spot, each paired with the corresponding Binance USD-M quarterly delivery future. No other symbols or contract choices.
- Entry: first common traded minute within five minutes of 00:00 UTC on January 1, April 1, and July 1. If there is no common minute, the quarter fails the evaluation.
- Exit: first common traded minute within five minutes of 00:00 UTC two calendar days before the last Friday of that quarter. Both legs close then, before delivery.
- Quantity: 0.5 units of initial normalized USDT spot allocation divided by that entry minute's spot high, independently for BTC and ETH. The future short has the same base-asset quantity. No resizing during a quarter.
- Adverse execution bound: buy spot at the entry minute's high, sell the future at its low; sell spot at the exit minute's low and buy the future at its high. This is a deliberately pessimistic within-minute price combination, not evidence of fill availability.
- Charge 10 bps spot and 5 bps future fee per side, plus 2 bps slippage per side on both markets. The stressed result adds 2 bps per side on each market and then a further 5 bps spot and 10 bps future per side. No funding cash flow is modeled for a delivery future. Idle USDT earns no interest.

## Capital and risk rule

- Initial normalized account: 1.05 units in the spot wallet and 2.00 in the futures wallet, for 3.05 total. Keep the wallets separate while positions are open.
- After both legs close, transfer USDT between the wallets to restore 2.00 units in futures before the next quarter. If spot proceeds cannot fund that transfer and the next spot entries, the rule fails. Transfers are assumed costless and possible during the two-day gap; this must be verified for the actual account before deployment.
- Each day while short futures are open, price both shorts at that day's archived futures kline high plus a further simultaneous 10% mark shock. The futures wallet must exceed an assumed 5% maintenance amount on this stressed short notional. This is a research safety bound, not Binance's account-specific mark-price/liquidation engine.
- Record daily account liquidation value after estimated exit costs and the maximum daily drawdown. Do not assume the spot asset is automatic futures collateral.

## Acceptance and interpretation

The quantitative gate needs all three 2026 quarters to have positive stressed profit, at least 1.5% aggregate stressed return on the 3.05 initial capital over the three quarters, a minimum futures margin cushion of 0.50 units, no spot-wallet funding shortfall, and less than 5% maximum daily account drawdown. Entry and exit must both have a common traded minute within five minutes. For an illustrative 1,000 USDT account, record whether first-minute volume exceeds the needed base-asset quantity in each leg; volume alone does not establish executable depth.

Passing this gate would establish a stronger historical candidate, not authorization for live orders. The actual capital, account eligibility, current fee tier, order-book depth for that size, and live order handling still need verification. The public `bookTicker` archive lacks many historical quarterly-contract dates, including all required 2025 entry and exit dates, so the 2023-2025 execution estimate relies on minute-range and cost stresses rather than complete historical bid/ask evidence. No parameter will be changed based on the 2026 result and then presented as a fresh holdout.
