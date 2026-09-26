from __future__ import annotations

import numpy as np
import pandas as pd

from laya_trader.config import LabelConfig


def _first_hit(mask: np.ndarray, horizon: int) -> np.ndarray:
    any_hit = mask.any(axis=1)
    return np.where(any_hit, mask.argmax(axis=1), horizon)


def _softmax(values: np.ndarray, temperature: float) -> np.ndarray:
    t = max(float(temperature), 1e-6)
    safe_values = np.where(np.isfinite(values), values, 0.0)
    z = safe_values / t
    z = z - z.max(axis=1, keepdims=True)
    exp = np.exp(z)
    return exp / exp.sum(axis=1, keepdims=True)


def add_triple_barrier_labels(df: pd.DataFrame, cfg: LabelConfig) -> pd.DataFrame:
    """Create causal labels for a close(t) decision with entry at open(t+1).

    Future highs/lows are used only to create labels. They must never be serialized into model state.
    Samples where TP and stop are first touched in the same candle are flagged ambiguous.
    """
    required = {"timestamp", "open", "high", "low", "close", "atr14"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"missing columns for labeling: {sorted(missing)}")

    n = len(df)
    h = int(cfg.horizon_bars)
    if n <= h + 1:
        return df.iloc[0:0].copy()

    high = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)
    open_ = df["open"].to_numpy(float)
    close = df["close"].to_numpy(float)
    atr = df["atr14"].to_numpy(float)

    count = n - h
    high_w = np.lib.stride_tricks.sliding_window_view(high[1:], h)[:count]
    low_w = np.lib.stride_tricks.sliding_window_view(low[1:], h)[:count]
    entry = open_[1 : 1 + count]
    atr0 = atr[:count]
    time_exit = close[h : h + count]

    valid = np.isfinite(entry) & np.isfinite(atr0) & (entry > 0) & (atr0 > 0)
    risk_distance = cfg.stop_loss_atr * atr0
    long_tp = entry + cfg.take_profit_atr * atr0
    long_sl = entry - cfg.stop_loss_atr * atr0
    short_tp = entry - cfg.take_profit_atr * atr0
    short_sl = entry + cfg.stop_loss_atr * atr0

    ltp_idx = _first_hit(high_w >= long_tp[:, None], h)
    lsl_idx = _first_hit(low_w <= long_sl[:, None], h)
    stp_idx = _first_hit(low_w <= short_tp[:, None], h)
    ssl_idx = _first_hit(high_w >= short_sl[:, None], h)

    long_ambiguous = (ltp_idx == lsl_idx) & (ltp_idx < h)
    short_ambiguous = (stp_idx == ssl_idx) & (stp_idx < h)

    rr = cfg.take_profit_atr / cfg.stop_loss_atr
    long_r = np.where(
        ltp_idx < lsl_idx,
        rr,
        np.where(lsl_idx < ltp_idx, -1.0, (time_exit - entry) / risk_distance),
    )
    short_r = np.where(
        stp_idx < ssl_idx,
        rr,
        np.where(ssl_idx < stp_idx, -1.0, (entry - time_exit) / risk_distance),
    )

    # OHLC bars do not reveal which barrier was touched first inside one bar.
    # Keep the row and charge the stop to the affected side when the order is unknown.
    long_r = np.where(long_ambiguous, -1.0, long_r)
    short_r = np.where(short_ambiguous, -1.0, short_r)

    round_trip_bps = 2.0 * (cfg.fee_bps_per_side + cfg.slippage_bps_per_side)
    round_trip_return = round_trip_bps * 1e-4
    cost_r = round_trip_return / (risk_distance / entry)
    long_r = long_r - cost_r
    short_r = short_r - cost_r

    adjusted = np.stack(
        [long_r - cfg.min_edge_r, short_r - cfg.min_edge_r, np.zeros_like(long_r)], axis=1
    )
    action_p = _softmax(adjusted, cfg.target_temperature)

    best_r = np.maximum(long_r, short_r)
    z = (best_r - cfg.min_edge_r) / max(cfg.tradeable_temperature, 1e-6)
    p_trade = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))

    # Continuous edge quality mapped onto five ordinal levels; use a Gaussian soft target.
    # -1R -> 0, 0R -> 1, 0.5R -> 2, 1R -> 3, >=2R -> 4.
    anchors = np.array([-1.0, 0.0, 0.5, 1.0, 2.0], dtype=float)
    safe_best_r = np.where(np.isfinite(best_r), best_r, 0.0)
    distance = (safe_best_r[:, None] - anchors[None, :]) / 0.45
    edge_logits = -0.5 * distance**2
    edge_logits = edge_logits - edge_logits.max(axis=1, keepdims=True)
    edge_p = np.exp(edge_logits)
    edge_p = edge_p / edge_p.sum(axis=1, keepdims=True)

    out = df.iloc[:count].copy()
    out["entry_price"] = entry
    out["label_end_ts"] = df["timestamp"].iloc[h : h + count].to_numpy()
    out["long_r"] = long_r
    out["short_r"] = short_r
    out["label_cost_r"] = cost_r
    out["long_ambiguous"] = long_ambiguous
    out["short_ambiguous"] = short_ambiguous
    out["target_long"] = action_p[:, 0]
    out["target_short"] = action_p[:, 1]
    out["target_flat"] = action_p[:, 2]
    out["target_trade_false"] = 1.0 - p_trade
    out["target_trade_true"] = p_trade
    for i in range(5):
        out[f"target_edge_{i}"] = edge_p[:, i]

    out = out.loc[valid].copy()
    if cfg.drop_ambiguous:
        out = out.loc[~(out["long_ambiguous"] | out["short_ambiguous"])].copy()
    return out.reset_index(drop=True)
