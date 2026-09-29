"""Bounded one-minute Jev BTCUSDT Spot paper experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .binance_data import Bar
from .cli import ROOT, RESULTS
from .jev import ENDPOINT, MODEL, load_api_key
from .market_state import ema, wilder
from .strategies import rsi, sma

SERIES = "minute_jev_paper_20260927"
ROOT_DIR = RESULTS / SERIES
LEDGER = ROOT_DIR / "events.jsonl"
STATUS = ROOT_DIR / "status.json"
LOCK = ROOT_DIR / "watch.lock"
STOP = ROOT_DIR / "watch.stop"
BINANCE = "https://api.binance.com/api/v3"
SYMBOL = "BTCUSDT"
INTERVALS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}
INITIAL_CASH = 100.0
FEE_RATE = 0.001
EXTRA_SLIPPAGE = 0.0005
ACTION_THRESHOLD = 0.60
MAX_HOURS = 72.0
MAX_CALLS = 4_320
MAX_SPEND_USD = 1.00
INPUT_PRICE_PER_TOKEN = 0.042 / 1_000_000
ZERO = "0" * 64
TLS_CONTEXT: ssl.SSLContext | None = None
CHOICES = {
    "BUY": "Open one long BTCUSDT Spot position when currently flat.",
    "SELL": "Close the entire BTCUSDT Spot position when currently long; when flat, do nothing.",
    "IDLE": "Keep the current state unchanged: remain flat or continue holding the existing long.",
}
QUESTION = {
    "action": {
        "type": "choice",
        "criteria": CHOICES,
        "instructions": (
            "Choose the single action justified by the supplied completed-candle indicators. "
            "Use BUY only to open a Spot long while flat, SELL only to close an existing Spot long, "
            "and IDLE to remain flat or keep holding. Consider agreement and disagreement across "
            "1-minute, 5-minute, 15-minute, and 1-hour RSI, MACD, trend, Fibonacci, volatility, "
            "and volume fields. Do not infer unseen data or treat confidence as a probability of profit."
        ),
    }
}
CONFIG = {
    "schema_version": 1,
    "mode": "paper",
    "symbol": SYMBOL,
    "market": "Binance Spot BTCUSDT",
    "model": MODEL,
    "cadence": "one request after each completed UTC 1-minute candle",
    "choices": CHOICES,
    "action_probability_minimum": ACTION_THRESHOLD,
    "initial_cash_usdt": INITIAL_CASH,
    "position": "long or cash; no short and no leverage",
    "fee_per_side": FEE_RATE,
    "extra_adverse_slippage_per_side": EXTRA_SLIPPAGE,
    "max_duration_hours": MAX_HOURS,
    "max_calls": MAX_CALLS,
    "max_api_spend_usd": MAX_SPEND_USD,
    "input_price_per_million_tokens_usd_at_freeze": 0.042,
    "screen_gate": {
        "minimum_completed_round_trips": 10,
        "net_return_after_costs_positive": True,
        "maximum_observed_drawdown_pct": 5.0,
        "positive_24h_windows_minimum": 2,
        "gate_failures_are_inconclusive_if_trade_count_or_data_quality_is_insufficient": True,
    },
    "live_orders_enabled": False,
    "exchanges_orders_enabled": False,
}


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _utc_now_ms() -> int:
    return time.time_ns() // 1_000_000


def _open_url(request: urllib.request.Request, timeout: float):
    if TLS_CONTEXT is None:
        return urllib.request.urlopen(request, timeout=timeout)
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=TLS_CONTEXT))
    return opener.open(request, timeout=timeout)


def _http_json(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None,
               timeout: float = 20) -> tuple[object, dict]:
    request = urllib.request.Request(url, data=data, headers=headers or {},
                                     method="POST" if data is not None else "GET")
    started = _utc_now_ms()
    with _open_url(request, timeout) as response:
        raw = response.read()
        status = response.status
    received = _utc_now_ms()
    parsed = json.loads(raw)
    return parsed, {"started_ms": started, "received_ms": received,
                    "http_status": status, "response_sha256": hashlib.sha256(raw).hexdigest(),
                    "response_bytes": len(raw)}


def _binance_json(path: str, params: dict[str, str] | None = None) -> tuple[object, dict]:
    query = "" if not params else "?" + urllib.parse.urlencode(params)
    return _http_json(BINANCE + path + query, headers={"User-Agent": "minute-jev-paper/0.1"})


def _server_time() -> tuple[int, dict]:
    body, meta = _binance_json("/time")
    value = body.get("serverTime") if isinstance(body, dict) else None
    if type(value) is not int or value <= 0:
        raise ValueError("invalid Binance server time response")
    return value, meta


def _load_bars(interval: str, server_ms: int) -> tuple[list[Bar], list[int], dict]:
    interval_ms = INTERVALS[interval]
    body, meta = _binance_json("/klines", {"symbol": SYMBOL, "interval": interval, "limit": "250"})
    if not isinstance(body, list):
        raise ValueError(f"invalid {interval} kline response")
    bars: list[Bar] = []
    close_times: list[int] = []
    for row in body:
        if not isinstance(row, list) or len(row) < 10:
            raise ValueError(f"malformed {interval} kline")
        open_ms, close_ms = int(row[0]), int(row[6])
        if close_ms >= server_ms:
            continue
        values = [float(row[index]) for index in (1, 2, 3, 4, 5, 7, 9)]
        if (not all(math.isfinite(number) for number in values) or
                any(number <= 0 for number in values[:5]) or values[5] <= 0 or values[6] < 0 or
                close_ms != open_ms + interval_ms - 1):
            raise ValueError(f"invalid completed {interval} candle")
        bars.append(Bar(open_ms, *values[:5], values[5], int(row[8]), values[6]))
        close_times.append(close_ms)
    if len(bars) < 205:
        raise ValueError(f"not enough completed {interval} candles: {len(bars)}")
    for previous, current in zip(bars, bars[1:]):
        if current.open_ms - previous.open_ms != interval_ms:
            raise ValueError(f"gap in completed {interval} candles")
    expected_last_open = (server_ms // interval_ms) * interval_ms - interval_ms
    if bars[-1].open_ms != expected_last_open:
        raise ValueError(f"stale {interval} candle window")
    return bars, close_times, meta


def _feature_set(bars: list[Bar]) -> dict:
    close = [bar.close for bar in bars]
    high = [bar.high for bar in bars]
    low = [bar.low for bar in bars]
    volume = [bar.volume for bar in bars]
    quote_volume = [bar.quote_volume or 0.0 for bar in bars]
    taker = [bar.taker_buy_base or 0.0 for bar in bars]
    exponential = {period: ema(close, period) for period in (12, 26)}
    macd_line = [fast - slow for fast, slow in zip(exponential[12], exponential[26])]
    macd_signal = ema(macd_line, 9)
    tr = [high[0] - low[0]]
    for index in range(1, len(bars)):
        tr.append(max(high[index] - low[index], abs(high[index] - close[index - 1]),
                      abs(low[index] - close[index - 1])))
    atr = wilder(tr, 14)
    rsi_values = rsi(close, 14)
    averages = {period: sma(close, period) for period in (20, 50, 200)}
    index = len(bars) - 1
    last_close = close[index]
    result = {
        "candle_close_ms": bars[index].open_ms + (bars[index].open_ms - bars[index - 1].open_ms),
        "close": last_close,
        "return_1_bar_pct": 100 * (last_close / close[index - 1] - 1),
        "return_5_bars_pct": 100 * (last_close / close[index - 5] - 1),
        "return_20_bars_pct": 100 * (last_close / close[index - 20] - 1),
        "rsi14": rsi_values[index],
        "macd_histogram_pct": 100 * (macd_line[index] - macd_signal[index]) / last_close,
        "atr14_pct": 100 * atr[index] / last_close,
        "sma_distance_pct": {str(period): 100 * (last_close / averages[period][index] - 1)
                              for period in averages},
        "sma50_slope_5_bars_pct": 100 * (averages[50][index] / averages[50][index - 5] - 1),
        "relative_volume20": volume[index] / (sum(volume[index - 20:index]) / 20),
        "quote_volume20_usdt": sum(quote_volume[index - 19:index + 1]),
        "taker_buy_fraction20": sum(taker[index - 19:index + 1]) / sum(volume[index - 19:index + 1]),
        "close_position_in_candle": ((last_close - low[index]) / (high[index] - low[index])
                                      if high[index] > low[index] else 0.5),
    }
    result["fibonacci"] = {}
    for window in (60, 180):
        sample_high = high[index - window + 1:index + 1]
        sample_low = low[index - window + 1:index + 1]
        low_index = min(range(window), key=sample_low.__getitem__)
        high_index = max(range(window), key=sample_high.__getitem__)
        swing_low, swing_high = sample_low[low_index], sample_high[high_index]
        spread = swing_high - swing_low
        retracement = (swing_high - last_close) / spread if spread else 0.0
        levels = {str(ratio): swing_high - ratio * spread for ratio in (0.382, 0.5, 0.618)}
        result["fibonacci"][str(window)] = {
            "high_after_low": high_index > low_index,
            "retracement_fraction": retracement,
            "distance_to_levels_pct": {key: 100 * (last_close / level - 1) if level else None
                                       for key, level in levels.items()},
        }
    return result


def _market_state(server_ms: int, account: dict) -> tuple[dict, dict]:
    intervals, sources = {}, {}
    bars_by_interval: dict[str, list[Bar]] = {}
    for interval in INTERVALS:
        bars, close_times, source = _load_bars(interval, server_ms)
        bars_by_interval[interval] = bars
        features = _feature_set(bars)
        intervals[interval] = features
        sources[interval] = {**source, "last_open_ms": bars[-1].open_ms,
                             "last_close_ms": close_times[-1], "bars_used": len(bars)}
    if len({intervals[name]["candle_close_ms"] for name in intervals if name == "1m"}) != 1:
        raise ValueError("minute feature timestamp mismatch")
    position = account["position"]
    state = {
        "symbol": SYMBOL,
        "market": "Binance Spot, long-or-cash, no leverage",
        "current_position": "long" if position["quantity"] > 0 else "flat",
        "entry_return_pct": (100 * (intervals["1m"]["close"] / position["entry_price"] - 1)
                              if position["quantity"] > 0 else None),
        "paper_account": {"equity_usdt": account["equity_usdt"],
                          "drawdown_pct": max(
                              0.0, 100 * (account["peak_equity_usdt"] - account["equity_usdt"])
                              / account["peak_equity_usdt"]
                          ),
                          "max_drawdown_pct": account["max_drawdown_pct"],
                          "cash_usdt": account["cash_usdt"]},
        "indicators": intervals,
    }
    last_1m = bars_by_interval["1m"][-1]
    sources["1m"]["last_ohlc"] = {"open": last_1m.open, "high": last_1m.high,
                                    "low": last_1m.low, "close": last_1m.close}
    return state, sources


def _quote(server_ms: int) -> tuple[dict, dict]:
    body, meta = _binance_json("/ticker/bookTicker", {"symbol": SYMBOL})
    if not isinstance(body, dict):
        raise ValueError("invalid Binance book ticker")
    bid, ask = float(body["bidPrice"]), float(body["askPrice"])
    bid_size, ask_size = float(body["bidQty"]), float(body["askQty"])
    if not all(math.isfinite(value) and value > 0 for value in (bid, ask, bid_size, ask_size)) or bid > ask:
        raise ValueError("invalid Binance top of book")
    midpoint = (bid + ask) / 2
    return {"bid": bid, "ask": ask, "bid_qty": bid_size, "ask_qty": ask_size,
            "spread_bps": (ask - bid) / midpoint * 10_000,
            "observed_server_ms": server_ms, **meta}, meta


def _request_payload(state: dict) -> dict:
    return {"model": MODEL, "state": state, "questions": QUESTION}


def _estimate_call(state: dict) -> tuple[bytes, int, float, float]:
    body = _json_bytes(_request_payload(state))
    estimated_tokens = max(700, math.ceil(len(body) / 2.4))
    estimated_cost = estimated_tokens * INPUT_PRICE_PER_TOKEN
    return body, estimated_tokens, estimated_cost, estimated_cost * 2


def _call_jev(body: bytes, api_key: str, estimated_tokens: int) -> tuple[dict, dict]:
    request = urllib.request.Request(ENDPOINT, data=body,
                                     headers={"Authorization": f"Bearer {api_key}",
                                              "Content-Type": "application/json"}, method="POST")
    started = _utc_now_ms()
    with _open_url(request, 25) as response:
        raw = response.read()
        status = response.status
    completed = _utc_now_ms()
    result = json.loads(raw)
    answers = result.get("answers", {})
    answer = answers.get("action")
    if status != 200 or not isinstance(answer, dict) or answer.get("type") != "choice":
        raise ValueError("Jev response does not match frozen choice schema")
    action = answer.get("choice")
    probabilities = answer.get("probabilities")
    if action not in CHOICES or not isinstance(probabilities, dict):
        raise ValueError("Jev returned an unknown action or missing probabilities")
    probability = probabilities.get(action)
    if (isinstance(probability, bool) or not isinstance(probability, (int, float)) or
            not math.isfinite(probability) or not 0 <= probability <= 1):
        raise ValueError("Jev returned an invalid chosen-action probability")
    usage = result.get("usage", {})
    cost = usage.get("cost")
    if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0:
        raise ValueError("Jev response omitted a valid billed usage.cost")
    if set(probabilities) != set(CHOICES):
        raise ValueError("Jev returned a different action probability set")
    normalized_probabilities = {key: float(probabilities[key]) for key in CHOICES}
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in normalized_probabilities.values()):
        raise ValueError("Jev returned an invalid action probability")
    return ({"action": action, "action_probability": float(probability),
             "action_probabilities": normalized_probabilities,
             "model": result.get("model"), "request_id": result.get("id"),
             "answers": answers,
             "usage": usage, "response_sha256": hashlib.sha256(raw).hexdigest(),
             "response_bytes": len(raw)},
            {"started_ms": started, "completed_ms": completed,
             "latency_ms": completed - started, "cost_usd": float(cost),
             "estimated_input_tokens": estimated_tokens})


def _mark(account: dict, price: float) -> tuple[float, float]:
    quantity = account["position"]["quantity"]
    equity = account["cash_usdt"] + quantity * price
    peak = max(account["peak_equity_usdt"], equity)
    drawdown = (peak - equity) / peak if peak else 0.0
    account["peak_equity_usdt"] = peak
    account["equity_usdt"] = equity
    account["max_drawdown_pct"] = max(account["max_drawdown_pct"], drawdown * 100)
    return equity, drawdown * 100


def _apply_action(account: dict, action: dict, quote: dict, event_ms: int) -> dict:
    choice = action["action"]
    probability = action["action_probability"]
    position = account["position"]
    if choice == "IDLE" or probability < ACTION_THRESHOLD:
        return {"action_taken": "IDLE", "reason": "model_idle_or_probability_below_threshold"}
    if choice == "BUY" and position["quantity"] > 0:
        return {"action_taken": "IDLE", "reason": "already_long"}
    if choice == "SELL" and position["quantity"] <= 0:
        return {"action_taken": "IDLE", "reason": "flat_cannot_short_spot"}
    if choice == "BUY":
        fill = quote["ask"] * (1 + EXTRA_SLIPPAGE)
        quantity = account["cash_usdt"] / (fill * (1 + FEE_RATE))
        notional = quantity * fill
        fee = notional * FEE_RATE
        account["cash_usdt"] -= notional + fee
        account["position"] = {"quantity": quantity, "entry_price": fill,
                                "entry_time_ms": event_ms, "entry_notional_usdt": notional,
                                "entry_fee_usdt": fee}
        account["fees_usdt"] += fee
        account["entry_count"] += 1
        return {"action_taken": "BUY", "fill_price": fill, "quantity": quantity,
                "notional_usdt": notional, "fee_usdt": fee}
    fill = quote["bid"] * (1 - EXTRA_SLIPPAGE)
    quantity = position["quantity"]
    notional = quantity * fill
    fee = notional * FEE_RATE
    proceeds = notional - fee
    basis = position["entry_notional_usdt"] + position["entry_fee_usdt"]
    pnl = proceeds - basis
    account["cash_usdt"] += proceeds
    account["fees_usdt"] += fee
    account["realized_pnl_usdt"] += pnl
    account["round_trips"].append({"entry_time_ms": position["entry_time_ms"],
                                   "exit_time_ms": event_ms, "entry_price": position["entry_price"],
                                   "exit_price": fill, "quantity": quantity,
                                   "gross_pnl_usdt": notional - position["entry_notional_usdt"],
                                   "net_pnl_usdt": pnl,
                                   "fees_usdt": position["entry_fee_usdt"] + fee})
    account["position"] = {"quantity": 0.0, "entry_price": None,
                            "entry_time_ms": None, "entry_notional_usdt": 0.0,
                            "entry_fee_usdt": 0.0}
    return {"action_taken": "SELL", "fill_price": fill, "quantity": quantity,
            "notional_usdt": notional, "fee_usdt": fee, "round_trip_net_pnl_usdt": pnl}


def _read_chain() -> list[dict]:
    rows, previous = [], ZERO
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            body = {key: value for key, value in row.items() if key != "record_sha256"}
            if body.get("previous_sha256") != previous or _digest(body) != row.get("record_sha256"):
                raise ValueError("minute paper event ledger hash chain is invalid")
            rows.append(row)
            previous = row["record_sha256"]
    return rows


def _append(body: dict, previous_sha256: str) -> dict:
    body = {**body, "previous_sha256": previous_sha256}
    row = {**body, "record_sha256": _digest(body)}
    ROOT_DIR.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return row


def _account_from_rows(rows: list[dict]) -> dict:
    if rows:
        if rows[-1].get("config_sha256") != _digest(CONFIG):
            raise ValueError("frozen minute strategy config changed since prior record")
        return rows[-1]["account_after"]
    return {"cash_usdt": INITIAL_CASH,
            "position": {"quantity": 0.0, "entry_price": None, "entry_time_ms": None,
                         "entry_notional_usdt": 0.0, "entry_fee_usdt": 0.0},
            "equity_usdt": INITIAL_CASH, "peak_equity_usdt": INITIAL_CASH,
            "max_drawdown_pct": 0.0, "max_adverse_drawdown_pct": 0.0,
            "fees_usdt": 0.0, "realized_pnl_usdt": 0.0,
            "entry_count": 0, "round_trips": []}


def _heartbeat(started_ms: int, deadline_ms: int, calls: int, spend: float, phase: str,
               last_error: str | None = None) -> None:
    state = {"pid": os.getpid(), "series": SERIES, "started_ms": started_ms,
             "expires_ms": deadline_ms, "calls": calls, "spend_usd": round(spend, 10),
             "phase": phase, "heartbeat_ms": _utc_now_ms(), "last_error": last_error,
             "config_sha256": _digest(CONFIG), "live_orders_enabled": False}
    temporary = STATUS.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(STATUS)


def _budget_state(rows: list[dict]) -> tuple[int, float]:
    reservations = {row["reservation_id"]: float(row["reserve_usd"])
                    for row in rows if row.get("record_type") == "api_reservation"}
    resolved = {row["resolved_reservation_id"]: float(row["api_cost_usd"])
                for row in rows if row.get("resolved_reservation_id")}
    if any(key not in reservations for key in resolved):
        raise ValueError("API ledger resolves an unknown reservation")
    spend = sum(resolved.get(key, reserved) for key, reserved in reservations.items())
    return len(reservations), spend


def _quantile(values: list[int], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return float(ordered[min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)])


def build_report() -> dict:
    rows = _read_chain()
    status = json.loads(STATUS.read_text(encoding="utf-8")) if STATUS.exists() else {}
    config_sha = _digest(CONFIG)
    if any(row.get("config_sha256") not in (None, config_sha) for row in rows):
        raise ValueError("event ledger contains another strategy configuration")
    start_ms = status.get("started_ms") or next(
        (row.get("started_ms") for row in rows if row.get("record_type") == "run_started"), None)
    expires_ms = status.get("expires_ms") or next(
        (row.get("expires_ms") for row in rows if row.get("record_type") == "run_started"), None)
    if not isinstance(start_ms, int) or not isinstance(expires_ms, int):
        raise ValueError("run timing is missing; report cannot be calculated")
    attempts, spend = _budget_state(rows)
    decision_rows = [row for row in rows if row.get("record_type") == "minute_decision"]
    valid_rows = [row for row in decision_rows if row.get("status") == "processed" and row.get("jev")]
    expected = min(MAX_CALLS, max(0, round((expires_ms - start_ms) / 60_000)))
    valid_fraction = len(valid_rows) / expected if expected else 0.0
    account = rows[-1].get("account_after") if rows else _account_from_rows([])
    if not isinstance(account, dict):
        raise ValueError("event ledger does not contain a final account")
    round_trips = account.get("round_trips", [])
    last_quote = next((row["quote_after_call"] for row in reversed(valid_rows)
                       if isinstance(row.get("quote_after_call"), dict)), None)
    final_equity = account.get("cash_usdt", 0.0)
    open_position = account.get("position", {})
    if open_position.get("quantity", 0.0) > 0 and last_quote:
        liquidation_bid = last_quote["bid"] * (1 - EXTRA_SLIPPAGE)
        final_equity += open_position["quantity"] * liquidation_bid * (1 - FEE_RATE)
    net_return_pct = 100 * (final_equity / INITIAL_CASH - 1)
    max_drawdown = max((float(row.get("account_after", {}).get("max_drawdown_pct", 0.0))
                        for row in valid_rows), default=0.0)
    max_adverse_drawdown = max((float(row.get("account_after", {}).get("max_adverse_drawdown_pct", 0.0))
                                for row in valid_rows), default=0.0)
    actions: dict[str, int] = {key: 0 for key in CHOICES}
    executions: dict[str, int] = {"BUY": 0, "SELL": 0, "IDLE": 0}
    for row in valid_rows:
        action = row.get("jev", {}).get("action")
        taken = row.get("execution", {}).get("action_taken")
        if action in actions:
            actions[action] += 1
        if taken in executions:
            executions[taken] += 1
    latencies = [int(row["jev"]["latency_ms"]) for row in valid_rows if row.get("jev", {}).get("latency_ms") is not None]
    event_equity = [(int(row["processed_at_ms"]), float(row["equity_usdt"]))
                    for row in valid_rows if isinstance(row.get("processed_at_ms"), int)]

    def equity_at(timestamp_ms: int) -> float:
        candidates = [value for at, value in event_equity if at <= timestamp_ms]
        if candidates:
            return candidates[-1]
        return INITIAL_CASH

    windows = []
    for index in range(3):
        window_start = start_ms + index * 86_400_000
        window_end = min(window_start + 86_400_000, expires_ms)
        if window_start >= expires_ms:
            break
        beginning = INITIAL_CASH if index == 0 else equity_at(window_start)
        ending = equity_at(window_end)
        windows.append({"start_ms": window_start, "end_ms": window_end,
                        "return_pct": 100 * (ending / beginning - 1) if beginning else None})
    positive_windows = sum(1 for item in windows if item["return_pct"] is not None and item["return_pct"] > 0)
    now_ms = _utc_now_ms()
    duration_complete = now_ms >= expires_ms
    sample_sufficient = len(round_trips) >= CONFIG["screen_gate"]["minimum_completed_round_trips"]
    data_sufficient = valid_fraction >= 0.99
    gate_evaluable = duration_complete and sample_sufficient and data_sufficient and len(windows) == 3
    screen_passed = bool(
        gate_evaluable and net_return_pct > 0
        and max_drawdown <= CONFIG["screen_gate"]["maximum_observed_drawdown_pct"]
        and max_adverse_drawdown <= CONFIG["screen_gate"]["maximum_observed_drawdown_pct"]
        and positive_windows >= CONFIG["screen_gate"]["positive_24h_windows_minimum"]
    )
    unresolved_reservations = max(0, attempts - sum(
        1 for row in rows if row.get("resolved_reservation_id")))
    errors: dict[str, int] = {}
    for row in decision_rows:
        if row.get("status") != "processed":
            name = row.get("error_type", "unknown")
            errors[name] = errors.get(name, 0) + 1
    report = {
        "schema_version": 1, "series": SERIES, "mode": "paper",
        "started_ms": start_ms, "expires_ms": expires_ms,
        "duration_hours": (expires_ms - start_ms) / 3_600_000,
        "config": CONFIG, "config_sha256": config_sha,
        "calls_attempted": attempts, "expected_minutes": expected,
        "valid_minutes": len(valid_rows), "valid_minute_fraction": valid_fraction,
        "api_spend_or_reserve_usd": spend, "unresolved_api_reservations": unresolved_reservations,
        "round_trips": len(round_trips), "entry_count": account.get("entry_count", 0),
        "open_position_at_end": open_position.get("quantity", 0.0) > 0,
        "net_liquidation_equity_usdt": final_equity, "net_return_pct": net_return_pct,
        "max_observed_drawdown_pct": max_drawdown,
        "max_adverse_drawdown_pct": max_adverse_drawdown,
        "fees_paid_usdt": float(account.get("fees_usdt", 0.0)),
        "actions": actions, "executions": executions,
        "positive_24h_windows": positive_windows, "windows": windows,
        "latency_p50_ms": _quantile(latencies, 0.50),
        "latency_p95_ms": _quantile(latencies, 0.95),
        "errors": errors, "run_phase": status.get("phase"),
        "gate_evaluable": gate_evaluable,
        "screen_passed": screen_passed,
        "outcome": "screen_passed" if screen_passed else "hypothesis_rejected" if gate_evaluable else "inconclusive",
        "goal_achieved": False, "deployable": False, "live_orders_enabled": False,
        "limitations": ["A 72-hour screen cannot establish annual CAGR or future drawdown.",
                        "One Spot symbol is not cross-asset validation.",
                        "Paper fills use top-of-book quotes and fixed fee/slippage assumptions."],
    }
    ROOT_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT_DIR / "summary.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Resultado do paper JEV por minuto",
        "",
        f"Resultado: **{report['outcome']}**. Este rastreio não demonstra a meta anual e não é liberado para ordens.",
        "",
        f"- Chamadas tentadas: {attempts}/{expected}; minutos válidos: {len(valid_rows)} ({valid_fraction:.2%}).",
        f"- Trades completos: {len(round_trips)}; retorno líquido de liquidação: {net_return_pct:.3f}%; ",
        f"drawdown observado/adverso: {max_drawdown:.3f}% / {max_adverse_drawdown:.3f}%.",
        f"- Gasto/reserva API: US${spend:.6f}; posição aberta no fim: {report['open_position_at_end']}.",
        f"- JEV BUY/SELL/IDLE: {actions['BUY']}/{actions['SELL']}/{actions['IDLE']}; ",
        f"ações simuladas BUY/SELL/IDLE: {executions['BUY']}/{executions['SELL']}/{executions['IDLE']}.",
        "",
        "## Janelas de 24 horas",
        "",
        "| Janela | Retorno líquido |",
        "|---:|---:|",
    ]
    lines.extend(f"| {i + 1} | {item['return_pct']:.3f}% |" for i, item in enumerate(windows)
                 if item["return_pct"] is not None)
    lines.extend(["", "## Limites", "",
                  "O gate serve somente para decidir se vale ampliar o paper. Um resultado inconclusivo não conta como aprovado; a validação prospectiva deve exigir acerto líquido de pelo menos 70%, payoff líquido mínimo de 1:1, EV líquido acima de 1,2% do capital comprometido por operação e drawdown máximo da conta de 10%. Mesmo passar autoriza apenas ampliar a pesquisa, sem ordens reais.", ""])
    (ROOT_DIR / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    return report


def run(hours: float = MAX_HOURS, ca_bundle: str | None = None) -> None:
    global TLS_CONTEXT
    if not 0 < hours <= MAX_HOURS:
        raise ValueError("duration must be greater than zero and at most 72 hours")
    if ca_bundle:
        TLS_CONTEXT = ssl.create_default_context(cafile=ca_bundle)
    if STOP.exists():
        raise ValueError("stop request exists; refusing to start")
    api_key = load_api_key(ROOT / ".env")
    rows = _read_chain()
    if rows:
        raise ValueError("this frozen series already has records; inspect its report instead of restarting")
    ROOT_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode("ascii"))
    os.close(fd)
    started_ms = _utc_now_ms()
    deadline_ms = started_ms + int(hours * 3_600_000)
    account = _account_from_rows([])
    chain_head = ZERO
    calls = 0
    spend = 0.0
    last_minute = -1
    error_streak = 0
    phase = "starting"
    config_sha = _digest(CONFIG)
    try:
        started = _append({"record_type": "run_started", "started_ms": started_ms,
                           "expires_ms": deadline_ms, "config": CONFIG,
                           "config_sha256": config_sha, "account_after": account,
                           "live_orders_enabled": False}, chain_head)
        chain_head = started["record_sha256"]
        _heartbeat(started_ms, deadline_ms, calls, spend, "starting")
        while _utc_now_ms() < deadline_ms and calls < MAX_CALLS and spend < MAX_SPEND_USD:
            if STOP.exists():
                phase = "stop_requested"
                break
            now_ms = _utc_now_ms()
            next_minute = (now_ms // 60_000 + 1) * 60_000
            target_ms = next_minute + 2_000
            while _utc_now_ms() < target_ms:
                if STOP.exists():
                    break
                _heartbeat(started_ms, deadline_ms, calls, spend, "waiting")
                time.sleep(min(10.0, max(0.0, (target_ms - _utc_now_ms()) / 1000)))
            if STOP.exists() or _utc_now_ms() >= deadline_ms:
                continue
            minute_open_ms = next_minute - 60_000
            if minute_open_ms <= last_minute:
                continue
            event: dict = {"record_type": "minute_decision", "schema_version": 1,
                           "series": SERIES, "minute_open_ms": minute_open_ms,
                           "started_ms": started_ms, "expires_ms": deadline_ms,
                           "config_sha256": config_sha, "call_index": calls + 1,
                           "live_orders_enabled": False}
            try:
                server_ms, server_meta = _server_time()
                market_state, candle_sources = _market_state(server_ms, account)
                event["input_state"] = market_state
                event["candle_sources"] = candle_sources
                event["server_time_before_call"] = {"server_ms": server_ms, **server_meta}

                request_body, estimated_tokens, estimated_cost, reserve_cost = _estimate_call(market_state)
                if spend + reserve_cost > MAX_SPEND_USD:
                    event.update({"status": "not_called_budget_cap",
                                  "reserve_would_be_usd": reserve_cost,
                                  "account_after": account})
                    saved = _append(event, chain_head)
                    chain_head = saved["record_sha256"]
                    last_minute = minute_open_ms
                    phase = "spend_cap_preflight"
                    break
                reservation_id = uuid.uuid4().hex
                reserve_record = _append({"record_type": "api_reservation",
                                          "reservation_id": reservation_id,
                                          "minute_open_ms": minute_open_ms,
                                          "call_index": calls + 1,
                                          "reserve_usd": reserve_cost,
                                          "estimated_cost_usd": estimated_cost,
                                          "estimated_input_tokens": estimated_tokens,
                                          "request_sha256": hashlib.sha256(request_body).hexdigest(),
                                          "config_sha256": config_sha,
                                          "account_after": account,
                                          "live_orders_enabled": False}, chain_head)
                chain_head = reserve_record["record_sha256"]
                spend += reserve_cost
                calls += 1
                last_minute = minute_open_ms
                event["reservation_id"] = reservation_id
                event["reserved_usd"] = reserve_cost
                event["api_request_attempted"] = True
                decision, call_meta = _call_jev(request_body, api_key, estimated_tokens)
                spend += call_meta["cost_usd"] - reserve_cost
                event["resolved_reservation_id"] = reservation_id
                event["api_cost_usd"] = call_meta["cost_usd"]
                event["jev"] = {**decision, "latency_ms": call_meta["latency_ms"],
                                 "usage": {**decision["usage"], "cost": call_meta["cost_usd"]}}
                event["call"] = call_meta
                quote_server_ms, quote_clock = _server_time()
                quote, quote_meta = _quote(quote_server_ms)
                event["quote_after_call"] = quote
                event["quote_server_clock"] = quote_clock
                if account["position"]["quantity"] > 0:
                    high = candle_sources["1m"]["last_ohlc"]["high"]
                    low = candle_sources["1m"]["last_ohlc"]["low"]
                    _mark(account, high)
                    adverse_mark = low * (1 - EXTRA_SLIPPAGE) * (1 - FEE_RATE)
                    _, adverse_drawdown = _mark(account, adverse_mark)
                    account["max_adverse_drawdown_pct"] = max(
                        account["max_adverse_drawdown_pct"], adverse_drawdown)
                    event["adverse_minute_low_mark"] = adverse_mark
                current_action = _apply_action(account, decision, quote, quote_server_ms)
                equity, drawdown = _mark(account, quote["bid"])
                event["execution"] = current_action
                event["equity_usdt"] = equity
                event["drawdown_pct"] = drawdown
                event["processed_at_ms"] = quote_server_ms
                event["account_after"] = account
                event["status"] = "processed"
                saved = _append(event, chain_head)
                chain_head = saved["record_sha256"]
                _heartbeat(started_ms, deadline_ms, calls, spend, "observed")
                error_streak = 0
            except Exception as exc:
                event.update({"status": "missed", "error_type": type(exc).__name__,
                              "error": str(exc)[:300], "account_after": account})
                saved = _append(event, chain_head)
                chain_head = saved["record_sha256"]
                error_streak += 1
                _heartbeat(started_ms, deadline_ms, calls, spend, "network_or_data_error",
                           f"{type(exc).__name__}: {str(exc)[:180]}")
                last_minute = minute_open_ms
                if error_streak >= 5:
                    phase = "five_consecutive_input_errors"
                    break
            if spend >= MAX_SPEND_USD:
                phase = "spend_cap_reached"
                break
        else:
            if _utc_now_ms() >= deadline_ms:
                phase = "expired"
            elif calls >= MAX_CALLS:
                phase = "call_cap_reached"
            elif spend >= MAX_SPEND_USD:
                phase = "spend_cap_reached"
    finally:
        _heartbeat(started_ms, deadline_ms, calls, spend, phase)
        LOCK.unlink(missing_ok=True)
        build_report()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=MAX_HOURS)
    parser.add_argument("--ca-bundle", help="PEM CA bundle approved for this host's HTTPS inspection proxy")
    parser.add_argument("--report", action="store_true", help="rebuild the report from the completed local ledger")
    args = parser.parse_args()
    build_report() if args.report else run(args.hours, args.ca_bundle)


if __name__ == "__main__":
    main()
