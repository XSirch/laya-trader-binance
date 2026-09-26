# Binance December 2026 forward quote observation

Frozen before the observation run. This extends the single public-book read in
`binance_dec26_forward_quote_protocol.md`; it does not change its symbols, two
intended sizes, quantity rounding, fees, capital charge, timing checks or 4%
annualized conditional return requirement. Each read uses the same evaluator.

- Take exactly 12 scheduled reads, 60 seconds apart by a monotonic local clock.
  A failed API read or evaluation counts as a failed sample; do not replace it.
  Keep every raw API response and local request/receive time in an append-only
  JSONL file. Flush each sample to disk before scheduling the next. Save a
  SHA256 digest of the finished JSONL file with the summary.
- For each sample, require the existing gate to pass for BTC and ETH at both
  500 and 1,000 USDT intended spot notionals. Require at least 10 of the 12
  scheduled samples to pass the full gate before requesting account-specific
  fees and checking whether a paper position is worth tracking. Report counts
  and the observed conditional returns for all four legs. Do not interpret
  12 adjacent readings as 12 independent return outcomes.
- A passing observation remains conditional. Displayed book depth does not
  establish fills, simultaneous hedging, future spot-sale prices, settlement
  convergence or a safe margin path. No order is authorized. Even repeated
  entry quotes cannot establish a robust realized profit.

The alternative daily reversal idea is deferred: the underlying
[primary research](https://eprints.lancs.ac.uk/172093/1/Babiak_Trading_Volume.pdf)
reports its strongest effect in smaller, less liquid coins and says larger,
more liquid coins have returns close to zero. It also says its hypothetical
closing-price fills are not a real-time trading recipe. Moving this effect
to this project's liquid perpetual universe would add financing, shorting
and execution assumptions before it offered credible executable evidence.
