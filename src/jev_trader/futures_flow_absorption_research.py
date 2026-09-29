"""Frozen 1m USD-M futures flow-absorption study; no exchange orders."""

from __future__ import annotations

import argparse
import bisect
import concurrent.futures
import csv
import hashlib
import io
import json
import math
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
FIRST_MONTH = "2024-01"
LAST_MONTH = "2026-08"
BASE_URL = "https://data.binance.vision/data/futures/um/monthly/klines"
DATA_ROOT = ROOT / "data" / "binance" / "futures" / "um" / "klines"
FUNDING_ROOT = ROOT / "data" / "binance" / "futures" / "um" / "fundingRate"
OUTPUT_DIR = ROOT / "results" / "futures_flow_absorption_20260927"
OUTPUT_JSON = OUTPUT_DIR / "research.json"
OUTPUT_TRADES = OUTPUT_DIR / "selected_trades.csv"
OUTPUT_STATIC_TRADES = OUTPUT_DIR / "static_signal_trades.csv"
PROTOCOL = ROOT / "docs" / "futures_flow_absorption_protocol_2026-09-27.md"
MONTH_START = datetime(2024, 1, 1, tzinfo=timezone.utc)
VALIDATION_START = datetime(2025, 1, 1, tzinfo=timezone.utc)
CONFIRMATION_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END_EXCLUSIVE = datetime(2026, 9, 1, tzinfo=timezone.utc)
BASE_SIDE_COST = 0.0010
STRESS_SIDE_COST = 0.0015
TARGET_R = 1.8
MAX_HOLD_MINUTES = 60
COOLDOWN_MINUTES = 30
MIN_STOP_PCT = 0.0015
MAX_STOP_PCT = 0.015
MIN_TRAINING_EVENTS = 400
MIN_SCREEN_TRADES = 30
MIN_VALIDATION_TRADES = 100
THRESHOLDS = tuple(round(value, 2) for value in np.arange(0.55, 0.901, 0.05))
SIDE_COSTS = {"base": BASE_SIDE_COST, "stress": STRESS_SIDE_COST}
FEATURE_NAMES = (
    "imbalance_1m", "imbalance_5m", "imbalance_15m",
    "quote_volume_5m_multiple_12h", "trade_count_5m_multiple_12h",
    "return_1m", "return_5m", "return_15m", "return_60m",
    "range_5m_pct", "close_location_5m", "upper_wick_5m_pct",
    "lower_wick_5m_pct", "realized_volatility_60m_pct",
)
BAR_DTYPE = np.dtype([
    ("t", "i8"), ("o", "f8"), ("h", "f8"), ("l", "f8"),
    ("c", "f8"), ("qv", "f8"), ("taker_buy_qv", "f8"), ("trades", "i8"),
])
ZERO_SHA256 = "0" * 64


def _month_sequence(first: str, last: str) -> list[str]:
    y, m = map(int, first.split("-"))
    end_y, end_m = map(int, last.split("-"))
    values = []
    while (y, m) <= (end_y, end_m):
        values.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return values


def _read_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "laya-futures-research/1.0"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def _checksum(payload: bytes) -> str:
    expected = payload.decode("ascii").strip().split()[0].lower()
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise ValueError("invalid first-party SHA-256 checksum")
    return expected


def _archive_paths(symbol: str, month: str) -> tuple[str, Path, Path]:
    filename = f"{symbol}-1m-{month}.zip"
    url = f"{BASE_URL}/{symbol}/1m/{filename}"
    target = DATA_ROOT / symbol / "1m" / filename
    return url, target, target.with_suffix(".zip.CHECKSUM")


def fetch_month(symbol: str, month: str) -> dict:
    url, target, checksum_path = _archive_paths(symbol, month)
    target.parent.mkdir(parents=True, exist_ok=True)
    if checksum_path.exists():
        checksum_payload = checksum_path.read_bytes()
    else:
        checksum_payload = _read_url(url + ".CHECKSUM")
        checksum_path.write_bytes(checksum_payload)
    expected = _checksum(checksum_payload)
    if target.exists():
        payload = target.read_bytes()
        actual = hashlib.sha256(payload).hexdigest()
        if actual != expected:
            raise ValueError(f"cached archive checksum mismatch: {target}")
    else:
        payload = _read_url(url)
        actual = hashlib.sha256(payload).hexdigest()
        if actual != expected:
            raise ValueError(f"downloaded archive checksum mismatch: {url}")
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if archive.testzip() is not None:
                raise ValueError(f"ZIP CRC mismatch: {url}")
        temporary = target.with_suffix(".zip.part")
        temporary.write_bytes(payload)
        temporary.replace(target)
    return {"symbol": symbol, "month": month, "sha256": expected,
            "bytes": len(payload), "path": str(target.relative_to(ROOT))}


def download_archives() -> list[dict]:
    tasks = [(symbol, month) for symbol in SYMBOLS for month in _month_sequence(FIRST_MONTH, LAST_MONTH)]
    results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fetch_month, symbol, month) for symbol, month in tasks]
        for count, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            results.append(future.result())
            if count % 16 == 0 or count == len(tasks):
                print(f"verified archives {count}/{len(tasks)}", flush=True)
    return sorted(results, key=lambda item: (item["symbol"], item["month"]))


def _parse_bar(row: list[str]) -> tuple:
    timestamp = int(row[0])
    if timestamp >= 10**15:
        timestamp //= 1000
    return (timestamp, float(row[1]), float(row[2]), float(row[3]), float(row[4]),
            float(row[7]), float(row[10]), int(row[8]))


def load_symbol_bars(symbol: str) -> tuple[np.ndarray, list[dict]]:
    chunks = []
    manifest = []
    for month in _month_sequence(FIRST_MONTH, LAST_MONTH):
        url, target, checksum_path = _archive_paths(symbol, month)
        if not target.exists() or not checksum_path.exists():
            raise FileNotFoundError(f"missing cached archive for {symbol} {month}; run without --skip-download")
        payload = target.read_bytes()
        sha = hashlib.sha256(payload).hexdigest()
        expected = _checksum(checksum_path.read_bytes())
        if sha != expected:
            raise ValueError(f"archive SHA-256 mismatch: {target}")
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if archive.testzip() is not None:
                raise ValueError(f"archive CRC mismatch: {target}")
            names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if len(names) != 1:
                raise ValueError(f"expected one CSV in {target}, found {len(names)}")
            with archive.open(names[0]) as raw:
                reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
                rows = ( _parse_bar(row) for row in reader if row and row[0].strip().isdigit() )
                chunk = np.fromiter(rows, dtype=BAR_DTYPE)
        if len(chunk) == 0:
            raise ValueError(f"empty kline archive: {target}")
        chunks.append(chunk)
        manifest.append({"symbol": symbol, "month": month, "sha256": sha,
                         "rows": len(chunk), "bytes": len(payload)})
    bars = np.concatenate(chunks)
    timestamps = bars["t"]
    if np.any(np.diff(timestamps) <= 0):
        raise ValueError(f"duplicate or unordered 1m timestamps for {symbol}")
    if np.any(np.diff(timestamps) != 60_000):
        gaps = int(np.count_nonzero(np.diff(timestamps) != 60_000))
        raise ValueError(f"{symbol} has {gaps} missing or irregular 1m intervals")
    return bars, manifest


def load_funding(symbol: str) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    times: list[int] = []
    rates: list[float] = []
    manifest = []
    for month in _month_sequence(FIRST_MONTH, LAST_MONTH):
        filename = f"{symbol}-fundingRate-{month}.zip"
        path = FUNDING_ROOT / symbol / filename
        checksum_path = path.with_suffix(".zip.CHECKSUM")
        if not path.exists() or not checksum_path.exists():
            raise FileNotFoundError(f"missing funding archive/checksum: {path}")
        payload = path.read_bytes()
        sha = hashlib.sha256(payload).hexdigest()
        if sha != _checksum(checksum_path.read_bytes()):
            raise ValueError(f"funding archive SHA-256 mismatch: {path}")
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if archive.testzip() is not None:
                raise ValueError(f"funding archive CRC mismatch: {path}")
            name = next(name for name in archive.namelist() if name.lower().endswith(".csv"))
            with archive.open(name) as raw:
                reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
                rows = list(reader)
        for row in rows:
            times.append(int(row["calc_time"]))
            rates.append(float(row["last_funding_rate"]))
        manifest.append({"symbol": symbol, "month": month, "sha256": sha, "rows": len(rows)})
    order = np.argsort(np.asarray(times, dtype=np.int64))
    time_array = np.asarray(times, dtype=np.int64)[order]
    rate_array = np.asarray(rates, dtype=np.float64)[order]
    if len(time_array) == 0 or np.any(np.diff(time_array) <= 0):
        raise ValueError(f"invalid funding timestamps for {symbol}")
    return time_array, rate_array, manifest


def _rolling_sum(values: np.ndarray, window: int) -> np.ndarray:
    safe = np.nan_to_num(values, nan=0.0)
    prefix = np.concatenate((np.zeros(1, dtype=np.float64), np.cumsum(safe, dtype=np.float64)))
    result = prefix[window:] - prefix[:-window]
    out = np.full(len(values), np.nan, dtype=np.float64)
    out[window - 1:] = result
    return out


def _rolling_mean(values: np.ndarray, window: int) -> np.ndarray:
    return _rolling_sum(values, window) / window


def _rolling_median_prior(values: np.ndarray, window: int, valid_start: int) -> np.ndarray:
    out = np.full(len(values), np.nan, dtype=np.float64)
    valid = values[valid_start:]
    if len(valid) < window:
        return out
    # The final window would include x[-1] and map to an event index len(x).
    views = np.lib.stride_tricks.sliding_window_view(valid, window)[:-1]
    for start in range(0, len(views), 2048):
        stop = min(start + 2048, len(views))
        out[valid_start + window + start:valid_start + window + stop] = np.median(views[start:stop], axis=1)
    return out


def _rolling_extreme(values: np.ndarray, window: int, maximum: bool) -> np.ndarray:
    out = np.full(len(values), np.nan, dtype=np.float64)
    views = np.lib.stride_tricks.sliding_window_view(values, window)
    out[window - 1:] = views.max(axis=1) if maximum else views.min(axis=1)
    return out


def build_features(bars: np.ndarray) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    n = len(bars)
    o, h, low, c = (bars[field].astype(np.float64, copy=False) for field in ("o", "h", "l", "c"))
    qv = bars["qv"].astype(np.float64, copy=False)
    buy_qv = bars["taker_buy_qv"].astype(np.float64, copy=False)
    trades = bars["trades"].astype(np.float64, copy=False)
    imb1 = np.divide(2 * buy_qv - qv, qv, out=np.zeros(n), where=qv > 0)
    qv5 = _rolling_sum(qv, 5)
    buy5 = _rolling_sum(buy_qv, 5)
    trade5 = _rolling_sum(trades, 5)
    imb5 = np.divide(2 * buy5 - qv5, qv5, out=np.zeros(n), where=qv5 > 0)
    qv15 = _rolling_sum(qv, 15)
    buy15 = _rolling_sum(buy_qv, 15)
    imb15 = np.divide(2 * buy15 - qv15, qv15, out=np.zeros(n), where=qv15 > 0)
    med_qv5 = _rolling_median_prior(qv5, 144, 4)
    med_trade5 = _rolling_median_prior(trade5, 144, 4)
    high5 = _rolling_extreme(h, 5, True)
    low5 = _rolling_extreme(low, 5, False)
    open5 = np.full(n, np.nan, dtype=np.float64)
    open5[4:] = o[:-4]
    ret1 = c / o - 1
    ret5 = c / open5 - 1
    ret15 = np.full(n, np.nan, dtype=np.float64)
    ret15[14:] = c[14:] / o[:-14] - 1
    ret60 = np.full(n, np.nan, dtype=np.float64)
    ret60[59:] = c[59:] / o[:-59] - 1
    candle_range5 = high5 - low5
    close_loc5 = np.divide(c - low5, candle_range5, out=np.full(n, 0.5), where=candle_range5 > 0)
    upper_wick = np.divide(high5 - np.maximum(open5, c), c, out=np.zeros(n), where=c > 0)
    lower_wick = np.divide(np.minimum(open5, c) - low5, c, out=np.zeros(n), where=c > 0)
    logret = np.zeros(n, dtype=np.float64)
    logret[1:] = np.log(c[1:] / c[:-1])
    vol60 = np.sqrt(np.maximum(0, _rolling_mean(logret * logret, 60)))
    true_range = np.maximum(h - low, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(low - np.roll(c, 1))))
    true_range[0] = h[0] - low[0]
    atr14 = _rolling_mean(true_range, 14)
    qv_multiple = np.divide(qv5, med_qv5, out=np.full(n, np.nan), where=med_qv5 > 0)
    trade_multiple = np.divide(trade5, med_trade5, out=np.full(n, np.nan), where=med_trade5 > 0)
    features = np.column_stack((imb1, imb5, imb15, qv_multiple, trade_multiple,
                                ret1, ret5, ret15, ret60,
                                np.divide(candle_range5, c, out=np.zeros(n), where=c > 0),
                                close_loc5, upper_wick, lower_wick, vol60))
    parts = {"imb1": imb1, "imb5": imb5, "qv5": qv5, "med_qv5": med_qv5,
             "high5": high5, "low5": low5, "ret5": ret5, "atr14": atr14,
             "features": features}
    return features, parts


def _funding_sum(times: np.ndarray, rates: np.ndarray, start_ms: int, end_ms: int) -> float:
    left = bisect.bisect_right(times, start_ms)
    right = bisect.bisect_right(times, end_ms)
    return float(np.sum(rates[left:right]))


def _simulate_trade(bars: np.ndarray, entry_index: int, direction: int, stop: float,
                    target: float, funding_times: np.ndarray, funding_rates: np.ndarray) -> dict:
    entry = float(bars[entry_index]["o"])
    first = entry_index
    end = min(entry_index + MAX_HOLD_MINUTES, len(bars))
    exit_index = end - 1
    exit_price = float(bars[exit_index]["c"])
    reason = "time"
    for index in range(first, end):
        bar = bars[index]
        op, high, low = float(bar["o"]), float(bar["h"]), float(bar["l"])
        if direction > 0:
            stop_hit, target_hit = low <= stop, high >= target
            if stop_hit:
                exit_index, exit_price, reason = index, min(op, stop), "stop"
                break
            if target_hit:
                exit_index, exit_price, reason = index, max(op, target), "target"
                break
        else:
            stop_hit, target_hit = high >= stop, low <= target
            if stop_hit:
                exit_index, exit_price, reason = index, max(op, stop), "stop"
                break
            if target_hit:
                exit_index, exit_price, reason = index, min(op, target), "target"
                break
    entry_ms = int(bars[entry_index]["t"])
    exit_ms = int(bars[exit_index]["t"]) + 60_000
    funding_sum = _funding_sum(funding_times, funding_rates, entry_ms, exit_ms)
    gross_return = direction * (exit_price / entry - 1)
    outcome = {"exit_index": int(exit_index), "exit_ms": exit_ms, "exit_price": exit_price,
               "reason": reason, "gross_return_pct": 100 * gross_return,
               "funding_rate_sum": funding_sum}
    for label, side_cost in SIDE_COSTS.items():
        net_return = gross_return - side_cost - side_cost * (exit_price / entry) - direction * funding_sum
        outcome[f"net_return_{label}_pct"] = 100 * net_return
    return outcome


def build_events(symbol: str, bars: np.ndarray, funding_times: np.ndarray,
                 funding_rates: np.ndarray) -> list[dict]:
    features, parts = build_features(bars)
    records = []
    start_index = 148
    end_index = len(bars) - MAX_HOLD_MINUTES - 1
    for index in range(start_index, end_index):
        imbalance = float(parts["imb5"][index])
        return5 = float(parts["ret5"][index])
        median_volume = float(parts["med_qv5"][index])
        volume5 = float(parts["qv5"][index])
        if not (math.isfinite(median_volume) and median_volume > 0 and volume5 >= 1.5 * median_volume):
            continue
        if imbalance >= 0.55 and return5 <= 0:
            direction = -1
        elif imbalance <= -0.55 and return5 >= 0:
            direction = 1
        else:
            continue
        entry_index = index + 1
        entry = float(bars[entry_index]["o"])
        atr = float(parts["atr14"][index])
        if not math.isfinite(atr) or atr <= 0:
            continue
        buffer = 0.1 * atr
        stop = float(parts["low5"][index] - buffer) if direction > 0 else float(parts["high5"][index] + buffer)
        risk = direction * (entry - stop)
        risk_pct = risk / entry
        if not (MIN_STOP_PCT <= risk_pct <= MAX_STOP_PCT):
            continue
        target = entry + direction * TARGET_R * risk
        vector = features[index]
        if not np.isfinite(vector).all():
            continue
        outcome = _simulate_trade(bars, entry_index, direction, stop, target, funding_times, funding_rates)
        records.append({
            "symbol": symbol, "signal_index": index, "entry_index": entry_index,
            "signal_close_ms": int(bars[index]["t"]) + 60_000,
            "entry_ms": int(bars[entry_index]["t"]), "direction": direction,
            "entry_price": entry, "stop_price": stop, "target_price": target,
            "stop_distance_pct": 100 * risk_pct, "features": vector.tolist(),
            **outcome,
        })
    return records


def _period_bounds(name: str) -> tuple[int, int]:
    starts = {"train": MONTH_START, "validation": VALIDATION_START,
              "confirmation": CONFIRMATION_START}
    ends = {"train": VALIDATION_START, "validation": CONFIRMATION_START,
            "confirmation": END_EXCLUSIVE}
    return int(starts[name].timestamp() * 1000), int(ends[name].timestamp() * 1000)


def _within_period(records: list[dict], name: str) -> list[dict]:
    start, end = _period_bounds(name)
    return [row for row in records if start <= row["entry_ms"] < end and row["exit_ms"] < end]


def _decluster_training(records: list[dict]) -> list[dict]:
    selected = []
    next_allowed: dict[str, int] = {}
    for row in sorted(records, key=lambda item: (item["symbol"], item["entry_ms"])):
        if row["entry_ms"] >= next_allowed.get(row["symbol"], 0):
            selected.append(row)
            next_allowed[row["symbol"]] = row["entry_ms"] + MAX_HOLD_MINUTES * 60_000
    return sorted(selected, key=lambda item: (item["entry_ms"], item["symbol"]))


def _choose_trades(records: list[dict], threshold: float) -> list[dict]:
    chosen = []
    next_allowed: dict[str, int] = {}
    for row in sorted(records, key=lambda item: (item["entry_ms"], item["symbol"])):
        if row.get("probability_win", 0.0) < threshold:
            continue
        if row["entry_ms"] < next_allowed.get(row["symbol"], 0):
            continue
        chosen.append(row)
        next_allowed[row["symbol"]] = row["exit_ms"] + COOLDOWN_MINUTES * 60_000
    return chosen


def _portfolio_drawdown(trades: list[dict], bars_by_symbol: dict[str, np.ndarray], cost_label: str) -> tuple[float, float]:
    deltas: dict[int, float] = {}
    sleeve_fraction = 0.25
    for trade in trades:
        bars = bars_by_symbol[trade["symbol"]]
        direction = trade["direction"]
        entry = trade["entry_price"]
        entry_index = trade["entry_index"]
        exit_index = trade["exit_index"]
        side_cost = SIDE_COSTS[cost_label]
        prior = 0.0
        for index in range(entry_index, exit_index + 1):
            bar = bars[index]
            is_exit = index == exit_index
            if is_exit:
                current = trade[f"net_return_{cost_label}_pct"] / 100
            else:
                mark = float(bar["l"] if direction > 0 else bar["h"])
                elapsed_funding = _funding_sum(
                    trade["funding_times"], trade["funding_rates"],
                    int(bars[entry_index]["t"]), int(bar["t"]) + 60_000)
                current = (direction * (mark / entry - 1) - side_cost
                           - side_cost * (mark / entry) - direction * elapsed_funding)
            timestamp = int(bar["t"]) + 60_000
            deltas[timestamp] = deltas.get(timestamp, 0.0) + sleeve_fraction * (current - prior)
            prior = current
    equity = 100.0
    peak = equity
    max_drawdown = 0.0
    for timestamp in sorted(deltas):
        equity += deltas[timestamp]
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, 100 * (peak - equity) / peak)
    return max_drawdown, equity - 100.0


def _metrics(trades: list[dict], bars_by_symbol: dict[str, np.ndarray], cost_label: str) -> dict:
    values = [float(row[f"net_return_{cost_label}_pct"]) for row in trades]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    mean_win = math.fsum(wins) / len(wins) if wins else None
    mean_loss = math.fsum(losses) / len(losses) if losses else None
    payoff = mean_win / abs(mean_loss) if mean_win is not None and mean_loss is not None else None
    drawdown, portfolio_return = _portfolio_drawdown(trades, bars_by_symbol, cost_label)
    win_rate = len(wins) / len(values) if values else None
    ev = math.fsum(values) / len(values) if values else None
    checks = {
        "at_least_30_closed_trades": len(values) >= MIN_SCREEN_TRADES,
        "win_rate_at_least_70_pct": win_rate is not None and win_rate >= 0.70,
        "net_payoff_at_least_1_to_1": payoff is not None and payoff >= 1.0,
        "net_ev_above_1_2_pct": ev is not None and ev > 1.2,
        "max_drawdown_at_most_10_pct": drawdown <= 10.0,
    }
    return {
        "closed_trades": len(values), "wins": len(wins), "losses": len(losses),
        "win_rate_pct": None if win_rate is None else 100 * win_rate,
        "net_payoff_ratio": payoff,
        "ev_net_pct_per_trade_on_committed_notional": ev,
        "max_adverse_drawdown_pct": drawdown,
        "portfolio_return_pct_non_compounded_25pct_sleeves": portfolio_return,
        "gate_checks": checks,
        "passes_all_gates": all(checks.values()),
    }


def _score_period(records: list[dict], name: str) -> list[dict]:
    start, end = _period_bounds(name)
    return [row for row in records if start <= row["entry_ms"] < end and row["exit_ms"] < end]


def _gate_for_threshold(records: list[dict], bars_by_symbol: dict[str, np.ndarray], threshold: float) -> dict:
    trades = _choose_trades(records, threshold)
    metrics = {label: _metrics(trades, bars_by_symbol, label) for label in SIDE_COSTS}
    passes = all(value["passes_all_gates"] for value in metrics.values())
    return {"threshold": threshold, "trades": len(trades), "by_cost": metrics, "passes_all_gates_both_costs": passes}


def _funding_for_trade_metrics(records: list[dict], funding_by_symbol: dict[str, tuple[np.ndarray, np.ndarray]]) -> None:
    for row in records:
        row["funding_times"], row["funding_rates"] = funding_by_symbol[row["symbol"]]


def _public_trade_record(row: dict) -> dict:
    return {key: value for key, value in row.items() if key not in ("features", "funding_times", "funding_rates")}


def _write_trade_csv(path: Path, rows: list[tuple[str, dict]]) -> None:
    fields = ["period", "symbol", "entry_ms", "exit_ms", "direction", "entry_price",
              "stop_price", "target_price", "exit_price", "reason", "gross_return_pct",
              "net_return_base_pct", "net_return_stress_pct", "probability_win"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for period, row in rows:
            writer.writerow({"period": period, **{key: row.get(key) for key in fields if key != "period"}})


def run(skip_download: bool = False) -> dict:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if skip_download:
        archive_manifest = []
        for symbol in SYMBOLS:
            for month in _month_sequence(FIRST_MONTH, LAST_MONTH):
                _, target, checksum_path = _archive_paths(symbol, month)
                if not target.exists() or not checksum_path.exists():
                    raise FileNotFoundError(f"missing archive {target}; omit --skip-download")
                payload = target.read_bytes()
                expected = _checksum(checksum_path.read_bytes())
                if hashlib.sha256(payload).hexdigest() != expected:
                    raise ValueError(f"archive checksum mismatch: {target}")
                archive_manifest.append({"symbol": symbol, "month": month, "sha256": expected,
                                         "bytes": len(payload), "path": str(target.relative_to(ROOT))})
    else:
        archive_manifest = download_archives()

    bars_by_symbol: dict[str, np.ndarray] = {}
    funding_by_symbol: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    input_manifest = []
    funding_manifest = []
    all_events = []
    for symbol in SYMBOLS:
        print(f"loading and evaluating {symbol}", flush=True)
        bars, month_manifest = load_symbol_bars(symbol)
        funding_times, funding_rates, funding_rows = load_funding(symbol)
        bars_by_symbol[symbol] = bars
        funding_by_symbol[symbol] = (funding_times, funding_rates)
        input_manifest.extend(month_manifest)
        funding_manifest.extend(funding_rows)
        events = build_events(symbol, bars, funding_times, funding_rates)
        all_events.extend(events)
        print(f"{symbol}: bars={len(bars)} funding={len(funding_times)} events={len(events)}", flush=True)

    _funding_for_trade_metrics(all_events, funding_by_symbol)
    train_rows = _decluster_training(_score_period(all_events, "train"))
    validation_rows = _score_period(all_events, "validation")
    confirmation_rows = _score_period(all_events, "confirmation")
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
    except ImportError as exc:
        raise RuntimeError("install the project tree-research extra to run the frozen ML model") from exc

    if len(train_rows) < MIN_TRAINING_EVENTS or len({int(row["net_return_base_pct"] > 0) for row in train_rows}) < 2:
        static_validation = _choose_trades(validation_rows, 0.0)
        static_confirmation = _choose_trades(confirmation_rows, 0.0)
        static_metrics = {
            "validation": {label: _metrics(static_validation, bars_by_symbol, label) for label in SIDE_COSTS},
            "confirmation_diagnostic": {label: _metrics(static_confirmation, bars_by_symbol, label)
                                        for label in SIDE_COSTS},
        }
        report = {
            "schema_version": 1, "series": "futures_flow_absorption_20260927",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "decision": "insufficient_training_events", "deployable": False,
            "full_goal_validated": False,
            "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "universe": list(SYMBOLS), "timeframe": "USD-M Futures 1m klines",
            "first_month": FIRST_MONTH, "last_month": LAST_MONTH,
            "bars_per_symbol": {symbol: len(bars) for symbol, bars in bars_by_symbol.items()},
            "funding_points_per_symbol": {symbol: len(values[0]) for symbol, values in funding_by_symbol.items()},
            "training_events": len(train_rows), "minimum_training_events": MIN_TRAINING_EVENTS,
            "validation_events": len(validation_rows), "confirmation_events": len(confirmation_rows),
            "target_and_execution": {"target_R_gross": TARGET_R,
                                      "max_hold_minutes": MAX_HOLD_MINUTES,
                                      "cooldown_minutes_after_exit": COOLDOWN_MINUTES,
                                      "side_costs_including_taker_and_slippage": SIDE_COSTS,
                                      "committed_notional_basis": "net operation PnL divided by entry notional",
                                      "allocation_per_pair": 0.25, "leverage": 1.0,
                                      "funding_included": True,
                                      "same_bar_stop_target_order": "stop first",
                                      "live_orders_enabled": False},
            "unfiltered_signal_diagnostic": static_metrics,
            "archive_count": len(archive_manifest), "input_archives": archive_manifest,
            "funding_archive_count": len(funding_manifest), "funding_archives": funding_manifest,
            "orders_sent": 0, "jev_calls": 0,
        }
        OUTPUT_JSON.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        _write_trade_csv(OUTPUT_STATIC_TRADES,
                         [("validation", row) for row in static_validation]
                         + [("confirmation_diagnostic", row) for row in static_confirmation])
        return report

    x_train = np.asarray([row["features"] for row in train_rows], dtype=np.float64)
    y_train = np.asarray([row["net_return_base_pct"] > 0 for row in train_rows], dtype=np.int8)
    model = HistGradientBoostingClassifier(
        early_stopping=False, l2_regularization=10.0, learning_rate=0.05,
        max_iter=100, max_leaf_nodes=7, min_samples_leaf=40, random_state=548,
    )
    model.fit(x_train, y_train)
    for rows in (validation_rows, confirmation_rows):
        if rows:
            probabilities = model.predict_proba(np.asarray([row["features"] for row in rows]))[:, 1]
            for row, probability in zip(rows, probabilities):
                row["probability_win"] = float(probability)

    validation_gates = [_gate_for_threshold(validation_rows, bars_by_symbol, threshold) for threshold in THRESHOLDS]
    passing = [row for row in validation_gates if row["passes_all_gates_both_costs"]]
    selected = max(
        passing,
        key=lambda row: min(m["ev_net_pct_per_trade_on_committed_notional"] for m in row["by_cost"].values()),
        default=None,
    )
    confirmation = None
    selected_validation_trades: list[dict] = []
    selected_confirmation_trades: list[dict] = []
    if selected is not None:
        threshold = selected["threshold"]
        selected_validation_trades = _choose_trades(validation_rows, threshold)
        selected_confirmation_trades = _choose_trades(confirmation_rows, threshold)
        confirmation = {
            "threshold_frozen_from_2025": threshold,
            "by_cost": {label: _metrics(selected_confirmation_trades, bars_by_symbol, label)
                        for label in SIDE_COSTS},
            "trades": [_public_trade_record(row) for row in selected_confirmation_trades],
        }

    validation_all = _gate_for_threshold(validation_rows, bars_by_symbol, 0.0)
    report = {
        "schema_version": 1,
        "series": "futures_flow_absorption_20260927",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "decision": "candidate_selected_on_validation" if selected else "no_threshold_passed_validation",
        "deployable": False, "full_goal_validated": False,
        "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "universe": list(SYMBOLS), "timeframe": "USD-M Futures 1m klines",
        "first_month": FIRST_MONTH, "last_month": LAST_MONTH,
        "training_events_after_60m_declustering": len(train_rows),
        "training_wins": int(sum(y_train)), "validation_events": len(validation_rows),
        "confirmation_events": len(confirmation_rows), "feature_names": list(FEATURE_NAMES),
        "model": {"name": "HistGradientBoostingClassifier", "early_stopping": False,
                  "l2_regularization": 10.0, "learning_rate": 0.05, "max_iter": 100,
                  "max_leaf_nodes": 7, "min_samples_leaf": 40, "random_state": 548},
        "target_and_execution": {"target_R_gross": TARGET_R,
                                  "max_hold_minutes": MAX_HOLD_MINUTES,
                                  "cooldown_minutes_after_exit": COOLDOWN_MINUTES,
                                  "side_costs_including_taker_and_slippage": SIDE_COSTS,
                                  "committed_notional_basis": "net operation PnL divided by entry notional",
                                  "allocation_per_pair": 0.25, "leverage": 1.0,
                                  "funding_included": True,
                                  "same_bar_stop_target_order": "stop first",
                                  "live_orders_enabled": False},
        "threshold_candidates": list(THRESHOLDS),
        "validation_all_events_no_ml_gate": validation_all,
        "validation_thresholds": validation_gates,
        "selected_threshold": None if selected is None else selected["threshold"],
        "selected_validation": selected,
        "confirmation": confirmation,
        "validation_sample_minimum": MIN_SCREEN_TRADES,
        "validation_passed": selected is not None,
        "validation_needs_100_trades_for_initial_confirmation": bool(
            selected is not None and selected["trades"] < MIN_VALIDATION_TRADES),
        "archive_count": len(archive_manifest), "input_archives": archive_manifest,
        "funding_archive_count": len(funding_manifest), "funding_archives": funding_manifest,
        "orders_sent": 0, "jev_calls": 0,
    }
    OUTPUT_JSON.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    if selected is not None:
        all_selected = [("validation", row) for row in selected_validation_trades]
        all_selected.extend(("confirmation", row) for row in selected_confirmation_trades)
        _write_trade_csv(OUTPUT_TRADES, all_selected)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-download", action="store_true", help="require and verify all cached archives")
    parser.add_argument("--download-only", action="store_true", help="download and verify monthly archives only")
    args = parser.parse_args()
    if args.download_only:
        rows = download_archives()
        print(f"verified {len(rows)} monthly archives")
        return
    report = run(skip_download=args.skip_download)
    print(f"{report['decision']}: train={report.get('training_events_after_60m_declustering', report.get('training_events'))}; "
          f"validation={report.get('validation_events')}; confirmation={report.get('confirmation_events')}; "
          f"selected_threshold={report.get('selected_threshold')}")


if __name__ == "__main__":
    main()
