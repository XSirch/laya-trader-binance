"""Walk-forward study of external macro features for weekly spot decisions."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import platform
import time
from urllib.parse import urlencode
from urllib.request import urlopen

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .binance_data import HOUR_MS, load_cached_range

SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
SIDE_COSTS = (0.0015, 0.003)
SERIES = ("NASDAQCOM", "VIXCLS", "DTWEXBGS")
MACRO_LAGS = (1, 5, 20)
PRICE_LAGS = (1, 4, 12)
MIN_TRAINING_WEEKS = 52
RIDGE_ALPHA = 1.0
MAX_AGE_DAYS = {"NASDAQCOM": 7, "VIXCLS": 7, "DTWEXBGS": 14}
FIRST_MONTH = "2023-01"
LAST_MONTH = "2026-08"
OBSERVATION_LOOKBACK_DAYS = 90
FINAL_HOLDOUT = date(2025, 1, 6)
INITIAL_EQUITY = 1.0
WEEK_MS = 7 * 24 * HOUR_MS
ROOT = Path.cwd()
MARKET_ROOT = ROOT / "data" / "binance" / "spot" / "1h"
CACHE_ROOT = ROOT / ".cache" / "macro_external_alpha"
PROTOCOL_PATH = ROOT / "docs" / "macro_external_alpha_protocol_2026-09-27.md"
SOURCES_PATH = ROOT / "docs" / "macro_crypto_sources_2026-09-27.md"
SCRIPT_PATH = ROOT / "src" / "jev_trader" / "macro_external_alpha_research.py"
REPORT_PATH = ROOT / "docs" / "macro_external_alpha_research_2026-09-27.md"
JSON_PATH = ROOT / "results" / "macro_external_alpha_research.json"
FORECASTS_PATH = ROOT / "results" / "macro_external_alpha_forecasts.csv"
CURVES_PATH = ROOT / "results" / "macro_external_alpha_curves.csv"
FILLS_PATH = ROOT / "results" / "macro_external_alpha_fills.csv"
UTC = timezone.utc


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def utc_datetime(timestamp_ms: int) -> datetime:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)


def iso(timestamp_ms: int) -> str:
    return utc_datetime(timestamp_ms).isoformat().replace("+00:00", "Z")


def utc_midnight_ms(value: date) -> int:
    return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp() * 1000)


def resolve_schedule():
    frames, manifest = load_cached_range(
        list(SYMBOLS), FIRST_MONTH, LAST_MONTH, MARKET_ROOT
    )
    bars_by_symbol = {
        symbol: {bar.open_ms: bar for bar in bars}
        for symbol, bars in frames.items()
    }
    common = sorted(set.intersection(*(set(bars) for bars in bars_by_symbol.values())))
    if not common:
        raise ValueError("the selected assets have no common hourly timestamps")
    archive_gaps = [gap for row in manifest for gap in row.get("gaps", [])]
    last_gap_boundary = max(
        (row["before_open_ms"] for row in archive_gaps), default=0
    )
    start = next(
        (
            timestamp
            for timestamp in common
            if timestamp >= last_gap_boundary
            and utc_datetime(timestamp).weekday() == 0
            and utc_datetime(timestamp).hour == 0
        ),
        None,
    )
    if start is None:
        raise ValueError("no complete Monday boundary follows the last data gap")
    terminal_candidates = [
        timestamp
        for timestamp in common
        if timestamp >= start
        and utc_datetime(timestamp).weekday() == 0
        and utc_datetime(timestamp).hour == 0
    ]
    if len(terminal_candidates) < MIN_TRAINING_WEEKS + 2:
        raise ValueError("the market tape is too short for the fixed training window")
    terminal = terminal_candidates[-1]
    for symbol, bars in bars_by_symbol.items():
        for timestamp in range(start, terminal + 1, HOUR_MS):
            if timestamp not in bars:
                raise ValueError(f"unresolved hourly gap for {symbol} at {timestamp}")
    boundaries = terminal_candidates
    if any(right - left != WEEK_MS for left, right in zip(boundaries, boundaries[1:])):
        raise ValueError("weekly UTC boundaries are not consecutive")
    for timestamp in boundaries:
        if any(timestamp not in bars_by_symbol[symbol] for symbol in SYMBOLS):
            raise ValueError("a weekly UTC execution boundary is missing")
    archive_payload = json.dumps(
        manifest, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return bars_by_symbol, manifest, boundaries, sha256(archive_payload)


def snapshot_path(series_id: str, vintage: date) -> Path:
    return CACHE_ROOT / series_id / f"{vintage.isoformat()}.csv"


def fetch_snapshot(series_id: str, vintage: date) -> dict:
    path = snapshot_path(series_id, vintage)
    if path.exists():
        payload = path.read_bytes()
        try:
            rows = parse_snapshot(series_id, vintage, payload)
            return {"series": series_id, "vintage": vintage, "path": path,
                    "payload": payload, "rows": rows, "cache_hit": True}
        except (ValueError, UnicodeError, csv.Error):
            pass

    query = urlencode({
        "id": series_id,
        "cosd": (vintage - timedelta(days=OBSERVATION_LOOKBACK_DAYS)).isoformat(),
        "coed": vintage.isoformat(),
        "vintage_date": vintage.isoformat(),
    })
    url = f"https://alfred.stlouisfed.org/graph/alfredgraph.csv?{query}"
    last_error = None
    payload = b""
    for attempt in range(5):
        try:
            with urlopen(url, timeout=20) as response:
                if response.status != 200:
                    raise OSError(f"ALFRED HTTP {response.status}")
                payload = response.read()
            rows = parse_snapshot(series_id, vintage, payload)
            break
        except Exception as exc:  # network and transient response failures
            last_error = exc
            if attempt == 4:
                raise RuntimeError(f"ALFRED request failed for {series_id} {vintage}") from exc
            time.sleep(0.5 * (2 ** attempt))
    else:  # pragma: no cover - guarded by the retry branch above
        raise RuntimeError(f"ALFRED request failed: {last_error}")

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".csv.tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)
    return {"series": series_id, "vintage": vintage, "path": path,
            "payload": payload, "rows": rows, "cache_hit": False}


def parse_snapshot(series_id: str, vintage: date, payload: bytes) -> list[tuple[date, float]]:
    decoded = payload.decode("utf-8", errors="strict")
    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames or reader.fieldnames[0] != "observation_date":
        raise ValueError("unexpected ALFRED CSV header")
    if len(reader.fieldnames) != 2 or not reader.fieldnames[1].startswith(series_id + "_"):
        raise ValueError("ALFRED response does not match the requested series")
    value_field = reader.fieldnames[1]
    values = []
    for row in reader:
        raw_date, raw_value = row.get("observation_date", ""), row.get(value_field, "")
        if not raw_date or not raw_value or raw_value == ".":
            continue
        observed = date.fromisoformat(raw_date)
        if observed > vintage:
            raise ValueError("ALFRED vintage contains an observation after its vintage date")
        number = float(raw_value)
        if not math.isfinite(number) or number <= 0:
            raise ValueError("macro price/index observations must be finite and positive")
        values.append((observed, number))
    if values != sorted(values, key=lambda row: row[0]):
        raise ValueError("ALFRED observations are not in chronological order")
    return values


def fetch_all_snapshots(boundaries: list[int]):
    requests = []
    for timestamp in boundaries[:-1]:
        decision_day = utc_datetime(timestamp).date() - timedelta(days=1)
        for series_id in SERIES:
            requests.append((series_id, decision_day))
    snapshots = {}
    cache_hits = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(fetch_snapshot, series_id, vintage): (series_id, vintage)
            for series_id, vintage in requests
        }
        for count, future in enumerate(as_completed(futures), start=1):
            item = future.result()
            key = (item["series"], item["vintage"])
            if key in snapshots:
                raise ValueError("duplicate ALFRED snapshot key")
            snapshots[key] = item
            cache_hits += int(item["cache_hit"])
            if count % 60 == 0 or count == len(futures):
                print(f"ALFRED snapshots {count}/{len(futures)}")
    if len(snapshots) != len(requests):
        raise ValueError("ALFRED snapshot inventory is incomplete")
    return snapshots, cache_hits


def macro_features(snapshot_items: dict, week_start: int):
    decision_day = utc_datetime(week_start).date() - timedelta(days=1)
    features = {}
    provenance = {}
    eligible = True
    for series_id in SERIES:
        item = snapshot_items[(series_id, decision_day)]
        values = item["rows"]
        if not values:
            provenance[series_id] = {
                "vintage_date": decision_day.isoformat(),
                "latest_observation_date": None,
                "age_calendar_days": None,
                "snapshot_sha256": sha256(item["payload"]),
                "status": "no_observations_in_snapshot_window",
            }
            eligible = False
            continue
        final_date, final_value = values[-1]
        if final_date > decision_day:
            raise ValueError("macro feature uses an observation from after the decision")
        age = (decision_day - final_date).days
        enough_history = len(values) >= max(MACRO_LAGS) + 1
        fresh_enough = age <= MAX_AGE_DAYS[series_id]
        provenance[series_id] = {
            "vintage_date": decision_day.isoformat(),
            "latest_observation_date": final_date.isoformat(),
            "age_calendar_days": age,
            "snapshot_sha256": sha256(item["payload"]),
            "status": "available" if enough_history and fresh_enough else (
                "insufficient_history" if not enough_history else "stale"
            ),
        }
        eligible &= enough_history and fresh_enough
        if not enough_history or not fresh_enough:
            continue
        for lag in MACRO_LAGS:
            prior_date, prior_value = values[-(lag + 1)]
            if prior_date >= final_date or prior_value <= 0:
                raise ValueError("invalid macro feature observation order")
            features[f"{series_id}_log_change_{lag}"] = math.log(final_value / prior_value)
    return (features if eligible else None), provenance


def price_features(bars_by_symbol: dict, boundaries: list[int], symbol: str, index: int):
    bars = bars_by_symbol[symbol]
    # The latest weekly open available at Sunday's decision is one boundary back.
    current_price = bars[boundaries[index - 1]].open
    result = {}
    for lag in PRICE_LAGS:
        prior_price = bars[boundaries[index - lag - 1]].open
        result[f"own_return_{lag}w"] = current_price / prior_price - 1.0
    return result


def model_features(price: dict, macro: dict, model: str):
    keys = sorted(price)
    values = [price[key] for key in keys]
    if model == "price_plus_macro":
        macro_keys = sorted(macro)
        keys += macro_keys
        values += [macro[key] for key in macro_keys]
    elif model != "price_only":
        raise ValueError(f"unknown model {model}")
    if not all(math.isfinite(value) for value in values):
        raise ValueError("nonfinite feature")
    return keys, np.asarray(values, dtype=float)


def build_forecasts(bars_by_symbol: dict, boundaries: list[int], snapshots: dict):
    features_by_week = {}
    provenance_by_week = {}
    for index, timestamp in enumerate(boundaries[:-1]):
        macro, provenance = macro_features(snapshots, timestamp)
        features_by_week[index] = macro
        provenance_by_week[index] = provenance

    forecasts = []
    for symbol in SYMBOLS:
        rows = []
        bars = bars_by_symbol[symbol]
        for index in range(13, len(boundaries) - 1):
            timestamp, exit_timestamp = boundaries[index], boundaries[index + 1]
            price = price_features(bars_by_symbol, boundaries, symbol, index)
            actual = bars[exit_timestamp].open / bars[timestamp].open - 1.0
            if not math.isfinite(actual):
                raise ValueError("weekly target is nonfinite")
            rows.append({
                "index": index,
                "timestamp_ms": timestamp,
                "exit_timestamp_ms": exit_timestamp,
                "price": price,
                "macro": features_by_week[index],
                "actual": actual,
            })

        for row in rows:
            index = row["index"]
            for model in ("price_only", "price_plus_macro"):
                if model == "price_plus_macro" and row["macro"] is None:
                    continue
                completed_train = [
                    sample for sample in rows
                    if sample["index"] <= index - 2
                    and (model == "price_only" or sample["macro"] is not None)
                ]
                if len(completed_train) < MIN_TRAINING_WEEKS:
                    continue
                keys, current_x = model_features(row["price"], row["macro"], model)
                x_train = []
                y_train = []
                for sample in completed_train:
                    train_keys, train_x = model_features(
                        sample["price"], sample["macro"], model
                    )
                    if train_keys != keys:
                        raise ValueError("feature order changed inside a walk-forward fit")
                    x_train.append(train_x)
                    y_train.append(sample["actual"])
                estimator = make_pipeline(
                    StandardScaler(), Ridge(alpha=RIDGE_ALPHA, fit_intercept=True)
                )
                estimator.fit(np.vstack(x_train), np.asarray(y_train))
                prediction = float(estimator.predict(current_x.reshape(1, -1))[0])
                if not math.isfinite(prediction):
                    raise ValueError("model emitted a nonfinite prediction")
                train_mean = float(np.mean(y_train))
                forecasts.append({
                    "index": index,
                    "signal_timestamp_ms": row["timestamp_ms"],
                    "signal_sunday_utc": (utc_datetime(row["timestamp_ms"]).date()
                                          - timedelta(days=1)).isoformat(),
                    "exit_timestamp_ms": row["exit_timestamp_ms"],
                    "symbol": symbol,
                    "model": model,
                    "prediction": prediction,
                    "actual": row["actual"],
                    "training_mean": train_mean,
                    "training_count": len(completed_train),
                    "training_last_completed_exit_ms": boundaries[index - 1],
                    "feature_count": len(keys),
                })
    forecasts.sort(key=lambda row: (row["index"], row["symbol"], row["model"]))
    return forecasts, provenance_by_week


def forecast_scores(forecasts: list[dict], start_index: int, end_index: int):
    output = {}
    selected = [
        row for row in forecasts if start_index <= row["index"] < end_index
    ]
    common_keys = {
        (row["index"], row["symbol"])
        for row in selected if row["model"] == "price_plus_macro"
    }
    for model in ("price_only", "price_plus_macro"):
        rows = [row for row in selected if row["model"] == model
                and (row["index"], row["symbol"]) in common_keys]
        if not rows:
            output[model] = {"count": 0}
            continue
        actual = np.asarray([row["actual"] for row in rows], dtype=float)
        pred = np.asarray([row["prediction"] for row in rows], dtype=float)
        mean = np.asarray([row["training_mean"] for row in rows], dtype=float)
        output[model] = {
            "count": len(rows),
            "unique_signal_weeks": len({row["index"] for row in rows}),
            "mse": float(np.mean((actual - pred) ** 2)),
            "mae": float(np.mean(np.abs(actual - pred))),
            "mse_vs_zero": float(np.mean(actual ** 2)),
            "mse_vs_training_mean": float(np.mean((actual - mean) ** 2)),
            "direction_accuracy": float(np.mean((actual > 0) == (pred > 0))),
            "positive_prediction_fraction": float(np.mean(pred > 0)),
        }
    if output["price_only"].get("count") and output["price_plus_macro"].get("count"):
        base = output["price_only"]["mse"]
        macro = output["price_plus_macro"]["mse"]
        output["macro_mse_skill_vs_price_only_pct"] = (
            100 * (1 - macro / base) if base > 0 else None
        )
    return output


def portfolio_replay(bars_by_symbol: dict, boundaries: list[int], forecasts: list[dict],
                     *, model: str, side_cost: float, start_index: int,
                     end_index: int, mode: str = "signal"):
    if mode not in {"signal", "buy_hold", "cash"}:
        raise ValueError("unsupported portfolio replay mode")
    if not 0 <= side_cost < 1 or start_index >= end_index:
        raise ValueError("invalid portfolio replay bounds or cost")
    start_ms, end_ms = boundaries[start_index], boundaries[end_index]
    signal_map = {
        (row["index"], row["symbol"]): row
        for row in forecasts if row["model"] == model
    }
    cash = {symbol: INITIAL_EQUITY / len(SYMBOLS) for symbol in SYMBOLS}
    quantity = {symbol: 0.0 for symbol in SYMBOLS}
    sleeve_start = INITIAL_EQUITY / len(SYMBOLS)
    sleeve_peak_open = {symbol: sleeve_start for symbol in SYMBOLS}
    sleeve_peak_adverse = {symbol: sleeve_start for symbol in SYMBOLS}
    sleeve_dd_open = {symbol: 0.0 for symbol in SYMBOLS}
    sleeve_dd_adverse = {symbol: 0.0 for symbol in SYMBOLS}
    sleeve_exposed_hours = {symbol: 0 for symbol in SYMBOLS}
    fees = turnover = 0.0
    fill_rows = []
    curve = []
    peak_open = peak_adverse = INITIAL_EQUITY
    max_dd_open = max_dd_adverse = 0.0
    exposed_asset_hours = 0
    total_asset_hours = (end_ms - start_ms) // HOUR_MS * len(SYMBOLS)
    threshold = 2 * side_cost / (1 - side_cost)
    candidate_week_rows = []
    active_weeks = profitable_active_weeks = 0
    order_count = 0

    def equity_at(field: str, timestamp: int) -> float:
        if field == "open":
            return math.fsum(
                cash[symbol] + quantity[symbol] * getattr(
                    bars_by_symbol[symbol][timestamp], "open"
                ) for symbol in SYMBOLS
            )
        return math.fsum(
            cash[symbol] + quantity[symbol] * getattr(
                bars_by_symbol[symbol][timestamp], field
            ) for symbol in SYMBOLS
        )

    def desired(index: int, symbol: str) -> bool:
        if mode == "cash":
            return False
        if mode == "buy_hold":
            return index >= start_index
        row = signal_map.get((index, symbol))
        return row is not None and row["prediction"] > threshold

    for timestamp in range(start_ms, end_ms + HOUR_MS, HOUR_MS):
        if any(timestamp not in bars_by_symbol[symbol] for symbol in SYMBOLS):
            raise ValueError(f"portfolio mark missing at {timestamp}")
        pre_by_symbol = {
            symbol: cash[symbol] + quantity[symbol] * bars_by_symbol[symbol][timestamp].open
            for symbol in SYMBOLS
        }
        pre = equity_at("open", timestamp)
        is_week_boundary = timestamp in boundaries
        if is_week_boundary and timestamp < end_ms:
            week_index = boundaries.index(timestamp)
            for symbol in SYMBOLS:
                row = signal_map.get((week_index, symbol)) if mode == "signal" else None
                if mode == "signal":
                    should_hold = row is not None and row["prediction"] > threshold
                    if row is not None:
                        candidate_week_rows.append(row)
                        if should_hold:
                            active_weeks += 1
                            profitable_active_weeks += int(row["actual"] > 0)
                elif mode == "buy_hold":
                    should_hold = True
                else:
                    should_hold = False

                bar = bars_by_symbol[symbol][timestamp]
                if quantity[symbol] > 0 and not should_hold:
                    notional = quantity[symbol] * bar.open
                    fee = notional * side_cost
                    cash[symbol] += notional - fee
                    fees += fee
                    turnover += notional
                    order_count += 1
                    fill_rows.append({
                        "mode": mode, "model": model, "side_cost": side_cost,
                        "timestamp_utc": iso(timestamp), "symbol": symbol,
                        "side": "SELL", "price": bar.open,
                        "quantity": quantity[symbol], "notional": notional,
                        "fee": fee, "prediction": row["prediction"] if row else None,
                        "threshold": threshold,
                    })
                    quantity[symbol] = 0.0
                elif quantity[symbol] == 0 and should_hold:
                    notional = cash[symbol] / (1.0 + side_cost)
                    fee = notional * side_cost
                    quantity[symbol] = notional / bar.open
                    cash[symbol] = 0.0
                    fees += fee
                    turnover += notional
                    order_count += 1
                    fill_rows.append({
                        "mode": mode, "model": model, "side_cost": side_cost,
                        "timestamp_utc": iso(timestamp), "symbol": symbol,
                        "side": "BUY", "price": bar.open,
                        "quantity": quantity[symbol], "notional": notional,
                        "fee": fee, "prediction": row["prediction"] if row else None,
                        "threshold": threshold,
                    })

        if timestamp == end_ms:
            for symbol in SYMBOLS:
                if quantity[symbol] <= 0:
                    continue
                bar = bars_by_symbol[symbol][timestamp]
                notional = quantity[symbol] * bar.open
                fee = notional * side_cost
                cash[symbol] += notional - fee
                fees += fee
                turnover += notional
                order_count += 1
                fill_rows.append({
                    "mode": mode, "model": model, "side_cost": side_cost,
                    "timestamp_utc": iso(timestamp), "symbol": symbol,
                    "side": "SELL", "price": bar.open,
                    "quantity": quantity[symbol], "notional": notional,
                    "fee": fee, "prediction": None, "threshold": threshold,
                })
                quantity[symbol] = 0.0

        post = equity_at("open", timestamp)
        high = math.fsum(
            cash[symbol] + quantity[symbol] * bars_by_symbol[symbol][timestamp].high
            for symbol in SYMBOLS
        )
        low = math.fsum(
            cash[symbol] + quantity[symbol] * bars_by_symbol[symbol][timestamp].low
            for symbol in SYMBOLS
        )
        for symbol in SYMBOLS:
            bar = bars_by_symbol[symbol][timestamp]
            sleeve_post = cash[symbol] + quantity[symbol] * bar.open
            sleeve_high = cash[symbol] + quantity[symbol] * bar.high
            sleeve_low = cash[symbol] + quantity[symbol] * bar.low
            sleeve_peak_open[symbol] = max(
                sleeve_peak_open[symbol], pre_by_symbol[symbol], sleeve_post
            )
            sleeve_dd_open[symbol] = max(
                sleeve_dd_open[symbol], 1 - sleeve_post / sleeve_peak_open[symbol]
            )
            sleeve_peak_adverse[symbol] = max(
                sleeve_peak_adverse[symbol], pre_by_symbol[symbol], sleeve_post, sleeve_high
            )
            sleeve_dd_adverse[symbol] = max(
                sleeve_dd_adverse[symbol], 1 - sleeve_low / sleeve_peak_adverse[symbol]
            )
            sleeve_exposed_hours[symbol] += int(quantity[symbol] > 0)
        peak_open = max(peak_open, pre, post)
        max_dd_open = max(max_dd_open, 1 - post / peak_open)
        peak_adverse = max(peak_adverse, pre, post, high)
        max_dd_adverse = max(max_dd_adverse, 1 - low / peak_adverse)
        exposed_asset_hours += sum(quantity[symbol] > 0 for symbol in SYMBOLS)
        curve.append({
            "timestamp_ms": timestamp,
            "timestamp_utc": iso(timestamp),
            "equity_pre": pre,
            "equity_post": post,
            "equity_intrahour_high": high,
            "equity_intrahour_low": low,
        })

    final = equity_at("open", end_ms)
    elapsed_days = (end_ms - start_ms) / (24 * HOUR_MS)
    cagr = (final / INITIAL_EQUITY) ** (365.25 / elapsed_days) - 1 if final > 0 else -1.0
    asset_performance = {}
    for symbol in SYMBOLS:
        sleeve_final = cash[symbol] + quantity[symbol] * bars_by_symbol[symbol][end_ms].open
        sleeve_cagr = (sleeve_final / sleeve_start) ** (365.25 / elapsed_days) - 1 if sleeve_final > 0 else -1.0
        symbol_fills = [row for row in fill_rows if row["symbol"] == symbol]
        asset_performance[symbol] = {
            "initial_equity": sleeve_start,
            "final_equity": sleeve_final,
            "return_pct": 100 * (sleeve_final / sleeve_start - 1),
            "cagr_pct": 100 * sleeve_cagr,
            "max_drawdown_open_pct": 100 * sleeve_dd_open[symbol],
            "max_drawdown_adverse_hourly_pct": 100 * sleeve_dd_adverse[symbol],
            "exposure_pct_hours": 100 * sleeve_exposed_hours[symbol] / (total_asset_hours / len(SYMBOLS)),
            "order_count": len(symbol_fills),
            "fees_initial_equity_units": math.fsum(row["fee"] for row in symbol_fills),
        }
    return {
        "mode": mode, "model": model, "side_cost": side_cost,
        "start_utc": iso(start_ms), "end_utc": iso(end_ms),
        "start_index": start_index, "end_index": end_index,
        "initial_equity": INITIAL_EQUITY, "final_equity": final,
        "return_pct": 100 * (final - 1), "cagr_pct": 100 * cagr,
        "max_drawdown_open_pct": 100 * max_dd_open,
        "max_drawdown_adverse_hourly_pct": 100 * max_dd_adverse,
        "fees_initial_equity_units": fees, "turnover_initial_equity_units": turnover,
        "order_count": order_count,
        "exposure_pct_asset_hours": 100 * exposed_asset_hours / total_asset_hours,
        "evaluated_active_weeks": active_weeks,
        "positive_active_week_fraction_pct": (
            100 * profitable_active_weeks / active_weeks if active_weeks else None
        ),
        "asset_performance": asset_performance,
        "forecast_weeks": len(candidate_week_rows),
        "threshold_gross_return_pct": 100 * threshold,
        "curve": curve,
        "fills": fill_rows,
    }


def period_returns(curve: list[dict], start_ms: int, end_ms: int, cadence: str):
    by_timestamp = {row["timestamp_ms"]: row for row in curve}
    first_dt, last_dt = utc_datetime(start_ms), utc_datetime(end_ms)
    windows = []
    if cadence == "year":
        year = first_dt.year
        while year <= last_dt.year:
            left_dt = datetime(year, 1, 1, tzinfo=UTC)
            right_dt = datetime(year + 1, 1, 1, tzinfo=UTC)
            label = str(year)
            year += 1
            windows.append((label, int(left_dt.timestamp() * 1000), int(right_dt.timestamp() * 1000)))
    elif cadence == "month":
        year, month = first_dt.year, first_dt.month
        while (year, month) <= (last_dt.year, last_dt.month):
            left_dt = datetime(year, month, 1, tzinfo=UTC)
            if month == 12:
                right_dt = datetime(year + 1, 1, 1, tzinfo=UTC)
                year, month = year + 1, 1
            else:
                right_dt = datetime(year, month + 1, 1, tzinfo=UTC)
                month += 1
            label = left_dt.strftime("%Y-%m")
            windows.append((label, int(left_dt.timestamp() * 1000), int(right_dt.timestamp() * 1000)))
    else:
        raise ValueError("cadence must be year or month")

    def mark(target_ms: int):
        timestamp = max(start_ms, min(end_ms, target_ms))
        row = by_timestamp.get(timestamp)
        if row is None:
            candidates = [value for value in by_timestamp if value >= timestamp]
            if not candidates:
                return by_timestamp[max(by_timestamp)]["equity_post"]
            row = by_timestamp[min(candidates)]
        if timestamp == start_ms:
            return row["equity_pre"]
        if timestamp == end_ms:
            return row["equity_post"]
        return row["equity_pre"]

    output = []
    for label, left, right in windows:
        clipped_left, clipped_right = max(start_ms, left), min(end_ms, right)
        if clipped_right <= clipped_left:
            continue
        start_value, end_value = mark(clipped_left), mark(clipped_right)
        output_row = {
            "period": label,
            "partial": clipped_left != left or clipped_right != right,
            "start_utc": iso(clipped_left),
            "end_utc": iso(clipped_right),
            "return_pct": 100 * (end_value / start_value - 1),
        }
        output.append(output_row)
    return output


def enrich_metrics(replay: dict):
    curve = replay["curve"]
    start_ms = int(datetime.fromisoformat(replay["start_utc"].replace("Z", "+00:00")).timestamp() * 1000)
    end_ms = int(datetime.fromisoformat(replay["end_utc"].replace("Z", "+00:00")).timestamp() * 1000)
    replay["annual_returns"] = period_returns(curve, start_ms, end_ms, "year")
    replay["monthly_returns"] = period_returns(curve, start_ms, end_ms, "month")
    del replay["curve"]
    del replay["fills"]
    return replay


def period_index(boundaries: list[int], target: date):
    target_ms = utc_midnight_ms(target)
    for index, timestamp in enumerate(boundaries[:-1]):
        if timestamp >= target_ms:
            return index
    raise ValueError("the fixed holdout start is after the market data")


def write_csv(path: Path, rows: list[dict], fields: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def render_report(result: dict):
    lines = [
        "# Replay de sinais macro externos em horizonte semanal",
        "",
        f"Execução: {result['created_utc']}. O resultado é exploratório e não autoriza ordens.",
        "",
        "## Desenho",
        "",
        "Comparamos Ridge de lags cripto (`price_only`) com o mesmo Ridge acrescido de Nasdaq Composite, VIX e índice amplo do dólar Fed (`price_plus_macro`). O treino é expansivo, por ativo, com no mínimo 52 semanas completas. As vintages ALFRED são consultadas para cada domingo de decisão. A decisão ocorre domingo às 23:00 UTC e pode ser executada somente na abertura da segunda-feira às 00:00 UTC.",
        "",
        f"Período de entradas: {result['schedule']['first_entry_utc']} a {result['schedule']['last_entry_utc']}; liquidação final em {result['schedule']['terminal_utc']}. Previsões por modelo: {result['forecast_count_by_model']}.",
        "",
        f"Arquivos de dados: {result['schedule']['binance_month_archives']} manifest entries; {result['schedule']['hourly_rows_common']} timestamps horários comuns; hash agregado do manifesto `{result['schedule']['archive_manifest_sha256']}`. Vintages consultadas: {result['macro_snapshot_count']} ({result['macro_cache_hits']} lidas do cache local). Semanas com as três séries frescas e histórico suficiente: {result['macro_eligible_feature_weeks']}; primeira semana elegível: {result['first_macro_eligible_week_utc']}.",
        "",
        "## Erro preditivo",
        "",
        "MSE e MAE são retornos simples ao quadrado/absolutos; MSE menor é melhor. A habilidade direcional não equivale a lucro.",
        "",
        "| Período | Modelo | ativo-semanas | semanas UTC únicas | MSE | MAE | MSE zero | MSE média treino | direção correta |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for period_name, scores in result["forecast_scores"].items():
        for model in ("price_only", "price_plus_macro"):
            row = scores[model]
            if not row.get("count"):
                lines.append(f"| {period_name} | {model} | 0 | 0 | — | — | — | — | — |")
                continue
            lines.append(
                f"| {period_name} | {model} | {row['count']} | {row['unique_signal_weeks']} | {row['mse']:.7g} | "
                f"{row['mae']:.5%} | {row['mse_vs_zero']:.7g} | "
                f"{row['mse_vs_training_mean']:.7g} | {row['direction_accuracy']:.2%} |"
            )
        skill = scores.get("macro_mse_skill_vs_price_only_pct")
        lines.append(f"| {period_name} | macro MSE skill vs price_only | — | — | {skill:.2f}% | — | — | — | — |" if skill is not None else f"| {period_name} | macro MSE skill vs price_only | — | — | — | — | — | — | — |")
    lines += [
        "",
        "## Carteiras",
        "",
        "Cada cenário começa com quatro saldos iguais. Compras e vendas são executadas na abertura semanal com custos fixos assumidos. O drawdown adverso usa a máxima antes da mínima de cada candle horário, mesmo quando essa ordem não ocorreu; é um limite compatível com OHLC, não um percurso observado.",
        "",
        "| Janela | custo/lado | regra | retorno líquido | CAGR | DD nas aberturas | limite adverso | % tempo exposto | ordens | retorno ativo semanal positivo |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for period_name, replays in result["portfolio_results"].items():
        for side_cost in SIDE_COSTS:
            for model in ("price_plus_macro", "price_only", "buy_hold", "cash"):
                row = replays[f"{side_cost:.4f}"][model]
                weekly = row["positive_active_week_fraction_pct"]
                weekly_text = "—" if weekly is None else f"{weekly:.1f}%"
                lines.append(
                    f"| {period_name} | {side_cost:.2%} | {model} | "
                    f"{row['return_pct']:.2f}% | {row['cagr_pct']:.2f}% | "
                    f"{row['max_drawdown_open_pct']:.2f}% | "
                    f"{row['max_drawdown_adverse_hourly_pct']:.2f}% | "
                    f"{row['exposure_pct_asset_hours']:.1f}% | {row['order_count']} | {weekly_text} |"
                )
    lines += ["", "## Resultado por ativo no holdout", "",
              "Cada coluna usa uma conta isolada iniciada com 25% do capital total; drawdowns são calculados sobre essa conta.",
              "", "| custo/lado | ativo | retorno | CAGR | DD nas aberturas | limite adverso | % horas exposto | ordens |",
              "|---:|---|---:|---:|---:|---:|---:|---:|"]
    for side_cost in SIDE_COSTS:
        holdout = result["portfolio_results"]["holdout_2025_plus"][f"{side_cost:.4f}"]["price_plus_macro"]
        for symbol, row in holdout["asset_performance"].items():
            lines.append(
                f"| {side_cost:.2%} | {symbol} | {row['return_pct']:.2f}% | "
                f"{row['cagr_pct']:.2f}% | {row['max_drawdown_open_pct']:.2f}% | "
                f"{row['max_drawdown_adverse_hourly_pct']:.2f}% | "
                f"{row['exposure_pct_hours']:.1f}% | {row['order_count']} |"
            )
    lines += ["", "## Diferença do sinal macro sobre o controle cripto", "",
              "| Janela | custo/lado | delta retorno líquido (macro - cripto) | delta MSE % |",
              "|---|---:|---:|---:|"]
    for period_name in ("walk_forward", "holdout_2025_plus"):
        for side_cost in SIDE_COSTS:
            rows = result["portfolio_results"][period_name][f"{side_cost:.4f}"]
            delta = rows["price_plus_macro"]["return_pct"] - rows["price_only"]["return_pct"]
            mse_skill = result["forecast_scores"][period_name].get("macro_mse_skill_vs_price_only_pct")
            lines.append(f"| {period_name} | {side_cost:.2%} | {delta:.2f} p.p. | {mse_skill:.2f}% |" if mse_skill is not None else f"| {period_name} | {side_cost:.2%} | {delta:.2f} p.p. | — |")
    lines += [
        "",
        "## Limitações e decisão",
        "",
        "As vintages ALFRED são diárias; elas não provam o minuto de publicação. A decisão é deliberadamente domingo 23:00 UTC, após o último fechamento norte-americano que a vintage contém, e antes da abertura cripto usada. O índice Fed H.10 tem cadência semanal e é avaliado apenas com a série que já aparece na vintage. Preços de abertura e OHLC horário não garantem execução; spread, impacto, imposto, juros sobre caixa e restrições de redistribuição dos índices não foram modelados.",
        "",
        f"Meta retrospectiva (CAGR líquido ≥50% e limite adverso de drawdown ≤10% nos dois custos, no walk-forward e no holdout): **{'atingida' if result['historical_gate_passed'] else 'não atingida'}**. O objetivo de encontrar uma estratégia lucrativa e consistente permanece **não comprovado**; negociação real: **não**. {result['decision']}.",
        "",
        f"Arquivos reproduzíveis: `{REPORT_PATH.relative_to(ROOT).as_posix()}`, `{JSON_PATH.relative_to(ROOT).as_posix()}`, `{FORECASTS_PATH.relative_to(ROOT).as_posix()}`, `{CURVES_PATH.relative_to(ROOT).as_posix()}`, `{FILLS_PATH.relative_to(ROOT).as_posix()}`. Dados macro brutos permanecem somente em cache local ignorado.",
        "",
        "Fontes de dados e contexto: [FRED/ALFRED](https://alfred.stlouisfed.org/help/downloaddata), [Nasdaq Composite](https://fred.stlouisfed.org/series/NASDAQCOM), [VIX](https://fred.stlouisfed.org/series/VIXCLS), [índice amplo do dólar](https://fred.stlouisfed.org/series/DTWEXBGS), [nota de pesquisa](macro_crypto_sources_2026-09-27.md).",
        "",
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main():
    bars_by_symbol, manifest, boundaries, archive_hash = resolve_schedule()
    print(f"market schedule {iso(boundaries[0])} -> {iso(boundaries[-1])}; weeks={len(boundaries)-1}")
    snapshots, cache_hits = fetch_all_snapshots(boundaries)
    forecasts, provenance_by_week = build_forecasts(bars_by_symbol, boundaries, snapshots)
    first_by_model = {
        model: min((row["index"] for row in forecasts if row["model"] == model), default=None)
        for model in ("price_only", "price_plus_macro")
    }
    if any(index is None for index in first_by_model.values()):
        raise ValueError("walk-forward did not emit both comparison models")
    first_forecast_index = max(first_by_model.values())
    terminal_index = len(boundaries) - 1
    holdout_index = period_index(boundaries, FINAL_HOLDOUT)
    if holdout_index < first_forecast_index or holdout_index >= terminal_index:
        raise ValueError("the fixed holdout is outside the forecast schedule")

    score_windows = {
        "walk_forward": (first_forecast_index, terminal_index),
        "development_2024": (first_forecast_index,
                              period_index(boundaries, date(2025, 1, 1))),
        "holdout_2025_plus": (holdout_index, terminal_index),
    }
    scores = {
        label: forecast_scores(forecasts, start_index, end_index)
        for label, (start_index, end_index) in score_windows.items()
    }

    portfolio_results = {}
    all_curve_rows, all_fills = [], []
    replay_objects = {}
    portfolio_windows = {
        "walk_forward": first_forecast_index,
        "holdout_2025_plus": holdout_index,
    }
    for period_name, start_index in portfolio_windows.items():
        period_replays = {}
        for side_cost in SIDE_COSTS:
            key_cost = f"{side_cost:.4f}"
            cost_replays = {}
            for model in ("price_plus_macro", "price_only"):
                replay = portfolio_replay(
                    bars_by_symbol, boundaries, forecasts, model=model,
                    side_cost=side_cost, start_index=start_index,
                    end_index=terminal_index, mode="signal",
                )
                replay_objects[(period_name, key_cost, model)] = replay
                cost_replays[model] = enrich_metrics(dict(replay))
                all_curve_rows.extend({
                    "period": period_name, "model": model, "side_cost": side_cost, **row
                } for row in replay["curve"])
                all_fills.extend({
                    "period": period_name, **row
                } for row in replay["fills"])
            for mode, label in (("buy_hold", "buy_hold"), ("cash", "cash")):
                replay = portfolio_replay(
                    bars_by_symbol, boundaries, forecasts, model=label,
                    side_cost=side_cost, start_index=start_index,
                    end_index=terminal_index, mode=mode,
                )
                replay_objects[(period_name, key_cost, label)] = replay
                cost_replays[label] = enrich_metrics(dict(replay))
                all_curve_rows.extend({
                    "period": period_name, "model": label, "side_cost": side_cost, **row
                } for row in replay["curve"])
                all_fills.extend({
                    "period": period_name, **row
                } for row in replay["fills"])
            period_replays[key_cost] = cost_replays
        portfolio_results[period_name] = period_replays

    forecast_csv_rows = []
    for row in forecasts:
        forecast_csv_rows.append({
            **row,
            "signal_timestamp_utc": iso(row["signal_timestamp_ms"]),
            "exit_timestamp_utc": iso(row["exit_timestamp_ms"]),
        })
    write_csv(FORECASTS_PATH, forecast_csv_rows, [
        "index", "signal_timestamp_ms", "signal_timestamp_utc", "signal_sunday_utc",
        "exit_timestamp_ms", "exit_timestamp_utc", "symbol", "model", "prediction",
        "actual", "training_mean", "training_count", "training_last_completed_exit_ms",
        "feature_count",
    ])
    write_csv(CURVES_PATH, all_curve_rows, [
        "period", "model", "side_cost", "timestamp_ms", "timestamp_utc", "equity_pre",
        "equity_post", "equity_intrahour_high", "equity_intrahour_low",
    ])
    write_csv(FILLS_PATH, all_fills, [
        "period", "mode", "model", "side_cost", "timestamp_utc", "symbol", "side",
        "price", "quantity", "notional", "fee", "prediction", "threshold",
    ])

    snapshot_audit = []
    for key in sorted(snapshots, key=lambda pair: (pair[1], pair[0])):
        item = snapshots[key]
        rows = item["rows"]
        latest_date = rows[-1][0] if rows else None
        snapshot_audit.append({
            "series": item["series"],
            "vintage_date": item["vintage"].isoformat(),
            "snapshot_sha256": sha256(item["payload"]),
            "observation_count": len(rows),
            "latest_observation_date": latest_date.isoformat() if latest_date else None,
            "latest_age_calendar_days": (item["vintage"] - latest_date).days if latest_date else None,
            "cache_hit": item["cache_hit"],
        })
    macro_identity = sha256(json.dumps(
        [{key: row[key] for key in ("series", "vintage_date", "snapshot_sha256")}
         for row in snapshot_audit], sort_keys=True, separators=(",", ":")
    ).encode("utf-8"))
    eligible_macro_weeks = [
        index for index, provenance in provenance_by_week.items()
        if all(row.get("status") == "available" for row in provenance.values())
    ]

    historical_gate_passed = True
    for period_name in ("walk_forward", "holdout_2025_plus"):
        for side_cost in SIDE_COSTS:
            row = portfolio_results[period_name][f"{side_cost:.4f}"]["price_plus_macro"]
            historical_gate_passed &= (
                row["cagr_pct"] >= 50
                and row["max_drawdown_adverse_hourly_pct"] <= 10
            )
    # Retrospective replays alone cannot finish the user's consistency goal.
    goal_achieved = False
    if historical_gate_passed:
        decision = "O filtro macro passou os limites retrospectivos congelados. Ainda precisa de validação prospectiva em paper antes de qualquer negociação."
    else:
        decision = "O filtro macro não passou todos os limites retrospectivos congelados; registrar a hipótese como rejeitada ou inconclusiva conforme erro e PnL, sem retunar esta amostra."

    created = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result = {
        "created_utc": created,
        "deployable": False,
        "goal_achieved": goal_achieved,
        "historical_gate_passed": bool(historical_gate_passed),
        "decision": decision,
        "schedule": {
            "first_entry_utc": iso(boundaries[first_forecast_index]),
        "first_available_signal_utc": iso(boundaries[first_forecast_index] - HOUR_MS),
            "last_entry_utc": iso(boundaries[-2]),
            "terminal_utc": iso(boundaries[-1]),
            "first_forecast_index": first_forecast_index,
            "terminal_index": terminal_index,
            "final_holdout_start_utc": iso(boundaries[holdout_index]),
            "first_forecast_week_by_model": {
                model: iso(boundaries[index])
                for model, index in first_by_model.items()
            },
            "first_common_forecast_week_utc": iso(boundaries[first_forecast_index]),
            "weeks_total": len(boundaries) - 1,
            "hourly_rows_common": sum(1 for timestamp in range(boundaries[0], boundaries[-1] + HOUR_MS, HOUR_MS)
                                      if all(timestamp in bars_by_symbol[symbol] for symbol in SYMBOLS)),
            "binance_month_archives": len(manifest),
            "archive_manifest_sha256": archive_hash,
        },
        "universe": list(SYMBOLS),
        "macro_series": list(SERIES),
        "macro_snapshot_count": len(snapshots),
        "macro_cache_hits": cache_hits,
        "macro_eligible_feature_weeks": len(eligible_macro_weeks),
        "first_macro_eligible_week_utc": (
            iso(boundaries[eligible_macro_weeks[0]]) if eligible_macro_weeks else None
        ),
        "macro_snapshot_identity_sha256": macro_identity,
        "macro_snapshots": snapshot_audit,
        "macro_feature_freshness_by_signal_week": {
            utc_datetime(boundaries[index]).date().isoformat(): provenance
            for index, provenance in provenance_by_week.items()
        },
        "config": {
            "decision_time_utc": "Sunday 23:00",
            "execution_time_utc": "Monday 00:00 candle open",
            "label": "simple return from Monday 00:00 open to next Monday 00:00 open",
            "models": ["price_only", "price_plus_macro"],
            "price_lags_weeks": list(PRICE_LAGS),
            "macro_log_change_observation_lags": list(MACRO_LAGS),
            "minimum_training_weeks": MIN_TRAINING_WEEKS,
            "training_schedule": "expanding per-asset; training labels must exit before Sunday 23:00 decision",
            "estimator": "StandardScaler + Ridge",
            "ridge_alpha": RIDGE_ALPHA,
            "side_costs": list(SIDE_COSTS),
            "cash_when_forecast_not_above_gross_cost_threshold": True,
            "threshold_formula": "2*c/(1-c)",
            "allocation_per_asset_initial": INITIAL_EQUITY / len(SYMBOLS),
            "final_holdout_start": FINAL_HOLDOUT.isoformat(),
            "hyperparameter_search": False,
            "orders_authorized": False,
            "jev_calls_authorized": False,
        },
        "forecast_count_by_model": {
            model: sum(row["model"] == model for row in forecasts)
            for model in ("price_only", "price_plus_macro")
        },
        "forecast_scores": scores,
        "portfolio_results": portfolio_results,
        "source_hashes": {
            "protocol": sha256(PROTOCOL_PATH.read_bytes()),
            "sources_note": sha256(SOURCES_PATH.read_bytes()),
            "script": sha256(SCRIPT_PATH.read_bytes()),
        },
        "runtime": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scikit_learn": __import__("sklearn").__version__,
        },
    }
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8", newline="\n")
    render_report(result)
    print(f"research complete; goal_achieved={goal_achieved}; report={REPORT_PATH}")


if __name__ == "__main__":
    main()
