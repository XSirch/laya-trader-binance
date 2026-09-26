# Exploratory BNSOL plus SOL perpetual monthly replay

This is post-selection exploration: the August-September 2026 BNSOLSOL
close-price rise and SOLUSDT funding were already inspected, and the public
BNSOLSOL daily series was checked for its first available date. It began
2024-10-10, so fix **all 22 complete calendar months from November 2024
through August 2026** before requesting older history. Do not drop an
unavailable or losing month. A pass requires independent prospective evidence.

Reuse the WBETH replay's `evaluate_month` economics **unchanged** from commit
`5088847`, substituting BNSOLSOL for WBETHETH and SOLUSDT for ETHUSDT. Buy an
illustrative 1,000 USDT of BNSOL at the previous daily close on entry day,
fix a short SOLUSDT perpetual equal to its starting SOL exposure, and close
both at the previous daily closes at the next month boundary. Include each
settled funding event strictly inside the month using its reported mark price.
Require all entry/exit closes and no funding gap over 8.5 hours. Maintain the
same four spot taker charges, two future taker charges, slippage, 0.50%
adverse liquid-staking-token exit-price stress, 1% annual capital charge and
2.05 times reserved capital. These are illustrative, not bounded risks.

The preliminary economics gate requires at least 17/22 months with positive
stressed cash, plus at least 4% annualized stressed return on reserved
capital in **both full 2025 and January-August 2026**. Report November-
December 2024 separately as short inception history. Passing these proxies
would still require account eligibility, fillable depth, redemption, margin
and prospective funding checks. No order or shadow position is authorized.

Binance says BNSOL rewards and redemption depend on a variable conversion
ratio, while spot prices can deviate from redemption value. Its official
October 2025 incident also included BNSOL collateral liquidations. Daily
closes cannot capture an intraday depeg or demonstrate margin safety.

Primary sources: [SOL staking](https://www.binance.com/en/solana-staking),
[depeg incident](https://www.binance.com/en/support/announcement/detail/0989d6c7f32545bfb019e3249eaabc3f),
[spot market data](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md),
[USDT-M funding history](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History).
