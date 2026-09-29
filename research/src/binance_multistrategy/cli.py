from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import pandas as pd
from .config import ResearchConfig
from .data import download_dataset, load_dataset, utc_timestamp
from .learning import TrainedGate, latest_signals, prepare_market, train_pipeline
from .simulation import evaluate, promotion_gate


def read_config(path: str) -> ResearchConfig:
    return ResearchConfig(**json.loads(Path(path).read_text(encoding="utf-8")))


def run_evaluation(model: TrainedGate, candles: pd.DataFrame, provenance: dict,
                   start: pd.Timestamp, end: pd.Timestamp, output: Path, registry: Path) -> dict:
    if start < utc_timestamp(model.metadata["selection_end"]):
        raise ValueError("Evaluation starts before model selection ended; this is not an out-of-sample evaluation")
    if start >= end or end > candles.open_time.max() + pd.Timedelta(minutes=1):
        raise ValueError("Invalid/unsupported evaluation interval")
    if set(candles.symbol) - set(model.metadata["symbols"]):
        raise ValueError("Dataset contains symbols not used to train this artifact")
    for symbol, bars in candles.groupby("symbol"):
        if bars.open_time.max() + pd.Timedelta(minutes=1) < end:
            raise ValueError(f"{symbol} history ends before requested evaluation end")
        if bars.open_time.min() > start - pd.Timedelta(hours=200):
            raise ValueError(f"{symbol} needs at least 200h of preceding warmup history; use the same full causal history as training")
    # Cut off the future explicitly before generating any features/candidates.
    candidates, market = prepare_market(candles.loc[candles.open_time < end], model.config)
    if candidates.empty:
        raise ValueError("No candidates in supplied history")
    scored = model.score(candidates)
    base, trades, equity = evaluate(scored, market, model.config, start, end, model.threshold)
    stress, stress_trades, stress_equity = evaluate(scored, market, model.config, start, end, model.threshold, stress=True)
    passed, failures = promotion_gate(base, stress, model.config)
    prior = []
    if registry.exists():
        for line in registry.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row["market"] == model.config.market and utc_timestamp(row["start"]) < end and utc_timestamp(row["end"]) > start:
                prior.append(row)
    report = {"model_id": model.metadata["model_id"], "market": model.config.market,
              "base": base, "stress": stress, "evaluation_gate_passed": passed,
              "failures": failures, "training_selection_gate_passed": model.research_gate_passed,
              "dataset": provenance, "overlapping_previous_evaluations": prior,
              "not_pristine_if_reused": bool(prior), "live_orders_supported": False,
              "warning": "Out-of-time is not automatically untouched. Prior project research already examined portions of 2025-2026. Registry cannot detect tests outside this output directory."}
    output.mkdir(parents=True, exist_ok=True)
    for filename, data in [("trades.csv", trades), ("equity.csv", equity),
                           ("stress_trades.csv", stress_trades), ("stress_equity.csv", stress_equity)]:
        data.to_csv(output / filename, index=False)
    (output / "evaluation.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    registry.parent.mkdir(parents=True, exist_ok=True)
    with registry.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"market": model.config.market, "model_id": model.metadata["model_id"],
                                 "start": str(start), "end": str(end), "dataset_sha256": provenance.get("data_sha256"),
                                 "timestamp": str(pd.Timestamp.now(tz="UTC"))}) + "\n")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Binance multistrategy research. No live orders or guaranteed hit rate.")
    sub = parser.add_subparsers(dest="command", required=True)
    download = sub.add_parser("download", help="Download checksum-verified complete monthly 1m archives")
    download.add_argument("--market", choices=["spot", "usd_m"], required=True)
    download.add_argument("--symbols", nargs="+", required=True)
    download.add_argument("--first-month", required=True)
    download.add_argument("--last-month", required=True)
    download.add_argument("--start-time", help="Optional inclusive UTC timestamp; requires --end-time")
    download.add_argument("--end-time", help="Optional exclusive UTC timestamp; requires --start-time")
    download.add_argument("--out", required=True)
    audit = sub.add_parser("audit", help="Validate dataset, gaps, timestamps and observed Futures funding")
    audit.add_argument("--market", choices=["spot", "usd_m"], required=True)
    audit.add_argument("--data", required=True)
    train = sub.add_parser("train", help="Train and select only on historical chronological partitions")
    train.add_argument("--config", required=True)
    train.add_argument("--data", required=True)
    train.add_argument("--train-end", required=True, help="Exclusive UTC boundary")
    train.add_argument("--calibration-end", required=True, help="Exclusive UTC boundary")
    train.add_argument("--selection-end", required=True, help="Exclusive UTC boundary; later data not used")
    train.add_argument("--backend", choices=["hist_cpu", "xgboost_cuda"], default="hist_cpu")
    train.add_argument("--out", required=True)
    test = sub.add_parser("evaluate", help="Frozen-model backtest, including cost stress, never retunes")
    test.add_argument("--model", required=True)
    test.add_argument("--data", required=True)
    test.add_argument("--start", required=True)
    test.add_argument("--end", required=True)
    test.add_argument("--out", required=True)
    signal = sub.add_parser("signal", help="Offline signal for the latest completed input candle; does not send orders")
    signal.add_argument("--model", required=True)
    signal.add_argument("--data", required=True)
    signal.add_argument("--diagnostic", action="store_true", help="Show eligible candidates even when research validation failed")
    walk = sub.add_parser("walk-forward", help="Explicit nonoverlapping forward test folds")
    walk.add_argument("--config", required=True)
    walk.add_argument("--data", required=True)
    walk.add_argument("--folds", required=True, help="JSON list of train_end/calibration_end/selection_end/test_end")
    walk.add_argument("--backend", choices=["hist_cpu", "xgboost_cuda"], default="hist_cpu")
    walk.add_argument("--out", required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "download":
            path = download_dataset(Path(args.out), args.market, args.symbols, args.first_month, args.last_month,
                                    args.start_time, args.end_time)
            print(path)
        elif args.command == "audit":
            data, meta = load_dataset(Path(args.data), args.market)
            print(json.dumps({"rows": len(data), "symbols": sorted(data.symbol.unique()),
                              "start": str(data.open_time.min()), "end": str(data.open_time.max()), "provenance": meta}, indent=2))
        elif args.command == "train":
            config = read_config(args.config)
            data, meta = load_dataset(Path(args.data), config.market)
            report = train_pipeline(data, meta, config, utc_timestamp(args.train_end), utc_timestamp(args.calibration_end),
                                    utc_timestamp(args.selection_end), Path(args.out), backend=args.backend)
            print(json.dumps({"status": report["status"], "model_id": report["model_id"],
                              "selection": report["selected_result"], "files": args.out}, indent=2))
        elif args.command in {"evaluate", "signal"}:
            print("Loading a local trusted joblib artifact; never load an unknown third-party model.", file=sys.stderr)
            model = TrainedGate.load(Path(args.model))
            data, meta = load_dataset(Path(args.data), model.config.market)
            if args.command == "signal":
                print(json.dumps(latest_signals(data, model, args.diagnostic), indent=2))
            else:
                output = Path(args.out)
                report = run_evaluation(model, data, meta, utc_timestamp(args.start), utc_timestamp(args.end),
                                        output, output.parent / "evaluation_registry.jsonl")
                print(json.dumps({"base": report["base"], "stress": report["stress"],
                                  "gate_passed": report["evaluation_gate_passed"], "failures": report["failures"],
                                  "reused": report["not_pristine_if_reused"]}, indent=2))
        elif args.command == "walk-forward":
            config = read_config(args.config)
            data, provenance = load_dataset(Path(args.data), config.market)
            folds = json.loads(Path(args.folds).read_text(encoding="utf-8"))
            if not isinstance(folds, list) or not folds:
                raise ValueError("folds must be a nonempty JSON list")
            output, last_test_end, reports = Path(args.out), None, []
            for i, fold in enumerate(folds, 1):
                boundaries = {name: utc_timestamp(fold[name]) for name in ["train_end", "calibration_end", "selection_end", "test_end"]}
                if not boundaries["train_end"] < boundaries["calibration_end"] < boundaries["selection_end"] < boundaries["test_end"]:
                    raise ValueError("Fold dates must increase strictly")
                if last_test_end is not None and boundaries["selection_end"] < last_test_end:
                    raise ValueError("Walk-forward test windows overlap")
                folder = output / f"fold_{i:02d}"
                train_pipeline(data, provenance, config, boundaries["train_end"], boundaries["calibration_end"],
                               boundaries["selection_end"], folder / "training", backend=args.backend)
                model = TrainedGate.load(folder / "training" / "model.joblib")
                report = run_evaluation(model, data, provenance, boundaries["selection_end"], boundaries["test_end"], folder / "test", output / "evaluation_registry.jsonl")
                reports.append(report)
                last_test_end = boundaries["test_end"]
            (output / "walk_forward.json").write_text(json.dumps(reports, indent=2, allow_nan=False), encoding="utf-8")
            print(json.dumps({"folds": len(reports), "out": str(output)}, indent=2))
    except (ValueError, RuntimeError, FileNotFoundError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
