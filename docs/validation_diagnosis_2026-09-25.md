# Validation diagnosis, 2026-09-25

## Decision

No candidate has demonstrated a robust, executable edge after costs. A six-month BTC/ETH delivery-basis replay passes its exploratory Binance historical gate, but an independent OKX price screen has two negative half-years, the fixed 1,000 USDT directional-volume proxy fails at ETH's July 2026 Binance entry, and Bybit has no future trade in the exact July entry window. The Binance entry premia were inspected before freezing the replay, live bid/ask depth remains unavailable, and the 2026 H2 exit has no completed outcome. Multiple exploratory probes have inspected 2025 H2, so it is not an untouched holdout. The frozen three-month quarterly-basis rule failed its January-September 2026 final test. A later audit found future-dependent ambiguous-bar exclusion in the older label dataset; the corrected positioning-metrics evaluation also fails below. Do not launch another full Laya training run or enable live orders on the current evidence.

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

The premium model fails the validation gate: fewer than 100 nonoverlapping trades, only three positive months, and a negative mean under the small cost stress. This is exploratory evidence, not a profitable strategy. The reproducibility script is `scripts/premium_probe.py`; run it with `uv run --with scikit-learn python -u scripts/premium_probe.py`. The raw result and cached premium data remain in ignored `outputs/` files. Five gaps longer than one hour were observed across the 131,400 archived premium bars, so a production feature pipeline would also need explicit gap handling. The separate quarterly-basis 2026 evaluation is reported below.

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

## Historical positioning-metrics probe (legacy labels; corrected below)

Downloaded 5,480 daily archives for the same five symbols from the [Binance USD-M metrics archive](https://data.binance.vision/?prefix=data/futures/um/daily/metrics/), covering 2023-2025. Each archive contains five-minute open-interest value, top-trader and global long/short ratios, and taker-volume ratios. The fixed features were the 24-hour change in open-interest value, the two long/short ratios, their log difference, and the trailing one-hour taker ratio. Every metric was joined at least one hour after its source timestamp; stale or incomplete observations were excluded. The baseline and augmented model used the same rows, weak gradient booster, 14 bps round-trip cost, and conservative nonoverlap per symbol. Threshold selection used only 2025 H1. The project trade-count rule requires `max(100, 0.5% of split rows)`: 107 calibration trades and 108 validation trades here.

| Training data and model | Calibration trades, mean R, positive months | 2025 H2 trades, mean R, positive months | H2 mean R with 4 bps extra cost |
|---|---:|---:|---:|
| Even sample, price/flow only | No passing threshold | Not used | Not used |
| Even sample, plus metrics | 128, +0.2323, 5/6 | 95, +0.1481, 4/6 | +0.1171 |
| Full 2023-2024 hourly data, price/flow only | 103, +0.1297, 5/6; below 107 minimum | 105, -0.0553, 2/6; diagnostic before gate alignment | -0.0941 |
| Full 2023-2024 hourly data, plus metrics | 113, +0.3509, 5/6 | 93, +0.0767, 3/6 | +0.0410 |

The even-sample metrics variant falls 13 trades short of the 108-trade validation minimum. Its 95% week-block bootstrap interval for mean R is [-0.1126, +0.4711]. With the full training set, the metrics variant falls 15 trades short and misses the profitable-month requirement; its interval is [-0.2583, +0.3612] R. ETH was negative in both variants, and the results are sensitive to the training sample. As a further chronological check, training on full 2023 data and selecting on 2024 H1 produced no qualifying threshold for either model; the metrics variant at threshold 0.10 had 122 calibration trades, +0.0762 R, and only 3/6 positive months. Its 2024 H2 was therefore not used. These are exploratory 2025 H2 comparisons, which have already been inspected by several hypotheses. Funding cash flows, portfolio sizing, and simultaneous cross-symbol exposure are not included. Neither variant supports a new GPU run or use of the untouched 2026 final test.

The dataset and probe scripts are `scripts/build_one_hour_full_five.py`, `scripts/metrics_probe.py`, `scripts/metrics_inner_probe.py`, and `scripts/analyze_metrics_probe.py`. Build the uncapped dataset with `uv run python -u scripts/build_one_hour_full_five.py`, then run the main probe with `uv run --with scikit-learn python -u scripts/metrics_probe.py --full-data --validation`. Daily source ZIPs and JSON reports remain in ignored `outputs/` files.

### Correction: ambiguous-bar selection

The original 1h metrics data inherited `drop_ambiguous = true`. It removed a row whenever a future candle first touched both the target and stop for either side. A live decision cannot know that fact, so the original metrics table above is a diagnostic of a future-filtered sample, not valid evidence of tradable profit. The common labeling code and dataset configuration now retain these rows and score the affected side as a stop when OHLC data cannot establish intrabar order. New dataset manifests record the ambiguity policy and per-split counts. Existing generated datasets and the completed Laya checkpoint still reflect their original labeling; they are not retroactively corrected. The local dataset manifest's old config hash differs from the current configuration hash, so resuming that checkpoint against a newly built dataset would mix label policies.

The five-symbol 1h data was rebuilt through 2025 with the same features, model, cost, chronological splits, and conservative full-horizon nonoverlap. Calibration still selected thresholds only from 2025 H1; 2025 H2 remained the next period. The corrected outcomes were:

| Training sample | 2025 H1 selection | 2025 H2 after 14 bps cost | Additional 4 bps stress | H2 gate |
|---|---|---|---:|---|
| Full 2023-2024, plus metrics | 0.075; 133 trades; +0.2558 R; 4/6 positive months | 118 trades; +0.0130 R; 2/6 positive months | -0.0236 R | Fail |
| Even sampled, plus metrics | No threshold passed calibration | Not evaluated | Not evaluated | Fail |
| Even sampled, price/flow only | 0.075; 153 trades; +0.1462 R; 5/6 positive months | 121 trades; -0.0237 R; 2/6 positive months | -0.0579 R | Fail |

The corrected full-data metric model had 86,845 training, 21,540 calibration, and 21,790 validation rows after causal metric availability checks. The even-sampled training variant had 12,533 rows. The trade minimums remained 107 and 108. The original full-data metric result was +0.0767 R on 93 H2 trades; the corrected evaluation is much weaker despite covering more rows. The even-sampled metric variant no longer qualifies for validation. Neither justifies evaluating 2026 or spending another GPU run. Reproduce the corrected research with `uv run python -u scripts/build_one_hour_conservative_five.py`, then `uv run --with scikit-learn python -u scripts/metrics_conservative_probe.py` and its `--even-train` variant. The generated datasets, trades, and reports are ignored under `outputs/`.

The local corrected full-data report SHA256 is `9fd873a5491e43814b182c2682021408af7d30333aee05a73bc02bd995e25352`; the even-sampled report SHA256 is `8e32343a21dcbbbdffa4c6627e64a599ab421d1713bd44cf5d2a8cce1bd7a06b2`.

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

The 2025 H1 gate required at least 150 complete days, a positive mean after the base and stressed costs, and four positive months. It failed on returns and month consistency. Its +0.74 bps daily funding receipt was far below the 14 bps turnover charge. The rule's 2025 H2 daily outcomes were therefore not calculated or used. Run `uv run python -u scripts/cross_basis_daily_probe.py` to reproduce the probe; cached archives and `outputs/cross_basis_daily_report.json` are ignored by Git. The separate quarterly-basis 2026 evaluation is reported below.

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

Despite positive compounded returns after the configured costs, neither variant demonstrates robust profit. Both miss the four-positive-month calibration gate and both week-block intervals include a negative mean. The equal-weight training return was concentrated in a few large months, including November 2024; its training drawdown exceeded 30%. Volatility weighting reduced drawdown but did not improve month consistency. These are gross-notional portfolio approximations: they omit margin, liquidation, actual weight drift within a week, and exchange execution. No 2025 H2 outcomes were calculated for either variant; the separate quarterly-basis 2026 evaluation is reported below. Run `uv run python -u scripts/time_momentum_weekly_probe.py` and add `--inverse-vol` for the second variant. Reports and weekly portfolios remain in ignored `outputs/` files.

## Long-only market trend, 28-day signal and five-day hold

A separate, unlevered spot rule was motivated by [Han, Kang and Ryu's time-series momentum study](https://acfr.aut.ac.nz/__data/assets/pdf_file/0009/918729/Time_Series_and_Cross_Sectional_Momentum_in_the_Cryptocurrency_Market_with_IA.pdf), which examined a 28-day lookback and five-day hold on a broader historical crypto market. This is an adaptation, not a replication: the local basket is fixed to BTC, ETH, BNB, SOL, and XRP at equal initial weights. Its market signal uses daily equal-weight open-to-open returns, ending at the previous day's open. The upper-tercile cutoff comes only from earlier 28-day returns in a trailing 365-day window, with at least 60 past observations. Five-day windows are anchored to 2023-04-01; if the signal exceeds the causal cutoff, the account buys the five spot assets for that window and otherwise remains in USDT. Every invested five-day window pays 12 bps per side in fee/slippage, even if the next window also invests; an extra 2 bps per side gives a 4 bps round-trip stress. No borrowed asset or futures margin is assumed.

| Period | Windows, invested | Net compounded | Extra-cost stress | Positive months | Daily drawdown | Four-window block 95% interval for mean window return |
|---|---:|---:|---:|---:|---:|---:|
| Apr 2023-Dec 2024 development | 128, 49 | +163.49% | +158.38% | 10/21 | -19.95% | [+0.070%, +1.691%] |
| 2025 H1 calibration | 35, 10 | +8.32% | +7.89% | 1/6 | -12.72% | [-0.452%, +1.379%] |

The calibration profit came mainly from May (+14.95% assigned to exit month); January and June lost money, and February-April held cash. The prespecified gate needed at least 12 invested windows, four positive months, positive stressed return, less than 25% modeled drawdown, and a positive lower block-bootstrap bound. It failed three of those five checks, despite the positive aggregate return. The same-date equal-weight spot buy-and-hold basket returned -14.88% during calibration, but avoiding that drawdown in this one period does not establish robust profit. The 2025 H2 outcome was not calculated. Run `uv run python -u scripts/market_trend_28_5_probe.py`; the report and window ledger are ignored under `outputs/`. The local report SHA256 is `79b45f8b76f7ab60e09d6262f22405ce8f2d11acf51040116f63bb9e591c9f13`.

## Slow BTC/ETH spot trend, 365-day signal and monthly hold

The distinct, unlevered slow-trend rule and gate were fixed in `docs/slow_spot_trend_protocol.md` at commit `27ade9f`, before calculating this rule's monthly results. It bought BTC and/or ETH spot for one month when that coin's own 365-day return through the previous daily open was positive. Each eligible coin received 49.5% of capital, with idle USDT earning zero. Every month paid a full 12 bps-per-side round trip; the stress raised this to 14 bps per side. The 62 required monthly archives for 2023-July 2025 were present, and the replay required a continuous daily series.

| Stage | Active coin-months | Positive months | Stressed compounded return | Maximum modeled daily drawdown | Two-month block 95% interval for stressed mean month |
| --- | ---: | ---: | ---: | ---: | ---: |
| February-December 2024 development | 22 | 6/11 | +74.94% | -36.31% | [-2.78%, +17.80%] |
| January-June 2025 calibration | 8 | 4/6 | **-12.37%** | **-32.31%** | [-11.36%, +4.98%] |

The predeclared calibration gate failed on stressed profit, drawdown and the bootstrap lower bound. February 2025 alone lost 24.89% in the stressed monthly replay and dominated the half-year loss. The 2025 H2 return was not calculated for this rule. This daily-open simulation does not establish fill availability at that price or the assumed slippage for a specific account. Reproduce with `uv run python -u scripts/slow_spot_trend_probe.py`; the ignored report SHA256 is `541e4819abe0d3d169440379ad1f3a00a6b1381f2bf25a4ce771af2cbaca9b21`.

## Evaluator fixes

- Top-class ECE now uses the predicted class probability.
- The random-direction baseline now takes the same number of directional trades as the evaluated policy.
- Threshold selection now uses calibration data and applies the selected threshold without retuning on validation. Both splits require enough conservatively nonoverlapping trades, positive mean R after configured costs, and profitable trades in at least two thirds of the months. It no longer falls back to an undersized or losing candidate.
- A stale threshold file is archived if a new validation selects none. The report distinguishes overlapping signals from the conservative nonoverlap result.

## Book-depth source check

Before building another input, a small quality check compared BTCUSDT snapshots from the [public daily `bookDepth` archive](https://data.binance.vision/?prefix=data/futures/um/daily/bookDepth/BTCUSDT/) with the local 15m candle open at or before each snapshot. The check estimated a book midpoint from the average of `notional / depth` for the -5 and +5 percentage bands. On 2024-01-01, all 2,880 snapshots aligned and none differed from the candle open by more than 10%. On 2025-05-19, 2,825 snapshots aligned but 46.87% differed from the candle open by more than 10%; the 95th percentile absolute difference was 20.36%. The 2023-01-09 ZIP contained only eight snapshots, all in its final four minutes. A [report in the Binance archive repository](https://github.com/binance/binance-public-data/issues/431) independently flags apparent price misalignment in this data family. This is a spot check, not a comprehensive quality audit; book depth must pass coverage and price-consistency checks before it can be used as a trading feature.

A wider audit then requested 1,824 daily BTCUSDT and ETHUSDT archives for 2023-2024 and 2025 H1, and checked ZIP CRC, snapshot coverage, and price consistency on available files. The reproducibility script is `scripts/book_depth_coverage_probe.py`; run its default 2025 H1 period or pass `--start 2023-01-01 --end 2024-12-31`. A day passes if it has at least 2,000 snapshots, paired -5/+5 bands in at least 94 of 96 fifteen-minute intervals, at least 95% price alignment, no duplicate band timestamps, and at most 1% of aligned snapshots differing by more than 10% from the contemporaneous contract candle open. This price comparison is an anomaly screen, not a documented exchange definition of the book-depth fields. A preliminary rule requiring a snapshot in the first and last five minutes falsely excluded near-complete 2023 days; it was replaced by 15m-interval coverage. The candle loader labels each bar by its close time, so an initial price join used the prior bar's open. The join was corrected to use `open_time` and both periods were recomputed; the accepted-day counts below remained unchanged.

| Period | BTC usable/requested | ETH usable/requested | Main exclusion |
|---|---:|---:|---|
| 2023-2024 | 716/731 | 715/731 | Isolated missing or sparse archives; two ETH price-anomaly days in March 2024 |
| 2025 H1 | 153/181 | 153/181 | The same 28-day price-anomaly block, 2025-04-22 through 2025-05-19 |

The 2025 block had normal snapshot counts but more than 1% large price deviations on every rejected day, for both symbols. It must be masked rather than treated as a normal feature history. Individual anomalous snapshots on accepted days must also be filtered before feature aggregation. The accepted 2023-2024 days provide enough coverage for a small BTC/ETH feature pilot, but this source has not yet shown predictive value, and a two-symbol pilot would not establish a robust 20-symbol trading result. Daily QC CSVs and JSON reports remain in ignored `outputs/book_depth_qc_*.{csv,json}` files. The 2025 H2 and 2026 outcomes were not inspected in this audit.

## Lagged book-depth feature pilot

A BTC/ETH-only one-hour pilot aggregated four fixed features from available archives: mean notional imbalance inside the -1/+1 and -5/+5 bands, the last -1/+1 imbalance, and log one-percent total notional depth. Each snapshot more than 10% away from the contemporaneous contract candle open was removed. An hour needed at least 60 valid snapshots covering all four 15m intervals. Its features became available one full hour after that source hour ended. The first implementation admitted hours based on whether the entire future day passed QC; that noncausal day-level selection was removed. After also correcting the candle-open alignment above, the baseline and augmented shallow gradient boosters used identical labeled rows and the same long/short realized-R targets, 14 bps configured round-trip cost, conservative per-symbol nonoverlap, and model settings. Training was 2023; calibration was 2024 H1 with labels ending inside the split. The final comparison had 16,678 training and 8,583 calibration rows, backed by 25,722 causal hourly feature rows.

| Calibration threshold | Baseline trades, mean R, positive months | Plus book depth trades, mean R, positive months |
|---:|---:|---:|
| 0.050 | 149, -0.3214 R, 2/6 | 165, -0.3106 R, 1/6 |
| 0.075 | 125, -0.3858 R, 1/6 | 140, -0.3087 R, 1/6 |
| 0.100 | 109, -0.2556 R, 1/6 | 119, -0.3606 R, 1/6 |
| 0.150 | 82, -0.2964 R, 1/6 | 76, -0.3803 R, 1/6 |

No threshold met the minimum 100 nonoverlapping trades, positive mean after costs and 4 bps stress, and four positive months simultaneously. All book-augmented thresholds had negative mean R and only one positive month. The book features did not rescue this fixed one-hour model; the result does not rule out other horizons or book representations. The script is `scripts/book_depth_inner_probe.py`, run with `uv run --with scikit-learn python -u scripts/book_depth_inner_probe.py`. Its report and cached hourly features are ignored under `outputs/`. This rule did not inspect 2024 H2, 2025, or 2026 outcomes. Funding cash flows and portfolio-level risk were not added because calibration already failed.

## Fifteen-minute book-depth feature pilot

A second BTC/ETH pilot used the same four book features inside each 15m candle, accepting only source snapshots at least one minute before the next-bar entry. A bar required at least 20 valid snapshots; the baseline and book models used identical labeled rows. The original 16-bar horizon and 14 bps round-trip cost were retained. Ambiguous barrier touches were charged as stops for the affected side rather than dropping the row based on a future event. Training was 2023 H1 and threshold selection was limited to 2023 H2. There were 67,952 book-feature bars, 32,618 training rows, and 35,265 calibration rows. The calibration gate required at least 176 nonoverlapping trades, a positive mean after base and 4 bps stressed costs, and at least four positive months out of six.

| Threshold | Baseline trades, mean R, positive months | Plus book trades, mean R, positive months |
|---:|---:|---:|
| 0.050 | 61, -0.4674 R, 1/6 | 61, -0.3890 R, 1/6 |
| 0.075 | 57, -0.4252 R, 1/6 | 55, -0.3408 R, 1/6 |
| 0.100 | 49, -0.4673 R, 1/6 | 53, -0.4260 R, 1/6 |
| 0.150 | 33, -0.4589 R, 3/6 | 30, -0.6050 R, 0/5 |

No threshold passed. The separate 2024 H1 window was not scored for this hypothesis. This pilot is reproducible with `uv run --with scikit-learn python -u scripts/book_depth_15m_probe.py`; its raw report is ignored under `outputs/book_depth_15m_probe_report.json`. A one-minute book buffer does not establish that an order could be filled at the next candle open after calculating candle-close features; live execution would need a latency and order-book simulation.

## Spot-perpetual funding-carry screen

A distinct, non-directional rule bought spot and sold the same-coin USD-M perpetual for BTC, ETH, BNB, SOL, and XRP when the previous 30 days of settled funding exceeded 0.5% and contained at least 80 observations. Positive funding pays the perpetual short under [Binance's funding convention](https://www.binance.com/en/support/faq/detail/360033525031). The screen used [Binance's public spot daily archives](https://github.com/binance/binance-public-data), existing local perpetual candles, and archived settled funding. Each monthly spot/perpetual pair paid 10/5 bps per-side fees respectively plus 2 bps slippage per side on each market, about 38 bps round trip, with a further 8 bps pair stress. Funding was multiplied by the contemporaneous perpetual price, and spot/perpetual basis changes were included. Returns were allocated equally across the five possible symbols, with cash in inactive slots.

| Period | Active legs | Positive months | Net on spot allocation | Stressed mean per month | Initial gate |
|---|---:|---:|---:|---:|---|
| 2023 H2 selection | 13 | 4/6 | +1.44% compounded | +0.205% | Pass |
| 2024 H1 | 25 | 5/6 | +5.25% compounded | +0.793% | Pass |
| 2024 H2 | 17 | 3/6, including two cash months | +1.93% compounded | +0.275% | Fail |

The original gate required at least four positive months in every six-month period, at least ten active legs, positive mean after base and stressed costs, and less than 15% month-end drawdown. After the 2024 H2 failure, an active-month consistency gate was explicitly added; this revision is exploratory. Under that revised gate, 2024 H2 passed with three positive months out of four active months. The next chronological period, 2025 H1, failed: only nine active legs in three months, +0.021% compounded before the extra cost, and a negative -0.0205% stressed mean per month. The 2025 H2 monthly-turnover outcome was not scored. Run `uv run python -u scripts/spot_perp_carry_probe.py` to reproduce the screen; its report and leg ledger are ignored under `outputs/`.

A second exploratory implementation retained each pair across monthly decisions while the signal remained active, paying fees only when actually entering or leaving. It reserved one unit of cash for the spot basket and one for perpetual margin, and did not reinvest gains. Thus its returns are on two units of initial capital, rather than on spot allocation alone. This accounting change was made after inspecting the first screen through 2025 H1. It produced +1.02% in 2023 H2, +5.70% in 2024 H1, +2.24% in 2024 H2, and +0.56% in 2025 H1 on the two-unit capital base. The 2025 H1 activity gate still failed: three active months and nine active symbol-months. A later 2025 H2 diagnostic, already a reused research period, was +0.24%. The annual results alone are not independent proof after the revision. Run `uv run python -u scripts/spot_perp_hold_probe.py` for the retained-position report.

A daily mark-to-market margin screen then showed why even those positive monthly figures are not executable evidence. With one unit of USDT reserved for the perpetual short account, held spot kept outside that account, and an assumed 5% maintenance requirement, the first modeled maintenance deficit appeared on 2024-11-23. The futures margin balance itself became negative on 2024-11-30; its minimum was -0.639 units and its minimum cushion versus assumed maintenance was -0.757 units. One XRP short run faced a 6.46-fold increase in the daily perpetual price relative to its entry. Using each day's highest 15m perpetual price for all open shorts simultaneously, the modeled margin would need at least 1.842 units just to avoid a maintenance breach. With an additional 10% simultaneous mark shock, that lower bound rises to 2.099 units, versus the one unit reserved by the return simulation. These are scenario calculations using an assumed maintenance percentage, not Binance's account-specific liquidation engine. The 10% shock is an extra scenario, not a claim that it happened. At the 2.099-unit futures margin lower bound plus one unit for spot, the fixed cash profit in February 2023-December 2025 would amount to about 6.60% on total initial capital, versus 10.24% on the unsafe two-unit account; the lower-bound scenario itself has no extra shock buffer. This is an arithmetic capital adjustment, not a new executable backtest. Extra collateral would dilute returns and still require intraday execution and margin safety proof. The historical positive monthly figures cannot establish robust executable profit. Run `uv run python -u scripts/spot_perp_margin_probe.py`; the daily ledger and report are ignored under `outputs/`.

## Daily funding-carry replay with separate wallets

An exploratory follow-up used a fixed daily rule rather than monthly turnover. It projected a 30-day funding amount from the previous seven days of settled rates, requiring at least 18 observations. A pair opened above 0.8% projected funding and stayed open until the projection fell below 0.4%. No future funding event entered a decision. The five-symbol portfolio allocated 0.20 units of spot capital per entry, started with 1.05 units in the spot wallet and 2.50 in the futures wallet, and charged the same spot/perpetual fees and slippage on actual entries and exits. The extra-cost scenario charged another 8 bps per completed pair. Open pairs were marked to a hypothetical liquidation value, including their future exit fees. A margin screen used the simultaneous highest 15m perpetual price of each day plus a further 10% mark shock, with an assumed 5% maintenance charge. This scenario is deliberately conservative but is not an exchange liquidation calculation. A spot entry was skipped when its wallet lacked cash; no automatic transfer from the futures wallet was assumed, consistent with the [separate-wallet transfer workflow](https://www.binance.com/en/support/faq/detail/360033773532).

| Period | Active months | Stressed return on 3.55 units initial capital | Skipped daily entry attempts |
|---|---:|---:|---:|
| 2023 February-June development | 5/5 | -0.152% | 0 |
| 2023 H2 selection | 5/6 | +0.491% | 102 |
| 2024 H1 | 6/6 | +1.769% | 135 |
| 2024 H2 | 5/6 | +0.813% | 36 |
| 2025 H1 | 3/6 | +0.304% | 0 |
| 2025 H2 diagnostic | 4/6 | -0.006% | 0 |

The minimum margin cushion under the stated shock was +1.515 units, and spot cash never went negative. Nevertheless, the full stressed return was only +3.220% from February 2023 through December 2025. The script's research gate failed because 2025 H2 was slightly negative and the full 2025 stressed return was far below the required 2% on initial capital. The 2025 H2 period has been examined by other hypotheses, so it is a diagnostic rather than a pristine holdout. Moving excess collateral between wallets might reduce skipped entries, but it would require a separately specified funding and margin rule; it was not silently assumed here. The separate quarterly-basis 2026 evaluation is reported below. Run `uv run python -u scripts/spot_perp_daily_carry_probe.py`; its report and daily ledger are ignored under `outputs/`.

### Twenty-symbol funding-only expansion screen

Before downloading the corresponding spot history for all 20 configured assets, a signal-only screen reused the archived settled funding records for January-June 2025. The screen requires complete coverage of 181 days and three settlements per symbol-day for each of the 20 symbols. It retained the fixed seven-day forecast, at least 18 past settlements, entry above 0.8% projected for 30 days, and exit below 0.4%. For a new-entry cohort starting empty on January 1, it assigned 0.05 normalized spot units per pair, 1.05 spot cash and 2.50 futures cash. There were 209 symbol-days above the entry threshold but only 30 actual entries after respecting held positions; all closed by June 30. No symbol-day exceeded 2% projected 30-day funding. The 30 pairs occupied 536 symbol-days, concentrated in January (384) and May (86).

At the original spot/future fee and slippage assumptions plus the extra 8 bps pair stress, a complete round trip costs about 46 bps of its initial spot notional. Funding receipts were approximated at that fixed notional. Even an optimistic convention that credits a settlement exactly on an entry's UTC boundary yields only +0.1444% of the 3.55-unit initial account against 0.1944% reserved round-trip cost, or **-0.0499% funding less cost**. Excluding such boundary settlements yields -0.0902%. Only two months have positive funding less cost under the optimistic convention, with February's amount negligible. The funding-only gate fails.

This is an input and carry-economics screen, not an account backtest or an upper bound on total pair profit: spot/perpetual basis changes, actual funding notional as price moves, pairs carried from 2024, margin, order-book depth and liquidation are absent. A favorable basis change could alter the result, but the projected funding component alone does not pay the modeled retail round trip in this H1 cohort. Reproduce with `uv run python -u scripts/expanded_carry_funding_screen.py`; its ignored report SHA256 is `b466bba31e645d73753bd9369467d84a319be50b1e8bed08066368bfe3757592`.

## BTC/ETH spot versus quarterly delivery futures

Another distinct cash-and-carry screen bought BTC and ETH spot at the first day of each quarter and sold the matching USD-M quarterly delivery futures, closing both legs at 00:00 UTC two days before the last Friday of that quarter. Binance describes these as [dated USD-M delivery contracts](https://www.binance.com/en/support/faq/detail/3ae441db4ae740e19af3fe9228eb6619), unlike the perpetuals used above. Each spot purchase was 0.5 normalized USDT units, and the matching short used the same base-asset quantity. The same 10 bps spot and 5 bps future fees plus 2 bps slippage per side were charged. The initial stress added another 8 bps per completed pair. One unit of spot capital plus a 0.05 spot cash buffer and two units of USDT futures margin gave 3.05 initial capital. Daily future highs plus 10% and an assumed 5% maintenance charge screened margin risk; both legs were closed before settlement, so no settlement-price assumption was needed.

The fixed all-quarter rule failed its initial 2023 selection gate, which required at least three profitable quarters and at least 2% annual stressed return on initial capital. The later years were inspected only as diagnostics after that failure. An account replay then preserved separate wallets through all twelve quarters, transferring USDT only after both legs closed to restore the two-unit futures reserve. Its results matched the leg calculations:

| Year | Positive quarters after initial stress | Stressed return on 3.05 initial capital | Minimum modeled margin cushion |
|---|---:|---:|---:|
| 2023 selection | 3/4 | +0.651% | +1.097 units |
| 2024 diagnostic | 4/4 | +4.853% | +0.969 units |
| 2025 diagnostic | 4/4 | +1.512% | +1.206 units |

The cumulative stressed cash profit was +7.016% of initial capital over three years, with a modeled daily liquidation-value drawdown of -0.806%. Spot proceeds were sufficient to restore the futures reserve after every quarter in this replay. This remains a backtest: no financing/opportunity cost for committed USDT, live liquidation engine, taxes, or venue-specific order rules were included. Reproduce the price screen with `uv run python -u scripts/quarterly_basis_probe.py`; add `--diagnostic-all` for 2024-2025. Then run `uv run python -u scripts/quarterly_basis_account_probe.py`. Reports and source ZIPs are ignored under `outputs/`.

Execution evidence is incomplete. The official daily `bookTicker` archive supplied only 14 of the 48 required future entry/exit days, covering both sides of six of 24 symbol-quarter trades and none of the required 2025 dates. Available first-minute quotes had median first spread 1.14 bps and 95th percentile 2.10 bps, but one first event arrived about five seconds after the intended time. At an illustrative 1,000 USDT account size, the first bid/ask quantity covered both sides for four of the six completely quoted trades; the smallest inferred top-book account capacity was about 139 USDT. Replacing the assumed 2 bps future slippage with those six observable bid/ask pairs improved their combined stressed cash result from 0.050874 to 0.052631 normalized units, but that subset cannot establish the missing years' execution. Run `uv run python -u scripts/quarterly_basis_execution_probe.py` for this SHA256-checked audit.

Because the quote series is incomplete, a separate screen downloaded 96 official spot and quarterly-future one-minute ZIPs. All 24 trades had a common traded minute at 00:00 UTC. It assumed the worst observed price inside that minute for every leg and then added a further 5 bps per spot side and 10 bps per future side beyond the initial 8 bps pair stress. On the same 3.05 initial capital, that produced +0.055% in 2023, +4.136% in 2024, and +0.971% in 2025. First-minute aggregate traded volume exceeded an illustrative 1,000 USDT account's base-asset quantity in 22 of 24 legs, but aggregate volume does not prove an order could fill at the modeled price. The very small 2023 and 2025 returns remain vulnerable to unmodeled execution and financing costs. Run `uv run python -u scripts/quarterly_basis_minute_probe.py`; its report and source ZIPs are ignored under `outputs/`.

The rule, stress assumptions, and acceptance criteria for a single 2026 historical evaluation were frozen in `docs/quarterly_basis_2026_protocol.md` at commit `5ad9f22`, before reading complete 2026 outcomes. The final evaluation is reported next; the protocol was not retuned.

## Frozen 2026 quarterly-basis evaluation

The fixed BTC/ETH spot-versus-quarterly-futures rule was applied to the three completed 2026 quarters. The evaluator verified SHA256 checksums and ZIP CRC for 144 official daily and one-minute spot/futures archives. September 2026 daily files completed the third quarter because its monthly archive was not yet available. All six symbol-quarter legs had the first common traded minute at exactly 00:00 UTC for entry and exit. The separate-wallet replay charged 19 bps per side on both markets in the final stress: original fees and 2 bps slippage, another 2 bps per side, then another 5 bps for spot or 10 bps for futures per side. The rule, costs and acceptance thresholds came from the earlier frozen protocol.

| Quarter | Profit after final stress, normalized USDT | Return on 3.05 initial capital |
|---|---:|---:|
| 2026 Q1 | +0.000469 | +0.015% |
| 2026 Q2 | -0.005482 | -0.180% |
| 2026 Q3 | -0.008367 | -0.274% |
| **Total** | **-0.013380** | **-0.439%** |

The aggregate return was already negative at the original fee/slippage level (-0.050% on initial capital), before either extra cost stress. The minimum spot-wallet cash was +0.0431 units. The minimum futures margin cushion under the daily-high plus 10% simultaneous mark shock and assumed 5% maintenance was +1.1113 units. The maximum estimated daily account drawdown was -0.554%. All six legs had aggregate first-minute traded volume exceeding the base-asset quantity for an illustrative 1,000 USDT account; this is neither order-book depth nor a fill guarantee.

The frozen quantitative gate **failed**: two of three quarters lost money and the total fell below the required +1.5%. The margin, spot funding, daily drawdown and common-minute conditions passed. At the April entry, BTC and ETH future premia were only about 26 and 23 bps; by exit the gross basis convergence could not pay the modeled round trip. The September ETH future premium was slightly higher at exit than at entry. No threshold or symbol was changed after seeing this result. This historical candidate does not satisfy the requested robust profit after costs. The replay still omits live executable depth, account-specific liquidation and lot-size rules, financing opportunity cost, and taxes. Reproduce it with `uv run python -u scripts/quarterly_basis_final_2026.py`; the report, source-hash manifest, leg ledger and daily ledger are ignored under `outputs/`.

The local report SHA256 is `98c45a5b591eec14701a95edd7679f66c14c08b8e3f64ab1ee3f7cf377b8ed7e`; the 144-archive source manifest SHA256 is `b958ac339a37073d6ed5c5292b9b08a136d28f1fd21fc0d6cb58cf943cace885`.

## Delayed December 2026 delivery-basis screen

A read-only screen checked the BTCUSDT and ETHUSDT December 25 delivery contracts using the first common positive-volume minute within five minutes of 00:00 UTC in the [official Binance public one-minute archives](https://data.binance.vision/). All four spot/future archives for each observed day passed their published SHA256 checksum and ZIP CRC. Spot entry was valued at that minute's high and the future short at its low; these are historical traded ranges, not executable bid/ask quotes. The 2026-09-24 archive is delayed relative to this 2026-09-26 review. A later correction excluded zero-volume candle rows; on September 23, BTC's first eligible minute was 00:04 UTC.

| Archived entry day | BTC adverse entry premium | ETH adverse entry premium | Hypothetical account return if exit prices equal entry spot and basis converges | If exit spot doubles and basis converges |
| --- | ---: | ---: | ---: | ---: |
| 2026-09-23 | 132.34 bps | 94.59 bps | +0.1221% | -0.0025% |
| 2026-09-24 | 120.73 bps | 93.37 bps | +0.1011% | -0.0235% |

The scenarios charge the frozen final stress of 19 bps per side in each market, reserve 3.05 normalized USDT units for two 0.5-unit spot allocations and separate futures cash, and assume future and spot prices become identical at exit. Fees on both exits grow with the exit price; the apparent premium at entry therefore leaves a small, price-sensitive account return. Convergence at the assumed exit instant is unproven, and neither minute volume nor a candle range establishes executable depth. The calculation omits a margin path, liquidation engine, financing, taxes and account-specific eligibility. It does not satisfy robust profit after costs or warrant an order. The direct futures quote API was unavailable from this environment, so no current bid/ask claim was made.

Reproduce with `uv run python -u scripts/delivery_basis_archived_screen.py --day 2026-09-24 --expiry 2026-12-25` (or `--day 2026-09-23`). The corrected ignored report SHA256 values are `59c8b3c841e9050b0f92dec99d77850f99b2b76f9f558786118a235b00647f93` and `dfd296ef44974d2b099209558708292931a7187da3bbeb91832d67790552df1a`, respectively. The report contains the four archive hashes for each day.

## Six-month BTC/ETH delivery-basis replay

The entry-only screen found larger premia on January/July starts, especially in 2024. After those entry premia had been viewed, the full exit, wallet and risk rules were frozen in `docs/six_month_basis_protocol.md` at commit `4e6e6ce`, with its replay implementation at `1f5e7d0` before exit prices were read. This is an exploratory, non-pristine historical evaluation. The fixed rule paired BTC and ETH spot with the June or December delivery future for nearly six months, exiting two days before expiry. It bought spot at the entry minute's high, shorted the future at its low, reversed at the adverse exit-minute prices, and charged 19 bps per side on both markets. Separate wallets began at 1.05 spot cash and 3.00 futures cash, 4.05 total. All 160 daily and minute archives passed Binance's SHA256 checksums and ZIP CRC.

| Completed period | Return after stressed execution costs on 4.05 initial capital | Minimum modeled futures margin cushion |
| --- | ---: | ---: |
| 2024 H1 | +1.713% | +1.887 units |
| 2024 H2 | +1.094% | +2.365 units |
| 2025 H1 | +1.321% | +2.703 units |
| 2025 H2 | +0.437% | +2.180 units |
| 2026 H1 | +0.270% | +2.682 units |

All ten symbol legs and all five half-years were positive. The full-period stressed cash profit was +4.835% of initial capital, with +2.807% in 2024 and +1.758% in 2025. The lowest modeled futures margin cushion under a simultaneous daily-high plus 10% mark shock and assumed 5% maintenance was +1.887 units; minimum spot cash was +0.0481 and maximum modeled daily liquidation-value drawdown was -2.462%. The prespecified **historical research gate passed**. The latest completed half-year returned only +0.270%, less than each earlier half-year. In a post-result diagnostic, another 30 bps per side on both markets reduces the total return to +3.284%; it leaves only about +0.026% in 2026 H1. Financing opportunity cost and taxes are still excluded.

The zero-volume correction shifted BTC's January 2025 entry from 00:00 to the first positive-volume minute at 00:01. At an illustrative 1,000 USDT account size, aggregate first-minute volume covered the required base quantity for 9 of 10 legs. The exception was BTC in 2026 H1: 0.001 BTC of first-minute future volume versus 0.001409 BTC of hypothetical order quantity. Even the other nine volumes cannot establish bid/ask depth or a fill at the modeled minute extremes. The July 2026 position remains incomplete; no profit was assigned to it. Live depth, actual account fees and eligibility, lot sizes, liquidation rules and financing are unverified, so this passed research gate is **not** proof of robust executable profit and does not authorize live orders.

A read-only 2026-09-26 check of the official historical futures `bookTicker` archive found only 2 of the 20 entry/exit contract-days required by these ten legs, both at the 2024 H1 entry. Zero legs have both entry and exit book archives. Reproduce the availability check with `uv run python -u scripts/six_month_bookticker_coverage.py`; its time-stamped ignored report is `outputs/six_month_bookticker_coverage.json`. The two available days cannot repair the missing execution evidence for the complete replay.

Reproduce the original six-month replay with `uv run python -u scripts/six_month_basis_replay.py`. The ignored report SHA256 is `c05ace60228b3bbbc5ccc64f51da16a714d6224e06276efba7ed58826b0e3595`; its 160-archive source manifest SHA256 is `9605a94241d8b8b061d6c52d55e4f8a2d305d9ea10a2ce42c55dbc49edde256d`.

### Five-minute trade-volume diagnostics

The post-result aggregate-volume protocol was frozen at `cd094c3`, and its implementation at `4a1e0f0`. For an illustrative 1,000 USDT account, all 10 legs accumulated at least their required base quantity on both markets within the 00:00-00:04 UTC window. The longest entry or exit delay was one minute. Repricing each leg with the adverse traded highs/lows through the common completion minute reduced the full-period return from +4.835% to +4.830% of initial capital. The 2026 H1 return became +0.265%. Its report is `outputs/six_month_volume_window_report.json` (SHA256 `bc79f885187031a630b426b68f5f41af937096609f9802f110df08793d44c2f3`); the source manifest remains `9605a94241d8b8b061d6c52d55e4f8a2d305d9ea10a2ce42c55dbc49edde256d`. Reproduce with `uv run python -u scripts/six_month_volume_window_probe.py`.

The next post-result protocol, frozen at `67e24da`, narrows the activity check to historical trades in each order's direction: spot taker buys and future taker sells at entry, then spot taker sells and future taker buys at exit. All 10 legs reached the illustrative quantity in each of these four flows within at most one minute. Two legs required one minute beyond their comparable aggregate-volume completion time: BTC's 2024 H1 entry and 2025 H2 exit. Their adverse repricing lowered the full-period return to +4.816%, with all five half-years still positive and the latest 2026 H1 at +0.265%. The minimum modeled futures margin cushion was +1.887 normalized units; the maximum modeled daily liquidation-value drawdown was -2.462%. The directional diagnostic report is `outputs/six_month_directional_volume_report.json` (SHA256 `72b956bfb88a5c70a6bd782d98edd054db5f02ab328221d5891fe68019c5b287`). Reproduce with `uv run python -u scripts/six_month_directional_volume_probe.py`.

These are sensitivity checks on inspected historical periods. The kline volume and taker-buy fields describe completed trades, not bid/ask depth, attainable size or queue position. Waiting for one hedge side can also create unhedged exposure. The 2/20 futures `bookTicker` coverage, account-specific fee/eligibility and the incomplete 2026 H2 outcome remain unresolved; the passed historical research gate is not a robust executable-profit result.

### Earlier-regime availability and capital-cost hurdle

An extension covering all four 2022-2023 half-years was frozen before the archive lookup at `4ad12aa`. The same Binance archive path returned `missing` for all eight future entry-day minute tasks (BTC and ETH in each half-year), along with 14 required future monthly daily archives. Consequently no leg and no account return can be calculated under the frozen six-month entry rule. The script records all 22 missing tasks among 128 checked archives in `outputs/six_month_2022_2023_extension_report.json` (SHA256 `1ba8f76722dc5770114e3f8a214fa557615be33d9262284005adba436c5b3ba0`; source manifest SHA256 `60811ed5e52ae3d3f3738b82ee679db7c59f10b47a3f31f7d96f4c20496d333b`). Reproduce with `uv run python -u scripts/six_month_2022_2023_extension.py`. Archive absence is not evidence that the contracts themselves never traded. The fixed rule cannot gain independent earlier-regime support from these archives, and changing dates or contracts would define another strategy.

The directional-volume replay's simple annualized break-even charge on the full 4.05 account was 3.518% in 2024 H1, 2.256% in 2024 H2, 2.755% in 2025 H1, 0.892% in 2025 H2 and 0.555% in 2026 H1. These are mathematical profit divided by capital and holding time, not market funding-rate observations. An illustrative 1% annual capital charge would make the last two completed half-years negative (-0.052% and -0.212% on initial capital, respectively). The latest historical profits are therefore thin even before actual financing, tax and execution uncertainty.

### July 2026 shadow entry

The 2026 H2 interim protocol was frozen at `4dd1362` before fetching the July 1 entry and daily risk path. All 108 required spot/future minute and daily archives passed their published SHA256 and ZIP CRC checks. BTC reached the direction-specific 1,000 USDT illustrative quantity by 00:01 UTC. ETH did not: its December-delivery future recorded 0.068 ETH of taker-sell volume through 00:04 versus a required 0.07844 ETH. Even using the highest spot price anywhere in that five-minute window would still require 0.07839 ETH. Total future volume was 0.285 ETH, illustrating why aggregate volume alone would miss this shortfall. The fixed two-leg proxy therefore marks the July entry unavailable and assigns no interim account risk or return. Historical same-direction volume is not a hard limit on what another order could have filled, and this does not prove execution was impossible at a different size or time.

The ignored report is `outputs/six_month_2026_h2_interim_report.json` (SHA256 `110a121393323b0643dca757161f004e031439622a5602f143fd56f811f5c68a`); its 108-archive manifest SHA256 is `692cc3d90a12a8d8458126a5ea52450413ca56eca53283e7cf641703c5c22807`. Reproduce with `uv run python -u scripts/six_month_2026_h2_interim.py`. The failure is at the prespecified illustrative size and directional-activity proxy, not a live order or a measured bid/ask fill.

### Independent OKX 2022-2023 price screen

The independent-venue protocol was frozen at `3b79c01` before OKX spot and dated-future prices were read. All 32 first-party daily trade ZIPs passed local SHA256 and ZIP CRC checks. The fixed January/July entries, exits two days before delivery, adverse five-minute traded-price extrema and 19 bps per side on both markets gave the following continuous-quantity cash results on the same 4.05 normalized capital:

| OKX period | Cash return after modeled execution costs |
| --- | ---: |
| 2022 H1 | +0.795% |
| 2022 H2 | -0.463% |
| 2023 H1 | -0.332% |
| 2023 H2 | +0.229% |

The four periods summed to only +0.228% before financing and taxes; both BTC and ETH legs were negative in 2022 H2 and 2023 H1. Thus the unchanged always-enter rule does not carry a robust positive price signal into this independent venue and earlier regime. This is a price-only screen: OKX contract rounding, direction-specific volume, bid/ask depth and margin path have not passed, so even its positive periods are not executable-profit evidence. The ignored report is `outputs/okx_six_month_2022_2023_price_screen.json` (SHA256 `fb44d6a1aac7827c6cf48df9e7becea791609019e8f4090736382ddde5803ac2`); the 32-archive manifest SHA256 is `f269e36744aaf7ec3135ca52e441fb6c87c533f869ebef825e2c3af09183b6aa`. Reproduce with `uv run python -u scripts/okx_six_month_2022_2023_price_screen.py`.

### Bybit July 2026 exact-window availability

A post-observation audit read the complete first-party Bybit trade gzip files for the December 25, 2026 BTC and ETH USDT futures on July 1. Neither contract recorded any trade from 00:00 through 00:04:59 UTC. The first ETH trade was 00:08:00.486 UTC and the first BTC trade 00:10:31.4744 UTC. This makes the fixed five-minute entry window unavailable on Bybit for both legs; moving entry later would be a changed rule. The compressed files passed full gzip reads and have local SHA256 checksums in `outputs/bybit_2026_h2_entry_window_audit.json` (report SHA256 `ff6cea87efaa7b1c89ef50ccde4832e035c514dbefcf25478daf753411d2b555`). Reproduce with `uv run python -u scripts/bybit_2026_h2_entry_window_audit.py`. This is trade-window evidence only, not a comparison of executable fills across venues.

## Next research gate

The existing 15m Laya checkpoint, 1h/4h price-flow baselines, lagged funding, premium-index and positioning-metrics probes, both fixed book-depth pilots, wider-barrier and daily-horizon label probes, weekly and daily cross-sectional carry rules, and both short- and slow-horizon spot trend rules fail their calibration or out-of-sample execution gate. The separate spot-perpetual hedge screen showed positive historical monthly returns, but its initial consistency gate failed in 2024 H2 and the retained-position version breached modeled futures margin in November 2024. A daily, better-collateralized carry replay stayed above its modeled margin requirement yet failed its cost-stressed 2025 gate. The original three-month quarterly BTC/ETH basis rule failed the frozen 2026 evaluation after costs. The distinct six-month delivery-basis rule passes its exploratory Binance historical gate, but the independent OKX price screen has two negative half-years, Binance's July 2026 ETH entry fails the fixed 1,000 USDT direction-specific activity proxy, and Bybit has no trade in the exact July entry window for either contract. The small latest completed Binance return also lacks live executable depth. The next evidence is account-specific fees and eligibility, executable quotes at a stated order size, and a genuinely uninspected outcome under a frozen rule. Do not retune these inspected periods. A positive historical average by itself is insufficient.

Earlier exploratory scripts and generated data are retained locally under `outputs/`, which is ignored by Git. The premium-index, funding, wider-barrier, carry, positioning-metrics, daily-horizon, daily cross-sectional, momentum, and book-depth scripts are tracked under `scripts/`. The Colab A100 runtime was disconnected after confirming the checkpoint and reports were in Drive.
