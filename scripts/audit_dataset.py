from __future__ import annotations

import argparse
import csv
import json
import zipfile
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

import numpy as np

from laya_trader.config import load_config

SPLITS = ("train", "calibration", "validation", "test")
FORBIDDEN_STATE_KEYS = {
    "entry_price",
    "label_end_ts",
    "label_end_time",
    "long_r",
    "short_r",
}
FORBIDDEN_STATE_PREFIXES = ("target_",)
RAW_STATE_KEYS = {"open", "high", "low", "close", "candles", "ohlcv"}


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _range_bound(value: str, *, end: bool) -> datetime:
    parsed = _parse_time(value)
    if end and len(str(value).strip()) == 10:
        parsed += timedelta(days=1) - timedelta(microseconds=1)
    return parsed


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and bool(np.isfinite(value))


def _walk_state(value: object, path: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield from _walk_state(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_state(child, f"{path}[{index}]")
    else:
        yield path, value


def _contains_forbidden_state_data(state: object) -> list[str]:
    found: list[str] = []
    if not isinstance(state, dict):
        return ["state is not an object"]
    for path, value in _walk_state(state):
        key = path.rsplit(".", 1)[-1].split("[", 1)[0]
        if key in FORBIDDEN_STATE_KEYS or any(
            key.startswith(prefix) for prefix in FORBIDDEN_STATE_PREFIXES
        ):
            found.append(path)
        if key.lower() in RAW_STATE_KEYS:
            found.append(path)
    return found


def _new_split_stats() -> dict:
    return {
        "rows": 0,
        "symbols": set(),
        "start": None,
        "end": None,
        "action": Counter(),
        "tradeable": [],
        "edge_quality_expected": [],
        "invalid": Counter(),
        "per_symbol": defaultdict(lambda: {
            "samples": 0,
            "action": Counter(),
            "long_r": [],
            "short_r": [],
        }),
    }


def _update_split_stats(stats: dict, record: dict, split_end: datetime, data_start: datetime, data_end: datetime):
    stats["rows"] += 1
    symbol = str(record.get("symbol", ""))
    stats["symbols"].add(symbol)
    decision = _parse_time(record["decision_time"])
    stats["start"] = decision if stats["start"] is None else min(stats["start"], decision)
    stats["end"] = decision if stats["end"] is None else max(stats["end"], decision)
    symbol_stats = stats["per_symbol"][symbol]
    symbol_stats["samples"] += 1

    targets = record.get("targets", {})
    target_specs = {"action": 3, "tradeable": 2, "edge_quality": 5}
    arrays: dict[str, list[float]] = {}
    for name, expected_len in target_specs.items():
        values = targets.get(name)
        if not isinstance(values, list) or len(values) != expected_len:
            stats["invalid"][f"{name}_shape"] += 1
            values = [float("nan")] * expected_len
        arrays[name] = [float(value) if isinstance(value, (int, float)) else float("nan") for value in values]
        if not all(_finite(value) for value in arrays[name]):
            stats["invalid"][f"{name}_nonfinite"] += 1
        if any(value < 0 for value in arrays[name] if _finite(value)):
            stats["invalid"][f"{name}_negative"] += 1
        total = sum(arrays[name])
        if not np.isfinite(total) or not np.isclose(total, 1.0, atol=1e-5):
            stats["invalid"][f"{name}_sum"] += 1

    action = arrays["action"]
    if all(_finite(value) for value in action):
        action_index = int(np.argmax(action))
        action_name = ("LONG", "SHORT", "FLAT")[action_index]
        stats["action"][action_name] += 1
        symbol_stats["action"][action_name] += 1
    else:
        action_name = "INVALID"

    tradeable = arrays["tradeable"][1] if _finite(arrays["tradeable"][1]) else float("nan")
    edge_expected = (
        float(np.dot(np.arange(5, dtype=float), arrays["edge_quality"]))
        if all(_finite(value) for value in arrays["edge_quality"])
        else float("nan")
    )
    stats["tradeable"].append(tradeable)
    stats["edge_quality_expected"].append(edge_expected)

    diagnostics = record.get("diagnostics", {})
    for name in ("long_r", "short_r"):
        value = diagnostics.get(name)
        if not _finite(value):
            stats["invalid"][f"diagnostics_{name}"] += 1
        else:
            symbol_stats[name].append(float(value))

    label_end_value = diagnostics.get("label_end_time")
    if not isinstance(label_end_value, str):
        stats["invalid"]["missing_label_end_time"] += 1
    else:
        label_end = _parse_time(label_end_value)
        if label_end < decision:
            stats["invalid"]["label_end_before_decision"] += 1
        if label_end > split_end:
            stats["invalid"]["label_crosses_split_boundary"] += 1
        if label_end > data_end or decision < data_start or decision > data_end:
            stats["invalid"]["outside_configured_data_range"] += 1

    state = record.get("state")
    forbidden = _contains_forbidden_state_data(state)
    if forbidden:
        stats["invalid"]["state_contains_future_or_label_data"] += 1
        stats.setdefault("state_violations", []).extend(forbidden[:5])

    if action_name == "INVALID":
        stats["invalid"]["action_invalid"] += 1


def _quantiles(values: list[float]) -> dict[str, float | None]:
    finite = np.asarray([value for value in values if np.isfinite(value)], dtype=float)
    if finite.size == 0:
        return {"mean": None, "p50": None, "p90": None}
    return {
        "mean": float(finite.mean()),
        "p50": float(np.quantile(finite, 0.50)),
        "p90": float(np.quantile(finite, 0.90)),
    }


def _finalize_stats(stats: dict) -> dict:
    out = {
        "rows": stats["rows"],
        "symbols": sorted(stats["symbols"]),
        "start": stats["start"].isoformat() if stats["start"] else None,
        "end": stats["end"].isoformat() if stats["end"] else None,
        "argmax_action": dict(stats["action"]),
        "tradeable": _quantiles(stats["tradeable"]),
        "edge_quality_expected_mean": (
            _quantiles(stats["edge_quality_expected"])["mean"]
        ),
        "invalid": dict(stats["invalid"]),
        "state_violations": sorted(set(stats.get("state_violations", [])))[:20],
        "per_symbol": {},
    }
    for symbol in sorted(stats["per_symbol"]):
        item = stats["per_symbol"][symbol]
        samples = item["samples"]
        out["per_symbol"][symbol] = {
            "samples": samples,
            "LONG_pct": 100.0 * item["action"]["LONG"] / samples if samples else None,
            "SHORT_pct": 100.0 * item["action"]["SHORT"] / samples if samples else None,
            "FLAT_pct": 100.0 * item["action"]["FLAT"] / samples if samples else None,
            "long_r_mean": float(np.mean(item["long_r"])) if item["long_r"] else None,
            "short_r_mean": float(np.mean(item["short_r"])) if item["short_r"] else None,
        }
    return out


def _raw_gap_audit(cfg) -> dict:
    root = (
        cfg.data.raw_dir
        / "binance"
        / "futures"
        / cfg.data.market
        / "monthly"
        / "klines"
    )
    expected_ms = (15 * 60) * 1000 if cfg.data.interval == "15m" else None
    if expected_ms is None:
        raise ValueError("audit raw gap check currently supports configured 15m data only")
    result = {"files": 0, "symbols": {}, "gaps": 0, "examples": []}
    start_ms = int(_range_bound(cfg.data.start, end=False).timestamp() * 1000)
    end_ms = int(_range_bound(cfg.data.end, end=True).timestamp() * 1000)
    for symbol in cfg.data.symbols:
        symbol_root = root / symbol / cfg.data.interval
        times: list[int] = []
        for path in sorted(symbol_root.glob("*.zip")):
            result["files"] += 1
            with zipfile.ZipFile(path) as archive:
                name = next(name for name in archive.namelist() if not name.endswith("/"))
                with archive.open(name) as raw:
                    reader = csv.reader(line.decode("utf-8") for line in raw)
                    for row in reader:
                        if row:
                            try:
                                value = int(float(row[0]))
                            except ValueError:
                                if row[0].strip().lower() == "open_time":
                                    continue
                                raise
                            if start_ms <= value <= end_ms:
                                times.append(value)
        times.sort()
        symbol_gaps = 0
        for previous, current in pairwise(times):
            delta = current - previous
            if delta != expected_ms:
                symbol_gaps += 1
                if len(result["examples"]) < 20:
                    result["examples"].append({
                        "symbol": symbol,
                        "before": datetime.fromtimestamp(previous / 1000, UTC).isoformat(),
                        "after": datetime.fromtimestamp(current / 1000, UTC).isoformat(),
                        "delta_minutes": delta / 60000,
                    })
        result["symbols"][symbol] = {"candles": len(times), "gaps": symbol_gaps}
        result["gaps"] += symbol_gaps
    return result


def audit_dataset(config_path: str | Path, dataset_dir: str | Path | None = None) -> dict:
    cfg = load_config(config_path)
    dataset_root = Path(dataset_dir) if dataset_dir else cfg.data.dataset_dir
    data_start = _range_bound(cfg.data.start, end=False)
    data_end = _range_bound(cfg.data.end, end=True)
    split_ends = {
        "train": _parse_time(cfg.splits.train_end),
        "calibration": _parse_time(cfg.splits.calibration_end),
        "validation": _parse_time(cfg.splits.validation_end),
        "test": _parse_time(cfg.splits.test_end),
    }

    duplicate_ids: Counter[str] = Counter()
    duplicate_timestamps: Counter[tuple[str, str]] = Counter()
    splits: dict[str, dict] = {}
    for split in SPLITS:
        stats = _new_split_stats()
        path = dataset_root / f"{split}.jsonl"
        if not path.exists():
            stats["invalid"]["missing_file"] += 1
            splits[split] = _finalize_stats(stats)
            continue
        with path.open("r", encoding="utf-8") as fh:
            for line_number, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    record_id = str(record["id"])
                    symbol = str(record["symbol"])
                    decision_time = str(record["decision_time"])
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    stats["invalid"]["malformed_record"] += 1
                    stats.setdefault("errors", []).append({"line": line_number, "error": str(exc)})
                    continue
                duplicate_ids[record_id] += 1
                duplicate_timestamps[(symbol, decision_time)] += 1
                _update_split_stats(stats, record, split_ends[split], data_start, data_end)
        splits[split] = _finalize_stats(stats)

    duplicate_id_values = sorted(key for key, count in duplicate_ids.items() if count > 1)
    duplicate_timestamp_values = sorted(
        {f"{symbol}:{timestamp}" for (symbol, timestamp), count in duplicate_timestamps.items() if count > 1}
    )
    raw_gaps = _raw_gap_audit(cfg)
    checks = {
        "duplicate_ids": {"count": len(duplicate_id_values), "examples": duplicate_id_values[:20]},
        "duplicate_timestamps_by_symbol": {
            "count": len(duplicate_timestamp_values),
            "examples": duplicate_timestamp_values[:20],
        },
        "targets_or_features_with_nan": {
            "count": sum(
                value
                for split in splits.values()
                for key, value in split["invalid"].items()
                if "nonfinite" in key or "diagnostics_" in key
            )
        },
        "negative_probabilities_or_bad_sums": {
            "count": sum(
                value
                for split in splits.values()
                for key, value in split["invalid"].items()
                if "negative" in key or key.endswith("_sum")
            )
        },
        "label_end_before_decision": {
            "count": sum(split["invalid"].get("label_end_before_decision", 0) for split in splits.values())
        },
        "labels_crossing_split_boundary": {
            "count": sum(split["invalid"].get("label_crosses_split_boundary", 0) for split in splits.values())
        },
        "records_outside_data_range": {
            "count": sum(split["invalid"].get("outside_configured_data_range", 0) for split in splits.values())
        },
        "state_contains_future_or_label_data": {
            "count": sum(
                split["invalid"].get("state_contains_future_or_label_data", 0)
                for split in splits.values()
            )
        },
        "raw_candle_gaps": raw_gaps,
    }
    failures = {
        name: value
        for name, value in checks.items()
        if isinstance(value, dict) and value.get("count", 0) > 0
    }
    return {
        "config": str(Path(config_path)),
        "dataset_dir": str(dataset_root),
        "interval": cfg.data.interval,
        "splits": splits,
        "checks": checks,
        "pass": not failures,
        "failures": failures,
    }


def _fmt(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def render_markdown(report: dict) -> str:
    lines = [
        "# Dataset Audit",
        "",
        f"- Result: **{'PASS' if report['pass'] else 'FAIL'}**",
        f"- Config: `{report['config']}`",
        f"- Dataset: `{report['dataset_dir']}`",
        "",
        "## Integrity checks",
        "",
    ]
    for name, value in report["checks"].items():
        if name == "raw_candle_gaps":
            lines.append(f"- `{name}`: {_fmt(value['gaps'])} gaps across {_fmt(value['files'])} ZIPs")
        else:
            lines.append(f"- `{name}`: {_fmt(value.get('count', 0))}")
    lines += ["", "## Split distribution", "", "| split | rows | symbols | start | end | LONG | SHORT | FLAT | tradeable mean | p50 | p90 | edge quality mean |", "|---|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for split, stats in report["splits"].items():
        action = stats["argmax_action"]
        tradeable = stats["tradeable"]
        lines.append(
            f"| {split} | {stats['rows']} | {len(stats['symbols'])} | {stats['start']} | {stats['end']} | "
            f"{action.get('LONG', 0)} | {action.get('SHORT', 0)} | {action.get('FLAT', 0)} | "
            f"{_fmt(tradeable['mean'])} | {_fmt(tradeable['p50'])} | {_fmt(tradeable['p90'])} | "
            f"{_fmt(stats['edge_quality_expected_mean'])} |"
        )
    lines += ["", "## Per-symbol distribution", ""]
    for split, stats in report["splits"].items():
        lines += [f"### {split}", "", "| symbol | samples | LONG % | SHORT % | FLAT % | long_r mean | short_r mean |", "|---|---:|---:|---:|---:|---:|---:|"]
        for symbol, item in stats["per_symbol"].items():
            lines.append(
                f"| {symbol} | {item['samples']} | {_fmt(item['LONG_pct'])} | {_fmt(item['SHORT_pct'])} | "
                f"{_fmt(item['FLAT_pct'])} | {_fmt(item['long_r_mean'])} | {_fmt(item['short_r_mean'])} |"
            )
        lines.append("")
    lines += ["## Raw candle gaps", "", "```json", json.dumps(report["checks"]["raw_candle_gaps"], indent=2), "```", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit causal Laya Trader JSONL splits")
    parser.add_argument("--config", default="configs/dataset.toml")
    parser.add_argument("--dataset-dir")
    parser.add_argument("--output-json", default="outputs/dataset_audit.json")
    parser.add_argument("--output-md", default="outputs/dataset_audit.md")
    args = parser.parse_args(argv)
    report = audit_dataset(args.config, args.dataset_dir)
    Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output_json).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    Path(args.output_md).write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"pass": report["pass"], "failures": report["failures"]}, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
