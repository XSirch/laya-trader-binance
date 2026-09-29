"""Walk-forward ablation of crypto-native stablecoin supply for Spot signals."""

from __future__ import annotations

from bisect import bisect_right
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
from urllib.request import Request, urlopen

import numpy as np
import sklearn
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import macro_external_alpha_research as weekly

ROOT = Path.cwd()
PROTOCOL_PATH = ROOT / "docs" / "crypto_liquidity_alpha_protocol_2026-09-27.md"
SOURCES_PATH = ROOT / "docs" / "crypto_liquidity_alpha_sources_2026-09-27.md"
SCRIPT_PATH = ROOT / "src" / "jev_trader" / "crypto_liquidity_alpha_research.py"
WEEKLY_HELPER_PATH = ROOT / "src" / "jev_trader" / "macro_external_alpha_research.py"
CACHE_PATH = ROOT / ".cache" / "crypto_liquidity_alpha" / "stablecoincharts_all.json"
INPUTS_PATH = ROOT / "results" / "crypto_liquidity_alpha_inputs.json"
JSON_PATH = ROOT / "results" / "crypto_liquidity_alpha_research.json"
REPORT_PATH = ROOT / "docs" / "crypto_liquidity_alpha_research_2026-09-27.md"
FORECASTS_PATH = ROOT / "results" / "crypto_liquidity_alpha_forecasts.csv"
FEATURES_PATH = ROOT / "results" / "crypto_liquidity_alpha_features.csv"
FILLS_PATH = ROOT / "results" / "crypto_liquidity_alpha_fills.csv"

SOURCE_URL = "https://stablecoins.llama.fi/stablecoincharts/all"
EXPECTED_PAYLOAD_SHA256 = "d3a1c35db255b36b0b02934195fbef10c8249e4fdce0234639de2423350618d9"
ACQUIRED_UTC = "2026-09-27T16:43:09.003959+00:00"
PUBLICATION_LAG_HOURS = 96
MAX_REFERENCE_AGE_HOURS = 48
LOOKBACK_DAYS = (7, 30)
DAY_MS = 24 * weekly.HOUR_MS
MIN_TRAINING_WEEKS = 52
MODEL_BASE = "price_only"
MODEL_LIQUIDITY = "price_plus_stablecoin_liquidity"
MODELS = (MODEL_BASE, MODEL_LIQUIDITY)
UTC = timezone.utc


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _iso(timestamp_ms: int) -> str:
    return weekly.iso(timestamp_ms)


def _read_supply_series(payload: bytes):
    root = json.loads(payload.decode("utf-8", errors="strict"))
    if not isinstance(root, list) or len(root) < 365:
        raise ValueError("stablecoin endpoint did not return a historical list")
    rows = []
    missing = 0
    for item in root:
        if not isinstance(item, dict) or "date" not in item:
            raise ValueError("stablecoin response contains an invalid record")
        raw = item.get("totalCirculatingUSD", {})
        value = raw.get("peggedUSD") if isinstance(raw, dict) else None
        if value is None:
            missing += 1
            continue
        timestamp_ms = int(item["date"]) * 1000
        amount = float(value)
        if timestamp_ms <= 0 or not math.isfinite(amount) or amount <= 0:
            raise ValueError("stablecoin observation is not finite and positive")
        rows.append((timestamp_ms, amount))
    timestamps = [row[0] for row in rows]
    if timestamps != sorted(set(timestamps)):
        raise ValueError("stablecoin observations are not unique and chronological")
    if len(rows) < 365:
        raise ValueError("too few valid USD-pegged stablecoin observations")
    deltas = [right - left for left, right in zip(timestamps, timestamps[1:])]
    return rows, {"response_records": len(root), "usable_records": len(rows),
                  "records_missing_usd_pegged_supply": missing,
                  "daily_gaps": sum(delta > DAY_MS for delta in deltas),
                  "missing_calendar_days": sum(max(0, delta // DAY_MS - 1)
                                                for delta in deltas),
                  "maximum_observation_gap_hours": max(deltas, default=0)
                  / weekly.HOUR_MS}


def _load_frozen_supply():
    if not CACHE_PATH.exists():
        raise FileNotFoundError(
            f"frozen API payload missing: {CACHE_PATH}; fetch once and verify its frozen SHA-256"
        )
    payload = CACHE_PATH.read_bytes()
    digest = _sha_bytes(payload)
    if digest != EXPECTED_PAYLOAD_SHA256:
        raise ValueError("cached stablecoin payload differs from the frozen protocol input")
    rows, counts = _read_supply_series(payload)
    return rows, payload, digest, counts


def fetch_frozen_supply():
    """Fetch the source once into cache; never replace an existing frozen payload."""
    if CACHE_PATH.exists():
        raise FileExistsError("refusing to overwrite the frozen stablecoin payload")
    request = Request(SOURCE_URL, headers={"User-Agent": "crypto-liquidity-research/1.0"})
    with urlopen(request, timeout=45) as response:
        if response.status != 200:
            raise OSError(f"stablecoin API returned HTTP {response.status}")
        payload = response.read()
    digest = _sha_bytes(payload)
    if digest != EXPECTED_PAYLOAD_SHA256:
        raise ValueError("live response differs from the protocol's frozen payload hash")
    _read_supply_series(payload)
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_bytes(payload)
    return {"bytes": len(payload), "sha256": digest}


def _latest_at_or_before(rows, timestamps, cutoff_ms):
    index = bisect_right(timestamps, cutoff_ms) - 1
    if index < 0:
        return None
    return index, rows[index]


def supply_features(rows, week_start_ms):
    decision_ms = week_start_ms - weekly.HOUR_MS
    current_cutoff = decision_ms - PUBLICATION_LAG_HOURS * weekly.HOUR_MS
    timestamps = [row[0] for row in rows]
    selected = _latest_at_or_before(rows, timestamps, current_cutoff)
    if selected is None:
        return None, {"status": "no_current_observation"}
    current_index, (current_ms, current_supply) = selected
    current_age_h = (current_cutoff - current_ms) / weekly.HOUR_MS
    provenance = {
        "status": "available",
        "decision_utc": _iso(decision_ms),
        "feature_cutoff_utc": _iso(current_cutoff),
        "observation_utc": _iso(current_ms),
        "observation_age_at_cutoff_hours": current_age_h,
        "supply_usd": current_supply,
        "lookbacks": {},
    }
    if current_age_h < 0 or current_age_h > MAX_REFERENCE_AGE_HOURS:
        provenance["status"] = "stale_current_observation"
        return None, provenance

    features = {}
    for days in LOOKBACK_DAYS:
        target_ms = current_ms - days * DAY_MS
        historical = _latest_at_or_before(rows, timestamps, target_ms)
        if historical is None:
            provenance["status"] = f"missing_{days}d_reference"
            return None, provenance
        _, (reference_ms, reference_supply) = historical
        age_h = (target_ms - reference_ms) / weekly.HOUR_MS
        provenance["lookbacks"][str(days)] = {
            "target_utc": _iso(target_ms),
            "observation_utc": _iso(reference_ms),
            "observation_age_at_target_hours": age_h,
            "supply_usd": reference_supply,
        }
        if age_h < 0 or age_h > MAX_REFERENCE_AGE_HOURS:
            provenance["status"] = f"stale_{days}d_reference"
            return None, provenance
        features[f"stablecoin_supply_log_change_{days}d"] = math.log(
            current_supply / reference_supply
        )
    if not all(math.isfinite(value) for value in features.values()):
        raise ValueError("stablecoin feature is nonfinite")
    return features, provenance


def _feature_vector(price, liquidity, model):
    features = dict(price)
    if model == MODEL_LIQUIDITY:
        if liquidity is None:
            return None, None
        features.update(liquidity)
    elif model != MODEL_BASE:
        raise ValueError(f"unknown model {model}")
    keys = sorted(features)
    vector = np.asarray([features[key] for key in keys], dtype=float)
    if not np.isfinite(vector).all():
        raise ValueError("nonfinite training or forecast feature")
    return keys, vector


def build_forecasts(bars_by_symbol, boundaries, supply_rows):
    by_week = {}
    ledger = []
    for index, timestamp in enumerate(boundaries[:-1]):
        features, provenance = supply_features(supply_rows, timestamp)
        by_week[index] = (features, provenance)
        ledger.append({
            "index": index,
            "signal_timestamp_ms": timestamp,
            "signal_timestamp_utc": _iso(timestamp),
            "features": features,
            "provenance": provenance,
        })

    observations = []
    for symbol in weekly.SYMBOLS:
        bars = bars_by_symbol[symbol]
        for index in range(13, len(boundaries) - 1):
            timestamp, exit_timestamp = boundaries[index], boundaries[index + 1]
            price = weekly.price_features(bars_by_symbol, boundaries, symbol, index)
            actual = bars[exit_timestamp].open / bars[timestamp].open - 1.0
            if not math.isfinite(actual):
                raise ValueError("weekly Spot return label is nonfinite")
            liquidity, provenance = by_week[index]
            observations.append({
                "index": index, "symbol": symbol, "timestamp_ms": timestamp,
                "exit_timestamp_ms": exit_timestamp, "price": price,
                "liquidity": liquidity, "provenance": provenance,
                "actual": actual,
            })

    forecasts = []
    fit_audits = []
    for current in observations:
        index = current["index"]
        for model in MODELS:
            current_keys, current_x = _feature_vector(
                current["price"], current["liquidity"], model
            )
            if current_keys is None:
                continue
            training = [row for row in observations
                        if row["symbol"] == current["symbol"]
                        and row["index"] <= index - 2
                        and (model == MODEL_BASE or row["liquidity"] is not None)]
            if len(training) < MIN_TRAINING_WEEKS:
                continue
            x_train = []
            y_train = []
            for row in training:
                train_keys, vector = _feature_vector(
                    row["price"], row["liquidity"], model
                )
                if train_keys != current_keys:
                    raise ValueError("feature order changed inside an expanding fit")
                x_train.append(vector)
                y_train.append(row["actual"])
            estimator = make_pipeline(
                StandardScaler(), Ridge(alpha=1.0, fit_intercept=True)
            )
            estimator.fit(np.vstack(x_train), np.asarray(y_train, dtype=float))
            prediction = float(estimator.predict(current_x.reshape(1, -1))[0])
            if not math.isfinite(prediction):
                raise ValueError("Ridge emitted a nonfinite weekly forecast")
            forecast = {
                "index": index,
                "signal_timestamp_ms": current["timestamp_ms"],
                "signal_timestamp_utc": _iso(current["timestamp_ms"]),
                "signal_sunday_utc": (
                    weekly.utc_datetime(current["timestamp_ms"]).date().isoformat()
                ),
                "exit_timestamp_ms": current["exit_timestamp_ms"],
                "exit_timestamp_utc": _iso(current["exit_timestamp_ms"]),
                "symbol": current["symbol"], "model": model,
                "prediction": prediction, "actual": current["actual"],
                "training_mean": float(np.mean(y_train)),
                "training_count": len(training),
                "training_last_completed_exit_ms": boundaries[index - 1],
                "feature_count": len(current_keys),
                "stablecoin_supply_log_change_7d": (
                    current["liquidity"].get("stablecoin_supply_log_change_7d")
                    if current["liquidity"] else None
                ),
                "stablecoin_supply_log_change_30d": (
                    current["liquidity"].get("stablecoin_supply_log_change_30d")
                    if current["liquidity"] else None
                ),
            }
            forecasts.append(forecast)
            fit_audits.append({
                "index": index, "symbol": current["symbol"], "model": model,
                "training_count": len(training),
                "training_first_signal_ms": training[0]["timestamp_ms"],
                "training_last_signal_ms": training[-1]["timestamp_ms"],
                "training_last_completed_exit_ms": boundaries[index - 1],
                "signal_timestamp_ms": current["timestamp_ms"],
                "feature_names": current_keys,
                "estimator": {"standard_scaler": True, "ridge_alpha": 1.0,
                              "fit_intercept": True},
            })

    forecasts.sort(key=lambda row: (row["index"], row["symbol"], row["model"]))
    return forecasts, ledger, fit_audits


def forecast_scores(forecasts, start_index, end_index):
    selected = [row for row in forecasts
                if start_index <= row["index"] < end_index]
    augmented_keys = {(row["index"], row["symbol"])
                      for row in selected if row["model"] == MODEL_LIQUIDITY}
    output = {}
    for model in MODELS:
        rows = [row for row in selected if row["model"] == model
                and (row["index"], row["symbol"]) in augmented_keys]
        if not rows:
            output[model] = {"count": 0}
            continue
        actual = np.asarray([row["actual"] for row in rows], dtype=float)
        predicted = np.asarray([row["prediction"] for row in rows], dtype=float)
        training_mean = np.asarray([row["training_mean"] for row in rows], dtype=float)
        output[model] = {
            "count_asset_weeks": len(rows),
            "unique_weeks": len({row["index"] for row in rows}),
            "mse": float(np.mean((actual - predicted) ** 2)),
            "mae": float(np.mean(np.abs(actual - predicted))),
            "mse_vs_zero": float(np.mean(actual ** 2)),
            "mse_vs_training_mean": float(np.mean((actual - training_mean) ** 2)),
            "direction_accuracy_pct": float(
                100 * np.mean((actual > 0) == (predicted > 0))
            ),
            "positive_prediction_fraction_pct": float(100 * np.mean(predicted > 0)),
        }
    base = output[MODEL_BASE].get("mse")
    augmented = output[MODEL_LIQUIDITY].get("mse")
    output["stablecoin_mse_skill_vs_price_only_pct"] = (
        100 * (1 - augmented / base) if base and augmented is not None else None
    )
    return output


def _model_forecasts(forecasts, model, common_keys):
    return [row for row in forecasts if row["model"] == model
            and (row["index"], row["symbol"]) in common_keys]


def _json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    raise TypeError(f"unsupported result type: {type(value).__name__}")


def _render_report(result):
    lines = [
        "# Sinal semanal de liquidez nativa de cripto",
        "",
        f"Execução: {result['created_utc']}. Replay histórico exploratório; nenhuma ordem foi enviada.",
        "",
        "## Resultado do modelo",
        "",
        "A feature usa apenas crescimento de oferta de stablecoins atreladas ao USD, defasada em 96 horas. O ativo negociado em todos os casos é um dos quatro pares Spot listados abaixo.",
        "",
        "| Janela | Semanas/p pares | Price-only MSE | Liquidez cripto MSE | Skill incremental | Acerto direcional com liquidez |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for window, scores in result["forecast_scores"].items():
        base, augmented = scores[MODEL_BASE], scores[MODEL_LIQUIDITY]
        lines.append(
            f"| {window} | {augmented.get('count_asset_weeks', 0)} / {augmented.get('unique_weeks', 0)} | "
            f"{base.get('mse', float('nan')):.8f} | {augmented.get('mse', float('nan')):.8f} | "
            f"{scores.get('stablecoin_mse_skill_vs_price_only_pct', float('nan')):+.2f}% | "
            f"{augmented.get('direction_accuracy_pct', float('nan')):.2f}% |"
        )
    lines.extend(["", "## Carteiras Spot long/caixa", "",
                  "CAGR e drawdown em %. A coluna adversa usa as mínimas horárias enquanto a carteira tem exposição; não prova fills nem o caminho intrabar.",
                  "", "| Janela | Custo/lado | Regra | CAGR | Retorno | DD observado | DD adverso | Exposição | Ordens |",
                  "|---|---:|---|---:|---:|---:|---:|---:|---:|"])
    for period, models in result["portfolio_results"].items():
        for cost_key, entries in models.items():
            for model in (MODEL_LIQUIDITY, MODEL_BASE, "buy_hold", "cash"):
                row = entries[model]
                lines.append(
                    f"| {period} | {float(cost_key) * 100:.2f}% | {model} | "
                    f"{row['cagr_pct']:+.2f}% | {row['return_pct']:+.2f}% | "
                    f"{row['max_drawdown_open_pct']:.2f}% | "
                    f"{row['max_drawdown_adverse_hourly_pct']:.2f}% | "
                    f"{row['exposure_pct_asset_hours']:.1f}% | {row['order_count']} |"
                )
    lines.extend([
        "", "## Decisão", "",
        result["decision"],
        "",
        f"Candidata atingiu a meta retrospectiva congelada nos períodos e custos exigidos: **{str(result['historical_gate_passed']).lower()}**. Meta de consistência confirmatória e prontidão para operar: **não demonstradas**.",
        "",
        "O endpoint não fornece vintages históricas, portanto o atraso de 96 horas não elimina possíveis revisões dos dados. As features podem representar uma variável endógena: retornos cripto também influenciam a emissão de stablecoins. A avaliação repete períodos de preço já estudados no projeto. Custos, spread e slippage são hipóteses fixas, não fills observados.",
        "",
        "## Dados e reprodutibilidade", "",
        f"- Pares Spot negociáveis: {', '.join(result['universe'])}.",
        f"- API: {SOURCE_URL}; registros válidos: {result['stablecoin_source']['usable_records']} de {result['stablecoin_source']['response_records']}; observações ausentes no campo USD-pegged: {result['stablecoin_source']['records_missing_usd_pegged_supply']}.",
        f"- Série observada: {result['stablecoin_source']['first_observation_utc']} a {result['stablecoin_source']['last_observation_utc']}; SHA-256: `{result['stablecoin_source']['payload_sha256']}`.",
        f"- Manifesto Binance Spot: `{result['schedule']['archive_manifest_sha256']}`; protocolo: `{result['integrity']['protocol_sha256']}`; fontes: `{result['integrity']['sources_sha256']}`; código: `{result['integrity']['script_sha256']}`.",
        f"- Scikit-learn: `{result['runtime']['scikit_learn']}`; Python: `{result['runtime']['python']}`.",
        "- Nenhuma stablecoin foi negociada. Nenhum ETF/produto não cripto, contrato futuro, ordem real, chamada JEV ou alteração no paper watcher foi usado.",
        f"- Reproduzir o estudo com `.venv\\Scripts\\python.exe -m jev_trader.crypto_liquidity_alpha_research`; o runner exige que o SHA-256 do payload congelado continue igual a `{EXPECTED_PAYLOAD_SHA256}`.",
        "",
    ])
    return "\n".join(lines)


def run():
    bars_by_symbol, manifest, boundaries, archive_hash = weekly.resolve_schedule()
    supply_rows, payload, payload_hash, supply_counts = _load_frozen_supply()
    acquired_ms = int(datetime.fromisoformat(ACQUIRED_UTC).timestamp() * 1000)
    if supply_rows[-1][0] > acquired_ms:
        raise ValueError("stablecoin payload contains an observation after acquisition time")
    forecasts, feature_ledger, fit_audits = build_forecasts(
        bars_by_symbol, boundaries, supply_rows
    )
    feature_status_counts = {}
    for entry in feature_ledger:
        status = entry["provenance"].get("status", "unknown")
        feature_status_counts[status] = feature_status_counts.get(status, 0) + 1
    first_by_model = {
        model: min((row["index"] for row in forecasts if row["model"] == model),
                   default=None)
        for model in MODELS
    }
    if any(index is None for index in first_by_model.values()):
        raise ValueError("the walk-forward did not produce both fixed models")
    first_forecast_index = max(first_by_model.values())
    terminal_index = len(boundaries) - 1
    holdout_index = weekly.period_index(boundaries, weekly.FINAL_HOLDOUT)
    development_end = weekly.period_index(boundaries, date(2025, 1, 6))
    development_start = max(first_forecast_index,
                            weekly.period_index(boundaries, date(2024, 1, 1)))
    if not first_forecast_index <= holdout_index < terminal_index:
        raise ValueError("the fixed final holdout is outside the forecast schedule")

    score_windows = {
        "walk_forward": (first_forecast_index, terminal_index),
        "development_2024": (development_start, development_end),
        "holdout_2025_plus": (holdout_index, terminal_index),
    }
    scores = {name: forecast_scores(forecasts, start, end)
              for name, (start, end) in score_windows.items()}
    portfolio_windows = {
        "walk_forward": first_forecast_index,
        "development_2024": development_start,
        "holdout_2025_plus": holdout_index,
    }
    portfolio_results = {}
    fill_rows = []
    for period_name, start_index in portfolio_windows.items():
        paired_keys = {
            (row["index"], row["symbol"]) for row in forecasts
            if row["model"] == MODEL_LIQUIDITY
            and start_index <= row["index"] < (
                development_end if period_name == "development_2024" else terminal_index
            )
        }
        rows = {}
        end_index = development_end if period_name == "development_2024" else terminal_index
        for side_cost in weekly.SIDE_COSTS:
            cost_key = f"{side_cost:.4f}"
            entries = {}
            for model in MODELS:
                model_forecasts = _model_forecasts(forecasts, model, paired_keys)
                replay = weekly.portfolio_replay(
                    bars_by_symbol, boundaries, model_forecasts, model=model,
                    side_cost=side_cost, start_index=start_index,
                    end_index=end_index, mode="signal",
                )
                entries[model] = weekly.enrich_metrics(dict(replay))
                fill_rows.extend({"period": period_name, **row}
                                 for row in replay["fills"])
            for mode in ("buy_hold", "cash"):
                replay = weekly.portfolio_replay(
                    bars_by_symbol, boundaries, [], model=mode,
                    side_cost=side_cost, start_index=start_index,
                    end_index=end_index, mode=mode,
                )
                entries[mode] = weekly.enrich_metrics(dict(replay))
                fill_rows.extend({"period": period_name, **row}
                                 for row in replay["fills"])
            rows[cost_key] = entries
        portfolio_results[period_name] = rows

    historical_gate_passed = True
    for period in ("walk_forward", "holdout_2025_plus"):
        for side_cost in weekly.SIDE_COSTS:
            metrics = portfolio_results[period][f"{side_cost:.4f}"][MODEL_LIQUIDITY]
            historical_gate_passed &= (
                metrics["cagr_pct"] >= 50
                and metrics["max_drawdown_adverse_hourly_pct"] <= 10
            )
    if historical_gate_passed:
        decision = (
            "A ablação passou o gate retrospectivo congelado; a série pode ter revisões e o histórico de preços já foi visto. "
            "É preciso acumular confirmação em paper com snapshots ponto-no-tempo e custos reais antes de considerar operar."
        )
    else:
        decision = (
            "A liquidez agregada de stablecoins não atingiu simultaneamente os limites retrospectivos congelados. "
            "Registrar este modelo como rejeitado ou inconclusivo conforme o erro preditivo e o PnL; não retunar esta amostra."
        )

    created = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    feature_identity = _sha_bytes(json.dumps(
        feature_ledger, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8"))
    result = {
        "created_utc": created,
        "deployable": False,
        "goal_achieved": False,
        "historical_gate_passed": bool(historical_gate_passed),
        "decision": decision,
        "universe": list(weekly.SYMBOLS),
        "tradable_market": "Binance Spot only",
        "stablecoins_traded": False,
        "other_products_traded": False,
        "model_names": list(MODELS),
        "schedule": {
            "first_market_boundary_utc": _iso(boundaries[0]),
            "first_common_forecast_utc": _iso(boundaries[first_forecast_index]),
            "terminal_utc": _iso(boundaries[-1]),
            "final_holdout_start_utc": _iso(boundaries[holdout_index]),
            "first_forecast_index": first_forecast_index,
            "terminal_index": terminal_index,
            "week_count": len(boundaries) - 1,
            "hourly_rows_common": sum(
                1 for timestamp in range(boundaries[0], boundaries[-1] + weekly.HOUR_MS,
                                         weekly.HOUR_MS)
                if all(timestamp in bars_by_symbol[symbol] for symbol in weekly.SYMBOLS)
            ),
            "binance_archive_count": len(manifest),
            "archive_manifest_sha256": archive_hash,
        },
        "stablecoin_source": {
            **supply_counts,
            "url": SOURCE_URL,
            "acquired_utc": ACQUIRED_UTC,
            "payload_bytes": len(payload),
            "payload_sha256": payload_hash,
            "field": "totalCirculatingUSD.peggedUSD",
            "first_observation_utc": _iso(supply_rows[0][0]),
            "last_observation_utc": _iso(supply_rows[-1][0]),
            "publication_lag_hours": PUBLICATION_LAG_HOURS,
            "maximum_reference_age_hours": MAX_REFERENCE_AGE_HOURS,
            "historical_vintages_available": False,
        },
        "feature_ledger": feature_ledger,
        "feature_status_counts": feature_status_counts,
        "feature_ledger_sha256": feature_identity,
        "fit_audits": fit_audits,
        "forecast_scores": scores,
        "portfolio_results": portfolio_results,
        "integrity": {
            "protocol_sha256": _sha_file(PROTOCOL_PATH),
            "sources_sha256": _sha_file(SOURCES_PATH),
            "script_sha256": _sha_file(SCRIPT_PATH),
            "weekly_helper_sha256": _sha_file(WEEKLY_HELPER_PATH),
            "raw_payload_sha256": payload_hash,
            "stablecoin_feature_ledger_sha256": feature_identity,
        },
        "runtime": {"python": platform.python_version(),
                    "scikit_learn": sklearn.__version__,
                    "argv": sys.argv},
    }

    INPUTS_PATH.write_text(json.dumps({
        "protocol_sha256": result["integrity"]["protocol_sha256"],
        "sources_sha256": result["integrity"]["sources_sha256"],
        "script_sha256": result["integrity"]["script_sha256"],
        "weekly_helper_sha256": result["integrity"]["weekly_helper_sha256"],
        "stablecoin_payload_sha256": payload_hash,
        "stablecoin_feature_ledger_sha256": feature_identity,
        "binance_manifest_sha256": archive_hash,
        "schedule": result["schedule"],
    }, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    forecast_rows = []
    for row in forecasts:
        forecast_rows.append(row)
    weekly.write_csv(FORECASTS_PATH, forecast_rows, [
        "index", "signal_timestamp_ms", "signal_timestamp_utc", "signal_sunday_utc",
        "exit_timestamp_ms", "exit_timestamp_utc", "symbol", "model", "prediction",
        "actual", "training_mean", "training_count", "training_last_completed_exit_ms",
        "feature_count", "stablecoin_supply_log_change_7d",
        "stablecoin_supply_log_change_30d",
    ])
    feature_rows = []
    for entry in feature_ledger:
        provenance = entry["provenance"]
        feature_rows.append({
            "index": entry["index"], "signal_timestamp_ms": entry["signal_timestamp_ms"],
            "signal_timestamp_utc": entry["signal_timestamp_utc"],
            "status": provenance.get("status"),
            "feature_cutoff_utc": provenance.get("feature_cutoff_utc"),
            "observation_utc": provenance.get("observation_utc"),
            "observation_age_at_cutoff_hours": provenance.get("observation_age_at_cutoff_hours"),
            "supply_usd": provenance.get("supply_usd"),
            "change_7d": (entry["features"] or {}).get("stablecoin_supply_log_change_7d"),
            "reference_7d": provenance.get("lookbacks", {}).get("7", {}).get("observation_utc"),
            "change_30d": (entry["features"] or {}).get("stablecoin_supply_log_change_30d"),
            "reference_30d": provenance.get("lookbacks", {}).get("30", {}).get("observation_utc"),
        })
    weekly.write_csv(FEATURES_PATH, feature_rows, [
        "index", "signal_timestamp_ms", "signal_timestamp_utc", "status",
        "feature_cutoff_utc", "observation_utc", "observation_age_at_cutoff_hours",
        "supply_usd", "change_7d", "reference_7d", "change_30d", "reference_30d",
    ])
    weekly.write_csv(FILLS_PATH, fill_rows, [
        "period", "mode", "model", "side_cost", "timestamp_utc", "symbol", "side",
        "price", "quantity", "notional", "fee", "prediction", "threshold",
    ])

    JSON_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                                    allow_nan=False, default=_json_default) + "\n",
                         encoding="utf-8")
    REPORT_PATH.write_text(_render_report(result), encoding="utf-8")
    print(json.dumps({
        "report": str(REPORT_PATH), "results": str(JSON_PATH),
        "inputs": str(INPUTS_PATH), "payload_sha256": payload_hash,
        "historical_gate_passed": result["historical_gate_passed"],
        "goal_achieved": result["goal_achieved"],
        "forecast_scores": scores,
        "portfolio_results": portfolio_results,
    }, ensure_ascii=True, indent=2, default=_json_default))
    return result


if __name__ == "__main__":
    run()
