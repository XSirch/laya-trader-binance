"""Eight explicit research hypotheses. Fixed defaults, not proven profitable rules."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import numpy as np
import pandas as pd
from .config import ResearchConfig
from .features import MODEL_FEATURES


@dataclass(frozen=True)
class Strategy:
    name: str
    stop_atr: float
    target_r: float
    trail_activation_r: float
    trail_distance_r: float
    max_hold_minutes: int


STRATEGIES = (
    Strategy("ema_pullback", 2.0, 2.0, 1.0, 1.0, 240),
    Strategy("donchian_breakout", 2.5, 2.5, 1.5, 1.25, 480),
    Strategy("squeeze_breakout", 2.0, 2.5, 1.5, 1.0, 360),
    Strategy("range_reversion", 1.5, 1.5, 1.0, .75, 120),
    Strategy("vwap_reclaim", 2.0, 2.0, 1.0, 1.0, 180),
    Strategy("fibonacci_pullback", 2.0, 2.0, 1.0, 1.0, 360),
    Strategy("rsi_recovery", 1.75, 1.75, 1.0, .75, 180),
    Strategy("momentum_continuation", 2.5, 2.5, 1.5, 1.25, 360),
)
STRATEGY_MAP = {s.name: s for s in STRATEGIES}
INPUT_FEATURES = MODEL_FEATURES + ["side", "regime", "stop_fraction", "target_r"] + [f"strategy_{s.name}" for s in STRATEGIES]


def generate_candidates(features: pd.DataFrame, symbol: str, config: ResearchConfig) -> pd.DataFrame:
    f = features
    candidates = []
    valid = f.ready & ~f.extreme_volatility & (f.volume_ratio > .05)
    for side in ([1] if config.market == "spot" else [1, -1]):
        trend = f.regime == side
        with_trend = (f.regime == side) | ((f.regime == 0) & (side * f["60m_distance_ema200"] > 0))
        # Symmetric long/short definitions; Spot never produces a short candidate.
        cross_ema = (side * (f.close - f.ema21) > 0) & (side * (f.close.shift() - f.ema21.shift()) <= 0)
        cross_vwap = (side * f.vwap_distance > 0) & (side * f.vwap_distance.shift() <= 0)
        breakout = (f.close > f.don_high) if side == 1 else (f.close < f.don_low)
        bb_break = (f.close > f.bb_up.shift()) if side == 1 else (f.close < f.bb_low.shift())
        rsi_cross = ((f.rsi > 35) & (f.rsi.shift() <= 35)) if side == 1 else ((f.rsi < 65) & (f.rsi.shift() >= 65))
        fib_cols = [f"fib_{'up' if side == 1 else 'down'}_{x}" for x in (.382, .5, .618)]
        near_fib = f[fib_cols].abs().min(axis=1) < .3
        reversal = side * f.ret1 > 0
        conditions = {
            "ema_pullback": trend & cross_ema & (side * (f.rsi - 50) > -10),
            "donchian_breakout": with_trend & breakout & (f.volume_ratio >= 1.3) & (f.adx >= 20),
            "squeeze_breakout": with_trend & (f["squeeze"].shift().rolling(5).max() > 0) & bb_break & (f.volume_ratio >= 1.2),
            "range_reversion": (f.regime == 0) & (f["15m_adx"] < 20) & (side * f.bb_z < -1.8) & reversal & (side * (f.rsi - 50) < -10),
            "vwap_reclaim": trend & cross_vwap & (f.volume_ratio >= 1),
            "fibonacci_pullback": trend & near_fib & reversal & (side * f.distance_ema21 < .5),
            "rsi_recovery": with_trend & rsi_cross & reversal,
            "momentum_continuation": trend & (side * f.ret5 > f.atr_pct * 1.5) & (side * f.macd_hist > 0) & (f.volume_ratio >= 1.5) & (side * (f.rsi - 50) < 25),
        }
        for strategy in STRATEGIES:
            indices = np.flatnonzero((valid & conditions[strategy.name]).fillna(False).to_numpy())
            # No need to emit the same persistent setup every minute.
            last_index = -10**12
            for i in indices:
                if i - last_index < config.candidate_cooldown_minutes:
                    continue
                stop_fraction = float(strategy.stop_atr * f.at[i, "atr"] / f.at[i, "close"])
                if not config.min_stop_fraction <= stop_fraction <= config.max_stop_fraction:
                    continue
                row = {name: float(f.at[i, name]) for name in MODEL_FEATURES}
                row.update({"symbol": symbol, "market": config.market, "side": side,
                            "strategy": strategy.name, "regime": int(f.at[i, "regime"]),
                            "signal_index": int(f.at[i, "bar_index"]),
                            "signal_time": f.at[i, "decision_time"],
                            "atr": float(f.at[i, "atr"]), "stop_fraction": stop_fraction,
                            **{k: v for k, v in asdict(strategy).items() if k != "name"}})
                for other in STRATEGIES:
                    row[f"strategy_{other.name}"] = float(other.name == strategy.name)
                candidates.append(row)
                last_index = int(i)
    if not candidates:
        return pd.DataFrame(columns=list(dict.fromkeys(INPUT_FEATURES + ["symbol", "market", "strategy", "signal_index", "signal_time", "atr", "stop_atr", "trail_activation_r", "trail_distance_r", "max_hold_minutes"])))
    return pd.DataFrame(candidates).sort_values(["signal_time", "strategy", "side"]).reset_index(drop=True)
