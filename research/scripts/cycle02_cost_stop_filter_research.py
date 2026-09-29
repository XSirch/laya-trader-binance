from __future__ import annotations

import argparse
import gc
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
ENGINE_PATH = SCRIPT_DIR / "cycle02_multiframe_research.py"
SOURCE_REPORT = ROOT / "research/results/cycle02_multiframe_corrected_2026-09-28/research.json"
OUTPUT = ROOT / "research/results/cycle02_cost_stop_filter_2026-09-28"
PROTOCOL = "research/docs/CICLO02_CUSTO_STOP_FILTER_PROTOCOLO.md"
MAX_COST_TO_STOP = 0.25

sys.path.insert(0, str(SCRIPT_DIR))
import cycle02_multiframe_research as engine  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def add_cost_to_stop_ratio(candidates: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    stop_fraction = pd.to_numeric(candidates["stop_fraction_signal"], errors="coerce")
    if stop_fraction.isna().any() or (stop_fraction <= 0).any():
        raise ValueError("Every candidate needs a finite positive causal stop fraction")
    round_trip_cost_rate = 2 * (float(config["fee_bps"]) + float(config["slippage_bps"])) / 10_000
    result = candidates.copy()
    result["round_trip_cost_rate_base"] = round_trip_cost_rate
    result["cost_to_stop_ratio"] = round_trip_cost_rate / stop_fraction.astype(float)
    result["cost_filter_pass"] = result["cost_to_stop_ratio"] <= MAX_COST_TO_STOP
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-report", type=Path, default=SOURCE_REPORT)
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--protocol", default=PROTOCOL)
    args = parser.parse_args()

    source_path = args.source_report.resolve()
    output_path = args.output.resolve()
    if output_path.exists() and (
        not output_path.is_dir() or any(output_path.iterdir())
    ):
        raise FileExistsError(f"Refusing to overwrite existing filter output: {output_path}")
    source_hash = sha256(source_path)
    if args.expected_source_sha256 and source_hash != args.expected_source_sha256:
        raise RuntimeError("Corrected source report hash differs from the preregistered hash.")
    source_report = json.loads(source_path.read_text(encoding="utf-8"))
    if source_report.get("invalidated"):
        raise RuntimeError("The source report is invalidated.")
    if source_report.get("correction_protocol") != "research/docs/CICLO02_CORRECAO_SAIDAS_PROTOCOLO.md":
        raise RuntimeError("The source report is not the corrected-exit replay.")
    preflight = source_report.get("exit_mode_label_preflight", [])
    if len(preflight) != 8 or any(item.get("distinct_label_hashes") != 3 for item in preflight):
        raise RuntimeError("All eight corrected label groups must have three distinct exits.")
    for group in preflight:
        for mode, expected_hash in group["label_hashes"].items():
            variant = (f"{group['market'].upper()}-{group['family'].upper()}-"
                       f"{group['horizon'].upper()}-{mode.upper()}")
            labels_path = source_path.parent / variant / "candidate_labels.csv"
            if not labels_path.is_file() or sha256(labels_path) != expected_hash:
                raise RuntimeError(f"Corrected label hash mismatch: {labels_path}")
    rule_baselines = {
        row["variant_id"]: row
        for row in source_report["models"]
        if not row.get("backend") and row.get("rule_baseline")
    }
    if len(rule_baselines) != 24:
        raise RuntimeError(f"Expected 24 corrected rule baselines, found {len(rule_baselines)}")

    output_path.mkdir(parents=True, exist_ok=True)
    report_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    input_records: list[dict[str, Any]] = []
    aggregate_candidates: dict[str, dict[str, int]] = {}
    round_trip_cost_rates: dict[str, float] = {}
    start = engine.CALIBRATION_END + pd.Timedelta(minutes=engine.EMBARGO_MINUTES)
    end = engine.SELECTION_END

    for market in ("spot", "usd_m"):
        folder = "spot_btc_eth_1m" if market == "spot" else "usdm_btc_eth_1m"
        dataset_path = ROOT / "research/data" / folder
        candles, provenance = engine.load_dataset(dataset_path, market)
        candles = candles.loc[candles.open_time < engine.DATA_END].copy()
        expected_data = next(row for row in source_report["data"] if row["market"] == market)
        if provenance["data_sha256"] != expected_data["dataset_sha256"]:
            raise RuntimeError(f"Dataset hash changed for {market}")
        if sha256(dataset_path / "dataset.json") != expected_data["manifest_sha256"]:
            raise RuntimeError(f"Dataset manifest hash changed for {market}")
        if not provenance.get("verified", False):
            raise RuntimeError(f"Dataset provenance is not verified for {market}")

        config = engine.gate_config(market)
        round_trip_cost_rates[market] = (
            2 * (float(config["fee_bps"]) + float(config["slippage_bps"])) / 10_000
        )
        arrays: dict[str, Any] = {}
        ema_by_symbol: dict[str, dict[pd.Timestamp, float]] = {}
        candidate_frames = []
        for symbol, grouped in candles.groupby("symbol", sort=True):
            bars = grouped.reset_index(drop=True)
            arrays[symbol] = engine.MarketArrays(bars)
            feature_frame, ema_map = engine.market_features(bars)
            ema_by_symbol[symbol] = ema_map
            generated = engine.generate_candidates(
                feature_frame, symbol, market, pd.DatetimeIndex(bars.open_time)
            )
            candidate_frames.append(generated)
            del feature_frame, generated, bars

        candidates = pd.concat(candidate_frames, ignore_index=True)
        candidates = candidates.sort_values(
            ["signal_time", "symbol", "family", "side"]
        ).reset_index(drop=True)
        candidates["candidate_id"] = candidates.candidate_id.astype(str)
        candidates = add_cost_to_stop_ratio(candidates, config)
        expected_counts = {
            variant["family"]: variant["candidate_count"]
            for variant in source_report["models"]
            if variant.get("market") == market and not variant.get("backend")
        }
        actual_counts = candidates.groupby("family").size().to_dict()
        for family, expected in expected_counts.items():
            if int(actual_counts.get(family, 0)) != int(expected):
                raise RuntimeError(
                    f"Candidate count mismatch for {market}/{family}: "
                    f"expected {expected}, found {actual_counts.get(family, 0)}"
                )
        filtered = candidates.loc[candidates.cost_filter_pass].copy()
        aggregate_candidates[market] = {
            "all_candidates": len(candidates),
            "eligible_candidates": len(filtered),
            "excluded_candidates": len(candidates) - len(filtered),
            "by_family": {
                family: {
                    "all_candidates": int(actual_counts.get(family, 0)),
                    "eligible_candidates": int(filtered.loc[filtered.family == family].shape[0]),
                }
                for family in engine.FAMILIES
            },
        }
        input_records.append({
            "market": market,
            "dataset_path": str(dataset_path.relative_to(ROOT)).replace("\\", "/"),
            "dataset_sha256": provenance["data_sha256"],
            "manifest_sha256": sha256(dataset_path / "dataset.json"),
            "rows": len(candles),
            "symbols": sorted(candles.symbol.unique()),
            "verified": bool(provenance.get("verified", False)),
        })
        for family in engine.FAMILIES:
            pool = filtered.loc[filtered.family == family].copy()
            pool["probability"] = 1.0
            pool["expected_r"] = 1.0
            for horizon_name, max_hold in engine.HORIZONS:
                for exit_mode, exit_plan in engine.EXITS:
                    variant_id = f"{market.upper()}-{family.upper()}-{horizon_name.upper()}-{exit_mode.upper()}"
                    cache: dict[tuple[str, bool], Any] = {}
                    base, base_trades = engine.evaluate_portfolio(
                        pool, arrays, {market: config},
                        exit_mode, max_hold, ema_by_symbol, start, end,
                        stress=False, outcome_cache=cache,
                    )
                    stress, stress_trades = engine.evaluate_portfolio(
                        pool, arrays, {market: config},
                        exit_mode, max_hold, ema_by_symbol, start, end,
                        stress=True, outcome_cache=cache,
                    )
                    passed, failures = engine.passes(base, stress)
                    baseline = rule_baselines[variant_id]["rule_baseline"]
                    report_rows.append({
                        "variant_id": variant_id,
                        "market": market,
                        "family": family,
                        "horizon": horizon_name,
                        "max_hold_minutes": max_hold,
                        "exit_mode": exit_mode,
                        "exit_plan": exit_plan,
                        "candidate_count_before_filter": int(actual_counts.get(family, 0)),
                        "candidate_count_after_filter": len(pool),
                        "selection_start": start.isoformat(),
                        "selection_end_exclusive": end.isoformat(),
                        "baseline_without_filter": baseline,
                        "filtered_base": base,
                        "filtered_stress": stress,
                        "base_ev_change_vs_baseline": (
                            base["mean_net_return"] - baseline["base"]["mean_net_return"]
                            if base["mean_net_return"] is not None
                            and baseline["base"]["mean_net_return"] is not None else None
                        ),
                        "base_trade_count_change_vs_baseline": (
                            base["trades"] - baseline["base"]["trades"]
                        ),
                        "stress_ev_change_vs_baseline": (
                            stress["mean_net_return"] - baseline["stress"]["mean_net_return"]
                            if stress["mean_net_return"] is not None
                            and baseline["stress"]["mean_net_return"] is not None else None
                        ),
                        "gate_passed": passed,
                        "gate_failures": failures,
                    })
                    for scenario, trades in (("base", base_trades), ("stress", stress_trades)):
                        for trade in trades:
                            trade_rows.append({
                                "variant_id": variant_id,
                                "scenario": scenario,
                                "cost_to_stop_ratio": float(
                                    pool.loc[pool.candidate_id == trade["candidate_id"],
                                             "cost_to_stop_ratio"].iloc[0]
                                ),
                                **trade,
                            })
            del pool
        del candidates, filtered, arrays, ema_by_symbol, candles
        gc.collect()

    trades_path = output_path / "cost_stop_filter_trades.csv"
    pd.DataFrame(trade_rows).to_csv(
        trades_path, index=False, encoding="utf-8", lineterminator="\n"
    )
    report = {
        "created_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "status": "posthoc_historical_cost_stop_filter_not_prospective",
        "pre_registration": args.protocol,
        "protocol_sha256": sha256(ROOT / args.protocol),
        "source_report": str(source_path.relative_to(ROOT)).replace("\\", "/"),
        "source_report_sha256": source_hash,
        "engine_script": str(ENGINE_PATH.relative_to(ROOT)).replace("\\", "/"),
        "engine_script_sha256": sha256(ENGINE_PATH),
        "research_script": str(Path(__file__).resolve().relative_to(ROOT)).replace("\\", "/"),
        "research_script_sha256": sha256(Path(__file__).resolve()),
        "markets": ["spot", "usd_m"],
        "symbols": ["BTCUSDT", "ETHUSDT"],
        "data": input_records,
        "filter": {
            "formula": "2 * (fee_bps_per_side + slippage_bps_per_side) / 10000 / stop_fraction_signal",
            "stop_fraction_signal": "ATR_15m_14 / completed_signal_close_15m",
            "maximum_cost_to_stop_ratio": MAX_COST_TO_STOP,
            "base_round_trip_cost_rate": round_trip_cost_rates,
            "stress_changes_filter": False,
            "causal_at_signal": True,
        },
        "candidate_coverage": aggregate_candidates,
        "variants": report_rows,
        "variant_count": len(report_rows),
        "gate_pass_count": sum(bool(row["gate_passed"]) for row in report_rows),
        "trade_ledger": {
            "path": str(trades_path.relative_to(ROOT)).replace("\\", "/"),
            "rows": len(trade_rows),
            "sha256": sha256(trades_path),
        },
        "training_performed": False,
        "gpu_training_performed": False,
        "real_orders_sent": False,
        "independent_validation": False,
        "costs_are_account_verified": False,
    }
    report_path = output_path / "research.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": report["status"],
        "variants": report["variant_count"],
        "gate_passes": report["gate_pass_count"],
        "training_performed": False,
        "real_orders_sent": False,
        "output": str(report_path),
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
