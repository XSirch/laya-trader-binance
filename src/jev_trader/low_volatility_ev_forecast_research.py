"""Walk-forward expected-return gate for the low-volatility beta-hedged futures rule."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from sklearn.ensemble import HistGradientBoostingRegressor

from . import broad_trade_reanalysis as episode_engine
from .binance_data import utc_ms
from .broad_data import load
from .broad_prediction import FIELDS
from .broad_research import DAY_MS, PERIODS, features, sign, target_weights
from .cli import RESULTS
from .target50_research import _offline_inputs

ROOT = Path(__file__).resolve().parents[2]
SOURCE_LEDGER = RESULTS / "broad_trade_ledger_20260927.csv"
SOURCE_REANALYSIS = RESULTS / "broad_trade_target_reanalysis_20260927.json"
SOURCE_SCREEN = RESULTS / "broad_research.json"
OUTPUT = RESULTS / "low_volatility_ev_forecast_20260928.json"
OUTPUT_CSV = RESULTS / "low_volatility_ev_forecast_ledger_20260928.csv"
OUTPUT_MD = ROOT / "docs" / "low_volatility_ev_forecast_research_2026-09-28.md"
PROTOCOL = ROOT / "docs" / "low_volatility_ev_forecast_protocol_2026-09-28.md"
COSTS = {"base": 0.001, "stress": 0.0015}
MIN_TRAINING_EPISODES = 100
TRAINING_WEEKS = 104
WEEK_MS = 7 * DAY_MS
GROSS_PER_SIDE = 0.25
PREDICTED_EV_THRESHOLD_PCT = 1.2


def _vector(row: dict) -> list[float]:
    return [float(row["features"][name]) for name in FIELDS] + [float(row["direction"])]


def _training_rows(states: dict, periods: dict) -> tuple[list[dict], dict]:
    period_ends = {name: utc_ms(dates[1]) for name, dates in periods.items()}
    output, seen = [], set()
    dropped = {"combined": 0, "proxy_exit": 0, "period_terminal": 0,
               "missing_features": 0, "zero_return": 0, "duplicate": 0}
    with SOURCE_LEDGER.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["factor"] != "low_volatility30_betahedged" or row["cost"] != "stress":
                continue
            period = row["period"]
            if period == "combined":
                dropped["combined"] += 1
                continue
            symbol = row["symbol"]
            entry_ms, exit_ms = int(row["entry_ms"]), int(row["exit_ms"])
            if row["unresolved_proxy_exit"] == "True":
                dropped["proxy_exit"] += 1
                continue
            if row["exit_reason"] == "signal_flat_or_terminal" and exit_ms == period_ends[period]:
                dropped["period_terminal"] += 1
                continue
            net_return = float(row["net_return_pct_on_entry_notional"])
            if not math.isfinite(net_return) or net_return == 0:
                dropped["zero_return"] += 1
                continue
            direction = int(row["direction"])
            key = (symbol, entry_ms, exit_ms, direction)
            if key in seen:
                dropped["duplicate"] += 1
                continue
            state = states.get(symbol, {}).get(entry_ms)
            if state is None:
                dropped["missing_features"] += 1
                continue
            seen.add(key)
            output.append({"symbol": symbol, "direction": direction, "entry_ms": entry_ms,
                           "exit_ms": exit_ms, "net_return_pct": net_return,
                           "features": {field: float(state[field]) for field in FIELDS}})
    output.sort(key=lambda row: (row["entry_ms"], row["symbol"], row["direction"]))
    return output, dropped


def _fit_model(history: list[dict]) -> HistGradientBoostingRegressor | None:
    if len(history) < MIN_TRAINING_EPISODES:
        return None
    model = HistGradientBoostingRegressor(max_iter=100, learning_rate=0.05,
                                           max_leaf_nodes=7, min_samples_leaf=15,
                                           l2_regularization=2.0, early_stopping=False,
                                           random_state=2026)
    model.fit([_vector(row) for row in history], [row["net_return_pct"] for row in history])
    return model


def _policy_for_period(states: dict, training: list[dict], start: str, end: str) -> tuple[dict, dict, list[dict]]:
    start_ms, end_ms = utc_ms(start), utc_ms(end)
    policy: dict[int, dict[str, float]] = {}
    prediction_map: dict[tuple[str, int, int], float] = {}
    audit = []
    held: dict[str, int] = {}

    for timestamp in range(start_ms, end_ms, DAY_MS):
        if datetime.fromtimestamp(timestamp / 1000, timezone.utc).weekday() != 0:
            continue
        current = {symbol: rows[timestamp] for symbol, rows in states.items() if timestamp in rows}
        base_targets = target_weights(current, "low_volatility30_betahedged")
        history = [row for row in training
                   if timestamp - TRAINING_WEEKS * WEEK_MS <= row["entry_ms"]
                   and row["exit_ms"] < timestamp]
        model = _fit_model(history)
        accepted: dict[str, int] = {}
        predictions = {}
        if model is not None and base_targets:
            for symbol, weight in sorted(base_targets.items()):
                direction = sign(weight)
                if held.get(symbol) == direction:
                    accepted[symbol] = direction
                    continue
                state = current.get(symbol)
                if state is None:
                    continue
                vector = [float(state[name]) for name in FIELDS] + [float(direction)]
                forecast = float(model.predict([vector])[0])
                predictions[symbol] = forecast
                if forecast >= PREDICTED_EV_THRESHOLD_PCT:
                    accepted[symbol] = direction
                    prediction_map[(symbol, timestamp, direction)] = forecast

        longs = sorted(symbol for symbol, direction in accepted.items() if direction > 0)
        shorts = sorted(symbol for symbol, direction in accepted.items() if direction < 0)
        if longs and shorts:
            weights = {symbol: GROSS_PER_SIDE / len(longs) for symbol in longs}
            weights.update({symbol: -GROSS_PER_SIDE / len(shorts) for symbol in shorts})
            policy[timestamp] = weights
            held = accepted
        else:
            policy[timestamp] = {}
            held = {}
        audit.append({"decision_ms": timestamp, "training_episodes": len(history),
                      "training_mean_return_pct": (sum(row["net_return_pct"] for row in history) / len(history)
                                                   if history else None),
                      "model_available": model is not None, "base_legs": len(base_targets),
                      "predicted_net_return_pct": predictions, "accepted_legs": len(policy[timestamp]),
                      "accepted_longs": len(longs) if policy[timestamp] else 0,
                      "accepted_shorts": len(shorts) if policy[timestamp] else 0})
    return policy, prediction_map, audit


def _simulate(data, states: dict, policy: dict[int, dict[str, float]], start: str, end: str,
              side_cost: float) -> tuple[list[dict], dict]:
    def policy_targets(current_state, factor):
        if factor != "low_volatility30_betahedged" or not current_state:
            return {}
        timestamp = next(iter(current_state.values()))["latest_observed_close_ms"]
        return policy.get(timestamp, {})

    from unittest.mock import patch
    with patch.object(episode_engine, "target_weights", policy_targets):
        return episode_engine._simulate_episodes(
            data, states, "low_volatility30_betahedged", start, end, side_cost)


def _gates(metrics: dict) -> dict:
    return {
        "win_rate_at_least_70_pct": metrics["win_rate_pct"] is not None and metrics["win_rate_pct"] >= 70,
        "payoff_at_least_1_to_1": metrics["net_payoff_ratio"] is not None and metrics["net_payoff_ratio"] >= 1,
        "ev_above_1_2_pct": (metrics["ev_net_pct_per_episode_on_entry_notional"] is not None and
                             metrics["ev_net_pct_per_episode_on_entry_notional"] > 1.2),
        "drawdown_at_most_10_pct": metrics["portfolio_replay"]["max_drawdown_pct"] <= 10,
        "at_least_30_episodes": metrics["episodes"] >= 30,
        "resolved_exits_only": metrics["unresolved_proxy_episodes"] == 0,
    }


def _run() -> dict:
    prior = json.loads(SOURCE_REANALYSIS.read_text(encoding="utf-8"))
    screen = json.loads(SOURCE_SCREEN.read_text(encoding="utf-8"))
    with _offline_inputs():
        data, manifest, _ = load()
    states = features(data)
    training, dropped = _training_rows(states, PERIODS)
    if not training:
        raise ValueError("no complete historical episode labels for EV regression")

    report = {"created_utc": datetime.now(timezone.utc).isoformat(),
              "hypothesis": "walk-forward HGB regression forecasts net return of low_volatility30_betahedged episodes",
              "base_rule": "low_volatility30_betahedged",
              "model": {"type": "HistGradientBoostingRegressor", "max_iter": 100,
                        "learning_rate": 0.05, "max_leaf_nodes": 7, "min_samples_leaf": 15,
                        "l2_regularization": 2.0, "early_stopping": False, "random_state": 2026},
              "fixed_predicted_return_threshold_pct": PREDICTED_EV_THRESHOLD_PCT,
              "minimum_training_episodes": MIN_TRAINING_EPISODES,
              "training_window_weeks": TRAINING_WEEKS,
              "reallocated_gross_per_side": GROSS_PER_SIDE,
              "label_metric_basis": "complete baseline episode net return on initial episode notional at 0.15% side cost",
              "selection_bias": "Exploratory candidate selected after prior historical metrics were inspected; all score periods have been seen at coarser strategy level.",
              "source_ledger_sha256": hashlib.sha256(SOURCE_LEDGER.read_bytes()).hexdigest(),
              "source_reanalysis_sha256": hashlib.sha256(SOURCE_REANALYSIS.read_bytes()).hexdigest(),
              "source_screen_sha256": hashlib.sha256(SOURCE_SCREEN.read_bytes()).hexdigest(),
              "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
              "analysis_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "source_manifest_sha256": screen["source_manifest_sha256"],
              "input_manifest_entries": len(manifest), "historical_training_episodes": len(training),
              "dropped_training_rows": dropped, "periods": {}, "limits": [
                  "The outcome periods were previously inspected for related strategy variants; this is not a fresh market holdout.",
                  "Predicted net returns are model estimates, not calibrated probabilities or guarantees.",
                  "EV uses entry notional per episode; portfolio drawdown and sleeves follow the existing engine.",
                  "Episodes across symbols can overlap in calendar time and share market-wide risk.",
                  "No future live-order evidence is included."]}

    ledger = []
    period_names = ("validation_2024", "calibration_2025h1", "validation_2025h2",
                    "confirmation_2026", "combined")
    for period in period_names:
        start, end = PERIODS[period]
        policy, predictions, audit = _policy_for_period(states, training, start, end)
        section = {"weekly_decisions": audit, "by_cost": {}}
        for cost_name, cost in COSTS.items():
            episodes, portfolio = _simulate(data, states, policy, start, end, cost)
            metrics = episode_engine._summarize(episodes)
            metrics["portfolio_replay"] = portfolio
            metrics["goal_gates"] = _gates(metrics)
            for episode in episodes:
                forecast = predictions.get((episode["symbol"], episode["entry_ms"], episode["direction"]))
                ledger.append({"period": period, "cost": cost_name, **episode,
                               "predicted_net_return_pct": forecast})
            if abs(math.fsum(row["net_pnl"] for row in episodes) - portfolio["return_pct"] / 100) > 1e-8:
                raise ValueError(f"episode PnL does not reconcile: {period}/{cost_name}")
            baseline = prior["periods"][period]["low_volatility30_betahedged"]["by_cost"][cost_name]
            section["by_cost"][cost_name] = {"baseline": baseline,
                                              "filtered": metrics,
                                              "baseline_drawdown_pct": baseline["portfolio_replay"]["max_drawdown_pct"]}
        report["periods"][period] = section

    for period in ("validation_2025h2", "confirmation_2026"):
        report["periods"][period]["strict_goal_gates"] = report["periods"][period]["by_cost"]["stress"]["filtered"]["goal_gates"]
    report["combined_drawdown_at_most_10_pct"] = (
        report["periods"]["combined"]["by_cost"]["stress"]["filtered"]["portfolio_replay"]["max_drawdown_pct"] <= 10)
    report["passes_all_primary_gates"] = (
        all(all(report["periods"][period]["strict_goal_gates"].values())
            for period in ("validation_2025h2", "confirmation_2026")) and
        report["combined_drawdown_at_most_10_pct"])

    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    fields = ["period", "cost", "symbol", "direction", "entry_ms", "exit_ms", "entry_price", "exit_price",
              "hold_days", "entry_notional", "price_pnl", "funding_pnl", "fees", "net_pnl",
              "net_return_pct_on_entry_notional", "predicted_net_return_pct", "exit_reason", "unresolved_proxy_exit"]
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(ledger)

    lines = ["# Resultado: regressão de EV para a regra de baixa volatilidade", "",
             f"O HGB regressor previu retorno líquido por operação e aceitou apenas previsões >= {PREDICTED_EV_THRESHOLD_PCT:.1f}% do notional. O treino foi walk-forward: só operações encerradas antes de cada segunda-feira UTC entraram no ajuste. Este teste reaproveita uma regra escolhida após inspeção histórica, portanto é exploratório.", "",
             "| Regra | Validação H2/2025 | Confirmação jan-jul/2026 | Combinado jan/2024-jul/2026 |", "|---|---|---|---|"]
    for label, key in (("Regra-base", "baseline"), ("HGB com gate de EV previsto", "filtered")):
        cells = []
        for period in ("validation_2025h2", "confirmation_2026", "combined"):
            metrics = report["periods"][period]["by_cost"]["stress"][key]
            payoff = metrics.get("net_payoff_ratio")
            cells.append(f"n={metrics['episodes']}; acerto {metrics.get('win_rate_pct') or 0:.1f}%; payoff {payoff if payoff is not None else 'n/a'}; EV {metrics.get('ev_net_pct_per_episode_on_entry_notional')}; DD {metrics['portfolio_replay']['max_drawdown_pct']:.2f}%")
        lines.append(f"| {label} | {cells[0]} | {cells[1]} | {cells[2]} |")
    lines += ["", "## Decisão", "",
              "Todos os gates primários passaram." if report["passes_all_primary_gates"] else
              "A regressão não passou todos os gates congelados. Mesmo se alguma janela isolada passar, não é evidência prospectiva porque estes períodos e a regra-base já foram vistos.",
              "Nenhuma ordem real ou chamada JEV foi feita.", "",
              f"Protocolo SHA-256 `{report['protocol_sha256']}`; código `{report['analysis_code_sha256']}`; ledger-fonte `{report['source_ledger_sha256']}`.",
              f"Ledger gerado: `results/{OUTPUT_CSV.name}`.", ""]
    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(json.dumps({"passes_all_primary_gates": report["passes_all_primary_gates"],
                      "historical_training_episodes": len(training),
                      "periods": {period: {cost: {key: report["periods"][period]["by_cost"][cost]["filtered"].get(key)
                                                          for key in ("episodes", "win_rate_pct", "net_payoff_ratio",
                                                                      "ev_net_pct_per_episode_on_entry_notional")}
                                                       for cost in COSTS}
                                for period in ("validation_2025h2", "confirmation_2026", "combined")},
                      "outputs": [str(OUTPUT), str(OUTPUT_CSV), str(OUTPUT_MD)]}, indent=2), flush=True)
    return report


if __name__ == "__main__":
    _run()
