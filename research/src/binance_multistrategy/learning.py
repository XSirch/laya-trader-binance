"""Supervised meta-labeling, expected-return regression and chronological calibration."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any
import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from threadpoolctl import threadpool_limits
from . import __version__
from .config import ResearchConfig
from .features import build_features
from .strategies import INPUT_FEATURES, STRATEGIES, generate_candidates
from .simulation import MarketArrays, evaluate, label_candidates, promotion_gate


def logit(probabilities: np.ndarray) -> np.ndarray:
    p = np.clip(probabilities, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p)).reshape(-1, 1)


def code_fingerprint() -> str:
    digest = hashlib.sha256()
    for file in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(file.name.encode())
        digest.update(file.read_bytes())
    return digest.hexdigest()


@dataclass
class TrainedGate:
    classifier: Any
    regressor: Any
    calibrator: Any
    config: ResearchConfig
    features: list[str]
    metadata: dict
    threshold: float
    research_gate_passed: bool

    def score(self, rows: pd.DataFrame) -> pd.DataFrame:
        result = rows.copy()
        if rows.empty:
            result["probability"] = pd.Series(dtype=float)
            result["expected_r"] = pd.Series(dtype=float)
            return result
        missing = set(self.features) - set(rows.columns)
        if missing:
            raise ValueError(f"Inference feature schema mismatch: {sorted(missing)}")
        x = rows[self.features].astype(float).replace([np.inf, -np.inf], np.nan)
        if self.metadata.get("ml_backend") == "xgboost_cuda":
            # Training uses CUDA; research scoring uses CPU to avoid implicit host/device
            # transfers for pandas inputs and to keep the full minute history in system RAM.
            self.classifier.set_params(device="cpu")
            self.regressor.set_params(device="cpu")
        with threadpool_limits(limits=self.config.n_threads):
            p = self.classifier.predict_proba(x)[:, 1]
            result["probability"] = self.calibrator.predict_proba(logit(p))[:, 1]
            result["expected_r"] = self.regressor.predict(x)
        return result

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        joblib.dump(self, temporary, compress=3)
        temporary.replace(path)

    @staticmethod
    def load(path: Path) -> "TrainedGate":
        # joblib/pickle can execute code: load ONLY artifacts produced by this trusted project.
        model = joblib.load(path)
        if not isinstance(model, TrainedGate):
            raise ValueError("Not a multistrategy TrainedGate artifact")
        if model.metadata.get("sklearn_version") != sklearn.__version__:
            raise ValueError("scikit-learn version differs from training; use the recorded environment or retrain")
        if model.metadata.get("ml_backend") == "xgboost_cuda":
            import xgboost
            if model.metadata.get("xgboost_version") != xgboost.__version__:
                raise ValueError("XGBoost version differs from training; use the recorded environment or retrain")
        if model.metadata.get("code_sha256") != code_fingerprint():
            raise ValueError("Code differs from the trained artifact; review changes and retrain")
        return model


def prepare_market(candles: pd.DataFrame, config: ResearchConfig) -> tuple[pd.DataFrame, dict[str, MarketArrays]]:
    frames, market = [], {}
    for symbol, bars in candles.groupby("symbol", sort=True):
        bars = bars.reset_index(drop=True)
        market[symbol] = MarketArrays(bars)
        features = build_features(bars)
        frame = generate_candidates(features, symbol, config)
        if not frame.empty:
            frames.append(frame)
        print(f"Features/candidates: {config.market} {symbol}, bars={len(bars)}, candidates={len(frame)}", flush=True)
    candidates = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=INPUT_FEATURES + ["symbol", "strategy", "signal_time"])
    if not candidates.empty:
        candidates = candidates.sort_values(["signal_time", "symbol", "strategy", "side"]).reset_index(drop=True)
    return candidates, market


def purged_window(rows: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, embargo: int) -> pd.DataFrame:
    gap = pd.Timedelta(minutes=embargo)
    return rows.loc[(rows.signal_time >= start + gap) & (rows.signal_time < end - gap)
                    & (rows.label_end_time < end)].copy()


def fit_heads(train: pd.DataFrame, calibration: pd.DataFrame, config: ResearchConfig,
              backend: str = "hist_cpu") -> tuple[Any, Any, Any, dict]:
    for name, subset in [("training", train), ("calibration", calibration)]:
        counts = subset.label.value_counts()
        if len(subset) < 300 or len(counts) != 2 or counts.min() < 30:
            raise ValueError(f"Insufficient {name} examples: {len(subset)}, classes={counts.to_dict()}; need >=300 rows, >=30/class")
        if not np.isfinite(subset.net_r).all():
            raise ValueError(f"Non-finite targets in {name}")
    if train.label_end_time.max() >= calibration.signal_time.min():
        raise ValueError("Training label horizon overlaps calibration; temporal leakage")
    if len(train) > config.max_training_rows:
        train = train.sample(n=config.max_training_rows, random_state=config.random_seed).sort_values("signal_time")
    if backend == "hist_cpu":
        common = dict(max_iter=160, learning_rate=.05, max_leaf_nodes=15,
                      min_samples_leaf=60, l2_regularization=10, early_stopping=False,
                      random_state=config.random_seed)
        classifier = HistGradientBoostingClassifier(**common)
        regressor = HistGradientBoostingRegressor(loss="squared_error", **common)
    elif backend == "xgboost_cuda":
        try:
            import xgboost
            from xgboost import XGBClassifier, XGBRegressor
        except ImportError as exc:
            raise RuntimeError("GPU training requires `uv sync --extra gpu` on Python 3.12+") from exc
        if not xgboost.build_info().get("USE_CUDA", False):
            raise RuntimeError("Installed XGBoost build has no CUDA support; refusing a silent CPU fallback")
        common = dict(n_estimators=320, max_depth=4, learning_rate=.04,
                      subsample=.8, colsample_bytree=.8, min_child_weight=40,
                      reg_lambda=10, max_bin=256, tree_method="hist", device="cuda:0",
                      n_jobs=config.n_threads, random_state=config.random_seed,
                      verbosity=0)
        classifier = XGBClassifier(objective="binary:logistic", eval_metric="logloss", **common)
        regressor = XGBRegressor(objective="reg:squarederror", **common)
    else:
        raise ValueError(f"Unsupported training backend: {backend}")
    x_train = train[INPUT_FEATURES].astype(float).replace([np.inf, -np.inf], np.nan)
    x_cal = calibration[INPUT_FEATURES].astype(float).replace([np.inf, -np.inf], np.nan)
    with threadpool_limits(limits=config.n_threads):
        classifier.fit(x_train, train.label.astype(int))
        regressor.fit(x_train, train.net_r.astype(float))
        raw = classifier.predict_proba(x_cal)[:, 1]
        calibrator = LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000, random_state=config.random_seed)
        calibrator.fit(logit(raw), calibration.label.astype(int))
        calibrated = calibrator.predict_proba(logit(raw))[:, 1]
    diagnostics = {
        "ml_backend": backend,
        "training_rows_used": len(train), "calibration_rows": len(calibration),
        "training_class_rate": float(train.label.mean()), "calibration_class_rate": float(calibration.label.mean()),
        "calibration_raw_brier": float(brier_score_loss(calibration.label, raw)),
        "calibration_fitted_brier": float(brier_score_loss(calibration.label, calibrated)),
        "calibration_fitted_log_loss": float(log_loss(calibration.label, calibrated)),
        "warning": "Calibration diagnostics are on the calibration-fitting sample, not independent test scores; candidate labels overlap.",
    }
    return classifier, regressor, calibrator, diagnostics


def train_pipeline(candles: pd.DataFrame, provenance: dict, config: ResearchConfig,
                   train_end: pd.Timestamp, calibration_end: pd.Timestamp,
                   selection_end: pd.Timestamp, output: Path,
                   *, backend: str = "hist_cpu") -> dict:
    beginning = candles.open_time.min()
    available_end = candles.open_time.max() + pd.Timedelta(minutes=1)
    if not beginning < train_end < calibration_end < selection_end <= available_end:
        raise ValueError("Require data_start < train_end < calibration_end < selection_end <= data_end")
    # Training never reads candles at or after selection_end, even if a later test was supplied.
    candles = candles.loc[candles.open_time < selection_end].copy()
    # Every requested symbol must span the same selection window; no silent late listings.
    for symbol, bars in candles.groupby("symbol"):
        if bars.open_time.max() + pd.Timedelta(minutes=1) < selection_end:
            raise ValueError(f"{symbol}: history ends before selection_end")
    candidates, market = prepare_market(candles, config)
    if candidates.empty:
        raise ValueError("No candidates: need sufficient completed history (>=200h warmup) and eligible setups")
    print("Simulating candidate outcomes with costs, stops, trailing and funding...", flush=True)
    labelled = label_candidates(candidates, market, config)
    if labelled.empty:
        raise ValueError("No fully observed labels")
    train = purged_window(labelled, beginning, train_end, config.embargo_minutes)
    calibration = purged_window(labelled, train_end, calibration_end, config.embargo_minutes)
    print(f"Training rows={len(train)}, calibration rows={len(calibration)}", flush=True)
    clf, reg, cal, diagnostics = fit_heads(train, calibration, config, backend)
    fingerprint_data = {"dataset_sha256": provenance.get("data_sha256"), "config": config.to_dict(),
                        "ml_backend": backend, "train_end": str(train_end), "calibration_end": str(calibration_end),
                        "selection_end": str(selection_end), "code": code_fingerprint()}
    model_id = hashlib.sha256(json.dumps(fingerprint_data, sort_keys=True).encode()).hexdigest()[:20]
    metadata = {**fingerprint_data, "model_id": model_id, "package_version": __version__,
                "code_sha256": code_fingerprint(), "sklearn_version": sklearn.__version__,
                "created_at": str(pd.Timestamp.now(tz="UTC")), "symbols": sorted(market),
                "data_provenance": provenance, "diagnostics": diagnostics,
                "strategy_names": [s.name for s in STRATEGIES],
                "live_orders_supported": False, "historical_results_are_exploratory": True,
                "max_training_label_end": str(train.label_end_time.max()),
                "min_calibration_signal_time": str(calibration.signal_time.min()),
                "max_calibration_label_end": str(calibration.label_end_time.max())}
    if backend == "xgboost_cuda":
        import xgboost
        metadata["xgboost_version"] = xgboost.__version__
        metadata["training_device"] = "cuda:0"
        metadata["gpu_training_reproducibility"] = "XGBoost CUDA histogram training may be nondeterministic."
    else:
        metadata["training_device"] = "cpu"
    model = TrainedGate(clf, reg, cal, config, list(INPUT_FEATURES), metadata,
                        config.minimum_probability, False)
    scored = model.score(candidates)
    selection_start = calibration_end + pd.Timedelta(minutes=config.embargo_minutes)
    if pd.Timestamp(metadata["max_calibration_label_end"]) >= selection_start:
        raise ValueError("Calibration/selection overlap")
    # Small preregistered grid; selection is not a pristine test.
    thresholds = sorted(set([config.minimum_probability] +
                            [p for p in (.40, .45, .50, .55, .60, .65, .70, .75, .80)
                             if p >= config.minimum_probability]))
    results, eligible = [], []
    for threshold in thresholds:
        base, _, _ = evaluate(scored, market, config, selection_start, selection_end, threshold)
        stress, _, _ = evaluate(scored, market, config, selection_start, selection_end, threshold, stress=True)
        passed, failures = promotion_gate(base, stress, config)
        row = {"threshold": threshold, "base": base, "stress": stress,
               "gate_passed": passed, "failures": failures}
        results.append(row)
        if passed:
            eligible.append(row)
    # Prefer broader support, not the prettiest small-sample win rate.
    if eligible:
        chosen = min(eligible, key=lambda r: (
            r["base"]["max_drawdown"], -r["base"]["mean_net_return"],
            abs(r["base"]["win_rate"] - config.target_win_rate), -r["base"]["trades"]))
        model.threshold, model.research_gate_passed = chosen["threshold"], True
    else:
        chosen = max(results, key=lambda r: (
            r["base"].get("mean_net_return") if r["base"].get("mean_net_return") is not None else -1,
            -r["base"]["max_drawdown"], r["base"]["trades"]))
    baseline_rows = candidates.copy()
    baseline_rows["probability"], baseline_rows["expected_r"] = 1.0, 1.0
    baseline, _, _ = evaluate(baseline_rows, market, config, selection_start, selection_end, 0)
    report = {"status": "research_gate_passed_not_live_approved" if eligible else "target_not_demonstrated",
              "model_id": model_id, "trained": True, "market": config.market,
              "objectives": {"min_net_ev_per_trade": config.min_net_ev_per_trade,
                             "min_payoff_ratio": config.min_payoff_ratio,
                             "preferred_win_rate": config.target_win_rate,
                             "win_rate_is_hard_gate": False,
                             "drawdown_ceiling": config.max_drawdown,
                             "drawdown_selection": "minimize among candidates meeting economic and sample gates"},
              "actual_historical_training": provenance.get("source", "user-provided data; authenticity not verified here"),
              "selected_threshold": model.threshold, "selected_result": chosen,
              "threshold_search": results, "rules_without_ml_baseline": baseline,
              "metadata": metadata,
              "interpretation": "The selector was chosen on selection data. Only a later, untouched test can support generalization; no performance guarantee."}
    output.mkdir(parents=True, exist_ok=True)
    model.save(output / "model.joblib")
    (output / "training_report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    environment = {"numpy": np.__version__, "pandas": pd.__version__,
                   "scikit-learn": sklearn.__version__, "joblib": joblib.__version__,
                   "ml_backend": backend, "training_device": metadata["training_device"]}
    if backend == "xgboost_cuda":
        import xgboost
        environment["xgboost"] = xgboost.__version__
        environment["xgboost_build_info"] = xgboost.build_info()
    (output / "environment.json").write_text(json.dumps(environment, indent=2, allow_nan=False), encoding="utf-8")
    return report


def latest_signals(candles: pd.DataFrame, model: TrainedGate, diagnostic: bool = False) -> list[dict]:
    allowed = set(model.metadata["symbols"])
    unknown = set(candles.symbol) - allowed
    if unknown:
        raise ValueError(f"Unvalidated symbols for this model: {sorted(unknown)}")
    candidates, _ = prepare_market(candles, model.config)
    result = []
    for symbol, bars in candles.groupby("symbol", sort=True):
        latest = bars.open_time.max() + pd.Timedelta(minutes=1)
        subset = candidates.loc[(candidates.symbol == symbol) & (candidates.signal_time == latest)]
        scored = model.score(subset)
        available = scored.loc[(scored.probability >= model.threshold) &
                               (scored.expected_r >= model.config.min_expected_r)]
        common = {"symbol": symbol, "market": model.config.market, "time": str(latest),
                  "model_id": model.metadata["model_id"], "offline_inference": True,
                  "stale_for_realtime": bool(pd.Timestamp.now(tz="UTC") - latest > pd.Timedelta(minutes=2)),
                  "research_gate_passed": model.research_gate_passed, "real_order_sent": False}
        if available.empty or (not model.research_gate_passed and not diagnostic):
            result.append({**common, "action": "ABSTAIN", "reason": "no_eligible_setup" if available.empty else "validation_target_not_demonstrated"})
            continue
        row = available.sort_values(["probability", "expected_r"], ascending=False).iloc[0]
        side, reference = int(row.side), float(bars.iloc[-1].close)
        distance = float(row.atr * row.stop_atr)
        sid = hashlib.sha256(f"{model.metadata['model_id']}|{symbol}|{latest}|{row.strategy}|{side}".encode()).hexdigest()[:24]
        result.append({**common, "action": "BUY" if side == 1 and model.config.market == "spot" else "OPEN_LONG" if side == 1 else "OPEN_SHORT",
                       "strategy": row.strategy, "signal_id": sid,
                       "probability_of_positive_net_trade": float(row.probability),
                       "expected_net_r": float(row.expected_r), "reference_price_not_fill": reference,
                       "stop_reference": reference - side * distance,
                       "take_profit_reference": reference + side * distance * row.target_r,
                       "trail_activation_r": float(row.trail_activation_r),
                       "trail_distance_r": float(row.trail_distance_r),
                       "max_hold_minutes": int(row.max_hold_minutes),
                       "diagnostic_only": not model.research_gate_passed,
                       "execution_note": "Recompute brackets from actual next fill; never execute this stale/offline snapshot directly."})
    return result
