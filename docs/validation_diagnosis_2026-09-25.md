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

## Causal premium-index feature probe

Downloaded 180 monthly 1h premium-index archives for BTC, ETH, BNB, SOL, and XRP from the [official Binance public data archive](https://github.com/binance/binance-public-data), covering 2023-2025. The source files contain premium-index OHLC values. The probe used the last completed premium close, its trailing eight-hour mean, its trailing 168-hour z-score, and its eight-hour change. Every joined premium observation was at least one hour older than the decision timestamp. The five-symbol 1h price/flow baseline and the premium model used the same sampled rows, weak gradient booster, and 2023-2024 training period. The threshold was selected only on 2025 H1 calibration and held fixed for 2025 H2 validation. Signals were conservatively nonoverlapping per symbol and include the configured 14 bps round-trip cost.

| Model | Calibration trades, mean R, positive months | Validation trades, mean R, positive months | Validation mean R with 4 bps extra cost |
|---|---:|---:|---:|
| Price and flow baseline | No threshold passed the calibration gate | Not evaluated | Not evaluated |
| Baseline plus lagged premium index | 106, +0.0829, 4/6 | 94, +0.0057, 3/6 | -0.0289 |

The premium model fails the validation gate: fewer than 100 nonoverlapping trades, only three positive months, and a negative mean under the small cost stress. This is exploratory evidence, not a profitable strategy. The reproducibility script is `scripts/premium_probe.py`; run it with `uv run --with scikit-learn python -u scripts/premium_probe.py`. The raw result and cached premium data remain in ignored `outputs/` files. Five gaps longer than one hour were observed across the 131,400 archived premium bars, so a production feature pipeline would also need explicit gap handling. The 2026 final test remains untouched.

## Wider-barrier label probe

A separate five-symbol 1h probe relabeled outcomes with a 24-hour horizon, a 3 ATR take profit, and a 2 ATR stop. Its entry was the next hourly open; a candle touching both barriers was conservatively scored as a stop. The 14 bps round-trip cost was charged in R units. Positions were held through the full 24-hour horizon for nonoverlap, even if a barrier was hit earlier. A new boundary check excluded every label whose horizon crossed its train, calibration, or validation cutoff; the original 16-bar embargo was insufficient for this 24-bar label. The weak gradient booster and the four threshold choices were fixed before inspecting validation. Training used either the existing even sample or all available 2023-2024 hourly bars.

| Training rows | Calibration result after boundary check | Validation |
|---:|---|---|
| 12,628 even-sampled | No threshold passed; at 0.10, 168 trades, -0.0193 R, 3/6 positive months | Not used |
| 87,590 full hourly | No threshold passed; at 0.10, 117 trades, +0.0350 R, 3/6 positive months | Not used |

The first run, before the boundary fix, appeared to pass calibration. Removing the few cross-boundary labels changed the fitted model enough to eliminate that result. This sensitivity is a further reason not to launch a GPU training run from this label. The reproducibility script is `scripts/wide_barrier_probe.py`; raw reports are in ignored `outputs/wide_barrier_probe_report.json` and `outputs/wide_barrier_full_train_report.json`.

## Weekly premium and funding carry probe

A fixed five-symbol market-neutral rule selected the lowest trailing eight-hour premium for a long and the highest for a short at each Monday UTC open. It held for seven days. The premium observation was at least one hour old; entries and exits used complete hourly candles. Historical settled funding was included with the side-appropriate sign, and each leg paid 14 bps round trip. The portfolio allocated half of gross notional to each leg. Weeks crossing split boundaries were omitted.

| Period | Complete weeks | Mean weekly net return | Mean weekly funding contribution | Positive months | Compounded return |
|---|---:|---:|---:|---:|---:|
| 2023-2024 development | 103 | +1.7618% | +0.0956% | 17/24 | +401.3% |
| 2025 H1 calibration | 25 | -0.9034% | +0.0090% | 1/6 | -21.3% |

The large earlier gain was mostly relative price movement, not funding carry, and failed in the next period. The rule was rejected at calibration; its 2025 H2 result was not used for selection. This approximation does not model liquidation, exchange margin, changing position notional, or funding settlement in a real account. The reproducibility script is `scripts/carry_probe.py`; run it with `uv run --with scikit-learn python -u scripts/carry_probe.py`. It obtains the premium and funding archives through the companion scripts if their caches are absent. The raw report is in ignored `outputs/carry_probe_report.json`.

## Target interpretation

The current 15m `tradeable` target comes from `max(long_r, short_r)` after observing the future path. In the local training split, 69.09% of rows had a positive best-side return in hindsight, although the mean long and mean short returns were -0.2867 R and -0.2428 R after costs. This distinction can explain why the model predicts tradeability near 0.68 while its action probabilities stay nearly uniform. It is an inference from the label definition and measured splits, not proof that a different label would create a tradable edge. A future label or teacher should estimate conditional expected net return from causal inputs, then be checked out of sample before spending GPU time.

## Historical positioning-metrics probe

Downloaded 5,480 daily archives for the same five symbols from the [Binance USD-M metrics archive](https://data.binance.vision/?prefix=data/futures/um/daily/metrics/), covering 2023-2025. Each archive contains five-minute open-interest value, top-trader and global long/short ratios, and taker-volume ratios. The fixed features were the 24-hour change in open-interest value, the two long/short ratios, their log difference, and the trailing one-hour taker ratio. Every metric was joined at least one hour after its source timestamp; stale or incomplete observations were excluded. The baseline and augmented model used the same rows, weak gradient booster, 14 bps round-trip cost, and conservative nonoverlap per symbol. Threshold selection used only 2025 H1. The project trade-count rule requires `max(100, 0.5% of split rows)`: 107 calibration trades and 108 validation trades here.

| Training data and model | Calibration trades, mean R, positive months | 2025 H2 trades, mean R, positive months | H2 mean R with 4 bps extra cost |
|---|---:|---:|---:|
| Even sample, price/flow only | No passing threshold | Not used | Not used |
| Even sample, plus metrics | 128, +0.2323, 5/6 | 95, +0.1481, 4/6 | +0.1171 |
| Full 2023-2024 hourly data, price/flow only | 103, +0.1297, 5/6; below 107 minimum | 105, -0.0553, 2/6; diagnostic before gate alignment | -0.0941 |
| Full 2023-2024 hourly data, plus metrics | 113, +0.3509, 5/6 | 93, +0.0767, 3/6 | +0.0410 |

The even-sample metrics variant falls 13 trades short of the 108-trade validation minimum. Its 95% week-block bootstrap interval for mean R is [-0.1126, +0.4711]. With the full training set, the metrics variant falls 15 trades short and misses the profitable-month requirement; its interval is [-0.2583, +0.3612] R. ETH was negative in both variants, and the results are sensitive to the training sample. As a further chronological check, training on full 2023 data and selecting on 2024 H1 produced no qualifying threshold for either model; the metrics variant at threshold 0.10 had 122 calibration trades, +0.0762 R, and only 3/6 positive months. Its 2024 H2 was therefore not used. These are exploratory 2025 H2 comparisons, which have already been inspected by several hypotheses. Funding cash flows, portfolio sizing, and simultaneous cross-symbol exposure are not included. Neither variant supports a new GPU run or use of the untouched 2026 final test.

The dataset and probe scripts are `scripts/build_one_hour_full_five.py`, `scripts/metrics_probe.py`, `scripts/metrics_inner_probe.py`, and `scripts/analyze_metrics_probe.py`. Build the uncapped dataset with `uv run python -u scripts/build_one_hour_full_five.py`, then run the main probe with `uv run --with scikit-learn python -u scripts/metrics_probe.py --full-data --validation`. Daily source ZIPs and JSON reports remain in ignored `outputs/` files.

## Daily-horizon label probe

A separate CPU probe used the existing 20-symbol universe and aggregated only complete groups of 96 source 15m candles into daily bars. Causal daily price, trend, volume, and flow features trained a fixed shallow gradient booster on 2023-2024. Outcomes entered at the next daily open, held for up to five days, used a 3 ATR take profit and 2 ATR stop, and charged 14 bps round trip. Same-day touches of both barriers were scored as a stop. Temporal purging and a conservative 16-day embargo came from the existing split policy; positions were considered occupied until the full five-day label horizon. There were 13,768 training rows, 3,200 calibration rows, and 3,260 reserved validation rows.

The 2025 H1 calibration had no qualifying threshold. At 0.20, it produced 105 nonoverlapping trades and +0.0671 R after costs, but only 3/6 positive months. The 2025 H2 labels were not scored for this rule. The reproducibility script is `scripts/daily_trend_probe.py`; the report is in ignored `outputs/daily_trend_probe_report.json`. Funding cash flows and portfolio-level exposure are not included, but the calibration failure already rules out this candidate.

## Daily cross-sectional premium and funding probe

A fixed market-neutral rule ranked the 20 configured symbols by their trailing eight-hour premium-index mean at each UTC daily open. It bought the five lowest and sold the five highest, with equal gross weight across the ten legs. Each premium observation ended at least one hour before the decision. Entries and exits used consecutive complete daily bars from the existing 15m candles. Actual funding settlements between the opens were included with the side-appropriate sign. Each leg paid 14 bps round trip, with a further 4 bps cost stress. This daily choice was motivated by the [historical cross-sectional basis study](https://www.repository.cam.ac.uk/items/3a556482-574b-42cd-af07-fe5c9f9db91c); that study is not evidence that this rule works in these years or after these costs.

The probe requested 1,440 monthly premium and funding ZIPs from the [Binance public archive](https://data.binance.vision/); 1,428 existed. The 12 unavailable ZIPs were ARBUSDT January-February 2023 and SUIUSDT January-April 2023, for each of premium and funding. The universe had 13-20 eligible symbols per completed day (median 20). The median premium spread between selected long and short baskets was about 4.56 bps. A day was excluded if any selected leg lacked a consecutive complete price bar or settled funding observation; the rule never replaced a missing leg using its future outcome. Funding settlement and mark-to-market are approximated by source rates and open prices; the simulation does not model margin, liquidation, changing contract notional, or exchange execution.

| Split | Complete days | Mean daily net return | Compounded return | Mean daily price | Mean daily funding | Positive months |
|---|---:|---:|---:|---:|---:|---:|
| 2023-2024 training | 729 | -13.56 bps | -64.37% | -0.96 bps | +1.39 bps | 6/24 |
| 2025 H1 calibration | 181 | -15.41 bps | -25.11% | -2.15 bps | +0.74 bps | 3/6 |

The 2025 H1 gate required at least 150 complete days, a positive mean after the base and stressed costs, and four positive months. It failed on returns and month consistency. Its +0.74 bps daily funding receipt was far below the 14 bps turnover charge. The rule's 2025 H2 daily outcomes were therefore not calculated or used. Run `uv run python -u scripts/cross_basis_daily_probe.py` to reproduce the probe; cached archives and `outputs/cross_basis_daily_report.json` are ignored by Git. The 2026 final test remains untouched.

## Weekly cross-sectional momentum probe

A second fixed portfolio rule ranked the same 20-symbol universe by its prior 30-day open-to-open price return, ending one day before each Monday UTC entry. It bought the five strongest and sold the five weakest for seven days, with equal gross weights across ten legs. Entries and exits used complete daily bars aggregated from existing 15m candles. Settled funding was included with the side-appropriate sign. The base case charged 14 bps round trip per leg on every weekly holding period; the stress added 4 bps. The rule and gate were set before 2025 H2 was calculated. Weeks crossing a split boundary were excluded.

| Split | Complete weeks | Mean weekly net | Compounded return | Positive months | Maximum drawdown |
|---|---:|---:|---:|---:|---:|
| 2023-2024 training | 99 | +0.421% | +41.98% | 13/23 | -16.80% |
| 2025 H1 calibration | 25 | -0.004% | -1.52% | 3/6 | -17.83% |

The calibration gate required at least 20 weeks, positive mean return with base and stressed fees, at least four positive months, and drawdown below 25%. It failed on return and month consistency. To bound the effect of turnover accounting, a deliberately optimistic variant charged only entry and exit fees when a symbol or side changed, with no resizing fee for retained names. It produced +0.080% mean weekly return and +0.57% compounded in calibration, but still only 3/6 positive months. Even with zero fees, only three months were positive. A fuller simulator would also account for weight drift, margin, liquidation, and execution. This candidate was rejected without calculating 2025 H2. Run `uv run python -u scripts/cross_momentum_weekly_probe.py`; the report and weekly portfolios remain in ignored `outputs/` files.

## Weekly time-series momentum probe

A fixed rule took the sign of each configured symbol's lagged 30-day return, long for positive and short for negative, then held every position for seven days. All decisions used prices ending one day before the Monday UTC entry. Complete daily bars from the existing 15m candles supplied entry and exit prices. Actual settled funding was included; each weekly leg paid a conservative 14 bps round trip plus a 4 bps stress. An equal-gross variant and an inverse trailing 30-day volatility variant used the same signs. The second weighting was explored after seeing the equal-gross 2025 H1 result, so it is explicitly exploratory rather than an independent confirmation.

| Weighting | 2023-2024 compounded | Training positive months | Training max drawdown | 2025 H1 compounded | H1 positive months | H1 max drawdown | 95% four-week-block interval for H1 mean weekly return |
|---|---:|---:|---:|---:|---:|---:|---:|
| Equal gross | +83.24% | 13/23 | -32.40% | +14.73% | 3/6 | -19.58% | [-0.98%, +2.61%] |
| Inverse volatility | +71.37% | 12/23 | -28.98% | +14.38% | 2/6 | -16.89% | [-0.81%, +2.35%] |

Despite positive compounded returns after the configured costs, neither variant demonstrates robust profit. Both miss the four-positive-month calibration gate and both week-block intervals include a negative mean. The equal-weight training return was concentrated in a few large months, including November 2024; its training drawdown exceeded 30%. Volatility weighting reduced drawdown but did not improve month consistency. These are gross-notional portfolio approximations: they omit margin, liquidation, actual weight drift within a week, and exchange execution. No 2025 H2 outcomes were calculated for either variant, and the 2026 final test remains untouched. Run `uv run python -u scripts/time_momentum_weekly_probe.py` and add `--inverse-vol` for the second variant. Reports and weekly portfolios remain in ignored `outputs/` files.

## Evaluator fixes

- Top-class ECE now uses the predicted class probability.
- The random-direction baseline now takes the same number of directional trades as the evaluated policy.
- Threshold selection now uses calibration data and applies the selected threshold without retuning on validation. Both splits require enough conservatively nonoverlapping trades, positive mean R after configured costs, and profitable trades in at least two thirds of the months. It no longer falls back to an undersized or losing candidate.
- A stale threshold file is archived if a new validation selects none. The report distinguishes overlapping signals from the conservative nonoverlap result.

## Book-depth source check

Before building another input, a small quality check compared BTCUSDT snapshots from the [public daily `bookDepth` archive](https://data.binance.vision/?prefix=data/futures/um/daily/bookDepth/BTCUSDT/) with the local 15m candle open at or before each snapshot. The check estimated a book midpoint from the average of `notional / depth` for the -5 and +5 percentage bands. On 2024-01-01, all 2,880 snapshots aligned and none differed from the candle open by more than 10%. On 2025-05-19, 2,825 snapshots aligned but 46.87% differed by more than 10%; the 95th percentile absolute difference was 20.56%. The 2023-01-09 ZIP contained only eight snapshots, all in its final four minutes. A [report in the Binance archive repository](https://github.com/binance/binance-public-data/issues/431) independently flags apparent price misalignment in this data family. This is a spot check, not a comprehensive quality audit; book depth must pass coverage and price-consistency checks before it can be used as a trading feature.

A wider audit then requested 1,824 daily BTCUSDT and ETHUSDT archives for 2023-2024 and 2025 H1, and checked ZIP CRC, snapshot coverage, and price consistency on available files. The reproducibility script is `scripts/book_depth_coverage_probe.py`; run its default 2025 H1 period or pass `--start 2023-01-01 --end 2024-12-31`. A day passes if it has at least 2,000 snapshots, paired -5/+5 bands in at least 94 of 96 fifteen-minute intervals, at least 95% price alignment, no duplicate band timestamps, and at most 1% of aligned snapshots differing by more than 10% from the contemporaneous contract candle open. This price comparison is an anomaly screen, not a documented exchange definition of the book-depth fields. A preliminary rule requiring a snapshot in the first and last five minutes falsely excluded near-complete 2023 days; it was replaced by 15m-interval coverage before the results below were accepted.

| Period | BTC usable/requested | ETH usable/requested | Main exclusion |
|---|---:|---:|---|
| 2023-2024 | 716/731 | 715/731 | Isolated missing or sparse archives; two ETH price-anomaly days in March 2024 |
| 2025 H1 | 153/181 | 153/181 | The same 28-day price-anomaly block, 2025-04-22 through 2025-05-19 |

The 2025 block had normal snapshot counts but more than 1% large price deviations on every rejected day, for both symbols. It must be masked rather than treated as a normal feature history. Individual anomalous snapshots on accepted days must also be filtered before feature aggregation. The accepted 2023-2024 days provide enough coverage for a small BTC/ETH feature pilot, but this source has not yet shown predictive value, and a two-symbol pilot would not establish a robust 20-symbol trading result. Daily QC CSVs and JSON reports remain in ignored `outputs/book_depth_qc_*.{csv,json}` files. The 2025 H2 and 2026 outcomes were not inspected in this audit.

## Next research gate

The existing 15m Laya checkpoint, 1h/4h price-flow baselines, lagged funding, premium-index and positioning-metrics probes, wider-barrier and daily-horizon label probes, weekly and daily cross-sectional carry rules, and both momentum families fail their calibration or out-of-sample execution gate. Avoid more changes to these momentum rules based on their inspected 2025 H1 months. The next experiment can test lagged order-book imbalance as a new causal input on QC-accepted BTC/ETH days, selecting its specification within 2023-2024 before any 2025 comparison, then scale to the configured universe only if it adds repeatable value. Further 2025 H2 comparisons are exploratory because this period has been reused. Freeze the model, threshold, execution assumptions, and risk rules before using the 2026 final test once. A positive independent-signal average by itself is insufficient.

Earlier exploratory scripts and generated data are retained locally under `outputs/`, which is ignored by Git. The premium-index, funding, wider-barrier, carry, positioning-metrics, daily-horizon, daily cross-sectional, momentum, and book-depth QC scripts are tracked under `scripts/`. The Colab A100 runtime was disconnected after confirming the checkpoint and reports were in Drive.
