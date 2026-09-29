from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import joblib
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "research/results/cycle02_multiframe_corrected_2026-09-28/research.json"
OUTPUT = ROOT / "research/results/cycle02_corrected_feature_diagnostics_2026-09-28"
PROTOCOL = "research/docs/CICLO02_FEATURE_DIAGNOSTICS_CORRIGIDO_PROTOCOLO.md"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_config_values(value: object, key: str, found: list[str]) -> None:
    if isinstance(value, dict):
        for item_key, item_value in value.items():
            if item_key == key and item_value not in (None, ""):
                found.append(str(item_value))
            collect_config_values(item_value, key, found)
    elif isinstance(value, list):
        for item in value:
            collect_config_values(item, key, found)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-report", type=Path, default=SOURCE)
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--protocol", default=PROTOCOL)
    args = parser.parse_args()

    source_path = args.source_report.resolve()
    output_path = args.output.resolve()
    source_sha256 = sha256(source_path)
    if args.expected_source_sha256 and source_sha256 != args.expected_source_sha256:
        raise RuntimeError("Source report hash differs from the preregistered hash.")
    if output_path.exists() and (
        not output_path.is_dir() or any(output_path.iterdir())
    ):
        raise FileExistsError(f"Refusing to overwrite existing feature diagnostic output: {output_path}")
    report = json.loads(source_path.read_text(encoding="utf-8"))
    if report.get("invalidated"):
        raise RuntimeError("Source models were invalidated; do not interpret their feature gain.")
    if report.get("correction_protocol") != "research/docs/CICLO02_CORRECAO_SAIDAS_PROTOCOLO.md":
        raise RuntimeError("Source report is not the registered corrected-exit replay.")
    preflight = report.get("exit_mode_label_preflight", [])
    if len(preflight) != 8 or any(row.get("distinct_label_hashes") != 3 for row in preflight):
        raise RuntimeError("Corrected source is missing distinct-label preflight for all eight groups.")
    models = [row for row in report["models"] if row.get("backend") == "xgboost_cuda"]
    if len(models) != 24:
        raise RuntimeError(f"Expected 24 frozen XGBoost models; found {len(models)}")
    if output_path.exists() and any(output_path.iterdir()):
        raise FileExistsError(f"Refusing to overwrite nonempty output: {output_path}")

    feature_rows: list[dict] = []
    model_rows: list[dict] = []
    for model in models:
        model_path = ROOT / model["model_path"]
        if not model_path.is_file() or sha256(model_path) != model["model_sha256"]:
            raise RuntimeError(f"Frozen corrected model hash mismatch: {model_path}")
        artifact = joblib.load(model_path)
        booster = artifact["classifier"].get_booster()
        gains = booster.get_score(importance_type="gain")
        features = list(artifact["features"])
        total_gain = sum(float(gains.get(name, 0.0)) for name in features)
        ranked = (sorted(features, key=lambda name: (-float(gains.get(name, 0.0)), name))
                  if total_gain > 0 else [])
        rank_by_feature = ({name: index + 1 for index, name in enumerate(ranked)}
                           if ranked else {name: 1000 for name in features})
        for name in features:
            gain = float(gains.get(name, 0.0))
            feature_rows.append({
                "variant_id": model["variant_id"],
                "market": model["market"],
                "family": model["family"],
                "horizon": model["horizon"],
                "exit_plan": model["exit_plan"],
                "exit_mode": model["exit_mode"],
                "feature": name,
                "gain": gain,
                "gain_share": gain / total_gain if total_gain > 0 else 0.0,
                "rank": rank_by_feature[name],
                "training_device": model.get("training_device"),
                "model_sha256": model["model_sha256"],
            })
        config = json.loads(booster.save_config())
        devices: list[str] = []
        tree_methods: list[str] = []
        collect_config_values(config, "device", devices)
        collect_config_values(config, "tree_method", tree_methods)
        model_rows.append({
            "variant_id": model["variant_id"],
            "market": model["market"],
            "family": model["family"],
            "horizon": model["horizon"],
            "exit_plan": model["exit_plan"],
            "exit_mode": model["exit_mode"],
            "classifier_has_feature_splits": total_gain > 0,
            "training_device_recorded": model.get("training_device"),
            "booster_device_config": sorted(set(devices)),
            "tree_method_config": sorted(set(tree_methods)),
            "model_sha256": model["model_sha256"],
        })

    output_path.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(feature_rows)
    frame.to_csv(output_path / "xgb_gain_by_model.csv", index=False,
                 encoding="utf-8", lineterminator="\n")
    summary = (frame.groupby(["market", "family", "horizon", "feature"], as_index=False)
               .agg(models=("variant_id", "nunique"),
                    exits=("exit_mode", "nunique"),
                    mean_gain_share=("gain_share", "mean"),
                    median_rank=("rank", "median"),
                    top3_count=("rank", lambda values: int((values <= 3).sum()))))
    summary = summary.sort_values(["market", "family", "horizon",
                                   "mean_gain_share", "median_rank"],
                                  ascending=[True, True, True, False, True])
    summary.to_csv(output_path / "xgb_gain_pattern_summary.csv", index=False,
                   encoding="utf-8", lineterminator="\n")
    try:
        import xgboost
        xgboost_version = xgboost.__version__
    except ImportError:
        xgboost_version = None
    device_path = output_path / "xgb_device_config.json"
    device_path.write_text(
        json.dumps({"source_report": str(source_path.relative_to(ROOT)).replace("\\", "/"),
                    "source_report_sha256": source_sha256,
                    "source_model_sha256s": [row["model_sha256"] for row in models],
                    "protocol": args.protocol,
                    "protocol_sha256": sha256(ROOT / args.protocol),
                    "diagnostic_script": str(Path(__file__).resolve().relative_to(ROOT)).replace("\\", "/"),
                    "diagnostic_script_sha256": sha256(Path(__file__).resolve()),
                    "xgboost_version": xgboost_version,
                    "models": model_rows,
                    "training_performed": False,
                    "performance_evaluation_performed": False,
                    "threshold_selection_performed": False,
                    "live_orders_sent": False,
                    "interpretation": "Tree gain is a descriptive in-sample split statistic, not causal evidence or a feature ablation."},
                   indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8")
    summary_path = output_path / "xgb_gain_pattern_summary.csv"
    print(json.dumps({"models": len(model_rows),
                      "feature_rows": len(feature_rows),
                      "groups": int(summary[["market", "family", "horizon"]].drop_duplicates().shape[0]),
                      "output": str(output_path),
                      "training_performed": False,
                      "performance_evaluation_performed": False}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
