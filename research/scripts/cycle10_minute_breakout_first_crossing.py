from __future__ import annotations

import gc
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits


ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "research"
sys.path.insert(0, str(RESEARCH / "scripts"))
import cycle02_multiframe_research as engine  # noqa: E402
import cycle03_direct_net_ev as direct_ev  # noqa: E402
import cycle04_rolling_refit as rolling  # noqa: E402


MARKET = "usd_m"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
BACKEND = "xgboost_cuda"
FAMILY = "breakout_continuation"
EXIT_MODE = "trend_loss"
MAX_HOLD_MINUTES = 1440
BREAKOUT_LOOKBACK_MINUTES = 300
SIGNAL_COOLDOWN_MINUTES = 1
OUTPUT = RESEARCH / "results/cycle10_minute_breakout_first_crossing_2026-09-28"
PROTOCOL = RESEARCH / "docs/CICLO10_MINUTE_BREAKOUT_FIRST_CROSSING_PROTOCOLO.md"
SOURCE_REPORT = RESEARCH / "results/cycle02_multiframe_corrected_2026-09-28/research.json"
PARENT_REPORT = RESEARCH / "results/cycle09_minute_breakout_first_crossing_2026-09-28/research.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def add_minute_breakout_levels(features: pd.DataFrame, bars_1m: pd.DataFrame) -> pd.DataFrame:
    """Attach causal 300-minute high/low and volume baselines, excluding this bar."""
    result = features.copy()
    result["don_high20"] = bars_1m.high.shift().rolling(
        BREAKOUT_LOOKBACK_MINUTES, min_periods=BREAKOUT_LOOKBACK_MINUTES
    ).max().to_numpy(dtype=float)
    result["don_low20"] = bars_1m.low.shift().rolling(
        BREAKOUT_LOOKBACK_MINUTES, min_periods=BREAKOUT_LOOKBACK_MINUTES
    ).min().to_numpy(dtype=float)
    result["volume_median20"] = bars_1m.volume.shift().rolling(
        BREAKOUT_LOOKBACK_MINUTES, min_periods=BREAKOUT_LOOKBACK_MINUTES
    ).median().to_numpy(dtype=float)
    return result


def apply_stop_atr_15m(features: pd.DataFrame, atr_15m: pd.Series) -> pd.DataFrame:
    """Use the last completed 15m ATR for stop sizing at every 1m signal close."""
    result = features.copy()
    aligned = atr_15m.reindex(result.index, method="ffill")
    result["atr"] = aligned.to_numpy(dtype=float)
    return result


def label_uniqueness_weights(labels: pd.DataFrame) -> tuple[pd.Series, dict[str, float]]:
    """Weight each mature label by mean inverse concurrency for its symbol and side."""
    if labels.empty:
        raise ValueError("Cannot calculate uniqueness weights for an empty training frame")
    minute_ns = 60_000_000_000
    starts_ns = pd.to_datetime(labels["signal_time"], utc=True).astype("int64").to_numpy()
    ends_ns = pd.to_datetime(labels["label_end_time"], utc=True).astype("int64").to_numpy()
    durations_ns = ends_ns - starts_ns
    if (durations_ns <= 0).any() or (durations_ns % minute_ns != 0).any():
        raise ValueError("Training label intervals must be positive whole minutes")
    raw = np.empty(len(labels), dtype=float)
    for positions in labels.groupby(["symbol", "side"], sort=False).indices.values():
        group_starts = starts_ns[positions]
        group_ends = ends_ns[positions]
        origin = int(group_starts.min())
        start_idx = ((group_starts - origin) // minute_ns).astype(np.int64)
        end_idx = ((group_ends - origin) // minute_ns).astype(np.int64)
        if (end_idx <= start_idx).any():
            raise ValueError("Training label interval collapsed to zero minutes")
        delta = np.zeros(int(end_idx.max()) + 1, dtype=np.int64)
        np.add.at(delta, start_idx, 1)
        np.add.at(delta, end_idx, -1)
        concurrency = np.cumsum(delta[:-1])
        inverse = np.zeros(len(concurrency), dtype=float)
        occupied = concurrency > 0
        inverse[occupied] = 1.0 / concurrency[occupied]
        prefix = np.concatenate(([0.0], np.cumsum(inverse)))
        raw[positions] = (prefix[end_idx] - prefix[start_idx]) / (end_idx - start_idx)
    if not np.isfinite(raw).all() or (raw <= 0).any():
        raise ValueError("Uniqueness weights must be finite and positive")
    weights = raw / raw.mean()
    effective_n = float(weights.sum() ** 2 / np.square(weights).sum())
    series = pd.Series(weights, index=labels.index, name="sample_weight")
    diagnostics = {
        "rows": int(len(weights)),
        "mean": float(weights.mean()),
        "median": float(np.median(weights)),
        "minimum": float(weights.min()),
        "maximum": float(weights.max()),
        "effective_sample_size": effective_n,
        "effective_sample_fraction": float(effective_n / len(weights)),
    }
    return series, diagnostics


def fit_uniqueness_weighted_regressor(
    train: pd.DataFrame,
) -> tuple[Any, float, dict[str, float]]:
    if train.empty:
        raise ValueError("No training labels after chronological purge")
    y = pd.to_numeric(train[direct_ev.TARGET], errors="coerce")
    valid = np.isfinite(y.to_numpy(dtype=float))
    train = train.loc[valid].copy()
    y = y.loc[valid].astype(float)
    weights, diagnostics = label_uniqueness_weights(train)
    x = train[list(engine.FEATURES)].astype(float).replace([np.inf, -np.inf], np.nan)
    model = direct_ev.create_regressor(BACKEND)
    with threadpool_limits(limits=4):
        model.fit(x, y, sample_weight=weights.to_numpy(dtype=float))
    diagnostics["weighted_target_mean"] = float(np.average(y.to_numpy(dtype=float), weights=weights))
    return model, float(y.mean()), diagnostics


def minute_market_features(bars: pd.DataFrame) -> tuple[pd.DataFrame, dict[pd.Timestamp, float]]:
    """Build 1m entry features, complete 1h/4h context and unchanged 15m exit EMA."""
    bars_1m = engine.aggregate_minutes(bars, 1)
    bars_15m = engine.aggregate_minutes(bars, 15)
    bars_60m = engine.aggregate_minutes(bars, 60)
    bars_240m = engine.aggregate_minutes(bars, 240)

    features = engine.indicators(bars_1m)
    contexts = {60: engine.indicators(bars_60m), 240: engine.indicators(bars_240m)}
    for timeframe, label in ((60, "1h"), (240, "4h")):
        context = contexts[timeframe].reindex(features.index, method="ffill")
        for name in engine.HIGHER_FEATURES:
            features[f"{label}_{name}"] = context[name].to_numpy(dtype=float)

    for column in ("open", "high", "low", "close", "volume"):
        features[column] = bars_1m[column].to_numpy(dtype=float)
    features = add_minute_breakout_levels(features, bars_1m)

    contexts_60 = contexts[60].reindex(features.index, method="ffill")
    contexts_240 = contexts[240].reindex(features.index, method="ffill")
    close_60 = bars_60m.close.reindex(features.index, method="ffill")
    close_240 = bars_240m.close.reindex(features.index, method="ffill")
    ema60_prior = contexts[60].ema200.shift(5).reindex(features.index, method="ffill")
    ema240_prior = contexts[240].ema200.shift(5).reindex(features.index, method="ffill")
    features["context_long"] = (
        (close_60 > contexts_60.ema200) & (contexts_60.ema200 > ema60_prior)
        & (close_240 > contexts_240.ema200) & (contexts_240.ema200 > ema240_prior)
    ).to_numpy(dtype=bool)
    features["context_short"] = (
        (close_60 < contexts_60.ema200) & (contexts_60.ema200 < ema60_prior)
        & (close_240 < contexts_240.ema200) & (contexts_240.ema200 < ema240_prior)
    ).to_numpy(dtype=bool)
    features["prior_close"] = bars_1m.close.shift().to_numpy(dtype=float)
    features["prior_don_high20"] = features.don_high20.shift().to_numpy(dtype=float)
    features["prior_don_low20"] = features.don_low20.shift().to_numpy(dtype=float)
    features["prior_ema21"] = features.ema21.shift().to_numpy(dtype=float)

    exit_features = engine.indicators(bars_15m)
    features = apply_stop_atr_15m(features, exit_features.atr)
    exit_ema = {
        pd.Timestamp(timestamp): float(value)
        for timestamp, value in exit_features.ema21.items()
        if np.isfinite(value)
    }
    return features, exit_ema


def generate_minute_breakout_candidates(
    features: pd.DataFrame,
    symbol: str,
    market: str,
    minute_times: pd.DatetimeIndex,
    *,
    cooldown_minutes: int = SIGNAL_COOLDOWN_MINUTES,
) -> pd.DataFrame:
    """Score a causal breakout state after every 1m close; preserve a 15m cooldown."""
    records: list[dict[str, Any]] = []
    sides = (1, -1) if market == "usd_m" else (1,)
    signal_times = pd.DatetimeIndex(features.index)
    cooldown_ns = int(cooldown_minutes) * 60_000_000_000
    for side in sides:
        context = features.context_long if side == 1 else features.context_short
        breakout = (
            (features.prior_close <= features.prior_don_high20)
            & (features.close > features.don_high20)
            if side == 1 else
            (features.prior_close >= features.prior_don_low20)
            & (features.close < features.don_low20)
        )
        volume_confirmed = features.volume >= 1.3 * features.volume_median20
        valid = (
            context & breakout & volume_confirmed
            & features.atr.notna() & features.ema21.notna() & features.atr_pct.notna()
        )
        indices = np.flatnonzero(valid.fillna(False).to_numpy(dtype=bool))
        last_signal: pd.Timestamp | None = None
        for index in indices:
            signal_time = pd.Timestamp(signal_times[index])
            if (last_signal is not None
                    and signal_time.value - last_signal.value < cooldown_ns):
                continue
            next_minute = int(minute_times.searchsorted(signal_time, side="left"))
            if (next_minute <= 0 or next_minute >= len(minute_times)
                    or minute_times[next_minute] != signal_time):
                continue
            values = features.iloc[index]
            if not np.isfinite(float(values.atr)) or float(values.atr) <= 0:
                continue
            row = {
                name: float(values[name]) if pd.notna(values[name]) else np.nan
                for name in engine.FEATURES[:-1]
            }
            row.update({
                "candidate_id": f"{symbol}|{FAMILY}|{side}|{signal_time.isoformat()}",
                "symbol": symbol,
                "market": market,
                "family": FAMILY,
                "side": side,
                "regime": side,
                "signal_time": signal_time,
                "signal_index": next_minute - 1,
                "atr": float(values.atr),
                "stop_atr": 1.0,
                "target_r": 1.5,
                "ema21": float(values.ema21),
                "stop_fraction_signal": float(values.atr / values.close),
            })
            row["side"] = side
            records.append(row)
            last_signal = signal_time
    return pd.DataFrame(records)


def _verify_dataset(source_report: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    data = {row["market"]: row for row in source_report["data"]}
    expected = data[MARKET]
    folder = ROOT / expected["dataset_path"]
    candles = folder / "candles.csv.gz"
    manifest = folder / "dataset.json"
    if digest(candles) != expected["dataset_sha256"]:
        raise AssertionError("USD-M candle archive hash differs from the source report")
    if digest(manifest) != expected["manifest_sha256"]:
        raise AssertionError("USD-M dataset manifest hash differs from the source report")
    return expected, {
        "dataset_path": str(folder.relative_to(ROOT)).replace("\\", "/"),
        "dataset_sha256": digest(candles),
        "manifest_sha256": digest(manifest),
        "rows": expected["rows"],
        "symbols": expected["symbols"],
    }


def run() -> dict[str, Any]:
    if OUTPUT.exists():
        raise FileExistsError(f"Output already exists; refusing overwrite: {OUTPUT}")
    source_report = json.loads(SOURCE_REPORT.read_text(encoding="utf-8"))
    _, dataset_hash = _verify_dataset(source_report)
    parent_report = json.loads(PARENT_REPORT.read_text(encoding="utf-8"))
    if parent_report["status"] != "retrospective_walk_forward_exploration":
        raise AssertionError("Unexpected Cycle 09 result status")

    OUTPUT.mkdir(parents=True, exist_ok=False)
    started_all = time.perf_counter()
    market_source = RESEARCH / "data" / "usdm_btc_eth_1m"
    candles, provenance = engine.load_dataset(market_source, MARKET)
    if provenance["data_sha256"] != dataset_hash["dataset_sha256"]:
        raise AssertionError("Loaded USD-M data hash differs from the audited archive")
    candles = candles.loc[candles.open_time < engine.DATA_END].copy()

    arrays: dict[str, Any] = {}
    ema_by_symbol: dict[str, dict[pd.Timestamp, float]] = {}
    candidate_parts: list[pd.DataFrame] = []
    for symbol, grouped in candles.groupby("symbol", sort=True):
        if symbol not in SYMBOLS:
            raise AssertionError(f"Unexpected symbol in USD-M dataset: {symbol}")
        bars = grouped.reset_index(drop=True)
        arrays[symbol] = engine.MarketArrays(bars)
        features, exit_ema = minute_market_features(bars)
        candidates = generate_minute_breakout_candidates(
            features, symbol, MARKET, pd.DatetimeIndex(bars.open_time)
        )
        if not candidates.empty:
            candidate_parts.append(candidates)
        ema_by_symbol[symbol] = exit_ema
        print(json.dumps({"symbol": symbol, "one_minute_bars": len(bars),
                          "candidates": len(candidates)}), flush=True)
        del bars, features, candidates
        gc.collect()
    del candles
    gc.collect()

    candidates = pd.concat(candidate_parts, ignore_index=True) if candidate_parts else pd.DataFrame()
    if candidates.empty:
        raise ValueError("The minute breakout scanner produced no candidates")
    candidates = candidates.loc[candidates.symbol.isin(SYMBOLS)].copy()
    candidates = candidates.sort_values(["signal_time", "symbol", "side"]).reset_index(drop=True)
    duplicate_ids = int(candidates.candidate_id.duplicated().sum())
    if duplicate_ids:
        raise AssertionError(f"Duplicate minute candidate IDs: {duplicate_ids}")
    candidates.to_csv(OUTPUT / "candidates.csv", index=False, encoding="utf-8", lineterminator="\n")

    config = {MARKET: engine.gate_config(MARKET)}
    labels = engine.apply_labels(
        candidates, arrays, config, EXIT_MODE, MAX_HOLD_MINUTES, ema_by_symbol
    )
    if labels.empty:
        raise ValueError("No complete labels were generated for minute candidates")
    labels.to_csv(OUTPUT / "candidate_labels.csv", index=False,
                  encoding="utf-8", lineterminator="\n")

    selection_start = engine.CALIBRATION_END + pd.Timedelta(minutes=engine.EMBARGO_MINUTES)
    selection_end = engine.SELECTION_END
    selection_pool = labels.loc[
        (labels.signal_time >= selection_start)
        & (labels.signal_time < selection_end - pd.Timedelta(minutes=MAX_HOLD_MINUTES))
    ].copy()
    folds = rolling.month_folds(
        selection_start, selection_end - pd.Timedelta(minutes=MAX_HOLD_MINUTES)
    )
    if selection_pool.empty or not folds:
        raise ValueError("Empty one-minute selection window")

    base_rows = selection_pool.drop(columns=list(direct_ev.LABEL_ONLY_COLUMNS), errors="ignore").copy()
    base_rows["probability"] = 1.0
    base_rows["expected_r"] = 1.0
    outcome_cache: dict[tuple[str, bool], Any] = {}
    rule_base, _ = engine.evaluate_portfolio(
        base_rows, arrays, config, EXIT_MODE, MAX_HOLD_MINUTES, ema_by_symbol,
        selection_start, selection_end, stress=False, outcome_cache=outcome_cache,
    )
    rule_stress, _ = engine.evaluate_portfolio(
        base_rows, arrays, config, EXIT_MODE, MAX_HOLD_MINUTES, ema_by_symbol,
        selection_start, selection_end, stress=True, outcome_cache=outcome_cache,
    )

    models_dir = OUTPUT / "models"
    models_dir.mkdir(parents=True, exist_ok=False)
    fold_rows: list[dict[str, Any]] = []
    score_parts: list[pd.DataFrame] = []
    for fold_start, fold_end in folds:
        as_of = fold_start.normalize().replace(day=1)
        train = rolling.matured_training_labels(labels, as_of)
        test = rolling.month_candidates(selection_pool, fold_start, fold_end)
        if train.empty or test.empty:
            raise ValueError(
                f"Empty one-minute fold {fold_start:%Y-%m}: train={len(train)}, test={len(test)}"
            )
        if (train.label_end_time >= as_of).any() or (train.signal_time >= as_of - rolling.EMBARGO).any():
            raise AssertionError("Lookahead in monthly minute-breakout training partition")

        fit_started = time.perf_counter()
        model, train_mean, weight_diagnostics = fit_uniqueness_weighted_regressor(train)
        fit_seconds = time.perf_counter() - fit_started
        config_text = model.get_booster().save_config()
        compact = config_text.replace(" ", "")
        if '"device":"cuda:0"' not in compact or '"tree_method":"hist"' not in compact:
            raise AssertionError("A monthly minute-breakout model did not train with CUDA hist")

        features = test.drop(columns=list(direct_ev.LABEL_ONLY_COLUMNS), errors="ignore").copy()
        x_test = features[list(engine.FEATURES)].astype(float).replace([np.inf, -np.inf], np.nan)
        predictions = np.asarray(model.predict(x_test), dtype=float)
        if not np.isfinite(predictions).all():
            raise AssertionError(f"Non-finite minute-breakout scores in {fold_start:%Y-%m}")
        features["predicted_net_return"] = predictions
        features["passed_fixed_cutoff"] = direct_ev.select_by_predicted_ev(
            features["predicted_net_return"]
        )
        features["probability"] = features["predicted_net_return"]
        features["expected_r"] = features["predicted_net_return"]
        selected = features.loc[features.passed_fixed_cutoff].copy()

        diagnostic = test[["candidate_id", "signal_time", "symbol", "net_return"]].copy()
        diagnostic["predicted_net_return"] = predictions
        diagnostic["passed_fixed_cutoff"] = features["passed_fixed_cutoff"].to_numpy()
        score_parts.append(diagnostic)

        model_path = models_dir / f"{fold_start:%Y-%m}.json"
        model.save_model(model_path)
        fold_rows.append({
            "fold_start": fold_start.isoformat(),
            "fold_end_exclusive": fold_end.isoformat(),
            "training_as_of": as_of.isoformat(),
            "training_rows": int(len(train)),
            "training_target_mean": train_mean,
            "sample_weight_diagnostics": weight_diagnostics,
            "candidate_rows": int(len(test)),
            "selected_candidates": int(len(selected)),
            "training_seconds": fit_seconds,
            "device": "cuda:0",
            "tree_method": "hist",
            "model_path": str(model_path.relative_to(ROOT)).replace("\\", "/"),
            "model_sha256": digest(model_path),
        })
        print(json.dumps({"fold": f"{fold_start:%Y-%m}", "train_rows": len(train),
                          "candidates": len(test), "selected": len(selected),
                          "seconds": round(fit_seconds, 2)}), flush=True)
        del model, train, test, features, x_test, predictions, selected, diagnostic
        gc.collect()

    all_scores = pd.concat(score_parts, ignore_index=True)
    if all_scores.candidate_id.duplicated().any():
        raise AssertionError("A minute candidate was scored more than once")
    selected_ids = set(all_scores.loc[all_scores.passed_fixed_cutoff, "candidate_id"])
    selection_features = selection_pool.drop(
        columns=list(direct_ev.LABEL_ONLY_COLUMNS), errors="ignore"
    ).copy()
    selection_features = selection_features.loc[
        selection_features.candidate_id.isin(selected_ids)
    ].copy()
    predicted_by_id = all_scores.set_index("candidate_id").predicted_net_return
    selection_features["predicted_net_return"] = selection_features.candidate_id.map(predicted_by_id)
    selection_features["probability"] = selection_features["predicted_net_return"]
    selection_features["expected_r"] = selection_features["predicted_net_return"]

    base, base_trades = engine.evaluate_portfolio(
        selection_features, arrays, config, EXIT_MODE, MAX_HOLD_MINUTES, ema_by_symbol,
        selection_start, selection_end, stress=False, outcome_cache=outcome_cache,
    )
    stress, stress_trades = engine.evaluate_portfolio(
        selection_features, arrays, config, EXIT_MODE, MAX_HOLD_MINUTES, ema_by_symbol,
        selection_start, selection_end, stress=True, outcome_cache=outcome_cache,
    )
    passed, failures = engine.passes(base, stress)

    bins = direct_ev.calibration_bins(
        all_scores.net_return, all_scores.predicted_net_return, bins=10
    )
    bins.to_csv(OUTPUT / "walk_forward_score_bins.csv", index=False,
                encoding="utf-8", lineterminator="\n")
    all_scores.to_csv(OUTPUT / "walk_forward_scores.csv", index=False,
                      encoding="utf-8", lineterminator="\n")
    pd.DataFrame(base_trades).to_csv(OUTPUT / "trades_base.csv", index=False,
                                     encoding="utf-8", lineterminator="\n")
    pd.DataFrame(stress_trades).to_csv(OUTPUT / "trades_stress.csv", index=False,
                                       encoding="utf-8", lineterminator="\n")

    parent_hash = digest(PARENT_REPORT)
    ordered_labels = labels.sort_values(["symbol", "side", "signal_time"]).copy()
    prior_max_end = ordered_labels.groupby(["symbol", "side"])["label_end_time"].transform(
        lambda series: series.cummax().shift(1)
    )
    overlap_mask = ordered_labels["signal_time"] < prior_max_end
    label_overlap_diagnostic = {
        "rows": int(len(ordered_labels)),
        "overlapping_prior_label_rows": int(overlap_mask.sum()),
        "overlap_fraction": float(overlap_mask.mean()),
        "independent_trade_count_source": "executed non-overlapping portfolio ledger only",
    }
    report = {
        "experiment_id": "C10-one-minute-breakout-first-crossing-2026-09-28",
        "status": "retrospective_walk_forward_exploration",
        "parent_experiment_id": "C09-one-minute-breakout-first-crossing-2026-09-28",
        "market": MARKET,
        "symbols": list(SYMBOLS),
        "entry_family": FAMILY,
        "entry_signal_interval_minutes": 1,
        "breakout_and_volume_lookback_minutes": BREAKOUT_LOOKBACK_MINUTES,
        "breakout_trigger": "previous close versus previous 300m channel state; current close outside current channel",
        "minimum_candidate_interval_minutes": SIGNAL_COOLDOWN_MINUTES,
        "horizon_minutes": MAX_HOLD_MINUTES,
        "exit_mode": EXIT_MODE,
        "exit_ema_timeframe_minutes": 15,
        "initial_stop_atr_timeframe_minutes": 15,
        "target": direct_ev.TARGET,
        "backend": BACKEND,
        "cutoff": {"operator": ">", "value": direct_ev.CUTOFF},
        "only_strategy_component_changed": "first-crossing trigger now compares prior close to prior Donchian channel; uniqueness weights unchanged",
        "monthly_refit_policy": "Cycle04 expanding training using matured labels",
        "training_sample_weighting": "mean inverse concurrency over each mature label interval, normalized to mean one per fold",
        "selection_start": selection_start.isoformat(),
        "selection_end_exclusive": selection_end.isoformat(),
        "total_candidate_events": int(len(candidates)),
        "total_labeled_events": int(len(labels)),
        "selection_candidate_events": int(len(selection_pool)),
        "selected_candidates": int(len(selected_ids)),
        "folds": fold_rows,
        "score_diagnostics": direct_ev._finite_metrics(
            all_scores.net_return.to_numpy(dtype=float),
            all_scores.predicted_net_return.to_numpy(dtype=float),
        ),
        "score_bins_path": str((OUTPUT / "walk_forward_score_bins.csv").relative_to(ROOT)).replace("\\", "/"),
        "rule_baseline": {"base": rule_base, "stress": rule_stress},
        "base": base,
        "stress": stress,
        "gate_passed": bool(passed),
        "gate_failures": failures,
        "dataset_sha256": dataset_hash["dataset_sha256"],
        "dataset_manifest_sha256": dataset_hash["manifest_sha256"],
        "source_c02_report_sha256": digest(SOURCE_REPORT),
        "parent_c09_report_sha256": parent_hash,
        "candidate_label_overlap_diagnostic": label_overlap_diagnostic,
        "cycle02_engine_sha256": digest(RESEARCH / "scripts/cycle02_multiframe_research.py"),
        "cycle03_direct_ev_sha256": digest(RESEARCH / "scripts/cycle03_direct_net_ev.py"),
        "script_sha256": digest(Path(__file__).resolve()),
        "protocol_sha256": digest(PROTOCOL),
        "training_seconds_total": time.perf_counter() - started_all,
        "real_orders_sent": False,
        "independent_validation": False,
        "retrospective_results_are_not_paper_or_live_authorization": True,
    }
    (OUTPUT / "research.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, ensure_ascii=False), flush=True)
