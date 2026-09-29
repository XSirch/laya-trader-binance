"""Exploratory short-only portfolio from the fixed low-volatility EV forecaster."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from . import low_volatility_ev_forecast_research as ev_engine
from .broad_data import load
from .broad_research import DAY_MS, PERIODS, features, sign, target_weights
from .cli import RESULTS
from .target50_research import _offline_inputs

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = RESULTS / "low_volatility_short_only_20260928.json"
OUTPUT_CSV = RESULTS / "low_volatility_short_only_ledger_20260928.csv"
OUTPUT_MD = ROOT / "docs" / "low_volatility_short_only_research_2026-09-28.md"
PROTOCOL = ROOT / "docs" / "low_volatility_short_only_protocol_2026-09-28.md"
GROSS_SHORT = 0.25
COSTS = {"base": 0.001, "stress": 0.0015}


def _policy_for_period(states: dict, training: list[dict], start: str, end: str) -> tuple[dict, list[dict]]:
    start_ms, end_ms = ev_engine.utc_ms(start), ev_engine.utc_ms(end)
    policy, audit = {}, []
    held: dict[str, int] = {}
    for timestamp in range(start_ms, end_ms, DAY_MS):
        if datetime.fromtimestamp(timestamp / 1000, timezone.utc).weekday() != 0:
            continue
        current = {symbol: rows[timestamp] for symbol, rows in states.items() if timestamp in rows}
        base_targets = target_weights(current, "low_volatility30_betahedged")
        history = [row for row in training
                   if timestamp - ev_engine.TRAINING_WEEKS * ev_engine.WEEK_MS <= row["entry_ms"]
                   and row["exit_ms"] < timestamp]
        model = ev_engine._fit_model(history)
        accepted, predictions = {}, {}
        if model is not None:
            for symbol, weight in sorted(base_targets.items()):
                direction = sign(weight)
                if direction >= 0:
                    continue
                if held.get(symbol) == direction:
                    accepted[symbol] = direction
                    continue
                state = current.get(symbol)
                if state is None:
                    continue
                vector = [float(state[name]) for name in ev_engine.FIELDS] + [float(direction)]
                forecast = float(model.predict([vector])[0])
                predictions[symbol] = forecast
                if forecast >= ev_engine.PREDICTED_EV_THRESHOLD_PCT:
                    accepted[symbol] = direction
        if accepted:
            policy[timestamp] = {symbol: -GROSS_SHORT / len(accepted) for symbol in accepted}
            held = accepted
        else:
            policy[timestamp] = {}
            held = {}
        audit.append({"decision_ms": timestamp, "training_episodes": len(history),
                      "model_available": model is not None, "base_short_candidates": sum(
                          sign(weight) < 0 for weight in base_targets.values()),
                      "predicted_net_return_pct": predictions, "accepted_short_legs": len(policy[timestamp])})
    return policy, audit


def _run() -> dict:
    prior = json.loads((RESULTS / "low_volatility_ev_forecast_20260928.json").read_text(encoding="utf-8"))
    with _offline_inputs():
        data, manifest, _ = load()
    states = features(data)
    training, dropped = ev_engine._training_rows(states, PERIODS)
    period_names = ("validation_2024", "calibration_2025h1", "validation_2025h2",
                    "confirmation_2026", "combined")
    report = {"created_utc": datetime.now(timezone.utc).isoformat(),
              "hypothesis": "short-only variant of the fixed low-volatility HGB expected-return gate",
              "selection_bias": "Short direction was selected after its returns were inspected in validation_2025h2 and confirmation_2026.",
              "model": prior["model"], "fixed_predicted_return_threshold_pct": prior["fixed_predicted_return_threshold_pct"],
              "minimum_training_episodes": prior["minimum_training_episodes"],
              "training_window_weeks": prior["training_window_weeks"],
              "short_gross_notional_fraction": GROSS_SHORT,
              "costs_per_side": COSTS, "training_episodes": len(training), "dropped_training_rows": dropped,
              "source_ev_research_sha256": hashlib.sha256((RESULTS / "low_volatility_ev_forecast_20260928.json").read_bytes()).hexdigest(),
              "source_ledger_sha256": hashlib.sha256(ev_engine.SOURCE_LEDGER.read_bytes()).hexdigest(),
              "source_manifest_entries": len(manifest),
              "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
              "analysis_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "periods": {}, "limits": [
                  "This direction was selected after observing the same historical windows.",
                  "Historical results are exploratory and cannot count as independent confirmation.",
                  "Per-trade EV is on entry notional; account drawdown is measured by the portfolio engine.",
                  "A prospective frozen paper period remains necessary."]}
    ledger = []
    for period in period_names:
        start, end = PERIODS[period]
        policy, audit = _policy_for_period(states, training, start, end)
        section = {"weekly_decisions": audit, "by_cost": {}}
        for cost_name, cost in COSTS.items():
            episodes, portfolio = ev_engine._simulate(data, states, policy, start, end, cost)
            metrics = ev_engine.episode_engine._summarize(episodes)
            metrics["portfolio_replay"] = portfolio
            metrics["goal_gates"] = ev_engine._gates(metrics)
            for episode in episodes:
                ledger.append({"period": period, "cost": cost_name, **episode})
            if abs(sum(row["net_pnl"] for row in episodes) - portfolio["return_pct"] / 100) > 1e-8:
                raise ValueError(f"short-only episode PnL does not reconcile: {period}/{cost_name}")
            section["by_cost"][cost_name] = metrics
        report["periods"][period] = section
    for period in ("validation_2025h2", "confirmation_2026"):
        report["periods"][period]["strict_goal_gates"] = report["periods"][period]["by_cost"]["stress"]["goal_gates"]
    combined_dd = report["periods"]["combined"]["by_cost"]["stress"]["portfolio_replay"]["max_drawdown_pct"]
    report["combined_drawdown_at_most_10_pct"] = combined_dd <= 10
    report["passes_all_primary_gates"] = (
        all(all(report["periods"][period]["strict_goal_gates"].values())
            for period in ("validation_2025h2", "confirmation_2026")) and combined_dd <= 10)

    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    fields = ["period", "cost", "symbol", "direction", "entry_ms", "exit_ms", "entry_price", "exit_price",
              "hold_days", "entry_notional", "price_pnl", "funding_pnl", "fees", "net_pnl",
              "net_return_pct_on_entry_notional", "exit_reason", "unresolved_proxy_exit"]
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(ledger)
    lines = ["# Resultado: carteira short-only de baixa volatilidade", "",
             "Este teste exploratório usa o mesmo HGB regressor, janela causal, limiar previsto de 1,2% do notional, custos e motor do filtro de EV. Remove as pernas long e aloca até 25% do patrimônio em posições short.", "",
             "| Período | Custo/lado | Episódios | Acerto | Payoff | EV/trade | DD marcado | Gates |", "|---|---:|---:|---:|---:|---:|---:|---|"]
    for period in ("validation_2025h2", "confirmation_2026", "combined"):
        for cost_name in ("base", "stress"):
            m = report["periods"][period]["by_cost"][cost_name]
            def fmt(value, suffix="%"):
                return "n/a" if value is None else f"{value:.2f}{suffix}"
            lines.append(f"| {period} | {100*COSTS[cost_name]:.2f}% | {m['episodes']} | {fmt(m.get('win_rate_pct'))} | {fmt(m.get('net_payoff_ratio'),'')} | {fmt(m.get('ev_net_pct_per_episode_on_entry_notional'))} | {fmt(m['portfolio_replay']['max_drawdown_pct'])} | {'PASS' if all(m['goal_gates'].values()) else 'fail'} |")
    lines += ["", "## Decisão", "",
              "Todos os gates primários passaram." if report["passes_all_primary_gates"] else
              "A carteira short-only não passou todos os gates congelados. As janelas já foram inspecionadas para escolher a direção; mesmo uma aprovação seria somente geração de hipótese.",
              "Nenhuma ordem real ou chamada JEV foi feita.", "",
              f"Protocolo SHA-256 `{report['protocol_sha256']}`; código `{report['analysis_code_sha256']}`; relatório EV de origem `{report['source_ev_research_sha256']}`.",
              f"Ledger de episódios: `results/{OUTPUT_CSV.name}`.", ""]
    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(json.dumps({"passes_all_primary_gates": report["passes_all_primary_gates"],
                      "periods": {p: {c: {k: report["periods"][p]["by_cost"][c].get(k)
                                           for k in ("episodes", "win_rate_pct", "net_payoff_ratio",
                                                     "ev_net_pct_per_episode_on_entry_notional")}
                                      for c in COSTS}
                                for p in ("validation_2025h2", "confirmation_2026", "combined")},
                      "outputs": [str(OUTPUT), str(OUTPUT_CSV), str(OUTPUT_MD)]}, indent=2), flush=True)
    return report


if __name__ == "__main__":
    _run()
