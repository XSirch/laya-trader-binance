"""Walk-forward quantile risk sizing with delayed Crypto Fear & Greed features."""

from __future__ import annotations

from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
from urllib.request import urlopen

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
    macro_features,
    period_index,
    period_returns,
    price_features,
    resolve_schedule,
    sha256,
    utc_datetime,
    write_csv,
)
from .macro_tail_risk_research import (
    QUANTILE,
    QUANTILE_ALPHA,
    RISK_BUDGET_PER_SLEEVE,
    RISK_FLOOR,
    pinball_loss,
    portfolio_replay,
    risk_portfolio_replay,
    summarize_replay,
)

ROOT = Path.cwd()
FGI_URL = "https://api.alternative.me/fng/?limit=0&format=json"
FGI_PATH = ROOT / ".cache" / "macro_fgi" / "fng.json"
PROTOCOL_PATH = ROOT / "docs" / "macro_sentiment_tail_risk_protocol_2026-09-27.md"
SOURCES_PATH = ROOT / "docs" / "macro_sentiment_tail_risk_sources_2026-09-27.md"
SCRIPT_PATH = ROOT / "src" / "jev_trader" / "macro_sentiment_tail_risk_research.py"
MACRO_SCRIPT_PATH = ROOT / "src" / "jev_trader" / "macro_external_alpha_research.py"
TAIL_SCRIPT_PATH = ROOT / "src" / "jev_trader" / "macro_tail_risk_research.py"
REPORT_PATH = ROOT / "docs" / "macro_sentiment_tail_risk_research_2026-09-27.md"
JSON_PATH = ROOT / "results" / "macro_sentiment_tail_risk_research.json"
FORECASTS_PATH = ROOT / "results" / "macro_sentiment_tail_risk_forecasts.csv"
CURVES_PATH = ROOT / "results" / "macro_sentiment_tail_risk_curves.csv"
FILLS_PATH = ROOT / "results" / "macro_sentiment_tail_risk_fills.csv"
MODELS = ("price_only", "price_plus_macro", "price_plus_fgi", "price_plus_macro_fgi")
FGI_FEATURE_NAMES = ("fgi_level", "fgi_change_7d", "fgi_change_30d")
DAY_MS = 24 * HOUR_MS
FGI_DELAY_MS = 48 * HOUR_MS
UTC = timezone.utc


def load_fgi():
    if FGI_PATH.exists():
        payload = FGI_PATH.read_bytes()
    else:
        FGI_PATH.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(FGI_URL, timeout=30) as response:
            if response.status != 200:
                raise OSError(f"Fear & Greed API returned HTTP {response.status}")
            payload = response.read()
        FGI_PATH.write_bytes(payload)

    document = json.loads(payload)
    if document.get("name") != "Fear and Greed Index" or document.get("metadata", {}).get("error"):
        raise ValueError("unexpected Fear & Greed API response")
    raw_rows = document.get("data")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("Fear & Greed history is empty")

    rows = []
    seen = set()
    for row in raw_rows:
        timestamp = int(row["timestamp"]) * 1000
        raw_value = str(row["value"])
        value = int(raw_value)
        if str(value) != raw_value or not 0 <= value <= 100:
            raise ValueError("Fear & Greed values must be integer scores from 0 through 100")
        if timestamp in seen:
            raise ValueError("duplicate Fear & Greed timestamp")
        seen.add(timestamp)
        rows.append({"timestamp_ms": timestamp, "value": value})
    rows.sort(key=lambda row: row["timestamp_ms"])
    times = [row["timestamp_ms"] for row in rows]
    if any(right <= left for left, right in zip(times, times[1:])):
        raise ValueError("Fear & Greed timestamps are not strictly increasing")
    return payload, rows


def fgi_features(rows, timestamps, week_start_ms):
    decision_ms = week_start_ms - HOUR_MS
    cutoff_ms = decision_ms - FGI_DELAY_MS
    current_index = bisect_right(timestamps, cutoff_ms) - 1
    if current_index < 0:
        return None
    current = rows[current_index]
    features = {"fgi_level": current["value"] / 100.0}
    for lag_days, name in ((7, "fgi_change_7d"), (30, "fgi_change_30d")):
        reference_time = current["timestamp_ms"] - lag_days * DAY_MS
        reference_index = bisect_right(timestamps, reference_time) - 1
        if reference_index < 0:
            return None
        features[name] = (current["value"] - rows[reference_index]["value"]) / 100.0
    provenance = {
        "decision_timestamp_ms": decision_ms,
        "cutoff_timestamp_ms": cutoff_ms,
        "observation_timestamp_ms": current["timestamp_ms"],
        "observation_age_hours": (decision_ms - current["timestamp_ms"]) / HOUR_MS,
        "level": current["value"],
        "change_7d_points": 100 * features["fgi_change_7d"],
        "change_30d_points": 100 * features["fgi_change_30d"],
    }
    if current["timestamp_ms"] > cutoff_ms or current["timestamp_ms"] > decision_ms:
        raise ValueError("Fear & Greed feature uses a future observation")
    return features, provenance


def feature_vector(price, macro, fgi, model):
    names = sorted(price)
    values = [price[name] for name in names]
    if "macro" in model:
        if macro is None:
            return None, None
        macro_names = sorted(macro)
        names.extend(macro_names)
        values.extend(macro[name] for name in macro_names)
    if "fgi" in model:
        if fgi is None:
            return None, None
        names.extend(FGI_FEATURE_NAMES)
        values.extend(fgi[name] for name in FGI_FEATURE_NAMES)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("nonfinite model feature")
    return names, np.asarray(values, dtype=float)


def build_forecasts(bars_by_symbol, boundaries, snapshots, fgi_rows):
    fgi_times = [row["timestamp_ms"] for row in fgi_rows]
    features_by_week = {}
    provenance_by_week = {}
    macro_provenance_by_week = {}
    for index, timestamp in enumerate(boundaries[:-1]):
        macro, macro_provenance = macro_features(snapshots, timestamp)
        sentiment_result = fgi_features(fgi_rows, fgi_times, timestamp)
        sentiment, sentiment_provenance = sentiment_result if sentiment_result else (None, None)
        features_by_week[index] = {"macro": macro, "fgi": sentiment}
        provenance_by_week[index] = sentiment_provenance
        macro_provenance_by_week[index] = macro_provenance

    forecasts = []
    for symbol in SYMBOLS:
        bars = bars_by_symbol[symbol]
        rows = []
        for index in range(13, len(boundaries) - 1):
            start, end = boundaries[index], boundaries[index + 1]
            start_price = bars[start].open
            lows = [bars[timestamp].low for timestamp in range(start, end, HOUR_MS)]
            if len(lows) != WEEK_MS // HOUR_MS:
                raise ValueError("a weekly downside label is missing hourly observations")
            price = price_features(bars_by_symbol, boundaries, symbol, index)
            external = features_by_week[index]
            rows.append({
                "index": index,
                "start_ms": start,
                "end_ms": end,
                "price": price,
                "macro": external["macro"],
                "fgi": external["fgi"],
                "fgi_provenance": provenance_by_week[index],
                "actual_worst_return": min(lows) / start_price - 1.0,
            })

        for row in rows:
            for model in MODELS:
                names, current_x = feature_vector(row["price"], row["macro"], row["fgi"], model)
                if current_x is None:
                    continue
                training = []
                for sample in rows:
                    if sample["index"] > row["index"] - 2:
                        continue
                    train_names, train_x = feature_vector(
                        sample["price"], sample["macro"], sample["fgi"], model
                    )
                    if train_x is not None:
                        if train_names != names:
                            raise ValueError("quantile feature order changed during walk-forward")
                        training.append((sample, train_x))
                if len(training) < MIN_TRAINING_WEEKS:
                    continue
                estimator = make_pipeline(
                    StandardScaler(),
                    QuantileRegressor(
                        quantile=QUANTILE,
                        alpha=QUANTILE_ALPHA,
                        solver="highs",
                        fit_intercept=True,
                    ),
                )
                estimator.fit(
                    np.vstack([item[1] for item in training]),
                    np.asarray([item[0]["actual_worst_return"] for item in training], dtype=float),
                )
                prediction = float(estimator.predict(current_x.reshape(1, -1))[0])
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
                    "actual_worst_return": row["actual_worst_return"],
                    "training_q10": float(np.quantile(
                        [item[0]["actual_worst_return"] for item in training], QUANTILE
                    )),
                    "training_count": len(training),
                    "training_last_completed_exit_ms": boundaries[row["index"] - 1],
                    "feature_count": len(names),
                    "fgi_observation_timestamp_ms": (
                        row["fgi_provenance"]["observation_timestamp_ms"]
                        if row["fgi_provenance"] else None
                    ),
                    "fgi_observation_age_hours": (
                        row["fgi_provenance"]["observation_age_hours"]
                        if row["fgi_provenance"] else None
                    ),
                    "fgi_level": row["fgi_provenance"]["level"]
                    if row["fgi_provenance"] else None,
                })
        print(f"sentiment tail quantile forecasts {symbol}: "
              f"{sum(row['symbol'] == symbol for row in forecasts)}")
    forecasts.sort(key=lambda row: (row["index"], row["symbol"], MODELS.index(row["model"])))
    return forecasts, provenance_by_week, macro_provenance_by_week


def forecast_scores(forecasts, start_index, end_index):
    selected = [row for row in forecasts if start_index <= row["index"] < end_index]
    by_model = {
        model: {(row["index"], row["symbol"]): row for row in selected if row["model"] == model}
        for model in MODELS
    }
    common = set.intersection(*(set(rows) for rows in by_model.values()))
    scores = {}
    for model in MODELS:
        rows = [by_model[model][key] for key in sorted(common)]
        actual = np.asarray([row["actual_worst_return"] for row in rows])
        predicted = np.asarray([row["prediction_q10"] for row in rows])
        training_q10 = np.asarray([row["training_q10"] for row in rows])
        scores[model] = {
            "count": len(rows),
            "unique_signal_weeks": len({row["index"] for row in rows}),
            "pinball": float(np.mean(pinball_loss(actual, predicted, QUANTILE))),
            "pinball_zero": float(np.mean(pinball_loss(actual, np.zeros(len(rows)), QUANTILE))),
            "pinball_training_q10": float(np.mean(pinball_loss(actual, training_q10, QUANTILE))),
            "coverage_pct": 100 * float(np.mean(actual <= predicted)),
            "mean_actual_worst_return_pct": 100 * float(np.mean(actual)),
            "mean_predicted_q10_pct": 100 * float(np.mean(predicted)),
        }
    for candidate, control in (("price_plus_fgi", "price_only"),
                               ("price_plus_macro_fgi", "price_plus_macro")):
        base = scores[control]["pinball"]
        candidate_loss = scores[candidate]["pinball"]
        scores[f"{candidate}_pinball_skill_vs_{control}_pct"] = (
            100 * (1 - candidate_loss / base) if base > 0 else None
        )
    return scores, len(common)


def summarize_portfolio_results(bars_by_symbol, boundaries, forecasts, first_common, holdout_index):
    terminal_index = len(boundaries) - 1
    portfolio_results = {}
    curve_rows, fill_rows = [], []
    for period, start_index in (("walk_forward", first_common),
                                ("holdout_2025_plus", holdout_index)):
        by_cost = {}
        for cost in SIDE_COSTS:
            cost_key = f"{cost:.4f}"
            by_model = {}
            for model in MODELS:
                replay = risk_portfolio_replay(
                    bars_by_symbol, boundaries, forecasts, model=model,
                    side_cost=cost, start_index=start_index, end_index=terminal_index,
                )
                by_model[model] = summarize_replay(replay)
                curve_rows.extend({"period": period, "model": model, "side_cost": cost, **row}
                                  for row in replay["curve"])
                fill_rows.extend({"period": period, **row} for row in replay["fills"])
            for model in ("buy_hold", "cash"):
                replay = portfolio_replay(
                    bars_by_symbol, boundaries, forecasts, model=model,
                    side_cost=cost, start_index=start_index, end_index=terminal_index,
                    mode=model,
                )
                by_model[model] = summarize_replay(replay)
                curve_rows.extend({"period": period, "model": model, "side_cost": cost, **row}
                                  for row in replay["curve"])
                fill_rows.extend({"period": period, **row} for row in replay["fills"])
            by_cost[cost_key] = by_model
        portfolio_results[period] = by_cost
    return portfolio_results, curve_rows, fill_rows


def render_report(result):
    lines = [
        "# Fear & Greed como feature de risco semanal",
        "",
        f"Execução {result['created_utc']}. Resultado retrospectivo; `deployable=false`.",
        "",
        "## Integridade dos dados e alinhamento",
        "",
        f"A API devolveu {result['fgi']['row_count']} observações entre "
        f"{result['fgi']['first_observation_utc']} e {result['fgi']['last_observation_utc']}; "
        f"SHA-256 do payload `{result['fgi']['payload_sha256']}`. Decisões usam o registro mais recente "
        "datado até 48 horas antes do domingo 23:00 UTC. A API não fornece vintages históricas; "
        "o atraso limita lookahead de publicação, mas não exclui revisões retrospectivas.",
        "",
        "## Previsão do quantil 10%",
        "",
        "Menor perda pinball é melhor. Todos os modelos são medidos nas mesmas combinações de ativo e semana.",
        "",
        "| Janela | Modelo | ativo-semanas | semanas | pinball | q10 treino | cobertura | q10 médio | pior retorno semanal médio |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for period, models in result["forecast_scores"].items():
        for model in MODELS:
            row = models[model]
            lines.append(
                f"| {period} | {model} | {row['count']} | {row['unique_signal_weeks']} | "
                f"{row['pinball']:.6f} | {row['pinball_training_q10']:.6f} | "
                f"{row['coverage_pct']:.1f}% | {row['mean_predicted_q10_pct']:.2f}% | "
                f"{row['mean_actual_worst_return_pct']:.2f}% |"
            )
        lines.append(
            f"| {period} | FGI skill: preço+FGI vs preço | — | — | "
            f"{models['price_plus_fgi_pinball_skill_vs_price_only_pct']:.2f}% | — | — | — | — |"
        )
        lines.append(
            f"| {period} | FGI skill: macro+FGI vs macro | — | — | "
            f"{models['price_plus_macro_fgi_pinball_skill_vs_price_plus_macro_pct']:.2f}% | — | — | — | — |"
        )
    lines += [
        "",
        "## Carteiras com sizing idêntico",
        "",
        "O orçamento segue o protocolo anterior: exposição `min(100%, 4% / max(1%, -q10))` por parcela. "
        "O drawdown adverso assume a máxima antes da mínima da hora.",
        "",
        "| Janela | custo/lado | modelo | retorno líquido | CAGR | DD adverso | alocação média | ordens |",
        "|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    for period, costs in result["portfolio_results"].items():
        for cost, models in costs.items():
            for model in (*MODELS, "buy_hold", "cash"):
                row = models[model]
                lines.append(
                    f"| {period} | {float(cost):.2%} | {model} | {row['return_pct']:.2f}% | "
                    f"{row['cagr_pct']:.2f}% | {row['max_drawdown_adverse_hourly_pct']:.2f}% | "
                    f"{row['average_exposure_pct_account']:.2f}% | {row['order_count']} |"
                    if "average_exposure_pct_account" in row else
                    f"| {period} | {float(cost):.2%} | {model} | {row['return_pct']:.2f}% | "
                    f"{row['cagr_pct']:.2f}% | {row['max_drawdown_adverse_hourly_pct']:.2f}% | "
                    f"— | {row['order_count']} |"
                )
    lines += [
        "",
        "## Decisão",
        "",
        f"{result['decision']}",
        "",
        "O FGI não é uma fonte comprovadamente point-in-time nesta série. Mesmo resultado positivo precisaria "
        "ser reavaliado prospectivamente com snapshots arquivados antes de qualquer interpretação operacional. "
        "O estudo não chama JEV, não altera o paper watcher e não envia ordens.",
        "",
        f"Arquivos: protocolo [macro_sentiment_tail_risk_protocol_2026-09-27.md]"
        f"(macro_sentiment_tail_risk_protocol_2026-09-27.md), fonte [macro_sentiment_tail_risk_sources_2026-09-27.md]"
        f"(macro_sentiment_tail_risk_sources_2026-09-27.md). Binance manifest `{result['schedule']['archive_manifest_sha256']}`; "
        f"vintages ALFRED `{result['macro_snapshot_identity_sha256']}`.",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main():
    bars_by_symbol, manifest, boundaries, archive_hash = resolve_schedule()
    fgi_payload, fgi_rows = load_fgi()
    snapshots, macro_cache_hits = fetch_all_snapshots(boundaries)
    forecasts, fgi_provenance, macro_provenance = build_forecasts(
        bars_by_symbol, boundaries, snapshots, fgi_rows
    )
    first_by_model = {
        model: min((row["index"] for row in forecasts if row["model"] == model), default=None)
        for model in MODELS
    }
    if any(index is None for index in first_by_model.values()):
        raise ValueError("a sentiment ablation model emitted no predictions")
    first_common = max(first_by_model.values())
    terminal_index = len(boundaries) - 1
    holdout_index = period_index(boundaries, FINAL_HOLDOUT)
    windows = {
        "walk_forward": (first_common, terminal_index),
        "development_2024": (first_common, period_index(boundaries, date(2025, 1, 1))),
        "holdout_2025_plus": (holdout_index, terminal_index),
    }
    forecast_scores_by_window = {}
    common_count_by_window = {}
    for name, (start, end) in windows.items():
        forecast_scores_by_window[name], common_count_by_window[name] = forecast_scores(
            forecasts, start, end
        )

    portfolio_results, curve_rows, fill_rows = summarize_portfolio_results(
        bars_by_symbol, boundaries, forecasts, first_common, holdout_index
    )
    forecast_rows = []
    for row in forecasts:
        forecast_rows.append({
            **row,
            "signal_timestamp_utc": utc_datetime(row["signal_timestamp_ms"]).isoformat().replace("+00:00", "Z"),
            "exit_timestamp_utc": utc_datetime(row["exit_timestamp_ms"]).isoformat().replace("+00:00", "Z"),
            "fgi_observation_timestamp_utc": (
                utc_datetime(row["fgi_observation_timestamp_ms"]).isoformat().replace("+00:00", "Z")
                if row["fgi_observation_timestamp_ms"] is not None else None
            ),
        })
    write_csv(FORECASTS_PATH, forecast_rows, [
        "index", "signal_timestamp_ms", "signal_timestamp_utc", "signal_sunday_utc",
        "exit_timestamp_ms", "exit_timestamp_utc", "symbol", "model", "prediction_q10",
        "actual_worst_return", "training_q10", "training_count", "training_last_completed_exit_ms",
        "feature_count", "fgi_observation_timestamp_ms", "fgi_observation_timestamp_utc",
        "fgi_observation_age_hours", "fgi_level",
    ])
    write_csv(CURVES_PATH, curve_rows, [
        "period", "model", "side_cost", "timestamp_ms", "timestamp_utc", "equity_pre",
        "equity_post", "equity_intrahour_high", "equity_intrahour_low",
    ])
    write_csv(FILLS_PATH, fill_rows, [
        "period", "model", "side_cost", "timestamp_utc", "symbol", "side", "price", "quantity",
        "notional", "fee", "predicted_q10", "target_exposure_fraction", "target_exposure_notional",
    ])

    snapshot_identity_rows = [
        {"series": series_id, "vintage_date": vintage.isoformat(),
         "snapshot_sha256": sha256(item["payload"])}
        for (series_id, vintage), item in sorted(snapshots.items(), key=lambda item: (item[0][1], item[0][0]))
    ]
    snapshot_identity = sha256(json.dumps(
        snapshot_identity_rows, sort_keys=True, separators=(",", ":")
    ).encode("utf-8"))
    fgi_times = [row["timestamp_ms"] for row in fgi_rows]
    gap_days = [(right - left) / DAY_MS for left, right in zip(fgi_times, fgi_times[1:])]
    walk_scores = forecast_scores_by_window["walk_forward"]
    holdout_scores = forecast_scores_by_window["holdout_2025_plus"]
    pinball_pass = all(
        forecast_scores_by_window[period]["price_plus_macro_fgi_pinball_skill_vs_price_plus_macro_pct"] > 0
        for period in ("walk_forward", "holdout_2025_plus")
    )
    candidate_metrics = [
        portfolio_results[period][f"{cost:.4f}"]["price_plus_macro_fgi"]
        for period in ("walk_forward", "holdout_2025_plus")
        for cost in SIDE_COSTS
    ]
    portfolio_pass = all(
        row["cagr_pct"] >= 50 and row["max_drawdown_adverse_hourly_pct"] <= 10
        for row in candidate_metrics
    )
    historical_gate_passed = pinball_pass and portfolio_pass
    decision = (
        "O FGI melhorou a previsão de cauda e a carteira primária passou os limites retrospectivos congelados; "
        "isso ainda exige confirmação prospectiva paper com dados arquivados."
        if historical_gate_passed else
        "A ablação FGI não passou o critério congelado de previsão e carteira. Não ajustar esta amostra; "
        "a meta de lucratividade consistente permanece não atingida."
    )

    result = {
        "created_utc": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "goal_achieved": False,
        "historical_gate_passed": historical_gate_passed,
        "deployable": False,
        "decision": decision,
        "schedule": {
            "first_common_forecast_utc": utc_datetime(boundaries[first_common]).isoformat().replace("+00:00", "Z"),
            "holdout_start_utc": utc_datetime(boundaries[holdout_index]).isoformat().replace("+00:00", "Z"),
            "last_entry_utc": utc_datetime(boundaries[-2]).isoformat().replace("+00:00", "Z"),
            "terminal_utc": utc_datetime(boundaries[-1]).isoformat().replace("+00:00", "Z"),
            "archive_manifest_sha256": archive_hash,
            "binance_manifest_entries": len(manifest),
            "first_by_model_utc": {model: utc_datetime(boundaries[index]).isoformat().replace("+00:00", "Z")
                                   for model, index in first_by_model.items()},
        },
        "universe": list(SYMBOLS),
        "models": list(MODELS),
        "quantile": QUANTILE,
        "quantile_alpha": QUANTILE_ALPHA,
        "minimum_training_weeks": MIN_TRAINING_WEEKS,
        "risk_budget_per_sleeve": RISK_BUDGET_PER_SLEEVE,
        "minimum_risk_denominator": RISK_FLOOR,
        "fgi": {
            "source_url": FGI_URL,
            "payload_sha256": sha256(fgi_payload),
            "row_count": len(fgi_rows),
            "first_observation_utc": utc_datetime(fgi_rows[0]["timestamp_ms"]).isoformat().replace("+00:00", "Z"),
            "last_observation_utc": utc_datetime(fgi_rows[-1]["timestamp_ms"]).isoformat().replace("+00:00", "Z"),
            "min_gap_days": min(gap_days),
            "max_gap_days": max(gap_days),
            "decision_delay_hours": FGI_DELAY_MS / HOUR_MS,
            "vintages_available": False,
            "retrospective_revision_risk": True,
        },
        "macro_snapshot_count": len(snapshots),
        "macro_cache_hits": macro_cache_hits,
        "macro_snapshot_identity_sha256": snapshot_identity,
        "forecast_count_by_model": {
            model: sum(row["model"] == model for row in forecasts) for model in MODELS
        },
        "common_forecast_count_by_window": common_count_by_window,
        "forecast_scores": forecast_scores_by_window,
        "portfolio_results": portfolio_results,
        "sentiment_provenance_by_week": {
            utc_datetime(boundaries[index]).date().isoformat(): provenance
            for index, provenance in fgi_provenance.items() if provenance is not None
        },
        "macro_provenance_by_week": {
            utc_datetime(boundaries[index]).date().isoformat(): provenance
            for index, provenance in macro_provenance.items()
        },
        "config": {
            "label": "minimum hourly low / Monday 00:00 entry open - 1 over the following 168 hours",
            "training": "expanding per asset; only labels completed before Sunday 23:00 UTC",
            "estimator": "StandardScaler + QuantileRegressor",
            "price_lags_weeks": list(PRICE_LAGS),
            "fgi_features": list(FGI_FEATURE_NAMES),
            "fgi_alignment": "latest timestamp <= Sunday 23:00 UTC minus 48 hours; no historical vintages",
            "risk_budget_formula": "min(1, 0.04 / max(0.01, -predicted_q10))",
            "side_costs": list(SIDE_COSTS),
            "hyperparameter_search": False,
            "orders_authorized": False,
            "jev_calls_authorized": False,
        },
        "source_hashes": {
            "protocol": sha256(PROTOCOL_PATH.read_bytes()),
            "sources": sha256(SOURCES_PATH.read_bytes()),
            "script": sha256(SCRIPT_PATH.read_bytes()),
            "macro_script": sha256(MACRO_SCRIPT_PATH.read_bytes()),
            "tail_risk_script": sha256(TAIL_SCRIPT_PATH.read_bytes()),
        },
        "runtime": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "forecast_skill_gate_passed": pinball_pass,
        "portfolio_target_gate_passed": portfolio_pass,
        "price_plus_fgi_holdout_skill_pct": holdout_scores[
            "price_plus_fgi_pinball_skill_vs_price_only_pct"
        ],
        "macro_plus_fgi_holdout_skill_pct": holdout_scores[
            "price_plus_macro_fgi_pinball_skill_vs_price_plus_macro_pct"
        ],
        "orders_sent": 0,
        "jev_calls": 0,
    }
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    render_report(result)
    print(f"sentiment tail research {JSON_PATH}")
    print(f"historical gate passed: {historical_gate_passed}; goal achieved: false")


if __name__ == "__main__":
    main()
