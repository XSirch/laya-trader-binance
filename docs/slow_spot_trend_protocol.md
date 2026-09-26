# Slow BTC/ETH spot trend research protocol

Specified before calculating this rule's 2025 monthly outcomes. The separate quarterly-basis research has already used some 2026 BTC/ETH prices, so 2026 cannot be described as an untouched market period.

## Hypothesis and fixed rule

[Moskowitz, Ooi and Pedersen's time-series momentum study](https://pages.stern.nyu.edu/~lpederse/papers/TSMOM_Slides.pdf) uses each instrument's own prior 12-month return as a directional signal in diversified futures. This is a narrower, unlevered spot adaptation, not a replication of their return claim.

- BTCUSDT and ETHUSDT spot only. No futures, borrowing, staking yield or short position.
- At 00:00 UTC on the first day of each month, buy a coin only when its open price at 00:00 UTC on the previous day exceeds its open price exactly 365 days earlier. The one-day lag makes both signal prices available before entry.
- Allocate 49.5% of starting-month capital to each eligible coin, including the entry fee; keep the rest as USDT. Close every active coin at the first daily open of the next month, even when it remains eligible. This charges a complete monthly round trip rather than assuming free continuation.
- Entry and exit use the archived daily open. Charge 10 basis points fee plus 2 basis points slippage per side. The stressed case adds another 2 basis points per side. Account value at each daily open assumes all held coins could be sold then at the same cost.
- Require continuous, positive daily opens from January 2023 through the last required exit. Start with February-December 2024 as development, then January-June 2025 as calibration. Exit June's positions on July 1. Do not calculate July-December 2025 for this rule if calibration fails.

## Gate and limits

Calibration needs at least four active months, at least six active coin-months, at least four profitable months out of six, positive compounded return after stressed costs, maximum modeled daily drawdown better than -25%, and a positive lower 95% bound for mean monthly return from a fixed-seed two-month circular block bootstrap with 10,000 samples. No parameter will be adjusted after seeing the 2025 H1 result and then presented as an independent test.

Passing this gate would permit a diagnostic 2025 H2 replay and a separate 2026 check, not establish robust executable profit. Daily candle opens are not order-book quotes or guaranteed fills; the fixed 2-4 basis point slippage allowance must be checked against live depth for the actual order size. USDT idle balance earns zero. Taxes and venue outages are omitted.
