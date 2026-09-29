"""Frozen hourly Supertrend strategy with an expanding ML trade-outcome filter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
import platform
from statistics import fmean, pstdev

import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from .binance_data import HOUR_MS
from .macro_external_alpha_research import (
    FINAL_HOLDOUT,
    INITIAL_EQUITY,
    SIDE_COSTS,
    SYMBOLS,
    period_index,
    period_returns,
    resolve_schedule,
    sha256,
    utc_datetime,
    write_csv,
)

ROOT = Path.cwd()
PROTOCOL_PATH = ROOT / "docs" / "supertrend_ml_protocol_2026-09-27.md"
SOURCES_PATH = ROOT / "docs" / "supertrend_ml_sources_2026-09-27.md"
SCRIPT_PATH = ROOT / "src" / "jev_trader" / "supertrend_ml_research.py"
REPORT_PATH = ROOT / "docs" / "supertrend_ml_research_2026-09-27.md"
JSON_PATH = ROOT / "results" / "supertrend_ml_research.json"
FORECASTS_PATH = ROOT / "results" / "supertrend_ml_forecasts.csv"
CURVES_PATH = ROOT / "results" / "supertrend_ml_curves.csv"
FILLS_PATH = ROOT / "results" / "supertrend_ml_fills.csv"
ATR_LENGTH = 10
ATR_MULTIPLIER = 3.0
MIN_TRAIN_TRADES = 100
HGB_CONFIG = {
    "max_iter": 100,
    "max_leaf_nodes": 7,
    "learning_rate": 0.05,
    "l2_regularization": 1.0,
    "min_samples_leaf": 20,
    "early_stopping": False,
}
FEATURE_NAMES = (
    "distance_to_supertrend_atr",
    "atr_fraction_close",
    "return_4h",
    "return_24h",
    "realized_volatility_24h",
    "volume_to_previous_24h_mean",
)
UTC = timezone.utc


@dataclass(frozen=True)
class HourState:
    atr: float | None
    upper: float | None
    lower: float | None
    line: float | None
    direction: int | None
    segment: int


def build_supertrend(bars):
    states = []
    segment = 0
    previous_bar = None
    previous_atr = None
    previous_upper = None
    previous_lower = None
    previous_direction = -1
    tr_buffer = []
    for bar in bars:
        if previous_bar is not None and bar.open_ms - previous_bar.open_ms != HOUR_MS:
            segment += 1
            previous_atr = None
            previous_upper = None
            previous_lower = None
            previous_direction = -1
            tr_buffer = []
        if previous_bar is None or states and states[-1].segment != segment:
            true_range = bar.high - bar.low
        else:
            true_range = max(
                bar.high - bar.low,
                abs(bar.high - previous_bar.close),
                abs(bar.low - previous_bar.close),
            )
        tr_buffer.append(true_range)
        if previous_atr is None:
            atr = fmean(tr_buffer) if len(tr_buffer) == ATR_LENGTH else None
        else:
            atr = ((previous_atr * (ATR_LENGTH - 1)) + true_range) / ATR_LENGTH

        if atr is None:
            states.append(HourState(None, None, None, None, None, segment))
            previous_bar = bar
            continue

        midpoint = (bar.high + bar.low) / 2.0
        basic_upper = midpoint + ATR_MULTIPLIER * atr
        basic_lower = midpoint - ATR_MULTIPLIER * atr
        if previous_upper is None or previous_lower is None:
            upper, lower = basic_upper, basic_lower
            direction = -1
        else:
            upper = basic_upper if basic_upper < previous_upper or previous_bar.close > previous_upper else previous_upper
            lower = basic_lower if basic_lower > previous_lower or previous_bar.close < previous_lower else previous_lower
            if previous_direction < 0:
                direction = 1 if bar.close > upper else -1
            else:
                direction = -1 if bar.close < lower else 1
        line = lower if direction > 0 else upper
        states.append(HourState(atr, upper, lower, line, direction, segment))
        previous_bar = bar
        previous_atr = atr
        previous_upper = upper
        previous_lower = lower
        previous_direction = direction
    return states


def event_features(bars, states, index):
    if index < 24:
        return None
    current = states[index]
    if current.atr is None or current.line is None:
        return None
    segment = current.segment
    if any(state.segment != segment or state.atr is None for state in states[index - 24:index + 1]):
        return None
    current_close = bars[index].close
    close_4h = bars[index - 4].close
    close_24h = bars[index - 24].close
    returns = [math.log(bars[i].close / bars[i - 1].close) for i in range(index - 23, index + 1)]
    prior_volume_mean = fmean(bars[i].volume for i in range(index - 24, index))
    if prior_volume_mean <= 0 or current.atr <= 0 or current_close <= 0:
        return None
    result = {
        "distance_to_supertrend_atr": (current_close - current.line) / current.atr,
        "atr_fraction_close": current.atr / current_close,
        "return_4h": current_close / close_4h - 1.0,
        "return_24h": current_close / close_24h - 1.0,
        "realized_volatility_24h": pstdev(returns),
        "volume_to_previous_24h_mean": bars[index].volume / prior_volume_mean,
    }
    if not all(math.isfinite(result[name]) for name in FEATURE_NAMES):
        raise ValueError("nonfinite Supertrend event feature")
    return result


def make_events(bars_by_symbol, boundaries):
    first_ms, terminal_ms = boundaries[0], boundaries[-1]
    all_candidates = []
    completed_events = []
    for symbol in SYMBOLS:
        bars = sorted((bar for bar in bars_by_symbol[symbol].values()
                       if bar.open_ms <= terminal_ms), key=lambda bar: bar.open_ms)
        states = build_supertrend(bars)
        flips = []
        for index in range(1, len(bars) - 1):
            prior, current = states[index - 1], states[index]
            if prior.direction is None or current.direction is None or prior.segment != current.segment:
                continue
            if bars[index].open_ms < first_ms or bars[index].open_ms >= terminal_ms:
                continue
            if prior.direction < 0 and current.direction > 0:
                kind = "BUY_SIGNAL"
            elif prior.direction > 0 and current.direction < 0:
                kind = "SELL_SIGNAL"
            else:
                continue
            features = event_features(bars, states, index) if kind == "BUY_SIGNAL" else None
            flips.append({
                "symbol": symbol,
                "kind": kind,
                "signal_index": index,
                "signal_close_ms": bars[index].open_ms + HOUR_MS,
                "execution_ms": bars[index + 1].open_ms,
                "execution_price": bars[index + 1].open,
                "features": features,
                "segment": current.segment,
            })

        buys = [event for event in flips if event["kind"] == "BUY_SIGNAL"]
        sells = [event for event in flips if event["kind"] == "SELL_SIGNAL"]
        for buy in buys:
            if buy["features"] is None:
                continue
            candidate = {
                **buy,
                "event_id": f"{symbol}:{buy['signal_close_ms']}",
                "entry_execution_ms": buy["execution_ms"],
                "entry_price": buy["execution_price"],
            }
            all_candidates.append(candidate)
            next_sell = next((event for event in sells
                              if event["signal_index"] > buy["signal_index"]
                              and event["segment"] == buy["segment"]), None)
            if next_sell is None:
                continue
            episode = {
                **candidate,
                "exit_signal_index": next_sell["signal_index"],
                "exit_execution_ms": next_sell["execution_ms"],
                "exit_price": next_sell["execution_price"],
            }
            episode["gross_return"] = episode["exit_price"] / episode["entry_price"] - 1.0
            completed_events.append(episode)

        for event in flips:
            event["event_id"] = f"{symbol}:{event['signal_close_ms']}:{event['kind']}"
            event["signal_bar_open_ms"] = bars[event["signal_index"]].open_ms
    all_candidates.sort(key=lambda row: (row["signal_close_ms"], row["symbol"]))
    completed_events.sort(key=lambda row: (row["signal_close_ms"], row["symbol"]))
    for event in all_candidates:
        if event["entry_execution_ms"] != event["signal_close_ms"]:
            raise ValueError("Supertrend signal is not aligned to the next hourly open")
    for event in completed_events:
        if event["exit_execution_ms"] <= event["entry_execution_ms"]:
            raise ValueError("Supertrend trade has nonpositive duration")
    return all_candidates, completed_events


def forecast_trade_returns(candidates, completed_events, side_cost):
    forecasts = []
    model = HistGradientBoostingRegressor(**HGB_CONFIG)
    outcomes = {row["event_id"]: row for row in completed_events}
    for event in candidates:
        training = [row for row in completed_events
                    if row["exit_execution_ms"] < event["signal_close_ms"]]
        if len(training) < MIN_TRAIN_TRADES:
            continue
        x_train = np.asarray([[row["features"][name] for name in FEATURE_NAMES]
                              for row in training], dtype=float)
        y_train = np.asarray([
            (row["exit_price"] / row["entry_price"])
            * (1 - side_cost) / (1 + side_cost) - 1
            for row in training
        ], dtype=float)
        x_now = np.asarray([[event["features"][name] for name in FEATURE_NAMES]], dtype=float)
        # Windows sandbox blocks worker-pool creation; a single thread leaves
        # the estimator, features, and fit protocol unchanged.
        with threadpool_limits(limits=1):
            model.fit(x_train, y_train)
            prediction = float(model.predict(x_now)[0])
        if not math.isfinite(prediction):
            raise ValueError("HistGradientBoostingRegressor emitted nonfinite prediction")
        outcome = outcomes.get(event["event_id"])
        actual = None
        if outcome is not None:
            actual = (outcome["exit_price"] / outcome["entry_price"])
            actual = actual * (1 - side_cost) / (1 + side_cost) - 1
        forecasts.append({
            "event_id": event["event_id"],
            "symbol": event["symbol"],
            "signal_timestamp_ms": event["signal_close_ms"],
            "entry_execution_ms": event["entry_execution_ms"],
            "exit_execution_ms": outcome["exit_execution_ms"] if outcome else None,
            "side_cost": side_cost,
            "predicted_net_return": prediction,
            "actual_net_return": actual,
            "training_mean_net_return": float(np.mean(y_train)),
            "training_count": len(training),
            "training_last_exit_ms": max(row["exit_execution_ms"] for row in training),
            "entry_accepted": prediction > 0,
        })
    return forecasts


def regression_scores(forecasts, start_ms, end_ms):
    rows = [row for row in forecasts
            if start_ms <= row["signal_timestamp_ms"] < end_ms
            and row["actual_net_return"] is not None]
    if not rows:
        return {"count": 0}
    actual = np.asarray([row["actual_net_return"] for row in rows])
    predicted = np.asarray([row["predicted_net_return"] for row in rows])
    mean = np.asarray([row["training_mean_net_return"] for row in rows])
    return {
        "count": len(rows),
        "unique_signal_weeks": len({row["signal_timestamp_ms"] // (7 * HOUR_MS * 24) for row in rows}),
        "mae": float(np.mean(np.abs(actual - predicted))),
        "mae_zero": float(np.mean(np.abs(actual))),
        "mae_training_mean": float(np.mean(np.abs(actual - mean))),
        "net_positive_hit_pct": 100 * float(np.mean((predicted > 0) == (actual > 0))),
        "accepted_count": sum(row["entry_accepted"] for row in rows),
        "accepted_realized_mean_net_pct": (
            100 * float(np.mean([row["actual_net_return"] for row in rows if row["entry_accepted"]]))
            if any(row["entry_accepted"] for row in rows) else None
        ),
    }


def replay(bars_by_symbol, boundaries, flips, forecasts, *, model, side_cost,
           start_index, end_index):
    start_ms, end_ms = boundaries[start_index], boundaries[end_index]
    bars = {symbol: bars_by_symbol[symbol] for symbol in SYMBOLS}
    forecast_by_event = {row["event_id"]: row for row in forecasts if row["side_cost"] == side_cost}
    signal_map = {(symbol, timestamp): event for symbol, timestamp, event in flips}
    cash = {symbol: INITIAL_EQUITY / len(SYMBOLS) for symbol in SYMBOLS}
    quantity = {symbol: 0.0 for symbol in SYMBOLS}
    fills, curve = [], []
    fees = turnover = 0.0
    order_count = 0
    trade_entries = trade_exits = 0
    peak_open = peak_adverse = INITIAL_EQUITY
    max_dd_open = max_dd_adverse = 0.0
    average_exposure_sum = {symbol: 0.0 for symbol in SYMBOLS}
    exposed_hours = {symbol: 0 for symbol in SYMBOLS}
    hours = (end_ms - start_ms) // HOUR_MS

    def portfolio_value(timestamp, field="open"):
        return math.fsum(cash[symbol] + quantity[symbol] * getattr(bars[symbol][timestamp], field)
                         for symbol in SYMBOLS)

    for timestamp in range(start_ms, end_ms + HOUR_MS, HOUR_MS):
        if any(timestamp not in bars[symbol] for symbol in SYMBOLS):
            raise ValueError(f"missing hourly bar at {timestamp}")
        pre_by_symbol = {
            symbol: cash[symbol] + quantity[symbol] * bars[symbol][timestamp].open
            for symbol in SYMBOLS
        }
        pre = portfolio_value(timestamp)
        if model in ("supertrend", "supertrend_ml") and timestamp < end_ms:
            for symbol in SYMBOLS:
                event = signal_map.get((symbol, timestamp))
                if event is None:
                    continue
                if event["kind"] == "BUY_SIGNAL" and quantity[symbol] <= 0:
                    accepted = model == "supertrend"
                    forecast = forecast_by_event.get(event["event_id"])
                    if model == "supertrend_ml":
                        accepted = forecast is not None and forecast["predicted_net_return"] > 0
                    if accepted:
                        bar = bars[symbol][timestamp]
                        equity = cash[symbol]
                        traded = equity / (1 + side_cost)
                        fee = traded * side_cost
                        units = traded / bar.open
                        cash[symbol] -= traded + fee
                        quantity[symbol] += units
                        fees += fee
                        turnover += traded
                        order_count += 1
                        trade_entries += 1
                        fills.append({
                            "model": model, "side_cost": side_cost,
                            "timestamp_utc": utc_datetime(timestamp).isoformat().replace("+00:00", "Z"),
                            "symbol": symbol, "side": "BUY", "price": bar.open,
                            "quantity": units, "notional": traded, "fee": fee,
                            "predicted_net_return": forecast["predicted_net_return"] if forecast else None,
                        })
                elif event["kind"] == "SELL_SIGNAL" and quantity[symbol] > 0:
                    bar = bars[symbol][timestamp]
                    traded = quantity[symbol] * bar.open
                    fee = traded * side_cost
                    units = quantity[symbol]
                    quantity[symbol] = 0.0
                    cash[symbol] += traded - fee
                    fees += fee
                    turnover += traded
                    order_count += 1
                    trade_exits += 1
                    fills.append({
                        "model": model, "side_cost": side_cost,
                        "timestamp_utc": utc_datetime(timestamp).isoformat().replace("+00:00", "Z"),
                        "symbol": symbol, "side": "SELL", "price": bar.open,
                        "quantity": units, "notional": traded, "fee": fee,
                        "predicted_net_return": None,
                    })

        if timestamp == end_ms:
            for symbol in SYMBOLS:
                if quantity[symbol] <= 0:
                    continue
                bar = bars[symbol][timestamp]
                traded = quantity[symbol] * bar.open
                fee = traded * side_cost
                units = quantity[symbol]
                cash[symbol] += traded - fee
                quantity[symbol] = 0.0
                fees += fee
                turnover += traded
                order_count += 1
                trade_exits += 1
                fills.append({
                    "model": model, "side_cost": side_cost,
                    "timestamp_utc": utc_datetime(timestamp).isoformat().replace("+00:00", "Z"),
                    "symbol": symbol, "side": "SELL_TERMINAL", "price": bar.open,
                    "quantity": units, "notional": traded, "fee": fee,
                    "predicted_net_return": None,
                })

        post = portfolio_value(timestamp)
        high = portfolio_value(timestamp, "high")
        low = portfolio_value(timestamp, "low")
        for symbol in SYMBOLS:
            bar = bars[symbol][timestamp]
            exposed_hours[symbol] += int(quantity[symbol] > 0)
            account = cash[symbol] + quantity[symbol] * bar.open
            if account > 0:
                average_exposure_sum[symbol] += quantity[symbol] * bar.open / account
        peak_open = max(peak_open, pre, post)
        max_dd_open = max(max_dd_open, 1.0 - post / peak_open)
        peak_adverse = max(peak_adverse, pre, post, high)
        max_dd_adverse = max(max_dd_adverse, 1.0 - low / peak_adverse)
        curve.append({
            "timestamp_ms": timestamp,
            "timestamp_utc": utc_datetime(timestamp).isoformat().replace("+00:00", "Z"),
            "equity_pre": pre,
            "equity_post": post,
            "equity_intrahour_high": high,
            "equity_intrahour_low": low,
        })

    final = portfolio_value(end_ms)
    days = (end_ms - start_ms) / (24 * HOUR_MS)
    cagr = (final / INITIAL_EQUITY) ** (365.25 / days) - 1 if final > 0 else -1.0
    asset_results = {}
    for symbol in SYMBOLS:
        asset_final = cash[symbol] + quantity[symbol] * bars[symbol][end_ms].open
        sleeve = INITIAL_EQUITY / len(SYMBOLS)
        asset_results[symbol] = {
            "return_pct": 100 * (asset_final / sleeve - 1),
            "average_exposure_pct_account": 100 * average_exposure_sum[symbol] / hours,
            "exposure_pct_hours": 100 * exposed_hours[symbol] / hours,
        }
    return {
        "model": model,
        "side_cost": side_cost,
        "start_utc": utc_datetime(start_ms).isoformat().replace("+00:00", "Z"),
        "end_utc": utc_datetime(end_ms).isoformat().replace("+00:00", "Z"),
        "start_index": start_index,
        "end_index": end_index,
        "final_equity": final,
        "return_pct": 100 * (final - INITIAL_EQUITY),
        "cagr_pct": 100 * cagr,
        "max_drawdown_open_pct": 100 * max_dd_open,
        "max_drawdown_adverse_hourly_pct": 100 * max_dd_adverse,
        "average_exposure_pct_account": 100 * math.fsum(average_exposure_sum.values()) / (hours * len(SYMBOLS)),
        "exposure_pct_asset_hours": 100 * math.fsum(exposed_hours.values()) / (hours * len(SYMBOLS)),
        "order_count": order_count,
        "trade_entries": trade_entries,
        "trade_exits": trade_exits,
        "fees_initial_equity_units": fees,
        "turnover_initial_equity_units": turnover,
        "asset_results": asset_results,
        "annual_returns": period_returns(curve, start_ms, end_ms, "year"),
        "monthly_returns": period_returns(curve, start_ms, end_ms, "month"),
        "curve": curve,
        "fills": fills,
    }


def replay_benchmark(bars_by_symbol, boundaries, *, model, side_cost, start_index, end_index):
    start_ms, end_ms = boundaries[start_index], boundaries[end_index]
    cash = {symbol: INITIAL_EQUITY / len(SYMBOLS) for symbol in SYMBOLS}
    quantity = {symbol: 0.0 for symbol in SYMBOLS}
    fills, curve = [], []
    fees = turnover = 0.0
    order_count = 0
    if model == "buy_hold":
        for symbol in SYMBOLS:
            bar = bars_by_symbol[symbol][start_ms]
            traded = cash[symbol] / (1 + side_cost)
            fee = traded * side_cost
            quantity[symbol] = traded / bar.open
            cash[symbol] -= traded + fee
            fees += fee
            turnover += traded
            order_count += 1
            fills.append({"model": model, "side_cost": side_cost, "timestamp_utc": utc_datetime(start_ms).isoformat().replace("+00:00", "Z"),
                          "symbol": symbol, "side": "BUY", "price": bar.open, "quantity": quantity[symbol],
                          "notional": traded, "fee": fee, "predicted_net_return": None})
    peak_open = peak_adverse = INITIAL_EQUITY
    max_dd_open = max_dd_adverse = 0.0
    for timestamp in range(start_ms, end_ms + HOUR_MS, HOUR_MS):
        pre = math.fsum(cash[s] + quantity[s] * bars_by_symbol[s][timestamp].open for s in SYMBOLS)
        if timestamp == end_ms and model == "buy_hold":
            for symbol in SYMBOLS:
                traded = quantity[symbol] * bars_by_symbol[symbol][timestamp].open
                fee = traded * side_cost
                units = quantity[symbol]
                cash[symbol] += traded - fee
                quantity[symbol] = 0.0
                fees += fee
                turnover += traded
                order_count += 1
                fills.append({"model": model, "side_cost": side_cost, "timestamp_utc": utc_datetime(timestamp).isoformat().replace("+00:00", "Z"),
                              "symbol": symbol, "side": "SELL_TERMINAL", "price": bars_by_symbol[symbol][timestamp].open,
                              "quantity": units, "notional": traded, "fee": fee, "predicted_net_return": None})
        post = math.fsum(cash[s] + quantity[s] * bars_by_symbol[s][timestamp].open for s in SYMBOLS)
        high = math.fsum(cash[s] + quantity[s] * bars_by_symbol[s][timestamp].high for s in SYMBOLS)
        low = math.fsum(cash[s] + quantity[s] * bars_by_symbol[s][timestamp].low for s in SYMBOLS)
        peak_open = max(peak_open, pre, post)
        max_dd_open = max(max_dd_open, 1 - post / peak_open)
        peak_adverse = max(peak_adverse, pre, post, high)
        max_dd_adverse = max(max_dd_adverse, 1 - low / peak_adverse)
        curve.append({
            "timestamp_ms": timestamp,
            "timestamp_utc": utc_datetime(timestamp).isoformat().replace("+00:00", "Z"),
            "equity_pre": pre,
            "equity_post": post,
            "equity_intrahour_high": high,
            "equity_intrahour_low": low,
        })
    final = math.fsum(cash[s] + quantity[s] * bars_by_symbol[s][end_ms].open for s in SYMBOLS)
    days = (end_ms - start_ms) / (24 * HOUR_MS)
    cagr = (final / INITIAL_EQUITY) ** (365.25 / days) - 1 if final > 0 else -1.0
    hours = (end_ms - start_ms) // HOUR_MS
    return {
        "model": model, "side_cost": side_cost,
        "start_utc": utc_datetime(start_ms).isoformat().replace("+00:00", "Z"),
        "end_utc": utc_datetime(end_ms).isoformat().replace("+00:00", "Z"),
        "start_index": start_index, "end_index": end_index,
        "final_equity": final, "return_pct": 100 * (final - INITIAL_EQUITY),
        "cagr_pct": 100 * cagr, "max_drawdown_open_pct": 100 * max_dd_open,
        "max_drawdown_adverse_hourly_pct": 100 * max_dd_adverse,
        "average_exposure_pct_account": 100 if model == "buy_hold" else 0,
        "exposure_pct_asset_hours": 100 if model == "buy_hold" else 0,
        "order_count": order_count, "trade_entries": len(SYMBOLS) if model == "buy_hold" else 0,
        "trade_exits": len(SYMBOLS) if model == "buy_hold" else 0,
        "fees_initial_equity_units": fees, "turnover_initial_equity_units": turnover,
        "annual_returns": period_returns(curve, start_ms, end_ms, "year"),
        "monthly_returns": period_returns(curve, start_ms, end_ms, "month"),
        "curve": curve, "fills": fills,
    }


def render_report(result):
    lines = [
        "# Supertrend horário com filtro ML",
        "",
        f"Execução {result['created_utc']}. Resultado histórico exploratório; `deployable=false`.",
        "",
        "## Eventos e previsões ML",
        "",
        f"O detector encontrou {result['event_count']['bullish_signals']} sinais de alta e "
        f"{result['event_count']['completed_trade_labels']} operações completas para rótulos. "
        f"O primeiro filtro treinado apareceu em {result['event_count']['first_ml_forecast_utc'] or 'nenhuma data'}.",
        "O alvo é o retorno líquido até a próxima transição para baixa. MAE menor é melhor; a tabela compara com zero e média móvel do treino.",
        "",
        "| Janela | custo/lado | previsões | operações aceitas | MAE | MAE zero | MAE média treino | acerto direção | retorno médio realizado aceito |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for period, costs in result["forecast_scores"].items():
        for cost, row in costs.items():
            lines.append(
                f"| {period} | {float(cost):.2%} | {row.get('count', 0)} | {row.get('accepted_count', 0)} | "
                f"{row.get('mae', 0):.5f} | {row.get('mae_zero', 0):.5f} | "
                f"{row.get('mae_training_mean', 0):.5f} | {row.get('net_positive_hit_pct', 0):.1f}% | "
                f"{row.get('accepted_realized_mean_net_pct') if row.get('accepted_realized_mean_net_pct') is not None else 0:.2f}% |"
            )
    lines += [
        "",
        "## Carteiras Spot long/cash",
        "",
        "Drawdown adverso marca a máxima antes da mínima de cada hora. Buy-and-hold e caixa usam a mesma janela e capital inicial.",
        "",
        "| Janela | custo/lado | estratégia | retorno líquido | CAGR | DD aberturas | DD adverso | alocação média | operações |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for period, costs in result["portfolio_results"].items():
        for cost, models in costs.items():
            for model in ("supertrend", "supertrend_ml", "buy_hold", "cash"):
                row = models[model]
                lines.append(
                    f"| {period} | {float(cost):.2%} | {model} | {row['return_pct']:.2f}% | "
                    f"{row['cagr_pct']:.2f}% | {row['max_drawdown_open_pct']:.2f}% | "
                    f"{row['max_drawdown_adverse_hourly_pct']:.2f}% | "
                    f"{row['average_exposure_pct_account']:.2f}% | {row['trade_entries']} |"
                )
    lines += [
        "",
        "## Decisão",
        "",
        f"{result['decision']}",
        "",
        "A simulação usa candles OHLC e custos hipotéticos. Ela não mede spread observado, slippage, latência, execução real, impostos ou impacto. O histórico posterior já foi visto em outros experimentos e não é um holdout global intocado.",
        "",
        "Referências: [fórmula Supertrend do TradingView](https://www.tradingview.com/support/solutions/43000634738-supertrend/); [protocolo congelado](supertrend_ml_protocol_2026-09-27.md).",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main():
    bars_by_symbol, manifest, boundaries, archive_hash = resolve_schedule()
    all_candidates, all_events = make_events(bars_by_symbol, boundaries)

    flip_events = []
    candidate_map = {(row["symbol"], row["signal_close_ms"]): row for row in all_candidates}
    for symbol in SYMBOLS:
        bars = sorted((bar for bar in bars_by_symbol[symbol].values()
                       if bar.open_ms <= boundaries[-1]), key=lambda bar: bar.open_ms)
        states = build_supertrend(bars)
        first_ms, terminal_ms = boundaries[0], boundaries[-1]
        for index in range(1, len(bars) - 1):
            if bars[index].open_ms < first_ms or bars[index].open_ms >= terminal_ms:
                continue
            previous, current = states[index - 1], states[index]
            if previous.direction is None or current.direction is None or previous.segment != current.segment:
                continue
            if previous.direction < 0 and current.direction > 0:
                kind = "BUY_SIGNAL"
            elif previous.direction > 0 and current.direction < 0:
                kind = "SELL_SIGNAL"
            else:
                continue
            signal_close_ms = bars[index].open_ms + HOUR_MS
            event_id = f"{symbol}:{signal_close_ms}"
            if kind == "BUY_SIGNAL":
                # Only bullish flips with valid causal features can receive an ML forecast.
                features = event_features(bars, states, index)
                if features is not None and (symbol, signal_close_ms) in candidate_map:
                    event = candidate_map[(symbol, signal_close_ms)]
                else:
                    event = {
                        "symbol": symbol, "signal_close_ms": signal_close_ms,
                        "entry_execution_ms": bars[index + 1].open_ms,
                        "entry_price": bars[index + 1].open,
                        "features": features,
                        "event_id": event_id,
                    }
            else:
                event = {"symbol": symbol, "signal_close_ms": signal_close_ms,
                         "event_id": f"{symbol}:{signal_close_ms}:SELL"}
            flip_events.append((symbol, bars[index + 1].open_ms, {
                **event,
                "kind": kind,
                "signal_index": index,
                "signal_bar_open_ms": bars[index].open_ms,
                "execution_ms": bars[index + 1].open_ms,
                "execution_price": bars[index + 1].open,
            }))
    flip_events.sort(key=lambda row: (row[1], row[0]))

    forecasts_by_cost = {}
    for cost in SIDE_COSTS:
        forecasts_by_cost[f"{cost:.4f}"] = forecast_trade_returns(all_candidates, all_events, cost)
    flat_forecasts = [row for rows in forecasts_by_cost.values() for row in rows]
    terminal_index = len(boundaries) - 1
    holdout_index = period_index(boundaries, FINAL_HOLDOUT)
    windows = {
        "walk_forward": (0, terminal_index),
        "holdout_2025_plus": (holdout_index, terminal_index),
    }
    forecast_scores = {}
    for period, (start_index, end_index) in windows.items():
        start_ms, end_ms = boundaries[start_index], boundaries[end_index]
        forecast_scores[period] = {
            cost: regression_scores(rows, start_ms, end_ms)
            for cost, rows in forecasts_by_cost.items()
        }

    portfolio_results = {}
    curve_rows, fill_rows = [], []
    for period, (start_index, end_index) in windows.items():
        by_cost = {}
        for cost in SIDE_COSTS:
            cost_key = f"{cost:.4f}"
            models = {}
            rows = forecasts_by_cost[cost_key]
            for model in ("supertrend", "supertrend_ml"):
                replay_result = replay(
                    bars_by_symbol, boundaries, flip_events, rows,
                    model=model, side_cost=cost,
                    start_index=start_index, end_index=end_index,
                )
                models[model] = {key: value for key, value in replay_result.items()
                                 if key not in {"curve", "fills"}}
                curve_rows.extend({"period": period, **row} for row in replay_result["curve"])
                fill_rows.extend({"period": period, **row} for row in replay_result["fills"])
            for model in ("buy_hold", "cash"):
                replay_result = replay_benchmark(
                    bars_by_symbol, boundaries, model=model, side_cost=cost,
                    start_index=start_index, end_index=end_index,
                )
                models[model] = {key: value for key, value in replay_result.items()
                                 if key not in {"curve", "fills"}}
                curve_rows.extend({"period": period, **row} for row in replay_result["curve"])
                fill_rows.extend({"period": period, **row} for row in replay_result["fills"])
            by_cost[cost_key] = models
        portfolio_results[period] = by_cost

    forecast_rows = []
    for row in flat_forecasts:
        forecast_rows.append({
            **row,
            "signal_timestamp_utc": utc_datetime(row["signal_timestamp_ms"]).isoformat().replace("+00:00", "Z"),
            "entry_execution_utc": utc_datetime(row["entry_execution_ms"]).isoformat().replace("+00:00", "Z"),
            "exit_execution_utc": utc_datetime(row["exit_execution_ms"]).isoformat().replace("+00:00", "Z")
            if row["exit_execution_ms"] is not None else None,
        })
    write_csv(FORECASTS_PATH, forecast_rows, [
        "event_id", "symbol", "signal_timestamp_ms", "signal_timestamp_utc", "entry_execution_ms",
        "entry_execution_utc", "exit_execution_ms", "exit_execution_utc", "side_cost",
        "predicted_net_return", "actual_net_return", "training_mean_net_return", "training_count",
        "training_last_exit_ms", "entry_accepted",
    ])
    write_csv(CURVES_PATH, curve_rows, [
        "period", "model", "side_cost", "timestamp_ms", "timestamp_utc", "equity_pre", "equity_post",
        "equity_intrahour_high", "equity_intrahour_low",
    ])
    write_csv(FILLS_PATH, fill_rows, [
        "period", "model", "side_cost", "timestamp_utc", "symbol", "side", "price", "quantity",
        "notional", "fee", "predicted_net_return",
    ])

    candidate_metrics = [portfolio_results[period][f"{cost:.4f}"]["supertrend_ml"]
                         for period in windows for cost in SIDE_COSTS]
    historical_gate = all(row["return_pct"] > 0 and row["max_drawdown_adverse_hourly_pct"] <= 10
                          for row in candidate_metrics)
    decision = (
        "O Supertrend com filtro ML passou retorno líquido positivo e drawdown adverso máximo de 10% "
        "em todos os períodos e custos; continua necessário confirmá-lo prospectivamente em paper."
        if historical_gate else
        "O Supertrend com filtro ML não passou retorno líquido positivo e drawdown adverso máximo de 10% "
        "em todos os períodos e custos. Não retunar esta amostra."
    )
    valid_buys = [event for _, _, event in flip_events if event["kind"] == "BUY_SIGNAL"
                  and event.get("features") is not None]
    first_forecast = min((row["signal_timestamp_ms"] for row in flat_forecasts), default=None)
    result = {
        "created_utc": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "goal_achieved": False,
        "historical_gate_passed": historical_gate,
        "deployable": False,
        "decision": decision,
        "schedule": {
            "start_utc": utc_datetime(boundaries[0]).isoformat().replace("+00:00", "Z"),
            "holdout_start_utc": utc_datetime(boundaries[holdout_index]).isoformat().replace("+00:00", "Z"),
            "terminal_utc": utc_datetime(boundaries[-1]).isoformat().replace("+00:00", "Z"),
            "last_entry_utc": utc_datetime(boundaries[-2]).isoformat().replace("+00:00", "Z"),
            "archive_manifest_sha256": archive_hash,
            "archive_manifest_entries": len(manifest),
            "first_by_model": {"supertrend": utc_datetime(boundaries[0]).isoformat().replace("+00:00", "Z"),
                               "supertrend_ml": utc_datetime(first_forecast).isoformat().replace("+00:00", "Z")
                               if first_forecast is not None else None},
        },
        "universe": list(SYMBOLS),
        "indicator": {"name": "Supertrend", "atr_length": ATR_LENGTH, "atr_multiplier": ATR_MULTIPLIER,
                      "atr": "Wilder", "timeframe": "1h", "direction": "long_cash"},
        "model": {"estimator": "HistGradientBoostingRegressor", "config": HGB_CONFIG,
                  "features": list(FEATURE_NAMES), "minimum_completed_training_trades": MIN_TRAIN_TRADES,
                  "entry_rule": "predicted net trade return > 0", "hyperparameter_search": False},
        "event_count": {
            "bullish_signals": sum(event["kind"] == "BUY_SIGNAL" for _, _, event in flip_events),
            "bearish_signals": sum(event["kind"] == "SELL_SIGNAL" for _, _, event in flip_events),
            "bullish_signals_with_features": len(valid_buys),
            "completed_trade_labels": len(all_events),
            "first_ml_forecast_utc": utc_datetime(first_forecast).isoformat().replace("+00:00", "Z")
            if first_forecast is not None else None,
            "forecast_count_by_side_cost": {cost: len(rows) for cost, rows in forecasts_by_cost.items()},
        },
        "forecast_scores": forecast_scores,
        "portfolio_results": portfolio_results,
        "side_costs": list(SIDE_COSTS),
        "source_hashes": {
            "protocol": sha256(PROTOCOL_PATH.read_bytes()),
            "sources": sha256(SOURCES_PATH.read_bytes()),
            "script": sha256(SCRIPT_PATH.read_bytes()),
        },
        "runtime": {"python": platform.python_version(), "numpy": np.__version__,
                    "scikit_learn": sklearn.__version__},
        "orders_sent": 0,
        "jev_calls": 0,
    }
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    render_report(result)
    print(f"Supertrend ML research {JSON_PATH}")
    print(f"gate passed: {historical_gate}; goal achieved: false")


if __name__ == "__main__":
    main()
