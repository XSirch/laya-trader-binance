"""Frozen five-minute BTCUSDT futures OI/taker continuation experiment."""
from __future__ import annotations
import csv
import hashlib
import json
import math
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from sklearn.ensemble import HistGradientBoostingClassifier

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
RUN = RESULTS / "oi_taker_5m_20260928_attempt5"
RAW = RUN / "raw"
INPUT_MANIFEST = RUN / "input_manifest.json"
PROTOCOL = ROOT / "docs" / "oi_taker_5m_protocol_2026-09-28.md"
OUTPUT = RESULTS / "oi_taker_5m_research_20260928.json"
OUTPUT_CSV = RESULTS / "oi_taker_5m_trades_20260928.csv"
OUTPUT_MD = ROOT / "docs" / "oi_taker_5m_research_2026-09-28.md"
BASE_URL = "https://fapi.binance.com"
SYMBOL = "BTCUSDT"
INTERVAL_MS = 300_000
AS_OF_SERVER_MS = 1_790_557_086_063
START_MS = 1_787_964_900_000
VALIDATION_START_MS = 1_789_692_900_000
END_MS = 1_790_556_900_000
FEATURES = ("return_60m", "return_15m", "oi_change_60m", "taker_buy_fraction_60m",
            "atr14_fraction", "close_position", "log_quote_volume_ratio_12")
COSTS = {"base": 0.001, "stress": 0.0015}
PRICE_MOVE_MIN = 0.003
OI_CHANGE_MIN = 0.001
TAKER_LONG_MIN = 0.53
TAKER_SHORT_MAX = 0.47
ENTRY_DELAY_BARS = 2
ATR_PERIOD = 14
STOP_ATR = 1.0
TARGET_ATR = 1.3
MAX_HOLD_BARS = 6
MODEL_THRESHOLD = 0.70
MIN_TRAIN_ROWS = 500
TRAINING_DAYS = 20


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _deduplicate_rows(rows: list, timestamp, name: str) -> list:
    unique = {}
    for row in rows:
        stamp = timestamp(row)
        previous = unique.get(stamp)
        if previous is not None and previous != row:
            raise ValueError(f"conflicting duplicate {name} timestamp {stamp}")
        unique[stamp] = row
    return [unique[stamp] for stamp in sorted(unique)]


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def _request(url: str) -> tuple[bytes, dict]:
    request = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "User-Agent": "laya-trader-oi-research/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
        meta = {"status": response.status, "date": response.headers.get("Date"),
                "content_type": response.headers.get("Content-Type"),
                "body_sha256": _sha(body), "bytes": len(body), "url": url}
    if meta["status"] != 200:
        raise RuntimeError(f"Binance returned HTTP {meta['status']}")
    return body, meta


def _fetch_pages(name: str, endpoint: str, params: dict, start: int, end: int,
                 limit: int, timestamp, direction: str) -> tuple[list, list[dict]]:
    cursor = start if direction == "forward" else end
    rows, pages, page_index = [], [], 0
    while (cursor <= end if direction == "forward" else cursor >= start):
        query = {**params, "startTime": cursor if direction == "forward" else start,
                 "endTime": cursor if direction == "backward" else end,
                 "limit": limit}
        url = BASE_URL + endpoint + "?" + urllib.parse.urlencode(query)
        body, meta = _request(url)
        parsed = json.loads(body.decode("utf-8", errors="strict"))
        if not isinstance(parsed, list):
            raise ValueError(f"{name} response is not a list")
        path = RAW / f"{name}_{page_index:03d}.json"
        if path.exists():
            raise FileExistsError(f"refusing to overwrite raw input {path}")
        path.write_bytes(body)
        meta["file"] = path.name
        pages.append(meta)
        if not parsed:
            break
        stamps = [timestamp(row) for row in parsed]
        if stamps != sorted(stamps) or len(stamps) != len(set(stamps)):
            raise ValueError(f"{name} timestamps are not unique and ordered")
        if direction == "forward":
            if stamps[0] < cursor or stamps[-1] > end:
                raise ValueError(f"{name} response outside requested time range")
            rows.extend(parsed)
            next_cursor = stamps[-1] + 1
            if next_cursor <= cursor:
                raise ValueError(f"{name} pagination failed to advance")
            cursor = next_cursor
        else:
            if stamps[-1] > cursor or stamps[0] < start - INTERVAL_MS:
                raise ValueError(f"{name} response outside requested time range")
            rows.extend(row for row, stamp in zip(parsed, stamps) if start <= stamp <= end)
            # The endpoint floors endTime to its 5m bucket; subtracting 1ms
            # skips the preceding bucket, so continue from the first row itself.
            next_cursor = stamps[0]
            if next_cursor >= cursor:
                raise ValueError(f"{name} reverse pagination failed to advance")
            cursor = next_cursor
            if stamps[0] <= start:
                break
        page_index += 1
        if len(parsed) < limit:
            break
        if page_index > 40:
            raise RuntimeError(f"{name} pagination exceeded bounded page count")
        time.sleep(0.12)
    return _deduplicate_rows(rows, timestamp, name), pages


def _acquire() -> tuple[dict[str, list], dict]:
    RAW.mkdir(parents=True, exist_ok=True)
    if INPUT_MANIFEST.exists():
        manifest = json.loads(INPUT_MANIFEST.read_text(encoding="utf-8"))
        data = {}
        for name, pages in manifest["sources"].items():
            joined = []
            for page in pages:
                body = (RAW / page["file"]).read_bytes()
                if _sha(body) != page["body_sha256"]:
                    raise ValueError(f"raw input changed: {page['file']}")
                joined.extend(json.loads(body.decode("utf-8", errors="strict")))
            timestamp = (lambda row: int(row[0])) if name == "klines" else (
                lambda row: int(row["fundingTime"]) if name == "funding" else int(row["timestamp"]))
            lower, upper = {
                "klines": (START_MS, END_MS - 1),
                "oi": (START_MS + INTERVAL_MS, END_MS),
                "taker": (START_MS, END_MS - 1),
                "funding": (START_MS, END_MS),
            }[name]
            bounded = [row for row in joined if lower <= timestamp(row) <= upper]
            data[name] = _deduplicate_rows(bounded, timestamp, name)
        return data, manifest
    if any(RAW.iterdir()):
        raise FileExistsError("partial raw directory without manifest; refusing to overwrite")
    before_body, before_meta = _request(BASE_URL + "/fapi/v1/time")
    before = json.loads(before_body.decode("utf-8", errors="strict"))["serverTime"]
    if before < END_MS:
        raise RuntimeError("exchange server is earlier than the frozen data cutoff")
    if before - START_MS >= 30 * 24 * 60 * 60 * 1000 + INTERVAL_MS:
        raise RuntimeError("frozen OI/taker start is outside the documented latest-30-day window")
    data, sources = {}, {}
    # OI timestamps denote period end; taker and kline timestamps denote period start.
    specs = {
        "klines": ("/fapi/v1/klines", {"symbol": SYMBOL, "interval": "5m"},
                   START_MS, END_MS - 1, 1500, lambda row: int(row[0]), "forward"),
        "oi": ("/futures/data/openInterestHist", {"symbol": SYMBOL, "period": "5m"},
               START_MS + INTERVAL_MS, END_MS, 500, lambda row: int(row["timestamp"]), "backward"),
        "taker": ("/futures/data/takerlongshortRatio", {"symbol": SYMBOL, "period": "5m"},
                  START_MS, END_MS - 1, 500, lambda row: int(row["timestamp"]), "backward"),
        "funding": ("/fapi/v1/fundingRate", {"symbol": SYMBOL},
                    START_MS, END_MS, 1000, lambda row: int(row["fundingTime"]), "forward"),
    }
    for name, (endpoint, params, start, end, limit, timestamp, direction) in specs.items():
        data[name], sources[name] = _fetch_pages(name, endpoint, params, start, end, limit, timestamp, direction)
    after_body, after_meta = _request(BASE_URL + "/fapi/v1/time")
    after = json.loads(after_body.decode("utf-8", errors="strict"))["serverTime"]
    manifest = {"symbol": SYMBOL, "interval": "5m", "window_start_ms": START_MS,
                "window_end_exclusive_ms": END_MS, "protocol_sha256": _sha(PROTOCOL.read_bytes()),
                "server_time_before_ms": before, "server_time_after_ms": after,
                "time_before_response": before_meta, "time_after_response": after_meta,
                "sources": sources, "source_row_counts": {key: len(value) for key, value in data.items()}}
    INPUT_MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return data, manifest


def _finite(value: float) -> bool:
    return math.isfinite(value)


def _align(data: dict) -> tuple[list[dict], dict]:
    klines = {}
    for row in data["klines"]:
        if len(row) != 12:
            raise ValueError("unexpected kline width")
        opened = int(row[0])
        values = [float(row[index]) for index in (1, 2, 3, 4, 5, 7, 9)]
        if not all(_finite(value) for value in values) or min(values[:5]) <= 0 or values[4] < 0 or values[5] < 0:
            raise ValueError(f"invalid kline at {opened}")
        op, high, low, close, volume, quote, taker_base = values
        if low > min(op, close) or high < max(op, close) or high < low or taker_base > volume + 1e-9:
            raise ValueError(f"inconsistent kline at {opened}")
        if opened in klines:
            raise ValueError("duplicate kline timestamp")
        klines[opened] = {"open_ms": opened, "open": op, "high": high, "low": low,
                          "close": close, "volume": volume, "quote_volume": quote,
                          "taker_buy_base": taker_base}

    oi = {}
    for row in data["oi"]:
        boundary = int(row["timestamp"])
        opened = boundary - INTERVAL_MS
        value = float(row["sumOpenInterest"])
        if not _finite(value) or value <= 0 or opened in oi:
            raise ValueError(f"invalid or duplicate OI at {boundary}")
        oi[opened] = value
    taker = {}
    for row in data["taker"]:
        opened = int(row["timestamp"])
        buy, sell = float(row["buyVol"]), float(row["sellVol"])
        if not _finite(buy) or not _finite(sell) or min(buy, sell) < 0 or buy + sell <= 0 or opened in taker:
            raise ValueError(f"invalid or duplicate taker volume at {opened}")
        taker[opened] = (buy, sell)

    common = sorted(set(klines) & set(oi) & set(taker))
    if not common:
        raise ValueError("no common bars across price, OI, and taker data")
    warmup_limit = 12 * INTERVAL_MS
    if common[0] - START_MS > warmup_limit:
        raise ValueError("initial source warm-up exceeds twelve bars")
    gaps = [(left, right) for left, right in zip(common, common[1:]) if right - left != INTERVAL_MS]
    if gaps:
        raise ValueError(f"unaligned/missing common bars after initial warm-up: {gaps[0]}")
    bars = []
    for opened in common:
        bar = dict(klines[opened])
        bar["oi"] = oi[opened]
        bar["taker_buy"] = taker[opened][0]
        bar["taker_sell"] = taker[opened][1]
        bars.append(bar)
    rates = []
    for row in data["funding"]:
        stamp, rate = int(row["fundingTime"]), float(row["fundingRate"])
        if not _finite(rate):
            raise ValueError("nonfinite funding rate")
        if START_MS < stamp <= END_MS:
            rates.append((stamp, rate))
    rates.sort()
    if any(a[0] == b[0] for a, b in zip(rates, rates[1:])):
        raise ValueError("duplicate funding timestamps")
    if len(rates) < 89:
        raise ValueError(f"funding history is incomplete: {len(rates)} settlements in a 30-day window")
    return bars, {"funding_rates": rates,
                  "common_rows": len(bars), "initial_warmup_missing_bars": (common[0]-START_MS)//INTERVAL_MS,
                  "first_common_open_ms": common[0], "last_common_open_ms": common[-1],
                  "kline_rows": len(klines), "oi_rows": len(oi), "taker_rows": len(taker),
                  "common_fraction_of_expected": len(bars)/((END_MS-START_MS)//INTERVAL_MS)}


def _features(bars: list[dict]) -> dict[int, dict]:
    tr = [0.0] * len(bars)
    for i in range(1, len(bars)):
        bar, prior = bars[i], bars[i-1]["close"]
        tr[i] = max(bar["high"]-bar["low"], abs(bar["high"]-prior), abs(bar["low"]-prior))
    output = {}
    for i in range(14, len(bars)):
        bar = bars[i]
        ret60 = bar["close"] / bars[i-12]["close"] - 1
        ret15 = bar["close"] / bars[i-3]["close"] - 1
        oi60 = bar["oi"] / bars[i-12]["oi"] - 1
        buy = math.fsum(bars[j]["taker_buy"] for j in range(i-11, i+1))
        sell = math.fsum(bars[j]["taker_sell"] for j in range(i-11, i+1))
        taker_fraction = buy / (buy + sell)
        atr_abs = fmean(tr[i-ATR_PERIOD+1:i+1])
        atr_fraction = atr_abs / bar["close"]
        candle_range = bar["high"] - bar["low"]
        close_position = (bar["close"]-bar["low"])/candle_range if candle_range else 0.5
        prior_volume = fmean(bars[j]["quote_volume"] for j in range(i-12, i))
        log_volume_ratio = math.log(max(bar["quote_volume"] / max(prior_volume, 1e-12), 1e-12))
        values = (ret60, ret15, oi60, taker_fraction, atr_fraction, close_position, log_volume_ratio)
        if not all(_finite(value) for value in values) or atr_abs <= 0:
            continue
        output[i] = {"x": list(values), "atr_abs": atr_abs, "return_60m": ret60,
                     "oi_change_60m": oi60, "taker_buy_fraction_60m": taker_fraction}
    return output


def _direction(feature: dict) -> int | None:
    ret, oi, flow = feature["return_60m"], feature["oi_change_60m"], feature["taker_buy_fraction_60m"]
    if abs(ret) < PRICE_MOVE_MIN or oi < OI_CHANGE_MIN:
        return None
    if ret > 0 and flow >= TAKER_LONG_MIN:
        return 1
    if ret < 0 and flow <= TAKER_SHORT_MAX:
        return -1
    return None


def _outcome(bars: list[dict], funding: list[tuple[int, float]], signal_index: int,
             direction: int, atr_abs: float, side_cost: float) -> dict | None:
    entry_index = signal_index + ENTRY_DELAY_BARS
    last_index = entry_index + MAX_HOLD_BARS - 1
    if last_index >= len(bars):
        return None
    entry_bar = bars[entry_index]
    entry_ms, entry = entry_bar["open_ms"], entry_bar["open"]
    stop = entry - direction * STOP_ATR * atr_abs
    target = entry + direction * TARGET_ATR * atr_abs
    exit_price, exit_index, reason = None, None, None
    for i in range(entry_index, last_index + 1):
        bar = bars[i]
        op, high, low = bar["open"], bar["high"], bar["low"]
        if direction == 1:
            if op <= stop:
                exit_price, reason = op, "stop_gap"
            elif op >= target:
                exit_price, reason = target, "target_gap"
            elif low <= stop:
                exit_price, reason = stop, "stop"
            elif high >= target:
                exit_price, reason = target, "target"
        else:
            if op >= stop:
                exit_price, reason = op, "stop_gap"
            elif op <= target:
                exit_price, reason = target, "target_gap"
            elif high >= stop:
                exit_price, reason = stop, "stop"
            elif low <= target:
                exit_price, reason = target, "target"
        if reason:
            exit_index = i
            break
    if exit_index is None:
        exit_index = last_index
        exit_price = bars[last_index]["close"]
        reason = "timeout"
    available_ms = bars[exit_index]["open_ms"] + INTERVAL_MS
    funding_rates = [(stamp, rate) for stamp, rate in funding if entry_ms < stamp <= available_ms]
    funding_cost = direction * math.fsum(rate for _, rate in funding_rates)
    gross = direction * (exit_price / entry - 1)
    net = gross - 2 * side_cost - funding_cost
    adverse_price = (min(bars[j]["low"] for j in range(entry_index, exit_index+1)) if direction == 1
                     else max(bars[j]["high"] for j in range(entry_index, exit_index+1)))
    return {"signal_ms": bars[signal_index]["open_ms"] + INTERVAL_MS,
            "entry_ms": entry_ms, "exit_ms": bars[exit_index]["open_ms"],
            "available_ms": available_ms, "entry_price": entry, "exit_price": exit_price,
            "stop_price": stop, "target_price": target, "direction": direction,
            "gross_return_pct": 100*gross, "funding_return_pct": -100*funding_cost,
            "net_return_pct": 100*net, "adverse_price": adverse_price,
            "exit_reason": reason, "held_bars": exit_index-entry_index+1,
            "held_minutes_upper_bound": 5*(exit_index-entry_index+1),
            "funding_events": len(funding_rates), "label_win": int(net > 0),
            "exit_index": exit_index}


def _training_data(bars: list[dict], features: dict[int, dict], funding: list[tuple[int, float]]) -> tuple[list, list, list, dict]:
    xs, ys, groups, audits = [], [], [], []
    for i, feature in features.items():
        decision_ms = bars[i]["open_ms"] + INTERVAL_MS
        if decision_ms >= VALIDATION_START_MS:
            break
        direction = _direction(feature)
        if direction is None:
            continue
        outcome = _outcome(bars, funding, i, direction, feature["atr_abs"], COSTS["stress"])
        if outcome is None or outcome["available_ms"] >= VALIDATION_START_MS:
            continue
        xs.append(feature["x"])
        ys.append(outcome["label_win"])
        groups.append(datetime.fromtimestamp(decision_ms/1000, timezone.utc).date().isoformat())
        audits.append({"decision_ms": decision_ms, "direction": direction,
                       "label_win": outcome["label_win"], "available_ms": outcome["available_ms"]})
    return xs, ys, groups, {"rows": len(ys), "wins": sum(ys), "losses": len(ys)-sum(ys),
                            "calendar_days": len(set(groups)), "overlapping_labels": True,
                            "last_label_available_ms": max((row["available_ms"] for row in audits), default=None)}


def _fit(xs: list, ys: list, groups: list):
    if len(ys) < MIN_TRAIN_ROWS or len(set(ys)) < 2:
        return None
    counts = Counter(groups)
    day_scale = len(groups) / len(counts)
    weights = [day_scale/counts[group] for group in groups]
    model = HistGradientBoostingClassifier(max_iter=100, learning_rate=0.05, max_leaf_nodes=7,
                                           min_samples_leaf=40, l2_regularization=10.0,
                                           early_stopping=False, random_state=2026)
    model.fit(xs, ys, sample_weight=weights)
    return model


def _backtest(bars: list[dict], features: dict[int, dict], funding: list[tuple[int, float]],
              model, use_ml: bool, cost: float) -> tuple[dict, list[dict]]:
    trades, decisions = [], []
    equity, peak, max_dd = 1.0, 1.0, 0.0
    i = 14
    while i in features and i < len(bars):
        feature = features[i]
        decision_ms = bars[i]["open_ms"] + INTERVAL_MS
        if decision_ms < VALIDATION_START_MS:
            i += 1
            continue
        if decision_ms >= END_MS - (ENTRY_DELAY_BARS+MAX_HOLD_BARS+1)*INTERVAL_MS:
            break
        direction = _direction(feature)
        if direction is None:
            i += 1
            continue
        probability = None
        if use_ml:
            if model is None:
                i += 1
                continue
            class_index = list(model.classes_).index(1)
            probability = float(model.predict_proba([feature["x"]])[0][class_index])
            if probability < MODEL_THRESHOLD:
                decisions.append({"signal_ms": decision_ms, "probability": probability,
                                  "direction": direction, "accepted": False})
                i += 1
                continue
        outcome = _outcome(bars, funding, i, direction, feature["atr_abs"], cost)
        if outcome is None or outcome["available_ms"] >= END_MS:
            i += 1
            continue
        outcome["probability_win"] = probability
        outcome["equity_before"] = equity
        outcome["net_pnl_equity_pct"] = 100 * outcome["net_return_pct"] / 100
        trades.append(outcome)
        decisions.append({"signal_ms": decision_ms, "probability": probability,
                          "direction": direction, "accepted": True,
                          "exit_ms": outcome["exit_ms"], "exit_reason": outcome["exit_reason"]})

        # Mark adverse candle extremes while open; candle ordering is unknown, so this is a conservative bound.
        entry_index = i + ENTRY_DELAY_BARS
        exit_index = outcome["exit_index"]
        mark_funding = 0.0
        for stamp, rate in funding:
            if outcome["entry_ms"] < stamp <= outcome["available_ms"]:
                mark_funding += direction * rate
        adverse = outcome["adverse_price"]
        adverse_factor = 1 + direction*(adverse/outcome["entry_price"]-1) - cost - mark_funding
        adverse_equity = max(0.0, equity * adverse_factor)
        max_dd = max(max_dd, 1 - adverse_equity / peak)
        equity *= 1 + outcome["net_return_pct"] / 100
        peak = max(peak, equity)
        max_dd = max(max_dd, 1 - equity / peak)
        i = max(i+1, exit_index+1)

    returns = [trade["net_return_pct"] for trade in trades]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    mean_win = fmean(wins) if wins else None
    mean_loss = fmean(losses) if losses else None
    summary = {"trades": len(trades), "wins": len(wins), "losses": len(losses),
               "win_rate_pct": 100*len(wins)/len(trades) if trades else None,
               "net_payoff_ratio": mean_win/abs(mean_loss) if mean_win is not None and mean_loss is not None else None,
               "ev_net_pct_per_trade_on_entry_notional": fmean(returns) if returns else None,
               "mean_win_pct": mean_win, "mean_loss_pct": mean_loss,
               "portfolio_return_pct": 100*(equity-1), "max_drawdown_pct": 100*max_dd,
               "unresolved_exits": 0, "cost_per_side_pct": 100*cost,
               "decisions_considered": len(decisions),
               "accepted_decisions": sum(row["accepted"] for row in decisions)}
    return summary, trades


def _gates(summary: dict) -> dict:
    return {"win_rate_at_least_70_pct": summary["win_rate_pct"] is not None and summary["win_rate_pct"] >= 70,
            "payoff_at_least_1_to_1": summary["net_payoff_ratio"] is not None and summary["net_payoff_ratio"] >= 1,
            "ev_above_1_2_pct": summary["ev_net_pct_per_trade_on_entry_notional"] is not None and summary["ev_net_pct_per_trade_on_entry_notional"] > 1.2,
            "drawdown_at_most_10_pct": summary["max_drawdown_pct"] <= 10,
            "minimum_30_trades": summary["trades"] >= 30}


def _run() -> dict:
    data, manifest = _acquire()
    bars, alignment = _align(data)
    features = _features(bars)
    xs, ys, groups, train_audit = _training_data(bars, features, alignment["funding_rates"])
    model = _fit(xs, ys, groups)
    outcomes = {"baseline": {}, "filtered": {}}
    trades_by_scenario = []
    for label, use_ml in (("baseline", False), ("filtered", True)):
        for cost_name, cost in COSTS.items():
            summary, trades = _backtest(bars, features, alignment["funding_rates"], model, use_ml, cost)
            summary["gates"] = _gates(summary)
            outcomes[label][cost_name] = summary
            for trade in trades:
                trades_by_scenario.append({"strategy": label, "cost": cost_name, **trade})
    stress = outcomes["filtered"]["stress"]
    base = outcomes["filtered"]["base"]
    passes = all(stress["gates"].values()) and base["win_rate_pct"] is not None and base["win_rate_pct"] >= 65
    manifest_bytes = INPUT_MANIFEST.read_bytes()
    report = {"created_utc": datetime.now(timezone.utc).isoformat(),
              "hypothesis": "five-minute price continuation confirmed by OI expansion and taker flow; HGB entry filter",
              "symbol": SYMBOL, "contract": "USDⓈ-M perpetual", "interval": "5m",
              "window": {"start_ms": START_MS, "validation_start_ms": VALIDATION_START_MS,
                         "end_exclusive_ms": END_MS, "start_utc": _utc(START_MS),
                         "validation_start_utc": _utc(VALIDATION_START_MS), "end_utc": _utc(END_MS),
                         "server_asof_ms": AS_OF_SERVER_MS},
              "parameters": {"price_move_min_pct": 100*PRICE_MOVE_MIN, "oi_increase_min_pct": 100*OI_CHANGE_MIN,
                             "taker_long_min": TAKER_LONG_MIN, "taker_short_max": TAKER_SHORT_MAX,
                             "entry_delay_bars": ENTRY_DELAY_BARS, "stop_atr": STOP_ATR,
                             "target_atr": TARGET_ATR, "max_hold_bars": MAX_HOLD_BARS,
                             "model_threshold": MODEL_THRESHOLD, "min_train_rows": MIN_TRAIN_ROWS,
                             "model_available": model is not None,
                             "model": {"type": "HistGradientBoostingClassifier", "max_iter": 100,
                                       "learning_rate": 0.05, "max_leaf_nodes": 7, "min_samples_leaf": 40,
                                       "l2_regularization": 10.0, "early_stopping": False, "random_state": 2026},
                             "features": list(FEATURES), "position_notional": "100% of equity; no leverage",
                             "costs_per_side_pct": {key: 100*value for key, value in COSTS.items()}},
              "training": train_audit, "alignment": alignment,
              "source_manifest_sha256": _sha(manifest_bytes),
              "protocol_sha256": _sha(PROTOCOL.read_bytes()),
              "analysis_code_sha256": _sha(Path(__file__).read_bytes()),
              "passes_primary_gates": passes,
              "limits": ["The official OI/taker endpoint exposes at most the latest 30 days.",
                         "Historical API responses were fetched now; their original publication time and revisions are unknown.",
                         "Five-minute labels overlap in training; effective sample size is below row count.",
                         "The validation spans 10 days and is too short to establish annual consistency.",
                         "HGB probabilities are not calibrated; threshold results are empirical only.",
                         "Intrabar candle path and actual fills are unknown; stop-first convention is conservative.",
                         "EV is expressed on entry notional; no leverage is used; account-specific fee tiers are unknown.",
                         "The tested date range was inspected by other repo studies at coarser granularity."],
              "results": outcomes}
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    fields = ["strategy", "cost", "signal_ms", "entry_ms", "exit_ms", "direction", "entry_price", "exit_price",
              "stop_price", "target_price", "gross_return_pct", "funding_return_pct", "net_return_pct",
              "probability_win", "exit_reason", "held_bars", "held_minutes_upper_bound", "funding_events"]
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for trade in trades_by_scenario:
            writer.writerow({key: trade.get(key) for key in fields})
    lines = ["# Resultado: OI e fluxo taker em 5 minutos", "",
             "A hipótese congelada combina expansão de open interest, direção do preço e fluxo taker em BTCUSDT perpétuo. Os primeiros 20 dias formaram a janela de treino e os últimos 10 dias, a validação temporal; o HGB só é ajustado quando a amostra atinge o mínimo congelado. Custos em percentual por lado; o drawdown marca uma posição por vez com notional igual ao patrimônio e sem alavancagem.", "",
             f"Treino: {train_audit['rows']} rótulos ({train_audit['wins']} vitórias, {train_audit['losses']} perdas), {train_audit['calendar_days']} dias; HGB {'ajustado' if model else 'indisponível por amostra/classe insuficiente'}. Dados alinhados: {alignment['common_rows']} candles; primeiro candle comum {_utc(alignment['first_common_open_ms'])}; último {_utc(alignment['last_common_open_ms'])}.", "",
             "| Estratégia | Custo/lado | Trades | Acerto | Payoff | EV/trade | DD | Retorno da carteira |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for label, title in (("baseline", "Regra-base"), ("filtered", "Regra + HGB")):
        for cost_name in ("base", "stress"):
            row = outcomes[label][cost_name]
            def fmt(value, suffix="%"):
                return "—" if value is None else f"{value:.2f}{suffix}".replace(".", ",")
            lines.append(f"| {title} | {fmt(row['cost_per_side_pct'])} | {row['trades']} | {fmt(row['win_rate_pct'])} | {fmt(row['net_payoff_ratio'], '')} | {fmt(row['ev_net_pct_per_trade_on_entry_notional'])} | {fmt(row['max_drawdown_pct'])} | {fmt(row['portfolio_return_pct'])} |")
    lines += ["", "## Decisão", "",
              "O filtro passou os gates nesta triagem." if passes else "A regra não passou todos os gates congelados; esta janela curta não demonstra a meta nem permite ajustes sem novo período independente.",
              "A amostra de validação é curta, a faixa inteira foi vista em pesquisas anteriores e os rótulos de treino sobrepõem-se. Nenhum resultado autoriza ordens reais.", "",
              "## Integridade", "",
              f"- Protocolo SHA-256 `{report['protocol_sha256']}`; código `{report['analysis_code_sha256']}`.",
              f"- Manifesto de aquisição SHA-256 `{report['source_manifest_sha256']}`.",
              f"- Trades completos: [CSV](../results/{OUTPUT_CSV.name}); métricas e proveniência: `results/{OUTPUT.name}`.",
              f"- Arquivos brutos e paginação: `results/{RUN.name}/raw/` e `input_manifest.json`.",
              "- Nenhuma chamada paga ao JEV ou ordem real foi feita.", ""]
    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(json.dumps({"passes_primary_gates": passes, "model_available": model is not None,
                      "training_rows": train_audit['rows'],
                      "validation": {name: outcomes[name]['stress'] for name in outcomes},
                      "outputs": [str(OUTPUT), str(OUTPUT_CSV), str(OUTPUT_MD), str(INPUT_MANIFEST)]}, ensure_ascii=True))
    return report


if __name__ == "__main__":
    _run()
