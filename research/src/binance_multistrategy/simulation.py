"""Deterministic execution assumptions, shared by labels and portfolio replay.

Signal on candle close -> next candle open. Intrabar uncertainty: opening gaps
first, then old stop before target. Trailing ratchets AFTER the completed bar
and takes effect in the next bar. It is not an intrabar Binance native trail.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
from .config import ResearchConfig


@dataclass
class TradeOutcome:
    entry_index: int
    exit_index: int
    entry_price: float
    exit_price: float
    initial_stop: float
    final_stop: float
    target: float
    net_return: float
    net_r: float
    funding_per_unit: float
    fee_per_unit: float
    exit_reason: str
    path_returns: np.ndarray | None = None


class MarketArrays:
    def __init__(self, bars: pd.DataFrame):
        self.bars = bars.reset_index(drop=True)
        self.time = self.bars.open_time
        self.values = {c: self.bars[c].to_numpy(dtype=float) for c in [
            "open", "high", "low", "close", "mark_open", "mark_high", "mark_low", "mark_close", "funding_rate"]}

    def __len__(self) -> int:
        return len(self.bars)


def exit_trigger(side: int, opening: float, high: float, low: float,
                 stop: float, target: float) -> tuple[float | None, str | None]:
    if side == 1:
        if opening <= stop:
            return opening, "stop_gap"
        if opening >= target:
            return target, "target_gap"
        if low <= stop:
            return stop, "stop"
        if high >= target:
            return target, "target"
    elif side == -1:
        if opening >= stop:
            return opening, "stop_gap"
        if opening <= target:
            return target, "target_gap"
        if high >= stop:
            return stop, "stop"
        if low <= target:
            return target, "target"
    else:
        raise ValueError("side must be +1 or -1")
    return None, None


def ratchet_stop(side: int, entry: float, stop: float, best: float, distance: float,
                 activation_r: float, trail_distance_r: float) -> float:
    if side * (best - entry) < activation_r * distance:
        return stop
    candidate = best - side * trail_distance_r * distance
    return max(stop, candidate) if side == 1 else min(stop, candidate)


def simulate_trade(arrays: MarketArrays, row: dict | pd.Series, config: ResearchConfig,
                   *, stress: bool = False, trace: bool = False) -> TradeOutcome | None:
    i = int(row["signal_index"]) + 1
    hold = int(row["max_hold_minutes"])
    last = i + hold - 1
    if i < 0 or last >= len(arrays):
        return None  # Censored; NOT a loss/win. Exclude a fixed horizon from evaluation end.
    side = int(row["side"])
    if side not in {-1, 1} or (config.market == "spot" and side == -1):
        raise ValueError("Spot is long-only; side must be +/-1")
    factor = config.stress_multiplier if stress else 1
    fee = config.fee_bps * factor / 10_000
    slip = config.slippage_bps * factor / 10_000
    a = arrays.values
    entry = a["open"][i] * (1 + side * slip)
    distance = float(row["atr"]) * float(row["stop_atr"])
    if not np.isfinite(distance) or distance <= 0:
        raise ValueError("Stop distance must be positive and finite")
    if not config.min_stop_fraction <= distance / entry <= config.max_stop_fraction:
        return None  # Rejected at actual entry price, not by outcome.
    stop = initial_stop = entry - side * distance
    target = entry + side * distance * float(row["target_r"])
    best, funding = entry, 0.0
    path = [] if trace else None
    for k in range(i, last + 1):
        exit_raw, reason = exit_trigger(side, a["open"][k], a["high"][k], a["low"][k], stop, target)
        if exit_raw is None and k == last:
            exit_raw, reason = a["close"][k], "time_stop"
        # Conservative funding timestamp/within-minute bounds. Pay on ambiguous
        # entry/exit settlement minutes; receive only if unambiguously held.
        rate_signed = side * a["funding_rate"][k]
        if rate_signed > 0:
            funding += rate_signed * a["mark_high"][k]
        elif rate_signed < 0 and k > i and exit_raw is None:
            funding += rate_signed * a["mark_low"][k]
        if exit_raw is not None:
            exit_fill = exit_raw * (1 - side * slip)
            fees = fee * (entry + exit_fill)
            pnl_per_unit = side * (exit_fill - entry) - fees - funding
            net = pnl_per_unit / entry
            if trace:
                path.append(net)
            return TradeOutcome(i, k, entry, exit_fill, initial_stop, stop, target,
                                net, pnl_per_unit / distance, funding, fees, str(reason),
                                np.asarray(path, dtype=float) if trace else None)
        if trace:
            mark_exit = a["mark_close"][k] * (1 - side * slip)
            path.append((side * (mark_exit - entry) - fee * (entry + mark_exit) - funding) / entry)
        best = max(best, a["high"][k]) if side == 1 else min(best, a["low"][k])
        stop = ratchet_stop(side, entry, stop, best, distance,
                            float(row["trail_activation_r"]), float(row["trail_distance_r"]))
    raise AssertionError("Every uncensored trade has a finite time stop")


def label_candidates(candidates: pd.DataFrame, market: dict[str, MarketArrays],
                     config: ResearchConfig) -> pd.DataFrame:
    records = []
    for row in candidates.to_dict("records"):
        arr = market[row["symbol"]]
        result = simulate_trade(arr, row, config)
        if result is None:
            continue
        row.update({"label": int(result.net_return > 0), "net_r": result.net_r,
                    "net_return": result.net_return,
                    "entry_time": arr.time.iloc[result.entry_index],
                    "label_end_time": arr.time.iloc[result.exit_index] + pd.Timedelta(minutes=1),
                    "exit_reason": result.exit_reason})
        records.append(row)
    return pd.DataFrame(records)


def weekly_bootstrap_lower(trades: pd.DataFrame, iterations: int, seed: int) -> tuple[float | None, int]:
    if trades.empty:
        return None, 0
    dates = pd.to_datetime(trades.exit_time, utc=True).dt.tz_localize(None)
    weeks = dates.dt.to_period("W-SUN")
    grouped = trades.assign(week=weeks, win=trades.pnl > 0).groupby("week").agg(wins=("win", "sum"), n=("win", "count"))
    full = pd.period_range(weeks.min(), weeks.max(), freq="W-SUN")
    grouped = grouped.reindex(full, fill_value=0)
    n_active = int((grouped.n > 0).sum())
    if n_active < 2:
        return None, n_active
    rng = np.random.default_rng(seed)
    selection = rng.integers(0, len(grouped), (iterations, len(grouped)))
    win_sum = grouped.wins.to_numpy()[selection].sum(axis=1)
    n_sum = grouped.n.to_numpy()[selection].sum(axis=1)
    rates = win_sum[n_sum > 0] / n_sum[n_sum > 0]
    if rates.size == 0:
        return None, n_active
    return float(np.quantile(rates, .025)), n_active


def metrics(trades: pd.DataFrame, equity: pd.DataFrame, initial: float,
            config: ResearchConfig) -> dict:
    if trades.empty:
        return {"trades": 0, "win_rate": None, "profit_factor": None, "net_profit": 0.0,
                "return": 0.0, "max_drawdown": 0.0, "mean_net_r": None,
                "weekly_bootstrap_lower_95": None, "active_weeks": 0, "average_win": None,
                "average_loss": None, "mean_net_return": None, "payoff_ratio": None,
                "average_win_net_return": None, "average_loss_net_return": None,
                "by_strategy": {}, "by_direction": {}}
    winners, losers = trades.pnl[trades.pnl > 0], trades.pnl[trades.pnl < 0]
    net_returns = trades.net_return.astype(float)
    winning_returns, losing_returns = net_returns[net_returns > 0], net_returns[net_returns < 0]
    profit_factor = float(winners.sum() / -losers.sum()) if len(losers) else None
    average_win_net_return = float(winning_returns.mean()) if len(winning_returns) else None
    average_loss_net_return = float(losing_returns.mean()) if len(losing_returns) else None
    payoff_ratio = (average_win_net_return / abs(average_loss_net_return)
                    if average_win_net_return is not None and average_loss_net_return is not None else None)
    values = np.r_[initial, equity.equity.to_numpy(dtype=float)]
    drawdown = 1 - values / np.maximum.accumulate(values)
    lower, weeks = weekly_bootstrap_lower(trades, config.bootstrap_iterations, config.random_seed)
    def breakdown(column: str) -> dict:
        return {str(key): {"trades": len(group), "win_rate": float((group.pnl > 0).mean()),
                           "net_profit": float(group.pnl.sum())}
                for key, group in trades.groupby(column)}
    return {"trades": len(trades), "win_rate": float((trades.pnl > 0).mean()),
            "profit_factor": profit_factor, "net_profit": float(trades.pnl.sum()),
            "return": float((initial + trades.pnl.sum()) / initial - 1),
            "max_drawdown": float(drawdown.max()), "mean_net_r": float(trades.net_r.mean()),
            "weekly_bootstrap_lower_95": lower, "active_weeks": weeks,
            "average_win": float(winners.mean()) if len(winners) else None,
            "average_loss": float(losers.mean()) if len(losers) else None,
            "mean_net_return": float(net_returns.mean()), "payoff_ratio": payoff_ratio,
            "average_win_net_return": average_win_net_return,
            "average_loss_net_return": average_loss_net_return,
            "by_strategy": breakdown("strategy"), "by_direction": breakdown("side")}


def evaluate(scored: pd.DataFrame, market: dict[str, MarketArrays], config: ResearchConfig,
             start: pd.Timestamp, end: pd.Timestamp, threshold: float,
             *, stress: bool = False, initial_equity: float = 10_000) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    if not np.isfinite(initial_equity) or initial_equity <= 0:
        raise ValueError("initial_equity must be positive")
    # Fixed no-entry buffer, independent of each candidate's future outcome.
    subset = scored.loc[(scored.signal_time >= start) &
                        (scored.signal_time < end - pd.Timedelta(minutes=480)) &
                        (scored.probability >= threshold) & (scored.expected_r >= config.min_expected_r)].copy()
    subset = subset.sort_values(["signal_time", "probability", "expected_r", "symbol", "strategy"],
                                ascending=[True, False, False, True, True])
    cash, next_free = float(initial_equity), start
    records, curve = [], [{"time": start, "equity": cash}]
    for row in subset.to_dict("records"):
        if row["signal_time"] < next_free or cash <= 0:
            continue
        arrays = market[row["symbol"]]
        outcome = simulate_trade(arrays, row, config, stress=stress, trace=True)
        if outcome is None:
            continue
        entry_time = arrays.time.iloc[outcome.entry_index]
        exit_time = arrays.time.iloc[outcome.exit_index] + pd.Timedelta(minutes=1)
        if entry_time < start or exit_time > end:
            continue
        cost_factor = config.stress_multiplier if stress else 1
        friction = 2 * (config.fee_bps + config.slippage_bps) * cost_factor / 10_000
        stop_fraction = abs(outcome.entry_price - outcome.initial_stop) / outcome.entry_price
        exposure = min(config.max_notional_equity, config.risk_fraction / (stop_fraction + friction))
        notional = cash * exposure
        pnl = notional * outcome.net_return
        # Mark-to-market at each completed minute; exits use the execution price.
        for offset, value in enumerate(outcome.path_returns):
            curve.append({"time": arrays.time.iloc[outcome.entry_index + offset] + pd.Timedelta(minutes=1),
                          "equity": cash + notional * float(value)})
        cash += pnl
        next_free = exit_time
        records.append({"symbol": row["symbol"], "market": config.market, "side": row["side"],
                        "strategy": row["strategy"], "regime": row["regime"],
                        "entry_time": entry_time, "exit_time": exit_time,
                        "entry_price": outcome.entry_price, "exit_price": outcome.exit_price,
                        "initial_stop": outcome.initial_stop, "final_stop": outcome.final_stop,
                        "target": outcome.target, "exit_reason": outcome.exit_reason,
                        "probability": row["probability"], "expected_r": row["expected_r"],
                        "net_r": outcome.net_r, "net_return": outcome.net_return,
                        "notional": notional, "pnl": pnl, "equity_after": cash})
    trades, equity = pd.DataFrame(records), pd.DataFrame(curve)
    summary = metrics(trades, equity, initial_equity, config)
    summary.update({"start": str(start), "end_exclusive": str(end), "threshold": threshold,
                    "stress": stress, "one_global_position": True,
                    "drawdown_measure": "minute-close mark-to-market plus executed exits; not tick-level",
                    "last_entry_buffer_minutes": 480})
    return summary, trades, equity


def promotion_gate(base: dict, stress: dict, config: ResearchConfig) -> tuple[bool, list[str]]:
    failures = []
    if base["trades"] < config.min_validation_trades:
        failures.append("insufficient_executed_trades")
    if base["active_weeks"] < config.min_validation_weeks:
        failures.append("insufficient_active_weeks")
    # No-loss samples still need the other sample/confidence gates; PF is undefined.
    if base.get("profit_factor") is None or base["profit_factor"] < config.min_profit_factor:
        failures.append("profit_factor_below_target")
    if (base.get("mean_net_return") is None
            or base["mean_net_return"] <= config.min_net_ev_per_trade):
        failures.append("net_ev_per_trade_below_target")
    if base.get("payoff_ratio") is None or base["payoff_ratio"] < config.min_payoff_ratio:
        failures.append("payoff_ratio_below_target")
    # Rev02 defines stress as positive net result; stress EV/payoff are diagnostics,
    # not additional qualification gates. A zero-trade stress replay has zero PnL.
    if stress["net_profit"] <= 0:
        failures.append("nonpositive_stressed_result")
    return not failures, failures
