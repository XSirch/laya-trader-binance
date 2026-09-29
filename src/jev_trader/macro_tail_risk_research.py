"""Walk-forward quantile risk sizing using point-in-time macro snapshots."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import csv
import hashlib
import json
import math
from pathlib import Path
import platform

import numpy as np
import sklearn
from sklearn.linear_model import QuantileRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .binance_data import HOUR_MS
from .macro_external_alpha_research import (
    FINAL_HOLDOUT,
    INITIAL_EQUITY,
    MIN_TRAINING_WEEKS,
    PRICE_LAGS,
    SIDE_COSTS,
    SYMBOLS,
    WEEK_MS,
    fetch_all_snapshots,
    iso,
    macro_features,
    model_features,
    period_index,
    period_returns,
    price_features,
    portfolio_replay,
    resolve_schedule,
    sha256,
    utc_datetime,
    write_csv,
)

ROOT = Path.cwd()
SOURCE_SCRIPT = ROOT / "src" / "jev_trader" / "macro_external_alpha_research.py"
PROTOCOL_PATH = ROOT / "docs" / "macro_tail_risk_protocol_2026-09-27.md"
REPORT_PATH = ROOT / "docs" / "macro_tail_risk_research_2026-09-27.md"
JSON_PATH = ROOT / "results" / "macro_tail_risk_research.json"
FORECASTS_PATH = ROOT / "results" / "macro_tail_risk_forecasts.csv"
CURVES_PATH = ROOT / "results" / "macro_tail_risk_curves.csv"
FILLS_PATH = ROOT / "results" / "macro_tail_risk_fills.csv"
QUANTILE = 0.10
QUANTILE_ALPHA = 0.01
RISK_BUDGET_PER_SLEEVE = 0.04
RISK_FLOOR = 0.01
UTC = timezone.utc


def build_risk_forecasts(bars_by_symbol, boundaries, snapshots):
    macro_by_week = {}
    freshness = {}
    for index, timestamp in enumerate(boundaries[:-1]):
        macro, provenance = macro_features(snapshots, timestamp)
        macro_by_week[index] = macro
        freshness[index] = provenance

    forecasts = []
    for symbol in SYMBOLS:
        rows = []
        bars = bars_by_symbol[symbol]
        for index in range(13, len(boundaries) - 1):
            start, end = boundaries[index], boundaries[index + 1]
            start_price = bars[start].open
            lows = [bars[timestamp].low for timestamp in range(start, end, HOUR_MS)]
            if len(lows) != WEEK_MS // HOUR_MS:
                raise ValueError("a weekly downside label is missing hourly observations")
            worst_return = min(lows) / start_price - 1.0
            rows.append({
                "index": index,
                "start_ms": start,
                "end_ms": end,
                "price": price_features(bars_by_symbol, boundaries, symbol, index),
                "macro": macro_by_week[index],
                "actual_q10_target": worst_return,
            })

        for row in rows:
            for model in ("price_only", "price_plus_macro"):
                if model == "price_plus_macro" and row["macro"] is None:
                    continue
                training = [
                    sample for sample in rows
                    if sample["index"] <= row["index"] - 2
                    and (model == "price_only" or sample["macro"] is not None)
                ]
                if len(training) < MIN_TRAINING_WEEKS:
                    continue
                feature_names, x_current = model_features(
                    row["price"], row["macro"], model
                )
                x_train = []
                y_train = []
                for sample in training:
                    names, vector = model_features(
                        sample["price"], sample["macro"], model
                    )
                    if names != feature_names:
                        raise ValueError("quantile feature order changed during walk-forward")
                    x_train.append(vector)
                    y_train.append(sample["actual_q10_target"])
                estimator = make_pipeline(
                    StandardScaler(),
                    QuantileRegressor(
                        quantile=QUANTILE,
                        alpha=QUANTILE_ALPHA,
                        solver="highs",
                        fit_intercept=True,
                    ),
                )
                estimator.fit(np.vstack(x_train), np.asarray(y_train, dtype=float))
                prediction = float(estimator.predict(x_current.reshape(1, -1))[0])
                if not math.isfinite(prediction):
                    raise ValueError("quantile model emitted a nonfinite forecast")
                forecasts.append({
                    "index": row["index"],
                    "signal_timestamp_ms": row["start_ms"],
                    "signal_sunday_utc": (utc_datetime(row["start_ms"]).date()
                                          - timedelta(days=1)).isoformat(),
                    "exit_timestamp_ms": row["end_ms"],
                    "symbol": symbol,
                    "model": model,
                    "prediction_q10": prediction,
                    "actual_worst_return": row["actual_q10_target"],
                    "training_q10": float(np.quantile(y_train, QUANTILE)),
                    "training_count": len(training),
                    "training_last_completed_exit_ms": boundaries[row["index"] - 1],
                    "feature_count": len(feature_names),
                })
        print(f"tail quantile forecasts {symbol}: {sum(row['symbol'] == symbol for row in forecasts)}")
    forecasts.sort(key=lambda row: (row["index"], row["symbol"], row["model"]))
    return forecasts, freshness


def pinball_loss(actual, predicted, quantile=QUANTILE):
    error = np.asarray(actual, dtype=float) - np.asarray(predicted, dtype=float)
    return np.maximum(quantile * error, (quantile - 1) * error)


def forecast_scores(forecasts, start_index, end_index):
    selected = [row for row in forecasts if start_index <= row["index"] < end_index]
    common = {
        (row["index"], row["symbol"])
        for row in selected if row["model"] == "price_plus_macro"
    }
    scores = {}
    for model in ("price_only", "price_plus_macro"):
        rows = [row for row in selected if row["model"] == model
                and (row["index"], row["symbol"]) in common]
        if not rows:
            scores[model] = {"count": 0, "unique_signal_weeks": 0}
            continue
        actual = np.asarray([row["actual_worst_return"] for row in rows])
        predicted = np.asarray([row["prediction_q10"] for row in rows])
        training_quantile = np.asarray([row["training_q10"] for row in rows])
        scores[model] = {
            "count": len(rows),
            "unique_signal_weeks": len({row["index"] for row in rows}),
            "pinball": float(np.mean(pinball_loss(actual, predicted))),
            "pinball_zero": float(np.mean(pinball_loss(actual, np.zeros(len(rows))))),
            "pinball_training_q10": float(np.mean(pinball_loss(actual, training_quantile))),
            "coverage_pct": 100 * float(np.mean(actual <= predicted)),
            "mean_actual_worst_return_pct": 100 * float(np.mean(actual)),
            "mean_predicted_q10_pct": 100 * float(np.mean(predicted)),
        }
    if scores["price_only"].get("count") and scores["price_plus_macro"].get("count"):
        base = scores["price_only"]["pinball"]
        candidate = scores["price_plus_macro"]["pinball"]
        scores["macro_pinball_skill_vs_price_only_pct"] = (
            100 * (1 - candidate / base) if base > 0 else None
        )
    return scores


def target_exposure(q10: float) -> float:
    forecast_loss = max(RISK_FLOOR, -q10)
    return min(1.0, RISK_BUDGET_PER_SLEEVE / forecast_loss)


def risk_portfolio_replay(bars_by_symbol, boundaries, forecasts, *, model,
                          side_cost, start_index, end_index):
    start_ms, end_ms = boundaries[start_index], boundaries[end_index]
    forecast_map = {
        (row["index"], row["symbol"]): row
        for row in forecasts if row["model"] == model
    }
    sleeve_start = INITIAL_EQUITY / len(SYMBOLS)
    cash = {symbol: sleeve_start for symbol in SYMBOLS}
    quantity = {symbol: 0.0 for symbol in SYMBOLS}
    fees = turnover = 0.0
    fills = []
    curve = []
    peak_open = peak_adverse = INITIAL_EQUITY
    max_dd_open = max_dd_adverse = 0.0
    asset_peak_open = {symbol: sleeve_start for symbol in SYMBOLS}
    asset_peak_adverse = {symbol: sleeve_start for symbol in SYMBOLS}
    asset_dd_open = {symbol: 0.0 for symbol in SYMBOLS}
    asset_dd_adverse = {symbol: 0.0 for symbol in SYMBOLS}
    exposed_hours = {symbol: 0 for symbol in SYMBOLS}
    exposure_fraction_sum = {symbol: 0.0 for symbol in SYMBOLS}
    total_hours = (end_ms - start_ms) // HOUR_MS
    order_count = 0
    active_asset_weeks = 0
    positive_active_asset_weeks = 0
    rebalanced_asset_weeks = 0

    def portfolio_open(timestamp):
        return math.fsum(cash[symbol] + quantity[symbol] * bars_by_symbol[symbol][timestamp].open
                         for symbol in SYMBOLS)

    for timestamp in range(start_ms, end_ms + HOUR_MS, HOUR_MS):
        if any(timestamp not in bars_by_symbol[symbol] for symbol in SYMBOLS):
            raise ValueError(f"missing hourly mark during risk replay at {timestamp}")
        pre_by_symbol = {
            symbol: cash[symbol] + quantity[symbol] * bars_by_symbol[symbol][timestamp].open
            for symbol in SYMBOLS
        }
        pre = portfolio_open(timestamp)
        if timestamp in boundaries and timestamp < end_ms:
            week_index = boundaries.index(timestamp)
            for symbol in SYMBOLS:
                row = forecast_map.get((week_index, symbol))
                exposure = target_exposure(row["prediction_q10"]) if row else 0.0
                bar = bars_by_symbol[symbol][timestamp]
                if exposure > 0:
                    active_asset_weeks += 1
                    positive_active_asset_weeks += int(
                        row is not None and row["actual_worst_return"] > -0.04
                    )
                current_notional = quantity[symbol] * bar.open
                equity_before = cash[symbol] + current_notional
                target_notional = exposure * equity_before
                difference = target_notional - current_notional
                if abs(difference) <= max(1e-12, equity_before * 1e-10):
                    continue
                rebalanced_asset_weeks += 1
                if difference < 0:
                    traded = min(quantity[symbol] * bar.open, -difference)
                    units = traded / bar.open
                    fee = traded * side_cost
                    quantity[symbol] -= units
                    cash[symbol] += traded - fee
                    side = "SELL"
                else:
                    traded = min(difference, cash[symbol] / (1 + side_cost))
                    if traded <= 0:
                        continue
                    units = traded / bar.open
                    fee = traded * side_cost
                    quantity[symbol] += units
                    cash[symbol] -= traded + fee
                    side = "BUY"
                fees += fee
                turnover += traded
                order_count += 1
                fills.append({
                    "model": model,
                    "side_cost": side_cost,
                    "timestamp_utc": iso(timestamp),
                    "symbol": symbol,
                    "side": side,
                    "price": bar.open,
                    "quantity": units,
                    "notional": traded,
                    "fee": fee,
                    "predicted_q10": row["prediction_q10"] if row else None,
                    "target_exposure_fraction": exposure,
                    "target_exposure_notional": target_notional,
                })

        if timestamp == end_ms:
            for symbol in SYMBOLS:
                if quantity[symbol] <= 0:
                    continue
                bar = bars_by_symbol[symbol][timestamp]
                traded = quantity[symbol] * bar.open
                fee = traded * side_cost
                units = quantity[symbol]
                cash[symbol] += traded - fee
                quantity[symbol] = 0.0
                fees += fee
                turnover += traded
                order_count += 1
                fills.append({
                    "model": model, "side_cost": side_cost,
                    "timestamp_utc": iso(timestamp), "symbol": symbol,
                    "side": "SELL", "price": bar.open, "quantity": units,
                    "notional": traded, "fee": fee, "predicted_q10": None,
                    "target_exposure_fraction": 0.0,
                    "target_exposure_notional": 0.0,
                })

        post = portfolio_open(timestamp)
        high = math.fsum(cash[symbol] + quantity[symbol] * bars_by_symbol[symbol][timestamp].high
                         for symbol in SYMBOLS)
        low = math.fsum(cash[symbol] + quantity[symbol] * bars_by_symbol[symbol][timestamp].low
                        for symbol in SYMBOLS)
        for symbol in SYMBOLS:
            bar = bars_by_symbol[symbol][timestamp]
            post_asset = cash[symbol] + quantity[symbol] * bar.open
            high_asset = cash[symbol] + quantity[symbol] * bar.high
            low_asset = cash[symbol] + quantity[symbol] * bar.low
            asset_peak_open[symbol] = max(asset_peak_open[symbol], pre_by_symbol[symbol], post_asset)
            asset_dd_open[symbol] = max(asset_dd_open[symbol], 1 - post_asset / asset_peak_open[symbol])
            asset_peak_adverse[symbol] = max(
                asset_peak_adverse[symbol], pre_by_symbol[symbol], post_asset, high_asset
            )
            asset_dd_adverse[symbol] = max(
                asset_dd_adverse[symbol], 1 - low_asset / asset_peak_adverse[symbol]
            )
            exposed_hours[symbol] += int(quantity[symbol] > 0)
            sleeve_value = cash[symbol] + quantity[symbol] * bar.open
            if sleeve_value > 0:
                exposure_fraction_sum[symbol] += quantity[symbol] * bar.open / sleeve_value
        peak_open = max(peak_open, pre, post)
        max_dd_open = max(max_dd_open, 1 - post / peak_open)
        peak_adverse = max(peak_adverse, pre, post, high)
        max_dd_adverse = max(max_dd_adverse, 1 - low / peak_adverse)
        curve.append({
            "timestamp_ms": timestamp,
            "timestamp_utc": iso(timestamp),
            "equity_pre": pre,
            "equity_post": post,
            "equity_intrahour_high": high,
            "equity_intrahour_low": low,
        })

    final = portfolio_open(end_ms)
    elapsed_days = (end_ms - start_ms) / (24 * HOUR_MS)
    cagr = (final / INITIAL_EQUITY) ** (365.25 / elapsed_days) - 1 if final > 0 else -1.0
    asset_results = {}
    for symbol in SYMBOLS:
        final_asset = cash[symbol] + quantity[symbol] * bars_by_symbol[symbol][end_ms].open
        asset_cagr = (final_asset / sleeve_start) ** (365.25 / elapsed_days) - 1 if final_asset > 0 else -1.0
        asset_fills = [row for row in fills if row["symbol"] == symbol]
        asset_results[symbol] = {
            "return_pct": 100 * (final_asset / sleeve_start - 1),
            "cagr_pct": 100 * asset_cagr,
            "max_drawdown_open_pct": 100 * asset_dd_open[symbol],
            "max_drawdown_adverse_hourly_pct": 100 * asset_dd_adverse[symbol],
            "exposure_pct_hours": 100 * exposed_hours[symbol] / total_hours,
            "average_exposure_pct_account": 100 * exposure_fraction_sum[symbol] / total_hours,
            "order_count": len(asset_fills),
            "fees_initial_equity_units": math.fsum(row["fee"] for row in asset_fills),
        }
    return {
        "model": model,
        "side_cost": side_cost,
        "start_utc": iso(start_ms),
        "end_utc": iso(end_ms),
        "start_index": start_index,
        "end_index": end_index,
        "final_equity": final,
        "return_pct": 100 * (final - INITIAL_EQUITY),
        "cagr_pct": 100 * cagr,
        "max_drawdown_open_pct": 100 * max_dd_open,
        "max_drawdown_adverse_hourly_pct": 100 * max_dd_adverse,
        "exposure_pct_asset_hours": 100 * math.fsum(exposed_hours.values()) / (total_hours * len(SYMBOLS)),
        "average_exposure_pct_account": 100 * math.fsum(exposure_fraction_sum.values()) / (total_hours * len(SYMBOLS)),
        "active_asset_weeks": active_asset_weeks,
        "positive_active_asset_weeks_under_4pct_loss_pct": (
            100 * positive_active_asset_weeks / active_asset_weeks if active_asset_weeks else None
        ),
        "rebalanced_asset_weeks": rebalanced_asset_weeks,
        "order_count": order_count,
        "fees_initial_equity_units": fees,
        "turnover_initial_equity_units": turnover,
        "asset_results": asset_results,
        "curve": curve,
        "fills": fills,
    }


def summarize_replay(replay):
    start_ms = int(datetime.fromisoformat(replay["start_utc"].replace("Z", "+00:00")).timestamp() * 1000)
    end_ms = int(datetime.fromisoformat(replay["end_utc"].replace("Z", "+00:00")).timestamp() * 1000)
    summary = {key: value for key, value in replay.items() if key not in {"curve", "fills"}}
    summary["annual_returns"] = period_returns(replay["curve"], start_ms, end_ms, "year")
    summary["monthly_returns"] = period_returns(replay["curve"], start_ms, end_ms, "month")
    return summary


def render_report(result):
    lines = [
        "# Sizing semanal com previsão de perda de cauda",
        "",
        f"Execução {result['created_utc']}. O estudo é retrospectivo e não autoriza negociação.",
        "",
        "## Validade da previsão de risco",
        "",
        f"A amostra OOS comum tem {result['forecast_scores']['walk_forward']['price_plus_macro'].get('unique_signal_weeks', 0)} semanas UTC e previsões por ativo. A perda pinball do quantil 10% é melhor quanto menor; cobertura próxima de 10% é desejável, mas não significa lucro.",
        "",
        "| Período | modelo | ativo-semanas | semanas UTC | pinball | pinball zero | pinball quantil treino | cobertura q10 | q10 médio | perda real média |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for period, scores in result["forecast_scores"].items():
        for model in ("price_only", "price_plus_macro"):
            row = scores[model]
            if not row.get("count"):
                lines.append(f"| {period} | {model} | 0 | 0 | — | — | — | — | — | — |")
                continue
            lines.append(
                f"| {period} | {model} | {row['count']} | {row['unique_signal_weeks']} | "
                f"{row['pinball']:.6f} | {row['pinball_zero']:.6f} | "
                f"{row['pinball_training_q10']:.6f} | {row['coverage_pct']:.1f}% | "
                f"{row['mean_predicted_q10_pct']:.2f}% | {row['mean_actual_worst_return_pct']:.2f}% |"
            )
        skill = scores.get("macro_pinball_skill_vs_price_only_pct")
        lines.append(
            f"| {period} | macro pinball skill vs price_only | — | — | {skill:.2f}% | — | — | — | — | — |"
            if skill is not None else
            f"| {period} | macro pinball skill vs price_only | — | — | — | — | — | — | — | — |"
        )
    lines += [
        "",
        "## Sizing e carteira",
        "",
        "A exposição alvo é `min(100%, 4% / max(1%, -q10))` do saldo de cada conta. O replay reequilibra na abertura de segunda-feira; o drawdown adverso considera a máxima e a mínima da hora como se a máxima viesse primeiro.",
        "",
        "| janela | custo/lado | modelo | retorno líquido | CAGR | DD nas aberturas | DD adverso | alocação média | horas com posição | ordens | semanas com perda prevista <4% |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for period, scenarios in result["portfolio_results"].items():
        for cost in SIDE_COSTS:
            for model in ("price_plus_macro", "price_only", "buy_hold", "cash"):
                row = scenarios[f"{cost:.4f}"][model]
                hit = row.get("positive_active_asset_weeks_under_4pct_loss_pct")
                hit_text = "—" if hit is None else f"{hit:.1f}%"
                lines.append(
                    f"| {period} | {cost:.2%} | {model} | {row['return_pct']:.2f}% | "
                    f"{row['cagr_pct']:.2f}% | {row['max_drawdown_open_pct']:.2f}% | "
                    f"{row['max_drawdown_adverse_hourly_pct']:.2f}% | "
                    f"{row.get('average_exposure_pct_account', row['exposure_pct_asset_hours']):.1f}% | "
                    f"{row['exposure_pct_asset_hours']:.1f}% | {row['order_count']} | {hit_text} |"
                )
    lines += ["", "## Resultado por ativo no holdout", "",
              "| custo/lado | modelo | ativo | retorno | CAGR | DD adverso | alocação média | horas com posição | ordens |",
              "|---:|---|---|---:|---:|---:|---:|---:|---:|"]
    for cost in SIDE_COSTS:
        for model in ("price_plus_macro", "price_only"):
            assets = result["portfolio_results"]["holdout_2025_plus"][f"{cost:.4f}"][model]["asset_results"]
            for symbol, row in assets.items():
                lines.append(
                    f"| {cost:.2%} | {model} | {symbol} | {row['return_pct']:.2f}% | "
                    f"{row['cagr_pct']:.2f}% | {row['max_drawdown_adverse_hourly_pct']:.2f}% | "
                    f"{row.get('average_exposure_pct_account', row['exposure_pct_hours']):.1f}% | "
                    f"{row['exposure_pct_hours']:.1f}% | {row['order_count']} |"
                )
    lines += [
        "",
        "## Conclusão",
        "",
        f"Meta retrospectiva de 50% CAGR líquido e limite adverso de drawdown de 10%, nos dois custos e nas duas janelas: **{'atingida' if result['historical_gate_passed'] else 'não atingida'}**. O objetivo de lucratividade consistente continua **não comprovado**; `deployable=false`. {result['decision']}",
        "",
        "O estudo MCQRNN publicado usou 1.500 observações diárias, janela de treino de 1.000 e 500 previsões OOS; esta avaliação tem muito menos semanas e usa outro alvo. Ver [protocolo](macro_tail_risk_protocol_2026-09-27.md) e [fonte primária Springer](https://link.springer.com/article/10.1007/s11135-023-01761-1).",
        "",
        f"Snapshots usados: {result['macro_snapshot_count']}; hash agregado `{result['macro_snapshot_identity_sha256']}`. Binance manifest: `{result['schedule']['archive_manifest_sha256']}`.",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main():
    bars_by_symbol, manifest, boundaries, archive_hash = resolve_schedule()
    snapshots, cache_hits = fetch_all_snapshots(boundaries)
    forecasts, freshness = build_risk_forecasts(bars_by_symbol, boundaries, snapshots)
    first_by_model = {
        model: min((row["index"] for row in forecasts if row["model"] == model), default=None)
        for model in ("price_only", "price_plus_macro")
    }
    if any(index is None for index in first_by_model.values()):
        raise ValueError("risk model walk-forward did not emit both comparison models")
    first_common = max(first_by_model.values())
    terminal_index = len(boundaries) - 1
    holdout_index = period_index(boundaries, FINAL_HOLDOUT)
    windows = {
        "walk_forward": (first_common, terminal_index),
        "development_2024": (first_common, period_index(boundaries, date(2025, 1, 1))),
        "holdout_2025_plus": (holdout_index, terminal_index),
    }
    scores = {
        name: forecast_scores(forecasts, start, end)
        for name, (start, end) in windows.items()
    }

    portfolio_results = {}
    curve_rows, fill_rows = [], []
    for period, start_index in {
        "walk_forward": first_common,
        "holdout_2025_plus": holdout_index,
    }.items():
        by_cost = {}
        for cost in SIDE_COSTS:
            cost_key = f"{cost:.4f}"
            by_model = {}
            for model in ("price_plus_macro", "price_only"):
                replay = risk_portfolio_replay(
                    bars_by_symbol, boundaries, forecasts,
                    model=model, side_cost=cost,
                    start_index=start_index, end_index=terminal_index,
                )
                by_model[model] = summarize_replay(replay)
                curve_rows.extend({
                    "period": period, "model": model, "side_cost": cost, **row
                } for row in replay["curve"])
                fill_rows.extend({"period": period, **row} for row in replay["fills"])
            for model in ("buy_hold", "cash"):
                replay = portfolio_replay(
                    bars_by_symbol, boundaries, forecasts, model=model,
                    side_cost=cost, start_index=start_index,
                    end_index=terminal_index, mode=model,
                )
                by_model[model] = summarize_replay(replay)
                curve_rows.extend({
                    "period": period, "model": model, "side_cost": cost, **row
                } for row in replay["curve"])
                fill_rows.extend({"period": period, **row} for row in replay["fills"])
            by_cost[cost_key] = by_model
        portfolio_results[period] = by_cost

    forecast_rows = []
    for row in forecasts:
        forecast_rows.append({
            **row,
            "signal_timestamp_utc": iso(row["signal_timestamp_ms"]),
            "exit_timestamp_utc": iso(row["exit_timestamp_ms"]),
        })
    write_csv(FORECASTS_PATH, forecast_rows, [
        "index", "signal_timestamp_ms", "signal_timestamp_utc", "signal_sunday_utc",
        "exit_timestamp_ms", "exit_timestamp_utc", "symbol", "model", "prediction_q10",
        "actual_worst_return", "training_q10", "training_count",
        "training_last_completed_exit_ms", "feature_count",
    ])
    write_csv(CURVES_PATH, curve_rows, [
        "period", "model", "side_cost", "timestamp_ms", "timestamp_utc", "equity_pre",
        "equity_post", "equity_intrahour_high", "equity_intrahour_low",
    ])
    write_csv(FILLS_PATH, fill_rows, [
        "period", "model", "side_cost", "timestamp_utc", "symbol", "side", "price",
        "quantity", "notional", "fee", "predicted_q10", "target_exposure_fraction",
        "target_exposure_notional",
    ])

    snapshot_identity_rows = []
    for series_id, vintage in sorted(snapshots, key=lambda key: (key[1], key[0])):
        item = snapshots[(series_id, vintage)]
        snapshot_identity_rows.append({
            "series": series_id,
            "vintage_date": vintage.isoformat(),
            "snapshot_sha256": sha256(item["payload"]),
        })
    macro_snapshot_identity = sha256(json.dumps(
        snapshot_identity_rows, sort_keys=True, separators=(",", ":")
    ).encode("utf-8"))

    all_gate_pass = True
    for period in ("walk_forward", "holdout_2025_plus"):
        for cost in SIDE_COSTS:
            row = portfolio_results[period][f"{cost:.4f}"]["price_plus_macro"]
            all_gate_pass &= row["cagr_pct"] >= 50 and row["max_drawdown_adverse_hourly_pct"] <= 10
    if all_gate_pass:
        decision = "O sizing macro passou os limites retrospectivos congelados. Ainda depende de confirmação prospectiva em paper antes de qualquer negociação."
    else:
        decision = "A previsão de cauda não passou todos os limites retrospectivos congelados. Registrar a hipótese como rejeitada ou inconclusiva; não ajustar esta amostra."

    created = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result = {
        "created_utc": created,
        "goal_achieved": False,
        "historical_gate_passed": bool(all_gate_pass),
        "deployable": False,
        "decision": decision,
        "schedule": {
            "first_by_model": {model: iso(boundaries[index]) for model, index in first_by_model.items()},
            "first_common_forecast_utc": iso(boundaries[first_common]),
            "holdout_start_utc": iso(boundaries[holdout_index]),
            "last_entry_utc": iso(boundaries[-2]),
            "terminal_utc": iso(boundaries[-1]),
            "archive_manifest_sha256": archive_hash,
            "binance_manifest_entries": len(manifest),
        },
        "universe": list(SYMBOLS),
        "quantile": QUANTILE,
        "quantile_alpha": QUANTILE_ALPHA,
        "risk_budget_per_sleeve": RISK_BUDGET_PER_SLEEVE,
        "minimum_risk_denominator": RISK_FLOOR,
        "macro_snapshot_count": len(snapshots),
        "macro_cache_hits": cache_hits,
        "macro_snapshot_identity_sha256": macro_snapshot_identity,
        "macro_feature_freshness_by_week": {
            utc_datetime(boundaries[index]).date().isoformat(): provenance
            for index, provenance in freshness.items()
        },
        "forecast_count_by_model": {
            model: sum(row["model"] == model for row in forecasts)
            for model in ("price_only", "price_plus_macro")
        },
        "forecast_scores": scores,
        "portfolio_results": portfolio_results,
        "config": {
            "label": "minimum hourly low / Monday 00:00 entry open - 1 over the following 168 hours",
            "training": "expanding per asset; only labels completed before Sunday 23:00 UTC",
            "estimator": "StandardScaler + QuantileRegressor",
            "price_lags_weeks": list(PRICE_LAGS),
            "risk_budget_formula": "min(1, 0.04 / max(0.01, -predicted_q10))",
            "side_costs": list(SIDE_COSTS),
            "hyperparameter_search": False,
            "orders_authorized": False,
            "jev_calls_authorized": False,
        },
        "source_hashes": {
            "protocol": sha256(PROTOCOL_PATH.read_bytes()),
            "source_script": sha256(SOURCE_SCRIPT.read_bytes()),
            "risk_script": sha256(Path(__file__).read_bytes()),
        },
        "runtime": {"python": platform.python_version(), "numpy": np.__version__,
                    "scikit_learn": sklearn.__version__},
    }
    JSON_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8", newline="\n")
    render_report(result)
    print(f"tail-risk replay complete; historical_gate_passed={all_gate_pass}; report={REPORT_PATH}")


if __name__ == "__main__":
    main()
