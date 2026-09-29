"""Complete Cycle 02 P0 funnel, paired-cost, and portfolio diagnostics.

This script only reads verified local candles and frozen model/evaluation artifacts.
It does not train, tune, contact external APIs, or submit orders.
"""
from __future__ import annotations

import csv
import gc
import hashlib
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str((ROOT / "research/src").resolve()))

import numpy as np
import pandas as pd

from binance_multistrategy.config import ResearchConfig
from binance_multistrategy.data import load_dataset
from binance_multistrategy.features import build_features
from binance_multistrategy.learning import TrainedGate, code_fingerprint
from binance_multistrategy.simulation import MarketArrays, simulate_trade
from binance_multistrategy.strategies import STRATEGIES, generate_candidates


RESULTS = ROOT / "research/results"
AUDIT = RESULTS / "accounting_audit_2026-09-28"
OUT = RESULTS / "p0_completion_2026-09-28"
OUT.mkdir(parents=True, exist_ok=True)
VARIANTS = (("spot_cuda_exploratory", "spot"),
            ("usdm_cuda_lowercut", "usd_m"),
            ("usdm_cpu_lowercut", "usd_m"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"Refusing to write empty diagnostic: {path}")
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8", lineterminator="\n")


def safe_regime(value: object) -> str:
    return "unknown" if pd.isna(value) else str(int(value))


def conditions_for_side(features: pd.DataFrame, side: int) -> dict[str, pd.Series]:
    f = features
    trend = f.regime == side
    with_trend = (f.regime == side) | ((f.regime == 0) & (side * f["60m_distance_ema200"] > 0))
    cross_ema = ((side * (f.close - f.ema21) > 0)
                 & (side * (f.close.shift() - f.ema21.shift()) <= 0))
    cross_vwap = ((side * f.vwap_distance > 0)
                  & (side * f.vwap_distance.shift() <= 0))
    breakout = (f.close > f.don_high) if side == 1 else (f.close < f.don_low)
    bb_break = (f.close > f.bb_up.shift()) if side == 1 else (f.close < f.bb_low.shift())
    rsi_cross = (((f.rsi > 35) & (f.rsi.shift() <= 35)) if side == 1
                 else ((f.rsi < 65) & (f.rsi.shift() >= 65)))
    fib_cols = [f"fib_{'up' if side == 1 else 'down'}_{x}" for x in (.382, .5, .618)]
    near_fib = f[fib_cols].abs().min(axis=1) < .3
    reversal = side * f.ret1 > 0
    return {
        "ema_pullback": trend & cross_ema & (side * (f.rsi - 50) > -10),
        "donchian_breakout": with_trend & breakout & (f.volume_ratio >= 1.3) & (f.adx >= 20),
        "squeeze_breakout": (with_trend & (f["squeeze"].shift().rolling(5).max() > 0)
                             & bb_break & (f.volume_ratio >= 1.2)),
        "range_reversion": ((f.regime == 0) & (f["15m_adx"] < 20)
                            & (side * f.bb_z < -1.8) & reversal
                            & (side * (f.rsi - 50) < -10)),
        "vwap_reclaim": trend & cross_vwap & (f.volume_ratio >= 1),
        "fibonacci_pullback": trend & near_fib & reversal & (side * f.distance_ema21 < .5),
        "rsi_recovery": with_trend & rsi_cross & reversal,
        "momentum_continuation": (trend & (side * f.ret5 > f.atr_pct * 1.5)
                                  & (side * f.macd_hist > 0) & (f.volume_ratio >= 1.5)
                                  & (side * (f.rsi - 50) < 25)),
    }


def pre_candidate_funnel(features: pd.DataFrame, generated: pd.DataFrame,
                         symbol: str, config: ResearchConfig,
                         start: pd.Timestamp, end: pd.Timestamp) -> list[dict]:
    """Count exclusive first rejection from feature eligibility through emission."""
    f = features
    times = pd.to_datetime(f.decision_time, utc=True)
    in_window = (times >= start) & (times < end)
    ready = f.ready.fillna(False).to_numpy(dtype=bool)
    extreme = f.extreme_volatility.fillna(False).to_numpy(dtype=bool)
    volume_ratio = f.volume_ratio.to_numpy(dtype=float)
    valid = ready & ~extreme & (volume_ratio > .05)
    regimes = f.regime.to_numpy()
    indices = f.bar_index.to_numpy(dtype=np.int64)
    atr = f.atr.to_numpy(dtype=float)
    close = f.close.to_numpy(dtype=float)
    emitted_expected = set()
    if not generated.empty:
        emitted_expected = {(int(r.side), str(r.strategy), int(r.signal_index))
                            for r in generated.itertuples(index=False)}
    result = []
    sides = (1,) if config.market == "spot" else (1, -1)

    for side in sides:
        side_conditions = conditions_for_side(f, side)
        for strategy in STRATEGIES:
            condition = side_conditions[strategy.name].fillna(False).to_numpy(dtype=bool)
            # Mirror the package generator's cooldown state across the full history.
            status = np.full(len(f), "setup_not_triggered", dtype=object)
            status[~ready] = "feature_not_ready"
            status[ready & extreme] = "extreme_volatility"
            status[ready & ~extreme & ~(volume_ratio > .05)] = "volume_ratio_below_or_unavailable"
            setup_mask = valid & condition
            status[valid & ~condition] = "setup_condition_not_met"
            last_index = -10**12
            expected_for_pair = set()
            for i in np.flatnonzero(setup_mask):
                if int(i) - last_index < config.candidate_cooldown_minutes:
                    status[i] = "candidate_cooldown"
                    continue
                stop_fraction = float(strategy.stop_atr * atr[i] / close[i])
                if not config.min_stop_fraction <= stop_fraction <= config.max_stop_fraction:
                    status[i] = "stop_fraction_out_of_bounds"
                    continue
                status[i] = "candidate_emitted"
                last_index = int(i)
                expected_for_pair.add((side, strategy.name, int(indices[i])))

            actual_for_pair = {key for key in emitted_expected
                               if key[0] == side and key[1] == strategy.name}
            if expected_for_pair != actual_for_pair:
                missing = len(expected_for_pair - actual_for_pair)
                extra = len(actual_for_pair - expected_for_pair)
                raise AssertionError(f"candidate mirror mismatch {symbol}/{strategy.name}/{side}: missing={missing}, extra={extra}")

            frame = pd.DataFrame({"regime": [safe_regime(x) for x in regimes[in_window.to_numpy()]],
                                  "terminal_stage": status[in_window.to_numpy()]})
            counts = frame.groupby(["regime", "terminal_stage"], dropna=False).size()
            for (regime, stage), count in counts.items():
                result.append({"symbol": symbol, "strategy": strategy.name, "side": side,
                               "regime": regime, "terminal_stage": stage,
                               "opportunity_count": int(count)})
    return result


def candidate_funnel(scored: pd.DataFrame, arrays: dict[str, MarketArrays],
                     model: TrainedGate, saved: list[dict], start: pd.Timestamp,
                     end: pd.Timestamp, threshold: float, cost: str,
                     variant: str, fold: str) -> list[dict]:
    frame = scored.loc[(scored.signal_time >= start) & (scored.signal_time < end)].copy().reset_index(drop=True)
    if frame.empty:
        return []
    frame["terminal_stage"] = ""
    buffer = frame.signal_time >= end - pd.Timedelta(minutes=480)
    frame.loc[buffer, "terminal_stage"] = "last_480m_entry_buffer"
    remaining = frame.terminal_stage.eq("")
    low_probability = remaining & (frame.probability < threshold)
    frame.loc[low_probability, "terminal_stage"] = "below_model_probability"
    remaining = frame.terminal_stage.eq("")
    low_ev = remaining & (frame.expected_r < model.config.min_expected_r)
    frame.loc[low_ev, "terminal_stage"] = "below_expected_r"
    candidates = frame.loc[frame.terminal_stage.eq("")].sort_values(
        ["signal_time", "probability", "expected_r", "symbol", "strategy"],
        ascending=[True, False, False, True, True])
    saved_keys = {(row["symbol"], int(row["side"]), row["strategy"],
                   pd.Timestamp(row["entry_time"])) for row in saved}
    replayed_keys = set()
    next_free = start
    for ix, series in candidates.iterrows():
        row = series.to_dict()
        signal_time = pd.Timestamp(row["signal_time"])
        if signal_time < next_free:
            frame.loc[ix, "terminal_stage"] = "blocked_by_open_position"
            continue
        outcome = simulate_trade(arrays[row["symbol"]], row, model.config,
                                 stress=(cost == "stress"))
        if outcome is None:
            frame.loc[ix, "terminal_stage"] = "entry_simulation_rejected"
            continue
        bars = arrays[row["symbol"]]
        entry_time = pd.Timestamp(bars.time.iloc[outcome.entry_index])
        exit_time = pd.Timestamp(bars.time.iloc[outcome.exit_index]) + pd.Timedelta(minutes=1)
        if entry_time < start or exit_time > end:
            frame.loc[ix, "terminal_stage"] = "outside_execution_bounds"
            continue
        key = (row["symbol"], int(row["side"]), row["strategy"], entry_time)
        if key not in saved_keys:
            raise AssertionError(f"Replay candidate missing from frozen ledger: {variant}/{fold}/{cost}/{key}")
        replayed_keys.add(key)
        frame.loc[ix, "terminal_stage"] = "executed_saved_replay"
        next_free = exit_time
    if replayed_keys != saved_keys:
        raise AssertionError(f"Frozen trade set mismatch {variant}/{fold}/{cost}: missing={len(saved_keys-replayed_keys)}, extra={len(replayed_keys-saved_keys)}")
    if frame.terminal_stage.eq("").any():
        raise AssertionError("Unclassified candidate remains in the post-candidate funnel")
    grouped = (frame.groupby(["symbol", "strategy", "side", "regime", "terminal_stage"],
                             dropna=False).size().rename("opportunity_count").reset_index())
    return grouped.to_dict("records")


def paired_cost_rows(ledger: pd.DataFrame, model: TrainedGate,
                     variant: str, fold: str) -> list[dict]:
    base = ledger.loc[(ledger.model_variant == variant) & (ledger.fold == fold)
                      & (ledger.cost == "base")]
    rows = []
    for row in base.to_dict("records"):
        side = int(row["side"])
        quantity = float(row["quantity_base_units"])
        entry_reference = float(row["entry_reference_open"])
        exit_reference = float(row["exit_reference_price"])
        funding = float(row["funding_cost_signed_usd"])
        notional = float(row["initial_notional_usd"])
        gross = side * (exit_reference - entry_reference) * quantity
        pair = {}
        for cost, multiplier in (("base", 1.0), ("paired_stress", model.config.stress_multiplier)):
            fee_rate = model.config.fee_bps * multiplier / 10_000
            slip_rate = model.config.slippage_bps * multiplier / 10_000
            entry_fill = entry_reference * (1 + side * slip_rate)
            exit_fill = exit_reference * (1 - side * slip_rate)
            slippage = side * ((entry_fill - entry_reference)
                               + (exit_reference - exit_fill)) * quantity
            fee = fee_rate * (entry_fill + exit_fill) * quantity
            net = gross - slippage - fee - funding
            pair[cost] = {"entry_fill": entry_fill, "exit_fill": exit_fill,
                          "slippage": slippage, "fee": fee, "funding": funding,
                          "net_pnl": net, "net_return": net / notional}
        delta = pair["base"]["net_pnl"] - float(row["net_pnl_usd"])
        if abs(delta) > 1e-7:
            raise AssertionError(f"Paired base accounting mismatch {row['trade_id']}: {delta}")
        rows.append({"trade_id": row["trade_id"], "model_variant": variant,
                     "model_id": row["model_id"], "market": row["market"], "fold": fold,
                     "symbol": row["symbol"], "side": side, "strategy": row["strategy"],
                     "regime": row["regime"], "entry_time": row["entry_time"],
                     "exit_time": row["exit_time"], "exit_reason": row["exit_reason"],
                     "quantity_fixed_base_units": quantity, "initial_notional_fixed_usd": notional,
                     "funding_fixed_from_observed_base_path_usd": funding,
                     "base_net_pnl": pair["base"]["net_pnl"],
                     "paired_stress_net_pnl": pair["paired_stress"]["net_pnl"],
                     "base_net_return": pair["base"]["net_return"],
                     "paired_stress_net_return": pair["paired_stress"]["net_return"],
                     "base_slippage_usd": pair["base"]["slippage"],
                     "paired_stress_slippage_usd": pair["paired_stress"]["slippage"],
                     "base_fee_usd": pair["base"]["fee"],
                     "paired_stress_fee_usd": pair["paired_stress"]["fee"],
                     "gross_reference_pnl_usd": gross,
                     "base_reconciliation_error_usd": delta,
                     "trade_path_fixed": True, "quantity_fixed": True,
                     "funding_observed_base_path_fixed": True})
    return rows


def payoff(returns: np.ndarray) -> float | None:
    wins = returns[returns > 0]
    losses = returns[returns < 0]
    return float(wins.mean() / abs(losses.mean())) if len(wins) and len(losses) else None


def monthly_and_portfolio(equity_file: Path, trades: list[dict],
                          evaluation: dict, variant: str, model_id: str,
                          fold: str, cost: str) -> tuple[dict, list[dict]]:
    start = pd.Timestamp(evaluation["start"])
    end = pd.Timestamp(evaluation["end_exclusive"])
    initial = 10_000.0
    saved = pd.read_csv(equity_file, encoding="utf-8")
    saved["time"] = pd.to_datetime(saved.time, utc=True)
    saved = saved.sort_values("time").drop_duplicates("time", keep="last").set_index("time")
    timeline = pd.date_range(start=start, end=end, freq="min")
    equity = saved.equity.astype(float).reindex(timeline).ffill().fillna(initial).to_numpy()
    diff = np.zeros(len(timeline) + 1, dtype=float)
    for row in trades:
        entry = pd.Timestamp(row["entry_time"])
        exit_time = pd.Timestamp(row["exit_time"])
        notional = float(row["notional"])
        first = int(timeline.searchsorted(entry, side="right"))
        after = int(timeline.searchsorted(exit_time, side="left"))
        if after > first:
            diff[first] += notional
            diff[after] -= notional
    exposure_notional = np.cumsum(diff[:-1])
    exposure = np.divide(exposure_notional, equity, out=np.zeros_like(equity), where=equity > 0)
    idle = equity - exposure_notional
    active_exposure = exposure[exposure_notional > 0]
    peaks = np.maximum.accumulate(np.r_[initial, equity])[1:]
    dd = np.divide(peaks - equity, peaks, out=np.zeros_like(equity), where=peaks > 0)

    series = pd.Series(equity, index=timeline, name="equity")
    prior = initial
    monthly_rows = []
    last_in_window = end - pd.Timedelta(minutes=1)
    first_period = start.tz_localize(None).to_period("M")
    last_period = last_in_window.tz_localize(None).to_period("M")
    for period in pd.period_range(first_period, last_period, freq="M"):
        month_start = pd.Timestamp(period.start_time, tz="UTC")
        month_end = pd.Timestamp(period.end_time.floor("min"), tz="UTC")
        target = min(month_end, end)
        target = max(target, start)
        value = float(series.asof(target))
        monthly_rows.append({"model_variant": variant, "model_id": model_id,
                             "fold": fold, "cost": cost,
                             "calendar_month": str(period),
                             "last_mark_time": target.isoformat(),
                             "equity_at_last_mark_usd": value,
                             "monthly_return": float(value / prior - 1),
                             "partial_calendar_month": bool(start > month_start or target < month_end),
                             "period_start": max(start, month_start).isoformat(),
                             "period_end_observed": target.isoformat(),
                             "test_end_exclusive": end.isoformat()})
        prior = float(value)

    portfolio = {"model_variant": variant, "model_id": model_id, "fold": fold,
                 "cost": cost, "test_start": start.isoformat(),
                 "test_end_exclusive": end.isoformat(), "minutes_marked": len(timeline),
                 "completed_trades": len(trades),
                 "net_profit_usd": float(equity[-1] - initial),
                 "total_return": float(equity[-1] / initial - 1),
                 "max_drawdown_minute_close": float(dd.max(initial=0)),
                 "fraction_minutes_with_position": float((exposure_notional > 0).mean()),
                 "mean_notional_over_equity": float(exposure.mean()),
                 "mean_notional_over_equity_when_position": (float(active_exposure.mean())
                                                             if len(active_exposure) else None),
                 "p95_notional_over_equity_when_position": (float(np.quantile(active_exposure, .95))
                                                            if len(active_exposure) else None),
                 "p95_notional_over_equity": float(np.quantile(exposure, .95)),
                 "max_notional_over_equity": float(exposure.max(initial=0)),
                 "mean_idle_capital_usd": float(idle.mean()),
                 "minimum_idle_capital_usd": float(idle.min(initial=initial))}
    return portfolio, monthly_rows


def path_bound_row(row: dict, arrays: MarketArrays) -> dict:
    times = pd.DatetimeIndex(pd.to_datetime(arrays.time, utc=True))
    entry_time = pd.Timestamp(row["entry_time"])
    exit_time = pd.Timestamp(row["exit_time"]) - pd.Timedelta(minutes=1)
    entry_index = int(times.get_indexer([entry_time])[0])
    exit_index = int(times.get_indexer([exit_time])[0])
    if entry_index < 0 or exit_index < entry_index:
        raise AssertionError(f"Cannot locate trade bars for {row['trade_id']}")
    side = int(row["side"])
    entry = float(row["entry_fill"])
    distance = abs(entry - float(row["initial_stop"]))
    values = arrays.values
    pre = range(entry_index, exit_index)
    pre_excursions = []
    for i in pre:
        pre_excursions.extend((side * (float(values["high"][i]) - entry),
                               side * (float(values["low"][i]) - entry)))
    exit_excursions = (side * (float(values["high"][exit_index]) - entry),
                       side * (float(values["low"][exit_index]) - entry))
    planned_risk = float(row["planned_stop_risk_usd"])
    friction = float(row["adverse_slippage_usd"]) + float(row["commission_usd"])
    total_cost = friction + float(row["funding_cost_signed_usd"])
    return {"trade_id": row["trade_id"], "model_variant": row["model_variant"],
            "model_id": row["model_id"], "market": row["market"], "fold": row["fold"],
            "cost": row["cost"], "symbol": row["symbol"], "strategy": row["strategy"],
            "side": side, "regime": row["regime"], "entry_time": row["entry_time"],
            "exit_time": row["exit_time"], "exit_reason": row["exit_reason"],
            "mfe_r_before_exit_candle": max(pre_excursions) / distance if pre_excursions else None,
            "mae_r_before_exit_candle": min(pre_excursions) / distance if pre_excursions else None,
            "exit_candle_max_excursion_r_ambiguous": max(exit_excursions) / distance,
            "exit_candle_min_excursion_r_ambiguous": min(exit_excursions) / distance,
            "exit_candle_intraminute_order_known": False,
            "execution_friction_usd": friction,
            "funding_cost_signed_usd": float(row["funding_cost_signed_usd"]),
            "all_costs_signed_usd": total_cost,
            "planned_stop_risk_usd": planned_risk,
            "execution_friction_over_planned_risk": friction / planned_risk if planned_risk else None,
            "all_costs_over_planned_risk_signed": total_cost / planned_risk if planned_risk else None}


def main() -> None:
    audit_summary = json.loads((AUDIT / "audit_summary.json").read_text(encoding="utf-8"))
    audit_ledger_path = AUDIT / "trade_cost_decomposition.csv"
    audit_ledger = pd.read_csv(audit_ledger_path, encoding="utf-8")
    artifact_list = []
    for variant, market in VARIANTS:
        for fold in ("fold_01", "fold_02"):
            base = RESULTS / variant / fold
            model_path = base / "training/model.joblib"
            eval_path = base / "test/evaluation.json"
            if model_path.exists() and eval_path.exists():
                artifact_list.append((variant, market, fold, base, model_path, eval_path))
    max_end = max(pd.Timestamp(json.loads(item[5].read_text(encoding="utf-8"))["base"]["end_exclusive"])
                  for item in artifact_list)
    funnel_rows: list[dict] = []
    pair_rows: list[dict] = []
    portfolio_rows: list[dict] = []
    monthly_rows: list[dict] = []
    path_rows: list[dict] = []
    model_records: list[dict] = []

    for market_name in ("spot", "usd_m"):
        items = [item for item in artifact_list if item[1] == market_name]
        if not items:
            continue
        print(f"START_MARKET {market_name}", flush=True)
        dataset = ROOT / "research/data" / ("spot_btc_eth_1m" if market_name == "spot" else "usdm_btc_eth_1m")
        candles, provenance = load_dataset(dataset, market_name)
        candles = candles.loc[candles.open_time < max_end].copy()
        expected_data_hash = next(source["normalized_data_sha256"] for source in audit_summary["data_sources"]
                                  if source["market"] == market_name)
        if provenance.get("data_sha256") != expected_data_hash:
            raise AssertionError(f"Dataset hash changed for {market_name}")
        first_model = TrainedGate.load(items[0][4])
        config: ResearchConfig = first_model.config
        arrays: dict[str, MarketArrays] = {}
        candidate_frames = []
        raw_by_window: dict[tuple[str, str], list[dict]] = {}

        for symbol, bars_group in candles.groupby("symbol", sort=True):
            bars = bars_group.reset_index(drop=True)
            arrays[symbol] = MarketArrays(bars)
            features = build_features(bars)
            generated = generate_candidates(features, symbol, config)
            candidate_frames.append(generated)
            windows = {}
            for variant, _, fold, _, _, eval_path in items:
                report = json.loads(eval_path.read_text(encoding="utf-8"))
                metrics = report["base"]
                tag = (metrics["start"], metrics["end_exclusive"])
                windows[tag] = (pd.Timestamp(metrics["start"]), pd.Timestamp(metrics["end_exclusive"]))
            for (start_text, end_text), (start, end) in windows.items():
                tag = (start_text, end_text)
                raw_by_window.setdefault(tag, []).extend(
                    pre_candidate_funnel(features, generated, symbol, config, start, end))
            print(f"FEATURES_READY {market_name}/{symbol}: bars={len(bars)} candidates={len(generated)} windows={len(windows)}", flush=True)
            del features, generated, bars
            gc.collect()

        candidates = pd.concat(candidate_frames, ignore_index=True)
        if not candidates.empty:
            candidates = candidates.sort_values(["signal_time", "symbol", "strategy", "side"]).reset_index(drop=True)
        del candidate_frames
        gc.collect()

        for variant, _, fold, base, model_path, eval_path in items:
            print(f"MODEL_START {variant}/{fold}", flush=True)
            model = TrainedGate.load(model_path)
            if code_fingerprint() != model.metadata.get("code_sha256"):
                raise AssertionError(f"Model/code fingerprint mismatch: {variant}/{fold}")
            generator_fields = ("market", "candidate_cooldown_minutes",
                                "min_stop_fraction", "max_stop_fraction")
            if any(getattr(model.config, field) != getattr(config, field)
                   for field in generator_fields):
                raise AssertionError(f"Candidate generation config drift: {variant}/{fold}")
            report = json.loads(eval_path.read_text(encoding="utf-8"))
            if (report["base"]["start"], report["base"]["end_exclusive"]) != (
                    report["stress"]["start"], report["stress"]["end_exclusive"]):
                raise AssertionError(f"Base/stress window mismatch: {variant}/{fold}")
            scored = model.score(candidates)
            mid = model.metadata["model_id"]
            model_records.append({"model_variant": variant, "model_id": mid, "market": market_name,
                                 "fold": fold, "model_sha256": sha256(model_path),
                                 "dataset_sha256": provenance["data_sha256"],
                                 "code_fingerprint": code_fingerprint(),
                                 "training_performed": False, "orders_sent": False})
            window_tag = (report["base"]["start"], report["base"]["end_exclusive"])
            raw = raw_by_window[window_tag]
            for cost in ("base", "stress"):
                eval_metrics = report[cost]
                saved_path = base / "test" / ("trades.csv" if cost == "base" else "stress_trades.csv")
                saved = list(csv.DictReader(saved_path.open(encoding="utf-8", newline="")))
                for row in raw:
                    funnel_rows.append({"model_variant": variant, "model_id": mid, "market": market_name,
                                        "fold": fold, "cost": cost, "phase": "pre_candidate",
                                        **row})
                post = candidate_funnel(scored, arrays, model, saved,
                                        pd.Timestamp(eval_metrics["start"]),
                                        pd.Timestamp(eval_metrics["end_exclusive"]),
                                        float(eval_metrics["threshold"]), cost, variant, fold)
                print(f"FUNNEL_OK {variant}/{fold}/{cost}: candidates={len(post)} trades={len(saved)}", flush=True)
                for row in post:
                    funnel_rows.append({"model_variant": variant, "model_id": mid, "market": market_name,
                                        "fold": fold, "cost": cost, "phase": "emitted_candidate",
                                        **row})

                equity_path = base / "test" / ("equity.csv" if cost == "base" else "stress_equity.csv")
                portfolio, monthly = monthly_and_portfolio(equity_path, saved, eval_metrics,
                                                            variant, mid, fold, cost)
                portfolio_rows.append(portfolio)
                monthly_rows.extend(monthly)
            pair_rows.extend(paired_cost_rows(audit_ledger, model, variant, fold))

        for row in audit_ledger.loc[audit_ledger.market == market_name].to_dict("records"):
            path_rows.append(path_bound_row(row, arrays[row["symbol"]]))
        del candidates, arrays, candles
        gc.collect()

    if not pair_rows:
        raise AssertionError("No base trades available for fixed-path paired cost analysis")
    pairs = pd.DataFrame(pair_rows)
    paired_summary = []
    for (variant, mid, market_name, fold), group in pairs.groupby(["model_variant", "model_id", "market", "fold"]):
        base_returns = group.base_net_return.to_numpy(dtype=float)
        stress_returns = group.paired_stress_net_return.to_numpy(dtype=float)
        base_wins = base_returns[base_returns > 0]
        base_losses = base_returns[base_returns < 0]
        stress_wins = stress_returns[stress_returns > 0]
        stress_losses = stress_returns[stress_returns < 0]
        base_pf = (float(base_wins.sum() / abs(base_losses.sum()))
                   if len(base_losses) else None)
        stress_pf = (float(stress_wins.sum() / abs(stress_losses.sum()))
                     if len(stress_losses) else None)
        paired_summary.append({"model_variant": variant, "model_id": mid, "market": market_name,
                               "fold": fold, "fixed_trade_count": len(group),
                               "base_ev_fixed_notional": float(base_returns.mean()),
                               "paired_stress_ev_fixed_notional": float(stress_returns.mean()),
                               "base_payoff": payoff(base_returns), "paired_stress_payoff": payoff(stress_returns),
                               "base_profit_factor": base_pf, "paired_stress_profit_factor": stress_pf,
                               "base_sum_pnl_usd": float(group.base_net_pnl.sum()),
                               "paired_stress_sum_pnl_usd": float(group.paired_stress_net_pnl.sum()),
                               "all_base_rows_reconcile": bool(group.base_reconciliation_error_usd.abs().max() <= 1e-7),
                               "fixed_quantity_and_exit_path": True,
                               "funding_uses_observed_base_path": True})

    write_csv(OUT / "funnel_detail.csv", funnel_rows)
    write_csv(OUT / "paired_cost_ledger.csv", pair_rows)
    write_csv(OUT / "paired_cost_summary.csv", paired_summary)
    write_csv(OUT / "portfolio_diagnostics.csv", portfolio_rows)
    write_csv(OUT / "monthly_equity_returns.csv", monthly_rows)
    write_csv(OUT / "path_bound_diagnostics.csv", path_rows)
    summary = {"status": "p0_diagnostics_completed_with_intraminute_ohlc_ambiguity",
               "created_utc": pd.Timestamp.now(tz="UTC").isoformat(),
               "scope": "frozen artifact diagnostics only; no training, tuning, network calls, or real orders",
               "models": model_records, "funnel_rows": len(funnel_rows),
               "paired_trade_rows": len(pair_rows), "portfolio_rows": len(portfolio_rows),
               "monthly_rows": len(monthly_rows), "path_rows": len(path_rows),
               "inputs": {"accounting_audit_summary_sha256": sha256(AUDIT / "audit_summary.json"),
                          "accounting_audit_ledger_sha256": sha256(audit_ledger_path)},
               "outputs": {path.name: sha256(path) for path in OUT.glob("*.csv")},
               "limitations": [
                   "Paired stress holds the base-path trade, quantity, exit time, and observed funding fixed; it isolates fees and slippage and is not the full stress replay.",
                   "The exact first-reject funnel mirrors the current candidate generator and aborts if generated candidate keys diverge.",
                   "One global position is inherited from the saved evaluator; spot and USD-M are not combined into a joint portfolio.",
                   "Intraminute ordering inside the exit candle is unknowable from one-minute OHLC; exit-candle excursions are separately flagged as ambiguous.",
                   "Costs are configured assumptions rather than account-specific rates or real fills."]}
    (OUT / "p0_completion_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": summary["status"], "funnel_rows": len(funnel_rows),
                      "paired_trade_rows": len(pair_rows), "portfolio_rows": len(portfolio_rows),
                      "monthly_rows": len(monthly_rows), "path_rows": len(path_rows),
                      "output_dir": str(OUT)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
