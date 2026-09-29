"""Descriptive path metrics for the corrected Cycle02 fixed-rule replays."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
ENGINE_PATH = SCRIPT_DIR / "cycle02_multiframe_research.py"
SOURCE_REPORT = ROOT / "research/results/cycle02_multiframe_corrected_2026-09-28/research.json"
OUTPUT = ROOT / "research/results/cycle02_path_diagnostics_2026-09-28"
PROTOCOL = "research/docs/CICLO02_PATH_DIAGNOSTICS_PROTOCOLO.md"
sys.path.insert(0, str(SCRIPT_DIR))
import cycle02_multiframe_research as engine  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def excursion_r(highs: Sequence[float], lows: Sequence[float], side: int,
                entry_price: float, stop_distance: float) -> tuple[float | None, float | None]:
    """Return gross favorable/adverse excursions in initial-stop units."""
    if side not in (-1, 1):
        raise ValueError("side must be -1 or 1")
    if not np.isfinite(stop_distance) or stop_distance <= 0:
        raise ValueError("stop_distance must be finite and positive")
    if len(highs) != len(lows):
        raise ValueError("highs and lows must have equal lengths")
    if not len(highs):
        return None, None
    high = np.asarray(highs, dtype=float)
    low = np.asarray(lows, dtype=float)
    if not np.isfinite(high).all() or not np.isfinite(low).all():
        raise ValueError("OHLC excursions must be finite")
    favorable_extreme = np.max(high) if side == 1 else np.min(low)
    adverse_extreme = np.min(low) if side == 1 else np.max(high)
    favorable = max(0.0, side * (float(favorable_extreme) - entry_price) / stop_distance)
    adverse = max(0.0, -side * (float(adverse_extreme) - entry_price) / stop_distance)
    return favorable, adverse


def median_or_none(values: pd.Series) -> float | None:
    median = values.median()
    return None if pd.isna(median) else float(median)


def path_record(variant_id: str, scenario: str, trade: dict[str, Any],
                outcome: Any, arrays: Any, candidate: dict[str, Any],
                config: dict[str, Any]) -> dict[str, Any]:
    side = int(trade["side"])
    entry_index, exit_index = int(outcome.entry_index), int(outcome.exit_index)
    entry_price = float(outcome.entry_price)
    stop_distance = abs(entry_price - float(outcome.initial_stop))
    values = arrays.values
    reason = str(outcome.exit_reason)
    ambiguous_exit_bar = reason in {"stop", "target"}

    complete_end = exit_index if ambiguous_exit_bar else exit_index + 1
    complete = range(entry_index, complete_end)
    complete_mfe, complete_mae = excursion_r(
        [values["high"][i] for i in complete],
        [values["low"][i] for i in complete], side, entry_price, stop_distance,
    )
    if ambiguous_exit_bar:
        exit_mfe, exit_mae = excursion_r(
            [values["high"][exit_index]], [values["low"][exit_index]],
            side, entry_price, stop_distance,
        )
    else:
        exit_mfe, exit_mae = None, None

    observed_mfe = [x for x in (complete_mfe, exit_mfe) if x is not None]
    observed_mae = [x for x in (complete_mae, exit_mae) if x is not None]
    fee_rate = float(config["fee_bps"]) * (2 if scenario == "stress" else 1) / 10_000
    slip_rate = float(config["slippage_bps"]) * (2 if scenario == "stress" else 1) / 10_000
    raw_entry = float(values["open"][entry_index])
    raw_exit = float(outcome.exit_price) / (1 - side * slip_rate)
    entry_slippage = abs(entry_price - raw_entry)
    exit_slippage = abs(float(outcome.exit_price) - raw_exit)
    fee_cost = float(outcome.fee_per_unit)
    friction_r = (entry_slippage + exit_slippage + fee_cost) / stop_distance
    funding_r = float(outcome.funding_per_unit) / stop_distance
    net_return = float(outcome.net_return)
    return {
        "variant_id": variant_id,
        "scenario": scenario,
        "candidate_id": str(trade["candidate_id"]),
        "symbol": str(trade["symbol"]),
        "market": str(trade["market"]),
        "family": str(trade["family"]),
        "side": side,
        "signal_time": pd.Timestamp(trade["signal_time"]).isoformat(),
        "entry_time": pd.Timestamp(trade["entry_time"]).isoformat(),
        "exit_time": pd.Timestamp(trade["exit_time"]).isoformat(),
        "duration_minutes": int(exit_index - entry_index + 1),
        "exit_reason": reason,
        "net_return": net_return,
        "pnl": float(trade["pnl"]),
        "win": net_return > 0,
        "initial_stop_distance": stop_distance,
        "complete_candle_count": max(0, complete_end - entry_index),
        "exit_bar_ambiguous": ambiguous_exit_bar,
        "mfe_complete_candles_r": complete_mfe,
        "mae_complete_candles_r": complete_mae,
        "mfe_ambiguous_exit_bar_r": exit_mfe,
        "mae_ambiguous_exit_bar_r": exit_mae,
        "mfe_including_exit_bar_r": max(observed_mfe) if observed_mfe else None,
        "mae_including_exit_bar_r": max(observed_mae) if observed_mae else None,
        "entry_slippage_over_stop_r": entry_slippage / stop_distance,
        "exit_slippage_over_stop_r": exit_slippage / stop_distance,
        "fees_over_stop_r": fee_cost / stop_distance,
        "total_estimated_friction_over_stop_r": friction_r,
        "funding_signed_over_stop_r": funding_r,
        "signal_stop_fraction": float(candidate["stop_fraction_signal"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-report", type=Path, default=SOURCE_REPORT)
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--expected-engine-sha256")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--protocol", default=PROTOCOL)
    args = parser.parse_args()

    source_path, output_path = args.source_report.resolve(), args.output.resolve()
    if output_path.exists() and (not output_path.is_dir() or any(output_path.iterdir())):
        raise FileExistsError(f"Refusing to overwrite nonempty output: {output_path}")
    source_hash, engine_hash = sha256(source_path), sha256(ENGINE_PATH)
    if args.expected_source_sha256 and source_hash != args.expected_source_sha256:
        raise RuntimeError("Corrected source report hash differs from preregistration.")
    if args.expected_engine_sha256 and engine_hash != args.expected_engine_sha256:
        raise RuntimeError("Engine hash differs from preregistration.")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if (source.get("correction_protocol")
            != "research/docs/CICLO02_CORRECAO_SAIDAS_PROTOCOLO.md"):
        raise RuntimeError("Expected the corrected-exit replay report.")
    if len(source.get("exit_mode_label_preflight", [])) != 8:
        raise RuntimeError("Expected eight corrected label groups.")
    for group in source["exit_mode_label_preflight"]:
        if group.get("distinct_label_hashes") != 3:
            raise RuntimeError("Each group must have three distinct exit labels.")
        for mode, expected in group["label_hashes"].items():
            variant = (f"{group['market'].upper()}-{group['family'].upper()}-"
                       f"{group['horizon'].upper()}-{mode.upper()}")
            labels_path = source_path.parent / variant / "candidate_labels.csv"
            if not labels_path.is_file() or sha256(labels_path) != expected:
                raise RuntimeError(f"Corrected candidate-label hash mismatch: {variant}")
    if len([row for row in source["models"] if not row.get("backend")]) != 24:
        raise RuntimeError("Expected exactly 24 corrected fixed-rule variants.")

    output_path.mkdir(parents=True, exist_ok=True)
    start = engine.CALIBRATION_END + pd.Timedelta(minutes=engine.EMBARGO_MINUTES)
    end = engine.SELECTION_END
    data_records: list[dict[str, Any]] = []
    trade_records: list[dict[str, Any]] = []
    for market in ("spot", "usd_m"):
        folder = "spot_btc_eth_1m" if market == "spot" else "usdm_btc_eth_1m"
        dataset_path = ROOT / "research/data" / folder
        candles, provenance = engine.load_dataset(dataset_path, market)
        candles = candles.loc[candles.open_time < engine.DATA_END].copy()
        expected_data = next(row for row in source["data"] if row["market"] == market)
        manifest_hash = sha256(dataset_path / "dataset.json")
        if provenance["data_sha256"] != expected_data["dataset_sha256"]:
            raise RuntimeError(f"Dataset hash mismatch for {market}")
        if manifest_hash != expected_data["manifest_sha256"] or not provenance.get("verified"):
            raise RuntimeError(f"Dataset manifest/provenance mismatch for {market}")

        arrays: dict[str, Any] = {}
        ema_by_symbol: dict[str, dict[pd.Timestamp, float]] = {}
        candidate_frames = []
        for symbol, grouped in candles.groupby("symbol", sort=True):
            bars = grouped.reset_index(drop=True)
            arrays[symbol] = engine.MarketArrays(bars)
            features, ema = engine.market_features(bars)
            ema_by_symbol[symbol] = ema
            candidate_frames.append(engine.generate_candidates(
                features, symbol, market, pd.DatetimeIndex(bars.open_time)))
            del bars, features
        candidates = pd.concat(candidate_frames, ignore_index=True)
        candidates = candidates.sort_values(
            ["signal_time", "symbol", "family", "side"]
        ).reset_index(drop=True)
        candidates["candidate_id"] = candidates.candidate_id.astype(str)
        expected_counts = {
            row["family"]: row["candidate_count"]
            for row in source["models"] if row["market"] == market and not row.get("backend")
        }
        actual_counts = candidates.groupby("family").size().to_dict()
        if any(int(actual_counts.get(family, 0)) != int(count)
               for family, count in expected_counts.items()):
            raise RuntimeError(f"Candidate-count mismatch for {market}")
        data_records.append({
            "market": market, "dataset_sha256": provenance["data_sha256"],
            "manifest_sha256": manifest_hash, "rows": len(candles),
            "candidate_counts": {k: int(v) for k, v in actual_counts.items()},
        })
        config = engine.gate_config(market)
        for family in engine.FAMILIES:
            pool = candidates.loc[candidates.family == family].copy()
            pool["probability"], pool["expected_r"] = 1.0, 1.0
            candidate_map = pool.set_index("candidate_id").to_dict("index")
            for horizon_name, max_hold in engine.HORIZONS:
                for exit_mode, _exit_plan in engine.EXITS:
                    variant_id = (f"{market.upper()}-{family.upper()}-"
                                  f"{horizon_name.upper()}-{exit_mode.upper()}")
                    for stress in (False, True):
                        cache: dict[tuple[str, bool], Any] = {}
                        _summary, trades = engine.evaluate_portfolio(
                            pool, arrays, {market: config}, exit_mode, max_hold,
                            ema_by_symbol, start, end, stress=stress,
                            outcome_cache=cache,
                        )
                        scenario = "stress" if stress else "base"
                        for trade in trades:
                            key = (str(trade["candidate_id"]), stress)
                            outcome = cache.get(key)
                            if outcome is None:
                                raise RuntimeError(f"Missing traced outcome for {key}")
                            trade_records.append(path_record(
                                variant_id, scenario, trade, outcome,
                                arrays[trade["symbol"]], candidate_map[key[0]], config,
                            ))
            del pool, candidate_map
        del candidates, arrays, ema_by_symbol, candles

    frame = pd.DataFrame(trade_records)
    trades_path = output_path / "path_metrics_by_trade.csv"
    frame.to_csv(trades_path, index=False, encoding="utf-8", lineterminator="\n")
    group_keys = ["variant_id", "scenario"]
    summaries = []
    for (variant_id, scenario), group in frame.groupby(group_keys, sort=True):
        row = {"variant_id": variant_id, "scenario": scenario,
               "trades": int(len(group)), "unique_candidates": int(group.candidate_id.nunique()),
               "wins": int(group.win.sum()), "losses": int((~group.win).sum()),
               "mean_net_return": float(group.net_return.mean()),
               "median_mfe_complete_r": median_or_none(group.mfe_complete_candles_r),
               "median_mae_complete_r": median_or_none(group.mae_complete_candles_r),
               "median_friction_over_stop_r": float(group.total_estimated_friction_over_stop_r.median()),
               "ambiguous_exit_bar_trades": int(group.exit_bar_ambiguous.sum()),
               "exit_reason_counts": {str(k): int(v) for k, v in group.exit_reason.value_counts().items()}}
        summaries.append(row)
    summary_path = output_path / "path_group_summary.json"
    summary_path.write_text(json.dumps(summaries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report = {
        "created_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "status": "posthoc_path_diagnostic_not_strategy_evidence",
        "protocol": args.protocol,
        "protocol_sha256": sha256(ROOT / args.protocol),
        "source_report": str(source_path.relative_to(ROOT)).replace("\\", "/"),
        "source_report_sha256": source_hash,
        "engine_script": str(ENGINE_PATH.relative_to(ROOT)).replace("\\", "/"),
        "engine_script_sha256": engine_hash,
        "research_script": str(Path(__file__).resolve().relative_to(ROOT)).replace("\\", "/"),
        "research_script_sha256": sha256(Path(__file__).resolve()),
        "markets": ["spot", "usd_m"], "symbols": ["BTCUSDT", "ETHUSDT"],
        "variants": 24, "scenarios": ["base", "stress"],
        "window_start": start.isoformat(), "window_end_exclusive": end.isoformat(),
        "data": data_records, "trade_rows": len(frame),
        "summary_rows": len(summaries),
        "outputs": {
            trades_path.name: sha256(trades_path),
            summary_path.name: sha256(summary_path),
        },
        "training_performed": False, "gpu_training_performed": False,
        "threshold_selection_performed": False, "real_orders_sent": False,
        "independent_validation": False,
        "interpretation": "Retrospective path measurements only. Trades repeated across variants are not independent; future excursions are diagnostic and not entry features.",
    }
    report_path = output_path / "research.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "variants": 24,
                      "trade_rows": len(frame), "summary_rows": len(summaries),
                      "report": str(report_path.relative_to(ROOT)).replace("\\", "/"),
                      "report_sha256": sha256(report_path)}, indent=2))


if __name__ == "__main__":
    main()
