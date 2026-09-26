# Independent Bybit USDC six-month basis price screen

Specified before reading prices from the Bybit USDC spot or dated-future trade archives for this sample. It applies the existing always-enter rule to a different settlement currency and venue; it is a historical price screen, not proof of executable profit.

## Fixed sample and execution

- Include all five half-years with archived BTC and ETH USDC dated futures at the fixed entry: 2023 H2 (December 29 expiry), 2024 H1 (June 28), 2024 H2 (December 27), 2025 H1 (June 27), and 2025 H2 (December 26). Enter at 00:00 UTC on January 1 or July 1 as applicable and exit at 00:00 UTC two calendar days before expiry. Use BTCUSDC and ETHUSDC spot and the matching BTC/ETH USDC dated future. Do not select, substitute, or retime a leg after reading prices.
- Read the complete first-party Bybit monthly spot gzip and daily dated-future gzip for each entry/exit day. Filter trade timestamps for the exact [00:00, 00:05) UTC window, independent of file ordering. Require positive finite prices, a matching symbol and at least one trade for every market-side window. Read each gzip stream to completion and record the compressed source SHA256. If a required window is absent, report no complete account return.
- Buy spot at the highest spot trade price and short the future at the lowest future trade price in the entry window. At exit, sell spot at its lowest and cover the future at its highest trade price in the exit window. Use continuous normalized spot quantity `0.5 / entry_spot_high` for each symbol and the same base quantity in the future. No contract rounding or fill is inferred from trade extremes.

## Fixed accounting and interpretation

- Charge 19 basis points per side in both markets, as in the frozen Binance six-month rule, and measure cash profit on the same 4.05 normalized starting account. Separately subtract a simple illustrative capital charge of 1% per 365 days on the full 4.05 capital during each holding period. This charge is a sensitivity assumption, not an observed borrowing rate or account-specific fee.
- Report each symbol, every half-year, total modeled cash return before and after that capital charge, and whether all five half-years remain positive after it. A negative period weakens cross-venue robustness. Positive prices alone cannot pass the final user criterion without lot-size, fee-tier, bid/ask capacity, margin/liquidation, USDC settlement and truly independent forward evidence.

This sample and cost rule will not be changed after observing the outcomes. No live orders are authorized.
