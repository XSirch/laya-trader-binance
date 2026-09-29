"""Walk-forward classifier that gates new low-volatility-30-betahedged futures episodes."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from sklearn.ensemble import HistGradientBoostingClassifier

from . import broad_trade_reanalysis as episode_engine
from .binance_data import utc_ms
from .broad_data import load
from .broad_prediction import FIELDS
from .broad_research import DAY_MS, PERIODS, evaluate, features, sign, target_weights
from .cli import RESULTS
from .target50_research import _offline_inputs

ROOT = Path(__file__).resolve().parents[2]
SOURCE_LEDGER = RESULTS / "broad_trade_ledger_20260927.csv"
SOURCE_REANALYSIS = RESULTS / "broad_trade_target_reanalysis_20260927.json"
SOURCE_SCREEN = RESULTS / "broad_research.json"
OUTPUT = RESULTS / "low_volatility_meta_filter_research_20260927.json"
OUTPUT_CSV = RESULTS / "low_volatility_meta_filter_ledger_20260927.csv"
OUTPUT_MD = ROOT / "docs" / "low_volatility_meta_filter_research_2026-09-27.md"
PROTOCOL = ROOT / "docs" / "low_volatility_meta_filter_protocol_2026-09-27.md"
COSTS = {"base": 0.001, "stress": 0.0015}
MODEL_THRESHOLD = 0.70
MIN_TRAINING_EPISODES = 100
TRAINING_WEEKS = 104
WEEK_MS = 7 * DAY_MS
GROSS_PER_SIDE = 0.25


def _x(row: dict) -> list[float]:
    return [float(row[name]) for name in FIELDS] + [float(row["direction"])]


def _training_rows(states: dict, periods: dict) -> tuple[list[dict], dict]:
    period_ends = {name: utc_ms(dates[1]) for name, dates in periods.items()}
    output, seen = [], set()
    dropped = {"combined": 0, "proxy_exit": 0, "period_terminal": 0, "missing_features": 0,
               "zero_return": 0, "duplicate": 0}
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
            if net_return == 0:
                dropped["zero_return"] += 1
                continue
            key = (symbol, entry_ms, exit_ms, int(row["direction"]))
            if key in seen:
                dropped["duplicate"] += 1
                continue
            state = states.get(symbol, {}).get(entry_ms)
            if state is None:
                dropped["missing_features"] += 1
                continue
            seen.add(key)
            output.append({
                "symbol": symbol,
                "direction": int(row["direction"]),
                "entry_ms": entry_ms,
                "exit_ms": exit_ms,
                "net_return_pct": net_return,
                "label_win": int(net_return > 0),
                "features": {field: float(state[field]) for field in FIELDS},
            })
    output.sort(key=lambda row: (row["entry_ms"], row["symbol"], row["direction"]))
    return output, dropped


def _fit_model(history: list[dict]) -> HistGradientBoostingClassifier | None:
    labels = {row["label_win"] for row in history}
    if len(history) < MIN_TRAINING_EPISODES or len(labels) < 2:
        return None
    model = HistGradientBoostingClassifier(
        max_iter=100,
        learning_rate=0.05,
        max_leaf_nodes=7,
        min_samples_leaf=15,
        l2_regularization=2.0,
        early_stopping=False,
        random_state=2026,
    )
    model.fit([_x({**row["features"], "direction": row["direction"]}) for row in history],
              [row["label_win"] for row in history])
    return model


def _policy_for_period(states: dict, training: list[dict], start: str, end: str) -> tuple[dict, dict, list[dict]]:
    start_ms, end_ms = utc_ms(start), utc_ms(end)
    policy: dict[int, dict[str, float]] = {}
    probabilities: dict[tuple[str, int, int], float] = {}
    weekly_audit = []
    held: dict[str, int] = {}

    for timestamp in range(start_ms, end_ms, DAY_MS):
        if datetime.fromtimestamp(timestamp / 1000, timezone.utc).weekday() != 0:
            continue
        current_state = {s: rows[timestamp] for s, rows in states.items() if timestamp in rows}
        base_targets = target_weights(current_state, "low_volatility30_betahedged")
        history = [row for row in training
                   if timestamp - TRAINING_WEEKS * WEEK_MS <= row["entry_ms"] and row["exit_ms"] < timestamp]
        model = _fit_model(history)
        accepted: dict[str, int] = {}
        candidate_probabilities = {}
        if model is not None and base_targets:
            positive_index = list(model.classes_).index(1)
            for symbol, weight in sorted(base_targets.items()):
                direction = sign(weight)
                if held.get(symbol) == direction:
                    accepted[symbol] = direction
                    continue
                state = current_state.get(symbol)
                if state is None:
                    continue
                vector = _x({**state, "direction": direction})
                probability = float(model.predict_proba([vector])[0][positive_index])
                candidate_probabilities[symbol] = probability
                if probability >= MODEL_THRESHOLD:
                    accepted[symbol] = direction
                    probabilities[(symbol, timestamp, direction)] = probability

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

        weekly_audit.append({
            "decision_ms": timestamp,
            "training_episodes": len(history),
            "training_win_rate_pct": 100 * sum(row["label_win"] for row in history) / len(history) if history else None,
            "model_available": model is not None,
            "base_legs": len(base_targets),
            "candidate_predictions": candidate_probabilities,
            "accepted_legs": len(policy[timestamp]),
            "accepted_longs": len(longs) if policy[timestamp] else 0,
            "accepted_shorts": len(shorts) if policy[timestamp] else 0,
        })
    return policy, probabilities, weekly_audit


def _simulate(data, states: dict, policy: dict[int, dict[str, float]], start: str, end: str,
              side_cost: float) -> tuple[list[dict], dict]:
    def policy_targets(current_state, factor):
        if factor != "low_volatility30_betahedged" or not current_state:
            return {}
        timestamp = next(iter(current_state.values()))["latest_observed_close_ms"]
        return policy.get(timestamp, {})

    # Reuse the already reconciled daily portfolio and episode accounting. The
    # scoped replacement changes only the target weights for this replay.
    from unittest.mock import patch
    with patch.object(episode_engine, "target_weights", policy_targets):
        episodes, portfolio = episode_engine._simulate_episodes(
            data, states, "low_volatility30_betahedged", start, end, side_cost)
    return episodes, portfolio


def _fmt(value: float | None, signed: bool = True) -> str:
    if value is None:
        return "indefinido"
    return (f"{value:+.2f}%" if signed else f"{value:.2f}%").replace(".", ",")


def _cell(metrics: dict) -> str:
    payoff = metrics["net_payoff_ratio"]
    payoff_s = "indefinido" if payoff is None else f"{payoff:.2f}".replace(".", ",")
    return (f"n={metrics['episodes']}; {metrics['win_rate_pct']:.1f}%".replace(".", ",") +
            f"; payoff {payoff_s}; EV {_fmt(metrics['ev_net_pct_per_episode_on_entry_notional'])}; " +
            f"DD {_fmt(metrics['portfolio_replay']['max_drawdown_pct'], signed=False)}")


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
    training, dropped_training = _training_rows(states, PERIODS)
    if not training:
        raise ValueError("no complete historical episode labels for the classifier")

    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "hypothesis": "walk-forward HistGradientBoosting meta-label for complete low_volatility30_betahedged episode win probability",
        "base_rule": "low_volatility30_betahedged",
        "features": [*FIELDS, "direction"],
        "model": {"type": "HistGradientBoostingClassifier", "max_iter": 100, "learning_rate": 0.05,
                  "max_leaf_nodes": 7, "min_samples_leaf": 15, "l2_regularization": 2.0,
                  "early_stopping": False, "random_state": 2026},
        "fixed_prediction_threshold": MODEL_THRESHOLD,
        "minimum_training_episodes": MIN_TRAINING_EPISODES,
        "training_window_weeks": TRAINING_WEEKS,
        "reallocated_gross_per_side": GROSS_PER_SIDE,
        "label_metric_basis": "complete baseline episode net return on initial episode notional at 0.15% side cost",
        "source_ledger_sha256": hashlib.sha256(SOURCE_LEDGER.read_bytes()).hexdigest(),
        "source_reanalysis_sha256": hashlib.sha256(SOURCE_REANALYSIS.read_bytes()).hexdigest(),
        "source_screen_sha256": hashlib.sha256(SOURCE_SCREEN.read_bytes()).hexdigest(),
        "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        "analysis_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_manifest_sha256": screen["source_manifest_sha256"],
        "input_manifest_entries": len(manifest),
        "historical_training_episodes": len(training),
        "dropped_training_rows": dropped_training,
        "selection_bias": "Exploratory: the low_volatility30_betahedged rule was chosen after its historical per-episode metrics were inspected.",
        "periods": {},
        "limits": [
            "All evaluated historical windows were previously inspected; no future holdout has yet elapsed.",
            "The 0.70 model probability threshold is fixed but HGB probabilities are not calibrated probabilities by construction.",
            "Training labels come from the baseline strategy, while filtering changes which episodes enter; distribution shift is possible.",
            "Daily open execution, assumed fees, adverse daily funding marks, and the historical constituent cohort limit executability.",
            "The rule rebalances weekly and is a candidate signal family, not a replacement for the separate minute JEV paper observer.",
        ],
    }
    all_ledger = []
    for period in ("validation_2024", "calibration_2025h1", "validation_2025h2", "confirmation_2026", "combined"):
        start, end = PERIODS[period]
        policy, probability_map, audit = _policy_for_period(states, training, start, end)
        report["periods"][period] = {"weekly_decisions": audit, "by_cost": {}}
        start_ms, end_ms = utc_ms(start), utc_ms(end)
        for cost_name, cost in COSTS.items():
            episodes, portfolio = _simulate(data, states, policy, start, end, cost)
            metrics = episode_engine._summarize(episodes)
            metrics["portfolio_replay"] = portfolio
            for episode in episodes:
                episode["meta_probability"] = probability_map.get(
                    (episode["symbol"], episode["entry_ms"], episode["direction"]))
                all_ledger.append({
                    "period": period, "cost": cost_name, **episode,
                })
            if abs(math.fsum(row["net_pnl"] for row in episodes) - portfolio["return_pct"] / 100) > 1e-8:
                raise ValueError(f"episode PnL does not reconcile: {period}/{cost_name}")
            source = prior["periods"][period]["low_volatility30_betahedged"]["by_cost"][cost_name]["portfolio_replay"]
            report["periods"][period]["by_cost"][cost_name] = {
                "baseline": prior["periods"][period]["low_volatility30_betahedged"]["by_cost"][cost_name],
                "filtered": {**metrics, "goal_gates_30_episode_screen": _gates(metrics)},
                "baseline_drawdown_pct": source["max_drawdown_pct"],
            }

    for period in ("validation_2025h2", "confirmation_2026", "combined"):
        if period == "combined":
            continue
        stress = report["periods"][period]["by_cost"]["stress"]["filtered"]
        report["periods"][period]["strict_goal_gates"] = _gates(stress)
    stress_combined = report["periods"]["combined"]["by_cost"]["stress"]["filtered"]
    report["combined_drawdown_at_most_10_pct"] = stress_combined["portfolio_replay"]["max_drawdown_pct"] <= 10
    report["passes_all_primary_gates"] = (
        all(report["periods"][p]["strict_goal_gates"][k] for p in ("validation_2025h2", "confirmation_2026")
            for k in ("win_rate_at_least_70_pct", "payoff_at_least_1_to_1", "ev_above_1_2_pct",
                      "drawdown_at_most_10_pct", "at_least_30_episodes", "resolved_exits_only")) and
        report["combined_drawdown_at_most_10_pct"]
    )

    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    fields = ["period", "cost", "symbol", "direction", "entry_ms", "exit_ms", "entry_price", "exit_price",
              "hold_days", "entry_notional", "price_pnl", "funding_pnl", "fees", "net_pnl",
              "net_return_pct_on_entry_notional", "meta_probability", "exit_reason", "unresolved_proxy_exit"]
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_ledger)

    lines = [
        "# Resultado: filtro ML para low_volatility30_betahedged", "",
        "Este teste exploratório aplicou um classificador HGB às novas entradas da regra `low_volatility30_betahedged`. O modelo treinou somente com episódios completos dessa mesma regra encerrados antes da decisão, usando janela móvel de 104 semanas; a entrada nova exigiu probabilidade prevista de vitória líquida >=70%. O candidato-base foi escolhido após inspeção dos resultados históricos, então estas janelas não são holdouts independentes.", "",
        "O custo de estresse é 0,15% por lado. EV representa o PnL líquido médio como percentual do notional inicial por episódio; drawdown é da carteira.", "",
        "| Regra | Validação H2/2025 | Confirmação jan–jul/2026 | Combinado jan/2024–jul/2026 |", "|---|---|---|---|",
    ]
    for label, key in (("low_volatility30_betahedged base", "baseline"),
                       ("low_volatility30_betahedged + filtro HGB", "filtered")):
        cells = []
        for period in ("validation_2025h2", "confirmation_2026", "combined"):
            value = report["periods"][period]["by_cost"]["stress"][key]
            cells.append(_cell(value))
        lines.append(f"| {label} | {cells[0]} | {cells[1]} | {cells[2]} |")
    lines += ["", "## Decisão", "",
              "O filtro passou todos os gates." if report["passes_all_primary_gates"] else
              "O filtro não passou todos os gates de acerto, payoff, EV, amostra e drawdown; confira quais critérios falharam por janela no JSON.",
              "O estudo é retrospectivo e exploratório. A regra-base foi selecionada após olhar métricas históricas, probabilidades HGB não têm calibração comprovada, e nenhum threshold ou hiperparâmetro foi ajustado após este replay.", "",
              "## Integridade e proveniência", "",
              "- Cada previsão usou apenas episódios cuja saída ocorreu estritamente antes do sinal; saídas proxy e posições truncadas no fim da janela não entraram no treino.",
              "- O PnL líquido dos episódios fecha com o retorno da carteira em cada janela e cenário de custo.",
              f"- Protocolo: SHA-256 `{report['protocol_sha256']}`.",
              f"- Ledger-fonte: SHA-256 `{report['source_ledger_sha256']}`; reanálise-fonte `{report['source_reanalysis_sha256']}`.",
              f"- Código do estudo: SHA-256 `{report['analysis_code_sha256']}`.",
              f"- Ledger filtrado: [CSV](../results/{OUTPUT_CSV.name}); previsões e métricas: [JSON](../results/{OUTPUT.name}).", "",
              "Nenhuma ordem real, chamada paga ao JEV ou alteração no paper JEV foi feita.", ""]
    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(json.dumps({"passes_all_primary_gates": report["passes_all_primary_gates"],
                      "historical_training_episodes": len(training),
                      "filtered_episodes": {p: report["periods"][p]["by_cost"]["stress"]["filtered"]["episodes"]
                                            for p in ("validation_2025h2", "confirmation_2026", "combined")},
                      "outputs": [str(OUTPUT), str(OUTPUT_CSV), str(OUTPUT_MD)]}, ensure_ascii=True))
    return report


if __name__ == "__main__":
    _run()
