from __future__ import annotations

import gc
import hashlib
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from threadpoolctl import threadpool_limits


ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "research"
ENGINE_PATH = RESEARCH / "scripts"
sys.path.insert(0, str(ENGINE_PATH))
import cycle02_multiframe_research as engine  # noqa: E402


SOURCE_REPORT = RESEARCH / "results/cycle02_multiframe_corrected_2026-09-28/research.json"
PROTOCOL = RESEARCH / "docs/CICLO03_DIRECT_NET_EV_PROTOCOLO.md"
OUTPUT = RESEARCH / "results/cycle03_direct_net_ev_2026-09-28"
BACKENDS = ("hist_cpu", "xgboost_cuda")
TARGET = "net_return"
CUTOFF = 0.012
LABEL_ONLY_COLUMNS = {
    "label", "net_return", "net_r", "label_end_time", "exit_reason", "entry_time"
}
TRADE_EXPORT_COLUMNS = (
    "candidate_id", "signal_time", "symbol", "market", "family", "side",
    "predicted_net_return", "passed_fixed_cutoff",
)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def select_by_predicted_ev(scores: pd.Series, cutoff: float = CUTOFF) -> pd.Series:
    """Return the single preregistered strict predicted-EV selection rule."""
    numeric = pd.to_numeric(scores, errors="coerce")
    return numeric > cutoff


def _finite_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float | int | None]:
    mask = np.isfinite(actual) & np.isfinite(predicted)
    y = actual[mask]
    p = predicted[mask]
    if not len(y):
        return {"rows": 0, "mae": None, "rmse": None, "r2": None,
                "actual_mean": None, "predicted_mean": None,
                "baseline_mean_mae": None, "baseline_mean_rmse": None,
                "pearson_r": None}
    baseline = np.full(len(y), float(np.mean(y)))
    corr = float(np.corrcoef(y, p)[0, 1]) if np.std(y) and np.std(p) else None
    return {
        "rows": int(len(y)),
        "mae": float(mean_absolute_error(y, p)),
        "rmse": float(math.sqrt(mean_squared_error(y, p))),
        "r2": float(r2_score(y, p)) if len(y) > 1 else None,
        "actual_mean": float(np.mean(y)),
        "predicted_mean": float(np.mean(p)),
        "baseline_mean_mae": float(mean_absolute_error(y, baseline)),
        "baseline_mean_rmse": float(math.sqrt(mean_squared_error(y, baseline))),
        "pearson_r": corr,
    }


def calibration_bins(actual: pd.Series, predicted: pd.Series, bins: int = 10) -> pd.DataFrame:
    frame = pd.DataFrame({"actual": actual.to_numpy(dtype=float),
                          "predicted": predicted.to_numpy(dtype=float)})
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna()
    if frame.empty:
        return pd.DataFrame(columns=["score_decile", "rows", "predicted_mean", "realized_mean"])
    rank = frame.predicted.rank(method="first", pct=True)
    q = min(bins, len(frame))
    frame["score_decile"] = pd.qcut(rank, q=q, labels=False, duplicates="drop")
    return (frame.groupby("score_decile", observed=True)
            .agg(rows=("actual", "size"), predicted_mean=("predicted", "mean"),
                 realized_mean=("actual", "mean"))
            .reset_index())


def create_regressor(backend: str) -> Any:
    if backend == "hist_cpu":
        return HistGradientBoostingRegressor(
            loss="squared_error", max_iter=160, learning_rate=0.05,
            max_leaf_nodes=15, min_samples_leaf=60, l2_regularization=10,
            early_stopping=False, random_state=27,
        )
    if backend == "xgboost_cuda":
        import xgboost
        from xgboost import XGBRegressor

        if not xgboost.build_info().get("USE_CUDA", False):
            raise RuntimeError("XGBoost has no CUDA build; refusing CPU fallback")
        return XGBRegressor(
            objective="reg:squarederror", n_estimators=320, max_depth=4,
            learning_rate=0.04, subsample=0.8, colsample_bytree=0.8,
            min_child_weight=40, reg_lambda=10, max_bin=256,
            tree_method="hist", device="cuda:0", n_jobs=4,
            random_state=27, verbosity=0,
        )
    raise ValueError(f"Unknown backend: {backend}")


def fit_regressor(train: pd.DataFrame, backend: str) -> tuple[Any, float]:
    if train.empty:
        raise ValueError("No training labels after chronological purge")
    y = pd.to_numeric(train[TARGET], errors="coerce")
    valid = np.isfinite(y.to_numpy(dtype=float))
    train = train.loc[valid].copy()
    y = y.loc[valid].astype(float)
    x = train[list(engine.FEATURES)].astype(float).replace([np.inf, -np.inf], np.nan)
    model = create_regressor(backend)
    threads = 1 if backend == "hist_cpu" else 4
    with threadpool_limits(limits=threads):
        model.fit(x, y)
    return model, float(y.mean())


def load_source() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    report = json.loads(SOURCE_REPORT.read_text(encoding="utf-8"))
    if CUTOFF != engine.MIN_NET_EV:
        raise AssertionError("The preregistered selection cutoff must match the current EV target")
    if TARGET in engine.FEATURES or list(engine.FEATURES) != report.get("features"):
        raise AssertionError("Target leakage or feature list drift detected")
    rows = [row for row in report["models"]
            if row.get("backend") in BACKENDS and row.get("candidate_labels_path")]
    by_variant: dict[str, dict[str, Any]] = {}
    for row in rows:
        variant = row["variant_id"]
        current = by_variant.setdefault(variant, row)
        if (row["candidate_labels_path"] != current["candidate_labels_path"]
                or row["candidate_labels_sha256"] != current["candidate_labels_sha256"]):
            raise AssertionError(f"Mismatched candidate-label source for {variant}")
    if len(by_variant) != 24:
        raise AssertionError(f"Expected 24 fixed variants, found {len(by_variant)}")
    source_path = ROOT / SOURCE_REPORT.relative_to(ROOT)
    if report.get("status") != "historical_exploratory_not_prospective":
        raise AssertionError("Unexpected source report status")
    return report, sorted(by_variant.values(), key=lambda row: row["variant_id"])


def verify_inputs(report: dict[str, Any], variants: list[dict[str, Any]]) -> dict[str, Any]:
    input_hashes: dict[str, Any] = {
        "source_report_sha256": digest(SOURCE_REPORT),
        "engine_sha256": digest(RESEARCH / "scripts/cycle02_multiframe_research.py"),
        "dataset_sources": {},
        "candidate_label_sources": {},
    }
    data_by_market = {row["market"]: row for row in report["data"]}
    if set(data_by_market) != {"spot", "usd_m"}:
        raise AssertionError("Source report does not cover Spot and USD-M")
    for market, row in data_by_market.items():
        dataset = ROOT / row["dataset_path"]
        manifest = dataset / "dataset.json"
        if not dataset.exists() or not manifest.exists():
            raise FileNotFoundError(dataset)
        data_hash = digest(dataset / "candles.csv.gz")
        manifest_hash = digest(manifest)
        if data_hash != row["dataset_sha256"] or manifest_hash != row["manifest_sha256"]:
            raise AssertionError(f"Dataset hash mismatch for {market}")
        input_hashes["dataset_sources"][market] = {
            "dataset_sha256": data_hash, "manifest_sha256": manifest_hash,
            "rows": row["rows"], "symbols": row["symbols"],
        }
    for row in variants:
        labels = ROOT / row["candidate_labels_path"]
        actual = digest(labels)
        expected = row["candidate_labels_sha256"]
        if actual != expected:
            raise AssertionError(f"Candidate label hash mismatch: {labels}")
        input_hashes["candidate_label_sources"][row["variant_id"]] = {
            "path": row["candidate_labels_path"], "sha256": actual,
        }
    return input_hashes


def load_market_context(market: str, expected: dict[str, Any]) -> tuple[dict, dict]:
    folder = "spot_btc_eth_1m" if market == "spot" else "usdm_btc_eth_1m"
    dataset_path = RESEARCH / "data" / folder
    candles, provenance = engine.load_dataset(dataset_path, market)
    candles = candles.loc[candles.open_time < engine.DATA_END].copy()
    if provenance["data_sha256"] != expected["dataset_sha256"]:
        raise AssertionError(f"Loaded dataset hash changed for {market}")
    arrays: dict[str, Any] = {}
    ema_by_symbol: dict[str, dict] = {}
    for symbol, grouped in candles.groupby("symbol", sort=True):
        bars = grouped.reset_index(drop=True)
        arrays[symbol] = engine.MarketArrays(bars)
        _, ema_map = engine.market_features(bars)
        ema_by_symbol[symbol] = ema_map
        del bars
        gc.collect()
    return arrays, ema_by_symbol


def save_model(model: Any, backend: str, model_dir: Path) -> tuple[str, str, str | None]:
    model_dir.mkdir(parents=True, exist_ok=False)
    if backend == "xgboost_cuda":
        path = model_dir / "regressor.json"
        model.save_model(path)
        config = model.get_booster().save_config()
        compact = config.replace(" ", "")
        if '"device":"cuda:0"' not in compact or '"tree_method":"hist"' not in compact:
            raise AssertionError("Saved XGBoost config does not confirm CUDA histogram training")
        return str(path.relative_to(ROOT)).replace("\\", "/"), digest(path), config
    import joblib

    path = model_dir / "regressor.joblib"
    joblib.dump({"model": model, "features": list(engine.FEATURES),
                 "target": TARGET, "cutoff": CUTOFF}, path, compress=3)
    return str(path.relative_to(ROOT)).replace("\\", "/"), digest(path), None


def run() -> dict[str, Any]:
    if OUTPUT.exists():
        raise FileExistsError(f"Output already exists; refusing overwrite: {OUTPUT}")
    source_report, variants = load_source()
    hashes = verify_inputs(source_report, variants)
    output_absent_before_run = not OUTPUT.exists()
    OUTPUT.mkdir(parents=True, exist_ok=False)
    (OUTPUT / "RUNNING.json").write_text(
        json.dumps({"status": "running", "started_utc": pd.Timestamp.now(tz="UTC").isoformat()},
                   indent=2) + "\n", encoding="utf-8")

    report = {
        "experiment_id": "C03-direct-net-ev-filter-2026-09-28",
        "status": "running",
        "source_report": str(SOURCE_REPORT.relative_to(ROOT)).replace("\\", "/"),
        "source_report_sha256": hashes["source_report_sha256"],
        "protocol": str(PROTOCOL.relative_to(ROOT)).replace("\\", "/"),
        "protocol_sha256": digest(PROTOCOL),
        "script_sha256": digest(Path(__file__).resolve()),
        "engine_sha256": hashes["engine_sha256"],
        "input_hashes": hashes,
        "output_absent_before_run": output_absent_before_run,
        "target": TARGET,
        "cutoff": {"operator": ">", "value": CUTOFF},
        "features": list(engine.FEATURES),
        "markets": ["spot", "usd_m"],
        "symbols": ["BTCUSDT", "ETHUSDT"],
        "selection_start": (engine.CALIBRATION_END + pd.Timedelta(minutes=engine.EMBARGO_MINUTES)).isoformat(),
        "selection_end_exclusive": engine.SELECTION_END.isoformat(),
        "training_performed": True,
        "gpu_training_performed": False,
        "real_orders_sent": False,
        "models": [],
    }
    market_sources = {row["market"]: row for row in source_report["data"]}
    for market in ("spot", "usd_m"):
        arrays, ema_by_symbol = load_market_context(market, market_sources[market])
        market_variants = [row for row in variants if row["market"] == market]
        for source in market_variants:
            variant_id = source["variant_id"]
            max_hold = int(source["max_hold_minutes"])
            exit_mode = source["exit_mode"]
            labels_path = ROOT / source["candidate_labels_path"]
            labels = pd.read_csv(labels_path)
            for column in ("signal_time", "entry_time", "label_end_time"):
                if column in labels:
                    labels[column] = pd.to_datetime(labels[column], utc=True)
            train, calibration, _ = engine.split_labels(labels)
            selection_start = engine.CALIBRATION_END + pd.Timedelta(minutes=engine.EMBARGO_MINUTES)
            selection_end = engine.SELECTION_END
            selection_pool = labels.loc[
                (labels.signal_time >= selection_start)
                & (labels.signal_time < selection_end - pd.Timedelta(minutes=max_hold))
            ].copy()
            if train.empty or calibration.empty or selection_pool.empty:
                raise ValueError(f"Empty chronological partition for {variant_id}")
            outcome_cache: dict[tuple[str, bool], Any] = {}
            base_rows = selection_pool.drop(columns=list(LABEL_ONLY_COLUMNS), errors="ignore").copy()
            base_rows["probability"] = 1.0
            base_rows["expected_r"] = 1.0
            rule_base, _ = engine.evaluate_portfolio(
                base_rows, arrays, {market: engine.gate_config(market)}, exit_mode,
                max_hold, ema_by_symbol, selection_start, selection_end, stress=False,
                outcome_cache=outcome_cache,
            )
            rule_stress, _ = engine.evaluate_portfolio(
                base_rows, arrays, {market: engine.gate_config(market)}, exit_mode,
                max_hold, ema_by_symbol, selection_start, selection_end, stress=True,
                outcome_cache=outcome_cache,
            )
            for backend in BACKENDS:
                started = time.perf_counter()
                model, training_mean = fit_regressor(train, backend)
                train_seconds = time.perf_counter() - started
                x_cal = calibration[list(engine.FEATURES)].astype(float).replace([np.inf, -np.inf], np.nan)
                y_cal = calibration[TARGET].to_numpy(dtype=float)
                cal_predictions = model.predict(x_cal)
                diagnostics = _finite_metrics(y_cal, np.asarray(cal_predictions, dtype=float))
                diagnostics["training_mean_baseline"] = _finite_metrics(
                    y_cal, np.full(len(y_cal), training_mean, dtype=float)
                )
                bins = calibration_bins(calibration[TARGET], pd.Series(cal_predictions))
                model_dir = OUTPUT / variant_id / backend
                model_path, model_hash, booster_config = save_model(model, backend, model_dir)
                bins_path = model_dir / "calibration_score_bins.csv"
                bins.to_csv(bins_path, index=False, encoding="utf-8", lineterminator="\n")

                selection_features = selection_pool.drop(
                    columns=list(LABEL_ONLY_COLUMNS), errors="ignore"
                ).copy()
                x_selection = selection_features[list(engine.FEATURES)].astype(float).replace(
                    [np.inf, -np.inf], np.nan
                )
                predicted = np.asarray(model.predict(x_selection), dtype=float)
                if not np.isfinite(predicted).all():
                    raise AssertionError(f"Non-finite predictions in {variant_id}/{backend}")
                scored = selection_features.copy()
                scored["predicted_net_return"] = predicted
                scored["passed_fixed_cutoff"] = select_by_predicted_ev(scored.predicted_net_return)
                qualified = scored.loc[scored.passed_fixed_cutoff].copy()
                eligible_scores = qualified[list(TRADE_EXPORT_COLUMNS)].copy()
                scores_path = model_dir / "eligible_scores.csv"
                eligible_scores.to_csv(scores_path, index=False, encoding="utf-8", lineterminator="\n")

                # The two engine score fields only impose deterministic ranking among simultaneous
                # candidates; here both carry predicted net return, not probability or R.
                qualified["probability"] = qualified["predicted_net_return"]
                qualified["expected_r"] = qualified["predicted_net_return"]
                base, base_trades = engine.evaluate_portfolio(
                    qualified, arrays, {market: engine.gate_config(market)}, exit_mode,
                    max_hold, ema_by_symbol, selection_start, selection_end, stress=False,
                    outcome_cache=outcome_cache,
                )
                stress, stress_trades = engine.evaluate_portfolio(
                    qualified, arrays, {market: engine.gate_config(market)}, exit_mode,
                    max_hold, ema_by_symbol, selection_start, selection_end, stress=True,
                    outcome_cache=outcome_cache,
                )
                passed, failures = engine.passes(base, stress)
                trades_dir = model_dir / "trades"
                trades_dir.mkdir(exist_ok=False)
                pd.DataFrame(base_trades).to_csv(
                    trades_dir / "base.csv", index=False, encoding="utf-8", lineterminator="\n"
                )
                pd.DataFrame(stress_trades).to_csv(
                    trades_dir / "stress.csv", index=False, encoding="utf-8", lineterminator="\n"
                )
                record = {
                    "variant_id": variant_id,
                    "market": market,
                    "family": source["family"],
                    "horizon": source["horizon"],
                    "exit_mode": exit_mode,
                    "backend": backend,
                    "training_device": "cuda:0" if backend == "xgboost_cuda" else "cpu",
                    "train_rows": len(train),
                    "calibration_rows": len(calibration),
                    "selection_candidates": len(selection_pool),
                    "eligible_prediction_count": len(qualified),
                    "selection_cutoff_strict": CUTOFF,
                    "selection_cutoff_operator": ">",
                    "training_seconds": train_seconds,
                    "train_target_mean": training_mean,
                    "calibration_regression_diagnostics": diagnostics,
                    "calibration_bins_path": str(bins_path.relative_to(ROOT)).replace("\\", "/"),
                    "calibration_bins_sha256": digest(bins_path),
                    "model_path": model_path,
                    "model_sha256": model_hash,
                    "booster_config": booster_config,
                    "eligible_scores_path": str(scores_path.relative_to(ROOT)).replace("\\", "/"),
                    "eligible_scores_sha256": digest(scores_path),
                    "rule_baseline": {"base": rule_base, "stress": rule_stress},
                    "base": base,
                    "stress": stress,
                    "gate_passed": passed,
                    "gate_failures": failures,
                    "base_trades_path": str((trades_dir / "base.csv").relative_to(ROOT)).replace("\\", "/"),
                    "stress_trades_path": str((trades_dir / "stress.csv").relative_to(ROOT)).replace("\\", "/"),
                    "independent_validation": False,
                    "status": "historical_selection_gates_met_not_prospective" if passed else "target_not_demonstrated",
                }
                report["models"].append(record)
                print(json.dumps({"variant": variant_id, "backend": backend,
                                  "selected": len(qualified), "trades": base["trades"],
                                  "ev": base["mean_net_return"], "stress_pnl": stress["net_profit"],
                                  "gate_passed": passed}, ensure_ascii=False), flush=True)
                del model, x_cal, x_selection, selection_features, qualified, scored
                gc.collect()
            del labels, train, calibration, selection_pool, base_rows, outcome_cache
            gc.collect()
        del arrays, ema_by_symbol
        gc.collect()
    report["gpu_training_performed"] = any(
        row["backend"] == "xgboost_cuda" for row in report["models"]
    )
    report["gate_pass_count"] = sum(bool(row["gate_passed"]) for row in report["models"])
    report["status"] = "complete_exploratory_not_independent"
    result_path = OUTPUT / "research.json"
    result_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    running_path = OUTPUT / "RUNNING.json"
    running_path.unlink()
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps({"status": result["status"], "models": len(result["models"]),
                      "gate_pass_count": result["gate_pass_count"],
                      "gpu_training_performed": result["gpu_training_performed"]},
                     ensure_ascii=False), flush=True)
