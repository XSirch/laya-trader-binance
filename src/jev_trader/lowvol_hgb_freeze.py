"""Fit and freeze the single preregistered C18 HGB model from mature history."""

from __future__ import annotations

import hashlib
import json
import math
import pickle
import platform
from datetime import datetime, timezone
from pathlib import Path

import sklearn
import threadpoolctl
from threadpoolctl import threadpool_limits

from . import low_volatility_meta_filter_research as historical
from .binance_data import parse_archive, utc_ms
from .broad_data import CACHE
from .broad_prediction import FIELDS
from .broad_research import DAY_MS, PERIODS, features
from .cli import ROOT
from .derivatives_data import parse_funding


PROTOCOL = ROOT / "research/docs/CICLO18_META_FILTRO_HGB_BAIXA_VOLATILIDADE_FORWARD_PROTOCOLO_2026-09-29.md"
OUTPUT = ROOT / "research/results/cycle18_lowvol_hgb_forward"
MODEL_DIR = OUTPUT / "model"
TRAIN_END_MS = utc_ms("2026-08-01")
LOOKBACK_MS = 104 * 7 * DAY_MS
MIN_TRAINING_EPISODES = 100
PROTOCOL_SHA256 = "8cf48c4b423ffd91026e69fbf19fc68f5da05ce4de37803bfe87181bff7778b4"
EXPECTED_INPUTS = {
    "research/docs/CICLO18_META_FILTRO_HGB_BAIXA_VOLATILIDADE_FORWARD_PROTOCOLO_2026-09-29.md": PROTOCOL_SHA256,
    "data/binance/broad/manifest.json": "bb5ca5238319ba119a2a86596203d4c9adcfce46fd113832ebf1c41a8a0fad33",
    "data/binance/broad/cohort.json": "f7716d2b673f37cecfd9779b9090b4c63681a8e4b667340e5586972a8661ed57",
    "data/binance/broad/supplements.json": "6b616a2052c2e2dcafff4777b950cbaeaa95fd2e828698befb07f69a0308160a",
    "results/broad_trade_ledger_20260927.csv": "b4eb4024531520aac41be58f9d229241b1a3392ea6d53a685531e96765f974f3",
    "results/broad_trade_target_reanalysis_20260927.json": "ece50f987518caec9d7adefdf68a9d929716425f7f38a673316fc9a9aaf93e9b",
    "results/broad_research.json": "9fa70e1fd1b486072392333decde61f110019c1d39276c517ab749d97582d3a0",
    "results/low_volatility_meta_filter_research_20260927.json": "2139c5441375e335cba442621188ec531219cacfb6d9fba7ef4b49b839b100af",
    "src/jev_trader/low_volatility_meta_filter_research.py": "f8e71887e12ae9561486343ed583d79ff87395eb87a2045ba0b7aecc14cfd690",
    "src/jev_trader/broad_prediction.py": "1348cf6c2b8a2ce011a19eff38546cf8c7204df9620781ed6af886af3ff7e358",
    "src/jev_trader/broad_research.py": "9144a4b085a71b2a6ee0a701b748fb8694e1409ee5f6a5cfd3b73c50179a154b",
    "src/jev_trader/broad_trade_reanalysis.py": "583575e3c129c8a109e6487ac19f29056f0ffb884fd61e2d4dd4e72766d01181",
    "src/jev_trader/broad_data.py": "d905e107025dcdc0bac6f0c7443ac86a9f00ed5ef5b8e99807c550fb14103a27",
    "src/jev_trader/binance_data.py": "464f3e057a119f26c9209a49135286617fc86e5a6ff15784cd641a90cb056cbf",
    "src/jev_trader/derivatives_data.py": "135e2d54fbd75c8ef43ad7bba762ca62f3e11b582a8f683ea7dba4abc08fa919",
    "src/jev_trader/market_state.py": "2234141e3892647489b4ce9af1944c6539c26c7271abef19bae03cfaf58a720f",
    "src/jev_trader/statistics.py": "c1f7e91a1472ad1ed7d540aa705c6e3eb2f34dd95d8f15adb42f3e3e99e9e426",
}
EXPECTED_SOURCE_MANIFEST_SHA256 = "11f72aa37a646cf46e7904337aced83e2aa06c052377f07c7596e0287465a05a"
EXPECTED_SOURCE_MANIFEST_ENTRIES = 4182


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _input_hashes() -> dict[str, str]:
    observed = {}
    for relative, expected in EXPECTED_INPUTS.items():
        path = ROOT / relative
        actual = _sha256(path)
        if actual != expected:
            raise ValueError(f"frozen C18 input changed: {relative}")
        observed[relative] = actual

    freeze = json.loads((ROOT / "docs/broad_candidate_freeze_2026-09-26.json").read_text(encoding="utf-8"))
    if freeze["daily_sources_sha256"] != observed["data/binance/broad/manifest.json"]:
        raise ValueError("broad daily source manifest differs from its freeze")
    broad_report = json.loads((ROOT / "results/broad_research.json").read_text(encoding="utf-8"))
    hgb_report = json.loads((ROOT / "results/low_volatility_meta_filter_research_20260927.json").read_text(encoding="utf-8"))
    if (broad_report["source_manifest_sha256"] != EXPECTED_SOURCE_MANIFEST_SHA256
            or hgb_report["source_manifest_sha256"] != EXPECTED_SOURCE_MANIFEST_SHA256):
        raise ValueError("C18 source manifest differs from the historical screening reports")
    cohort = json.loads((CACHE / "cohort.json").read_text(encoding="utf-8"))
    if cohort["selected"] != freeze["cohort"]:
        raise ValueError("C18 cohort differs from the fixed historical cohort")
    observed["docs/broad_candidate_freeze_2026-09-26.json"] = _sha256(
        ROOT / "docs/broad_candidate_freeze_2026-09-26.json")
    return observed


def _load_frozen_economic_data() -> tuple[dict, str, int]:
    """Read the already verified local feature inputs without fetching or writing."""
    cohort = json.loads((CACHE / "cohort.json").read_text(encoding="utf-8"))
    manifest = json.loads((CACHE / "manifest.json").read_text(encoding="utf-8"))
    supplements = json.loads((CACHE / "supplements.json").read_text(encoding="utf-8"))
    source_rows = manifest + supplements
    source_index = [{key: row[key] for key in ("kind", "symbol", "month", "sha256")}
                    for row in source_rows]
    if len(source_index) != EXPECTED_SOURCE_MANIFEST_ENTRIES:
        raise ValueError("historical input manifest entry count changed")
    source_manifest_hash = hashlib.sha256(json.dumps(source_index, sort_keys=True).encode("utf-8")).hexdigest()
    if source_manifest_hash != EXPECTED_SOURCE_MANIFEST_SHA256:
        raise ValueError("historical source manifest differs from the HGB study")

    symbols = cohort["selected"]
    klines: dict[str, list] = {symbol: [] for symbol in symbols}
    funding: dict[str, list] = {symbol: [] for symbol in symbols}
    rows_read = 0

    def verified_path(row: dict) -> Path:
        path = Path(row["path"]).resolve()
        if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
            raise ValueError("historical input path is missing or outside the workspace")
        if _sha256(path) != row["sha256"]:
            raise ValueError(f"historical input file hash changed: {path}")
        return path

    for row in manifest:
        if row["kind"] not in ("klines", "fundingRate"):
            continue
        if row["symbol"] not in klines:
            raise ValueError("historical source manifest contains an unexpected symbol")
        path = verified_path(row)
        rows_read += 1
        if row["kind"] == "klines":
            klines[row["symbol"]].extend(parse_archive(path, max_gap_hours=24 * 40))
        else:
            funding[row["symbol"]].extend(parse_funding(path))

    for row in supplements:
        if row["kind"] != "klines":
            continue
        if row["symbol"] not in klines:
            raise ValueError("historical supplement contains an unexpected symbol")
        path = verified_path(row)
        rows_read += 1
        klines[row["symbol"]].extend(parse_archive(path))

    for symbol in symbols:
        trade_lookup = {bar.open_ms: bar for bar in klines[symbol]
                        if bar.volume > 0 and bar.trades > 0}
        traded = sorted(trade_lookup.values(), key=lambda bar: bar.open_ms)
        if not traded or any(current.open_ms - prior.open_ms != DAY_MS
                             for prior, current in zip(traded, traded[1:])):
            raise ValueError(f"frozen daily trading calendar is incomplete: {symbol}")
        klines[symbol] = traded
        funding[symbol].sort(key=lambda event: event.timestamp_ms)
        if (not funding[symbol]
                or len({event.timestamp_ms for event in funding[symbol]}) != len(funding[symbol])):
            raise ValueError(f"frozen funding history is empty or duplicated: {symbol}")

    return {"klines": klines, "fundingRate": funding}, source_manifest_hash, rows_read


def train_and_freeze() -> dict:
    """Train once; fail closed if the output already exists or data changed."""
    if OUTPUT.exists():
        raise FileExistsError(f"C18 output exists; refusing to overwrite: {OUTPUT}")
    input_hashes = _input_hashes()

    data, source_manifest_hash, rows_read = _load_frozen_economic_data()
    states = features(data)
    complete, dropped = historical._training_rows(states, PERIODS)
    start_ms = TRAIN_END_MS - LOOKBACK_MS
    history = [row for row in complete
               if start_ms <= row["entry_ms"] < TRAIN_END_MS and row["exit_ms"] < TRAIN_END_MS]
    history.sort(key=lambda row: (row["entry_ms"], row["symbol"], row["direction"]))

    labels = [row["label_win"] for row in history]
    classes = sorted(set(labels))
    if len(history) < MIN_TRAINING_EPISODES or classes != [0, 1]:
        raise ValueError("C18 static fit lacks 100 mature episodes or both label classes")
    if (any(not math.isfinite(value) for row in history
            for value in historical._x({**row["features"], "direction": row["direction"]}))
            or any(not math.isfinite(row["net_return_pct"]) for row in history)):
        raise ValueError("non-finite C18 training feature")

    with threadpool_limits(limits=1):
        model = historical._fit_model(history)
    if model is None or list(model.classes_) != [0, 1]:
        raise ValueError("frozen historical HGB fit did not produce both classes")

    OUTPUT.mkdir(parents=True, exist_ok=False)
    MODEL_DIR.mkdir()
    model_path = MODEL_DIR / "model.pkl"
    with model_path.open("xb") as handle:
        pickle.dump(model, handle, protocol=pickle.HIGHEST_PROTOCOL)
        handle.flush()

    model_hash = _sha256(model_path)
    result = {
        "schema_version": 1,
        "experiment_id": "C18-lowvol-hgb-forward-static-2026-09-29",
        "status": "static_model_frozen_before_forward_inference",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "market": "Binance USD-M",
        "base_rule": "low_volatility30_betahedged",
        "training": {
            "mode": "one static fit; no prospective refits",
            "entry_start_inclusive_ms": start_ms,
            "entry_start_inclusive_utc": datetime.fromtimestamp(start_ms / 1000, timezone.utc).isoformat(),
            "outcome_end_exclusive_ms": TRAIN_END_MS,
            "outcome_end_exclusive_utc": datetime.fromtimestamp(TRAIN_END_MS / 1000, timezone.utc).isoformat(),
            "mature_episode_count": len(history),
            "class_counts": {str(label): labels.count(label) for label in classes},
            "first_entry_ms": min(row["entry_ms"] for row in history),
            "latest_entry_ms": max(row["entry_ms"] for row in history),
            "latest_exit_ms": max(row["exit_ms"] for row in history),
            "labels": "net episode return > 0 after observed USD-M funding and historical 0.15% per-side stress cost",
            "minimum_examples": MIN_TRAINING_EPISODES,
            "dropped_rows": dropped,
        },
        "features": [*FIELDS, "direction"],
        "model": {
            "type": "HistGradientBoostingClassifier",
            "parameters": {
                "max_iter": 100, "learning_rate": 0.05, "max_leaf_nodes": 7,
                "min_samples_leaf": 15, "l2_regularization": 2.0,
                "early_stopping": False, "random_state": 2026,
            },
            "prediction_threshold": 0.70,
            "compute": "CPU",
            "fit_thread_limit": 1,
            "gpu_training_performed": False,
        },
        "model_path": str(model_path.relative_to(ROOT)).replace("\\", "/"),
        "model_sha256": model_hash,
        "input_sha256": input_hashes,
        "source_archive_manifest_sha256": source_manifest_hash,
        "source_archive_manifest_entries": EXPECTED_SOURCE_MANIFEST_ENTRIES,
        "source_archive_files_verified_for_features": rows_read,
        "historical_input_loading": {"network_calls": False, "shared_cache_writes": False,
                                     "monthly_klines_and_funding_plus_cached_kline_supplements_only": True},
        "python_version": platform.python_version(),
        "scikit_learn_version": sklearn.__version__,
        "threadpoolctl_version": threadpoolctl.__version__,
        "prospective_scores_computed": False,
        "forward_market_observations_collected": False,
        "real_orders_sent": False,
        "orders_enabled": False,
    }
    metadata_path = OUTPUT / "model_training.json"
    with metadata_path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
        handle.flush()
    print(json.dumps({"status": result["status"], "training_episodes": len(history),
                      "class_counts": result["training"]["class_counts"],
                      "model_sha256": model_hash, "metadata": str(metadata_path),
                      "gpu_training_performed": False, "orders_enabled": False}, indent=2))
    return result


if __name__ == "__main__":
    train_and_freeze()
