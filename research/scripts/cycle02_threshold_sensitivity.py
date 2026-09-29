from __future__ import annotations

import hashlib
import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
ENGINE_PATH = SCRIPT_DIR / "cycle02_multiframe_research.py"
SOURCE_OUTPUT = ROOT / "research/results/cycle02_multiframe_corrected_2026-09-28"
SENSITIVITY_OUTPUT = ROOT / "research/results/cycle02_corrected_threshold_sensitivity_2026-09-28"
PROTOCOL = "research/docs/CICLO02_SENSIBILIDADE_CORRIGIDA_PROTOCOLO.md"

sys.path.insert(0, str(SCRIPT_DIR))
import cycle02_multiframe_research as engine  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-report", type=Path, default=SOURCE_OUTPUT / "research.json")
    parser.add_argument("--output", type=Path, default=SENSITIVITY_OUTPUT)
    parser.add_argument("--thresholds", default="0.05,0.10,0.15,0.20,0.25,0.30")
    parser.add_argument("--protocol", default=PROTOCOL)
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--market", choices=("spot", "usd_m"))
    args = parser.parse_args()

    source_report_path = args.source_report.resolve()
    source_output = source_report_path.parent
    sensitivity_output = args.output.resolve()
    thresholds = tuple(round(float(value.strip()), 2)
                       for value in args.thresholds.split(",") if value.strip())
    if not thresholds or len(set(thresholds)) != len(thresholds):
        raise SystemExit("--thresholds must be a nonempty comma-separated list of unique values")
    if any(value <= 0 or value > 1 for value in thresholds):
        raise SystemExit("Each threshold must be greater than 0 and at most 1")
    if sensitivity_output.exists() and (
        not sensitivity_output.is_dir() or any(sensitivity_output.iterdir())
    ):
        raise FileExistsError(f"Refusing to overwrite existing sensitivity output: {sensitivity_output}")
    source_report = json.loads(source_report_path.read_text(encoding="utf-8"))
    source_report_sha256 = sha256(source_report_path)
    if args.expected_source_sha256 and source_report_sha256 != args.expected_source_sha256:
        raise RuntimeError("Corrected source report hash differs from the preregistered hash.")
    if source_report.get("invalidated"):
        raise RuntimeError("Source models were invalidated; register and point to a corrected run before reuse.")
    if source_report.get("correction_protocol") != "research/docs/CICLO02_CORRECAO_SAIDAS_PROTOCOLO.md":
        raise RuntimeError("Source report is not the registered corrected-exit replay.")
    preflight = source_report.get("exit_mode_label_preflight", [])
    if len(preflight) != 8 or any(row.get("distinct_label_hashes") != 3 for row in preflight):
        raise RuntimeError("Corrected source is missing distinct-label preflight for all eight groups.")
    source_models = [row for row in source_report["models"] if row.get("backend")]
    if len(source_models) != 48:
        raise RuntimeError(f"Expected 48 fitted backend rows; found {len(source_models)}")
    model_by_key = {}
    expected_label_hashes = {}
    for preflight_row in preflight:
        for mode, label_hash in preflight_row["label_hashes"].items():
            variant = (f"{preflight_row['market'].upper()}-"
                       f"{preflight_row['family'].upper()}-"
                       f"{preflight_row['horizon'].upper()}-{mode.upper()}")
            expected_label_hashes[variant] = label_hash
    for row in source_models:
        model_by_key[(row["variant_id"], row["backend"])] = row
        if row.get("candidate_labels_sha256") != expected_label_hashes.get(row["variant_id"]):
            raise RuntimeError(f"Model/label provenance mismatch: {row['variant_id']}")
    if len(expected_label_hashes) != 24 or len(model_by_key) != 48:
        raise RuntimeError(f"Expected 24 corrected label sets; found {len(expected_label_hashes)}")
    for row in source_models:
        model_path = ROOT / row["model_path"]
        if not model_path.is_file() or sha256(model_path) != row["model_sha256"]:
            raise RuntimeError(f"Frozen model hash mismatch: {model_path}")

    engine.THRESHOLDS = thresholds
    engine.OUTPUT = sensitivity_output

    original_apply_labels = engine.apply_labels

    def reuse_labels(candidates: Any, arrays: Any, configs: dict[str, dict],
                     exit_mode: str, max_hold: int, ema_by_symbol: Any,
                     *, smoke_limit: int | None = None) -> Any:
        if smoke_limit is not None:
            return original_apply_labels(candidates, arrays, configs, exit_mode,
                                         max_hold, ema_by_symbol,
                                         smoke_limit=smoke_limit)
        market = next(iter(configs))
        family = str(candidates.family.iloc[0])
        horizon = "6h" if max_hold == 360 else "24h"
        exit_name = exit_mode
        if exit_name not in {name for name, _ in engine.EXITS}:
            raise RuntimeError(f"Unknown canonical exit mode in corrected replay: {exit_name}")
        variant_id = f"{market.upper()}-{family.upper()}-{horizon.upper()}-{exit_name.upper()}"
        labels_path = source_output / variant_id / "candidate_labels.csv"
        expected_hash = expected_label_hashes.get(variant_id)
        if expected_hash is None or sha256(labels_path) != expected_hash:
            raise RuntimeError(f"Corrected source label hash mismatch: {labels_path}")
        labels = engine.pd.read_csv(labels_path)
        for column in ("signal_time", "entry_time", "label_end_time"):
            labels[column] = engine.pd.to_datetime(labels[column], utc=True)
        candidate_ids = set(candidates.candidate_id.astype(str))
        if labels.candidate_id.duplicated().any():
            raise RuntimeError(f"Duplicate candidate labels in {labels_path}")
        if not labels.candidate_id.astype(str).isin(candidate_ids).all():
            raise RuntimeError(f"Candidate label mismatch in {labels_path}")
        return labels

    engine.apply_labels = reuse_labels

    def reuse_fitted_model(train: Any, calibration: Any, backend: str) -> tuple[Any, Any, Any, dict]:
        row = next(fit_rows, None)
        if row is None or row["backend"] != backend:
            raise RuntimeError(f"Frozen model order/backend mismatch for {backend}")
        artifact = engine.joblib.load(ROOT / row["model_path"])
        return (artifact["classifier"], artifact["regressor"],
                artifact["calibrator"], row["train_diagnostics"])

    engine.fit_filter = reuse_fitted_model

    requested_market = args.market
    expected_rows = [row for row in source_models
                     if requested_market is None or row["market"] == requested_market]
    expected_count = 24 if requested_market is not None else 48
    if len(expected_rows) != expected_count:
        raise RuntimeError(f"Unexpected frozen model count: expected {expected_count}, found {len(expected_rows)}")
    fit_rows = iter(expected_rows)

    original_stdout = sys.stdout

    class ReuseLog:
        def write(self, value: str) -> int:
            value = value.replace("TRAIN_START ", "MODEL_REUSE_START ")
            value = value.replace("TRAIN_DONE ", "MODEL_REUSE_DONE ")
            return original_stdout.write(value)

        def flush(self) -> None:
            original_stdout.flush()

        @property
        def encoding(self) -> str:
            return original_stdout.encoding

    sys.stdout = ReuseLog()
    original_argv = sys.argv
    try:
        sys.argv = [original_argv[0]]
        if requested_market is not None:
            sys.argv.extend(["--market", requested_market])
        engine.main()
    finally:
        sys.stdout = original_stdout
        sys.argv = original_argv

    unused = next(fit_rows, None)
    if unused is not None:
        raise RuntimeError(f"Not all expected frozen models were reused; next={unused['variant_id']}")

    result_path = sensitivity_output / "research.json"
    report = json.loads(result_path.read_text(encoding="utf-8"))
    report["status"] = "posthoc_historical_threshold_sensitivity_not_prospective"
    report["pre_registration"] = args.protocol
    report["analysis_type"] = "posthoc_threshold_sensitivity_using_frozen_models"
    report["independent_validation"] = False
    report["training_performed"] = False
    report["gpu_training_performed"] = False
    report["source_gpu_training_performed"] = bool(source_report["gpu_training_performed"])
    report["source_research_report"] = str(source_report_path.relative_to(ROOT)).replace("\\", "/")
    report["source_research_report_sha256"] = source_report_sha256
    report["source_engine_script"] = str(ENGINE_PATH.relative_to(ROOT)).replace("\\", "/")
    report["source_engine_script_sha256"] = sha256(ENGINE_PATH)
    report["replay_script"] = str(Path(__file__).resolve().relative_to(ROOT)).replace("\\", "/")
    report["replay_script_sha256"] = sha256(Path(__file__).resolve())
    report["source_label_hashes"] = expected_label_hashes
    report["models_reused_without_refit"] = True
    for row in report["models"]:
        if row.get("backend"):
            original = model_by_key[(row["variant_id"], row["backend"])]
            row["training_performed"] = False
            row["model_reused_without_refit"] = True
            row["source_model_path"] = original["model_path"]
            row["source_model_sha256"] = original["model_sha256"]
            row["source_candidate_labels_path"] = original["candidate_labels_path"]
            row["source_candidate_labels_sha256"] = original["candidate_labels_sha256"]
    result_path.write_text(json.dumps(report, indent=2, ensure_ascii=False,
                                      allow_nan=False, default=str) + "\n",
                           encoding="utf-8")
    print(json.dumps({"status": report["status"],
                      "models_reused": len(source_models),
                      "threshold_grid": report["threshold_grid"],
                      "training_performed": report["training_performed"],
                      "output": str(result_path)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
