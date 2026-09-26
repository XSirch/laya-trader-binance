# Fixed historical extension of the six-month delivery-basis rule

This extension was specified after the 2024-2026 H1 results were inspected. It checks earlier market regimes, not a prospective holdout or independent proof of a future edge. No parameters or periods will be selected after viewing their outcomes.

## Periods and execution

- Evaluate all four half-years: 2022 H1 (entry January 1, June 24 delivery), 2022 H2 (entry July 1, December 30 delivery), 2023 H1 (entry January 1, June 30 delivery), and 2023 H2 (entry July 1, December 29 delivery). Use BTCUSDT and ETHUSDT USDT-margined delivery futures in every period, closing two calendar days before delivery at 00:00 UTC.
- Apply the same spot allocation, separate wallets, 19 bps per side in each market, five-minute direction-specific traded-volume window for an illustrative 1,000 USDT account, adverse minute highs/lows, daily-high plus 10% future mark shock, and 5% assumed maintenance as `docs/six_month_basis_protocol.md` and `docs/six_month_directional_volume_protocol.md`.
- Require Binance-public-data SHA256 and ZIP CRC for every daily and minute archive. If any contract archive or one of the four order-side direction-specific volumes is unavailable by the fifth minute, report the missing leg and no full-account return. Do not substitute another contract, date, market, size, or execution rule.
- Report each half-year return, each symbol leg, cumulative return on the 4.05 normalized account, minimum spot cash, minimum modeled futures margin cushion and maximum daily account drawdown. Report simple annualized break-even capital charge for each half-year as its return on initial capital times 365 divided by holding days. This charge is an opportunity-cost sensitivity, not an observed borrowing rate.

The original 2024-2026 research gate does not apply to this older extension. A negative half-year or wallet/margin failure weakens the robustness claim; positive returns still do not establish live executable depth or account eligibility. No live orders are authorized.
