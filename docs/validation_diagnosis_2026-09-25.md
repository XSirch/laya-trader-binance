# Validation diagnosis, 2026-09-25

## Decision

No candidate has demonstrated a robust, executable edge after costs. Multiple exploratory probes have now inspected 2025 H2, so it is no longer an untouched holdout for these ideas. The 2026 final test remains untouched. Do not launch another full Laya training run or enable live orders on the current evidence.

## Existing 15 minute Laya checkpoint

The completed Colab A100 run evaluated 100,000 records from 2025 H2. The report is preserved in `MyDrive/laya-trader-colab/persistent/validation_report.json` and `.md`; the checkpoint is in `MyDrive/laya-trader-colab/checkpoints/laya-trader-v0.1-local`.

- Default thresholds: zero trades. The loosest grid pair (tradeable 0.50, action probability 0.40) admitted 870 signals, all classified FLAT.
- Action target agreement: 34.902%; choosing the most frequent target action gives 34.585%. Action NLL: 1.097049, close to the uniform three-class NLL of 1.098612.
- A stratified 2,000-record A100 probe across 20 symbols found median maximum action probability 0.3506 and 99th percentile 0.4009. No LONG or SHORT in that probe passed both 0.50 tradeability and 0.40 action probability. Mean predicted tradeability was 0.6753.
- Calibration action NLL changed from 1.097170 to 1.096957. Calibration cannot repair poor action ranking.
- The old report's `action_ece=0.347559` used entropy confidence rather than the probability of the predicted class; that number is not a valid top-class ECE. The evaluator has been corrected, but the full report has not been regenerated with the corrected metric.

The local dataset manifest shows 100,000 examples per split and stable action-target proportions. Mean label cost rose from 0.2706 R in calibration to 0.3186 R in validation. The original training log's loss near 8.85 was inflated by dividing eight accumulated microbatches by one update; future logging now reports mean loss per microbatch.

## Lower-cost model probes

These are diagnostic baselines using the already downloaded 15 minute candles. Candidate model and threshold choices used 2025 H1 calibration; 2025 H2 was evaluated afterward. The six model variants make calibration selection optimistic. Results are in R units after the configured 14 bps round-trip fees and slippage. Signals may overlap unless marked as nonoverlapping.

| Data and selected model | Calibration signals, mean R | Validation signals, mean R | Calibration nonoverlap by symbol | Validation nonoverlap by symbol |
|---|---:|---:|---:|---:|
| 15m, 20 symbols, ridge | 692, +0.2743 | 555, -0.1370 | not audited | not audited |
| 1h, five major symbols, shallow gradient boosting | 564, +0.0289 | 616, +0.1056 | 109, -0.0515 | 127, +0.1316 |
| 1h, all 20 symbols, ridge | 1,416, +0.2172 | 1,170, -0.0069 | not audited | not audited |
| 4h, all 20 symbols, ridge | 1,336, +0.2136 | 1,106, +0.0365 | 259, +0.1737 | 225, +0.0203 |

The five-symbol 1h result fails the calibration nonoverlap check. Its validation mean has a 95% week-block bootstrap interval of [-0.0698, +0.3091] R. The 4h result has only two profitable validation months out of six after nonoverlap; an extra 4 bps round-trip cost reduces its mean to +0.0016 R. Its 95% week-block interval is [-0.2807, +0.3096] R. Neither is strong enough to justify a new expensive Laya run.

The resampling probes accepted only complete groups of four or sixteen source candles, kept temporal purging and a 16-bar embargo, and used the configured triple-barrier outcomes. Nonoverlap held each symbol through the full label horizon, which is conservative because an actual barrier hit may close earlier. Funding, portfolio position sizing, and simultaneous cross-symbol risk are not included.

## Causal funding feature probe

Downloaded 16,440 historical funding records for BTC, ETH, BNB, SOL, and XRP from the [official Binance public data archive](https://data.binance.vision/), covering 2023-2025. A 1h probe used only the most recently settled funding rate and its trailing three-event mean, with at least a one-hour lag. Training used 2023-2024; calibration was 2025 H1; validation was 2025 H2. Both models used the same weak gradient booster and thresholds were chosen on calibration. Returns below are after the configured 14 bps round-trip cost and conservatively nonoverlapping per symbol.

| Model | Calibration trades, mean R, positive months | Validation trades, mean R, positive months | Validation mean R with 4 bps extra cost |
|---|---:|---:|---:|
| Price and flow baseline | 220, +0.0291, 4/6 | 242, -0.0253, 2/6 | -0.0596 |
| Baseline plus lagged funding | 232, +0.0974, 4/6 | 242, -0.1147, 2/6 | -0.1507 |

Funding increased the calibration result but worsened the later period. The label still omits actual funding cash flows, so even a positive result would require an execution-level check. This experiment does not support a new GPU run.

## Evaluator fixes

- Top-class ECE now uses the predicted class probability.
- The random-direction baseline now takes the same number of directional trades as the evaluated policy.
- Threshold selection now uses calibration data and applies the selected threshold without retuning on validation. Both splits require enough conservatively nonoverlapping trades, positive mean R after configured costs, and profitable trades in at least two thirds of the months. It no longer falls back to an undersized or losing candidate.
- A stale threshold file is archived if a new validation selects none. The report distinguishes overlapping signals from the conservative nonoverlap result.

## Next research gate

The existing 15m Laya checkpoint, 1h/4h price-flow baselines, and 1h lagged-funding probe all fail the out-of-sample execution gate. The next hypothesis needs a changed label or a genuinely new causal input, such as historical order-book information, specified from training data before another validation comparison. Freeze the model, threshold, execution assumptions, and risk rules before using the 2026 final test once. A positive independent-signal average by itself is insufficient.

The exploratory scripts and generated data are retained locally under `outputs/`, which is ignored by Git. The Colab A100 runtime was disconnected after confirming the checkpoint and reports were in Drive.
