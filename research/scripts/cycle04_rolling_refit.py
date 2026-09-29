from __future__ import annotations

import gc
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "research"
sys.path.insert(0, str(RESEARCH / "scripts"))
import cycle02_multiframe_research as engine  # noqa: E402
import cycle03_direct_net_ev as direct_ev  # noqa: E402


VARIANT_ID = "USD_M-BREAKOUT_CONTINUATION-24H-TREND_LOSS"
BACKEND = "xgboost_cuda"
OUTPUT = RESEARCH / "results/cycle04_rolling_refit_2026-09-28"
PROTOCOL = RESEARCH / "docs/CICLO04_ROLLING_REFIT_PROTOCOLO.md"
EMBARGO = pd.Timedelta(minutes=engine.EMBARGO_MINUTES)


def month_folds(start: pd.Timestamp, end: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Return non-overlapping UTC calendar-month windows clipped to [start, end)."""
    start = pd.Timestamp(start).tz_convert("UTC")
    end = pd.Timestamp(end).tz_convert("UTC")
    if start >= end:
        raise ValueError("start must be earlier than end")
    cursor = start.normalize().replace(day=1)
    folds: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    while cursor < end:
        next_month = cursor + pd.offsets.MonthBegin(1)
        fold_start = max(cursor, start)
        fold_end = min(next_month, end)
        if fold_start < fold_end:
            folds.append((fold_start, fold_end))
        cursor = next_month
    return folds


def matured_training_labels(
    labels: pd.DataFrame, as_of: pd.Timestamp, embargo: pd.Timedelta = EMBARGO
) -> pd.DataFrame:
    """Use only labels known before the monthly retrain, with the existing purge."""
    as_of = pd.Timestamp(as_of).tz_convert("UTC")
    return labels.loc[
        (labels.signal_time < as_of - embargo)
        & (labels.label_end_time < as_of)
    ].copy()


def month_candidates(
    labels: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
) -> pd.DataFrame:
    """Return all pre-censored candidate events in one monthly scoring fold."""
    return labels.loc[
        (labels.signal_time >= start)
        & (labels.signal_time < end)
    ].copy()


def _read_static_reference() -> tuple[dict[str, Any], dict[str, Any]]:
    report_path = RESEARCH / "results/cycle03_direct_net_ev_2026-09-28/research.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rows = [
        row for row in report["models"]
        if row["variant_id"] == VARIANT_ID and row["backend"] == BACKEND
    ]
    if len(rows) != 1:
        raise AssertionError(f"Expected one static reference row, found {len(rows)}")
    return report, rows[0]


def run() -> dict[str, Any]:
    if OUTPUT.exists():
        raise FileExistsError(f"Output already exists; refusing overwrite: {OUTPUT}")

    source_report, variants = direct_ev.load_source()
    variant_rows = [row for row in variants if row["variant_id"] == VARIANT_ID]
    if len(variant_rows) != 1:
        raise AssertionError(f"Expected one source variant, found {len(variant_rows)}")
    source = variant_rows[0]
    input_hashes = direct_ev.verify_inputs(source_report, [source])
    direct_report, static_reference = _read_static_reference()
    direct_report_path = RESEARCH / "results/cycle03_direct_net_ev_2026-09-28/research.json"
    OUTPUT.mkdir(parents=True, exist_ok=False)
    labels_path = ROOT / source["candidate_labels_path"]
    labels = pd.read_csv(labels_path)
    for column in ("signal_time", "entry_time", "label_end_time"):
        labels[column] = pd.to_datetime(labels[column], utc=True)

    selection_start = engine.CALIBRATION_END + EMBARGO
    selection_end = engine.SELECTION_END
    max_hold = int(source["max_hold_minutes"])
    selection_pool = labels.loc[
        (labels.signal_time >= selection_start)
        & (labels.signal_time < selection_end - pd.Timedelta(minutes=max_hold))
    ].copy()
    folds = month_folds(selection_start, selection_end - pd.Timedelta(minutes=max_hold))
    if selection_pool.empty or not folds:
        raise ValueError("Empty walk-forward selection window")

    data_source = next(row for row in source_report["data"] if row["market"] == "usd_m")
    arrays, ema_by_symbol = direct_ev.load_market_context("usd_m", data_source)
    model_root = OUTPUT / "models"
    model_root.mkdir(parents=True, exist_ok=False)
    fold_rows: list[dict[str, Any]] = []
    score_parts: list[pd.DataFrame] = []
    started_all = time.perf_counter()

    for fold_start, fold_end in folds:
        as_of = fold_start.normalize().replace(day=1)
        train = matured_training_labels(labels, as_of)
        test = month_candidates(selection_pool, fold_start, fold_end)
        if train.empty or test.empty:
            raise ValueError(
                f"Empty fold at {fold_start.isoformat()}: train={len(train)}, test={len(test)}"
            )
        if (train.label_end_time >= as_of).any() or (train.signal_time >= as_of - EMBARGO).any():
            raise AssertionError("Lookahead detected in rolling training partition")

        fit_started = time.perf_counter()
        model, train_mean = direct_ev.fit_regressor(train, BACKEND)
        fit_seconds = time.perf_counter() - fit_started
        config = model.get_booster().save_config()
        compact_config = config.replace(" ", "")
        if '"device":"cuda:0"' not in compact_config or '"tree_method":"hist"' not in compact_config:
            raise AssertionError("Monthly XGBoost model did not train on CUDA hist")

        features = test.drop(columns=list(direct_ev.LABEL_ONLY_COLUMNS), errors="ignore").copy()
        x_test = features[list(engine.FEATURES)].astype(float).replace([np.inf, -np.inf], np.nan)
        predicted = np.asarray(model.predict(x_test), dtype=float)
        if not np.isfinite(predicted).all():
            raise AssertionError(f"Non-finite predictions in fold {fold_start:%Y-%m}")
        features["predicted_net_return"] = predicted
        features["passed_fixed_cutoff"] = direct_ev.select_by_predicted_ev(
            features["predicted_net_return"]
        )
        features["probability"] = features["predicted_net_return"]
        features["expected_r"] = features["predicted_net_return"]
        qualified = features.loc[features.passed_fixed_cutoff].copy()

        diagnostic = test[["candidate_id", "signal_time", "symbol", "net_return"]].copy()
        diagnostic["predicted_net_return"] = predicted
        diagnostic["passed_fixed_cutoff"] = features["passed_fixed_cutoff"].to_numpy()
        score_parts.append(diagnostic)

        model_path = model_root / f"{fold_start:%Y-%m}.json"
        model.save_model(model_path)
        fold_rows.append({
            "fold_start": fold_start.isoformat(),
            "fold_end_exclusive": fold_end.isoformat(),
            "training_as_of": as_of.isoformat(),
            "training_rows": int(len(train)),
            "training_target_mean": train_mean,
            "candidate_rows": int(len(test)),
            "selected_candidates": int(len(qualified)),
            "training_seconds": fit_seconds,
            "device": "cuda:0",
            "tree_method": "hist",
            "model_path": str(model_path.relative_to(ROOT)).replace("\\", "/"),
            "model_sha256": direct_ev.digest(model_path),
        })
        print(json.dumps({
            "fold": f"{fold_start:%Y-%m}", "train_rows": len(train),
            "candidates": len(test), "selected": len(qualified),
            "seconds": round(fit_seconds, 2),
        }), flush=True)
        del model, train, test, features, x_test, predicted, qualified, diagnostic
        gc.collect()

    all_scores = pd.concat(score_parts, ignore_index=True)
    if all_scores.candidate_id.duplicated().any():
        raise AssertionError("Candidate scored more than once across monthly folds")
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

    outcome_cache: dict[tuple[str, bool], Any] = {}
    base, base_trades = engine.evaluate_portfolio(
        selection_features, arrays, {"usd_m": engine.gate_config("usd_m")},
        source["exit_mode"], max_hold, ema_by_symbol,
        selection_start, selection_end, stress=False, outcome_cache=outcome_cache,
    )
    stress, stress_trades = engine.evaluate_portfolio(
        selection_features, arrays, {"usd_m": engine.gate_config("usd_m")},
        source["exit_mode"], max_hold, ema_by_symbol,
        selection_start, selection_end, stress=True, outcome_cache=outcome_cache,
    )
    passed, failures = engine.passes(base, stress)

    features_all = all_scores.predicted_net_return.to_numpy(dtype=float)
    actual_all = all_scores.net_return.to_numpy(dtype=float)
    score_diagnostics = direct_ev._finite_metrics(actual_all, features_all)
    bins = direct_ev.calibration_bins(
        pd.Series(actual_all), pd.Series(features_all), bins=10
    )
    all_scores.to_csv(OUTPUT / "walk_forward_scores.csv", index=False,
                      encoding="utf-8", lineterminator="\n")
    bins.to_csv(OUTPUT / "walk_forward_score_bins.csv", index=False,
                encoding="utf-8", lineterminator="\n")
    pd.DataFrame(base_trades).to_csv(OUTPUT / "trades_base.csv", index=False,
                                     encoding="utf-8", lineterminator="\n")
    pd.DataFrame(stress_trades).to_csv(OUTPUT / "trades_stress.csv", index=False,
                                       encoding="utf-8", lineterminator="\n")

    direct_hash = direct_ev.digest(direct_report_path)
    report = {
        "experiment_id": "C04-monthly-expanding-xgboost-roll-2026-09-28",
        "status": "retrospective_walk_forward_exploration",
        "variant_id": VARIANT_ID,
        "market": "usd_m",
        "backend": BACKEND,
        "entry_family": source["family"],
        "horizon_minutes": max_hold,
        "exit_mode": source["exit_mode"],
        "target": direct_ev.TARGET,
        "cutoff": {"operator": ">", "value": direct_ev.CUTOFF},
        "only_strategy_component_changed": "monthly expanding-window model refit using matured labels",
        "script_sha256": direct_ev.digest(Path(__file__).resolve()),
        "protocol_sha256": direct_ev.digest(PROTOCOL),
        "cycle03_direct_script_sha256": direct_ev.digest(RESEARCH / "scripts/cycle03_direct_net_ev.py"),
        "features": list(engine.FEATURES),
        "window_start": selection_start.isoformat(),
        "window_end_exclusive": selection_end.isoformat(),
        "folds": fold_rows,
        "training_seconds_total": time.perf_counter() - started_all,
        "input_hashes": input_hashes,
        "source_c03_report_sha256": direct_hash,
        "source_c03_static_reference": static_reference,
        "walk_forward_score_diagnostics": score_diagnostics,
        "walk_forward_score_bins_path": str((OUTPUT / "walk_forward_score_bins.csv").relative_to(ROOT)).replace("\\", "/"),
        "selected_candidates": len(selected_ids),
        "base": base,
        "stress": stress,
        "gate_passed": bool(passed),
        "gate_failures": failures,
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
