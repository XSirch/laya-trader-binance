# Jev Binance Research

This repository is a clean research pipeline for unleveraged Binance Spot trading. It downloads first-party hourly BTCUSDT, ETHUSDT, BNBUSDT, and SOLUSDT candles, checks Binance's published SHA256 for every ZIP, compares a fixed set of long-or-flat rules, and optionally asks OpenRouter Jev 1.13 whether to accept each candidate entry. It never sends an order.

## Setup

Use Python 3.11 or newer. On Windows:

```powershell
uv sync --python 3.13
uv run jev-trader research
```

For Jev calls, put the API key in the repo-root `.env`:

```text
OPENROUTER_API_KEY=your_key_here
```

The `.env` file is ignored by Git. Never commit or paste the key. Then run:

```powershell
uv run jev-trader jev-smoke
uv run jev-trader jev-replay
```

`research-cached` recalculates the rule comparison from verified local ZIPs without network downloads.

`uv run jev-trader research-extended` runs the second, explicitly exploratory
comparison: 11 daily technical rules, five weekly statistical forecasts, cash,
buy-and-hold, and a quarterly selector that can abstain. It uses only verified
cached archives and cached Jev decisions; no paid requests are made. Forecasts
use trailing training data with fully observed seven-day labels, and selection
uses only earlier periods. Outputs include training timestamp audits, cost and
execution-delay stress, asset exclusions, an hourly equity check, and a direct
numeric-checklist versus Jev comparison in `results/extended_research.json`.
See [the second-round report](docs/extended_research_2026-09-26.md).

For the multi-parameter Jev experiment, use
`uv run python -m jev_trader.multifactor` for local rules and cached responses.
It combines 103 market fields across daily candles, four-hour candles and
cross-asset context. All indicators and all five adherence questions travel in
**one request per asset/time decision**. Jev returns only criterion adherence;
the Python script owns entry, hold and exit decisions through fixed thresholds.
The paid replay is explicit: `uv run python -m jev_trader.multifactor --budget-usd 2`.
The user authorized a maximum of USD 2 for this experiment on 2026-09-26.
The ledger reserves in-flight charges and blocks retries with unreconciled costs.
See [the multi-parameter report](docs/multifactor_research_2026-09-26.md).

The extended implementation corrects entry-cost compounding: entry costs reduce
capital before the subsequent market return. Earlier reports retain their
historical values; fresh replays use the corrected execution arithmetic.

## Fixed research design

- Data: official Binance Spot 1h archives, 2023-01 through 2026-08 inclusive. Each ZIP is matched to its `.CHECKSUM`; timestamp gaps and OHLC sanity are checked. The extra August archive supplies the 2026-08-01 exit open. No candle is invented for a gap. The exact source ZIP hashes and gap counts are recorded in `data/binance/spot/1h/manifest.json`.
- Signals: buy and hold benchmark, two moving-average trends, two channel breakouts, two RSI reversals, and one 24-hour momentum rule. Parameters are fixed in `strategies.py` before evaluation.
- Execution: signal from a completed candle acts at the next candle's open. Splits begin flat and force a close at the end. Base cost is 0.15% per side (0.10% fee plus 0.05% assumed adverse execution); stress cost is 0.25% per side. These are assumptions, not an account-specific fee quote.
- Periods: 2023-04 to 2024-12 development; 2025 H1 calibration and single-rule selection; 2025 H2 validation; 2026 Jan-Jul confirmation. A rule must have at least 12 trades, positive return under both costs, positive results in at least two-thirds of months, and at most 25% stress drawdown for each gate.
- Selection: only the chosen non-hold rule and the fixed hold benchmark are evaluated in the later periods. A failed calibration still yields a clearly labeled diagnostic leader, not a trading recommendation.
- Jev: the pinned `typesafe/jev-1.13` model sees only completed-bar features at each RSI14 rule entry. It returns a Noul probability that an explicit entry checklist is satisfied: RSI14 <= 30, close > SMA200, 24-hour return in [-5%, 0%], 24-hour high/low range <= 8%, and last one-hour return > -1.5%. Code enforces those numeric bounds; Jev probability must also be at least 0.70. The exit rule is deterministic: RSI14 >= 55, close < SMA200, or end of the split. Each record is sent in a separate request because 20-record batches yielded inconsistent numeric judgments in a diagnostic comparison. Responses are cached by content hash in `results/jev_checklist_single_decisions.jsonl`; the API key is never written there.

Reports are written to `results/research.json` and `results/jev_replay.json`. `data/` and `results/` are ignored by Git. No live trading, leverage, shorting, order routing, or exchange API keys are present.

## Interpretation

The ranking identifies the best candidate **within this fixed comparison**, not a guaranteed profitable strategy. Hourly kline opens do not prove order fills; slippage is assumed. Fees vary by account. Earlier project research already inspected parts of 2025-2026, so these periods are not pristine holdouts. Jev is a general structured-decision model, not a price model trained on these candles. Its entry filter must improve a chronologically later period after costs before it can be considered useful.

Sources: [Binance public-data format and checksums](https://github.com/binance/binance-public-data/blob/master/README.md), [OpenRouter Jev Decisions API](https://openrouter.ai/blog/insights/what-is-jev/).
