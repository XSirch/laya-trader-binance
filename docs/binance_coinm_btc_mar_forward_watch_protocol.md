# Prospective BTC March 2027 COIN-M quote observation

Freeze this read-only schedule before the first new book read. The earlier
full-universe COIN-M screen found BTCUSD_270326 closest to its 4% annualized
preliminary gate, at 2.166%. This is explicitly **post-selection** forward
observation of one previously inspected contract, not an independent test or
a completed trade. Reuse `binance_coinm_delivery_universe_screen.evaluate`
unchanged, including 500/1,000 USDT intended sizes, lot rounding, inverse
contract arithmetic, fees, uncertainty, capital charge, freshness rules and
the 4% threshold. Do not replace the contract or weaken its gate.

- Starting immediately after the protocol and collector are committed, take
  exactly 12 samples at monotonic offsets 0, 30, 60, ..., 330 minutes. For
  each sample fetch current Binance spot and COIN-M metadata, a 100-level
  BTCUSDT spot ask book, a 100-level BTCUSD_270326 COIN-M bid book, then a
  COIN-M server time. Record raw responses, URLs and local request/receive
  times in append-only JSONL; flush and sync before advancing the schedule.
  A request or evaluation error is a failed sample, not a reason to retry.
  If the computer sleeps and a scheduled start is more than two minutes late,
  record that sample as missed without replacing it.
- Require at least ten of twelve scheduled samples to pass the existing
  *both-size* 4%-annualized conditional quote gate before any account-specific
  review or forward paper-position design. Keep the exact sample timestamps,
  individual outcomes, SHA256 of raw JSONL and a final summary. A single
  favorable quote, or an incomplete run, does not pass. Adjacent readings
  are correlated and not independent profit outcomes.
- This is local, bounded research that stops after the twelfth sample. No
  order, transfer or shadow position is authorized. Even a stable quote does
  not prove fillable volume, fee tier, safe coin collateral, spot sale,
  settlement convergence or realized after-cost profit.

Official data sources: [Binance COIN-M market-data API](https://developers.binance.com/docs/derivatives/coin-margined-futures/market-data/rest-api/Get-Funding-Info), [Binance spot REST API](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md).
