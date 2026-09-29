"""Reaggregate frozen real-price barrier fills under the per-trade targets."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "results" / "barrier_payoff_research.json"
PROTOCOL = ROOT / "docs" / "barrier_payoff_trade_target_reanalysis_protocol_2026-09-28.md"
OUTPUT = ROOT / "results" / "barrier_payoff_trade_target_reanalysis_20260928.json"
OUTPUT_MD = ROOT / "docs" / "barrier_payoff_trade_target_reanalysis_2026-09-28.md"
MIN_TRADES = 30


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _trades(scenario: dict) -> list[dict]:
    metrics = scenario["metrics"]
    entries, exits = {}, {}
    for event in metrics["trade_events"]:
        entry_ms = event.get("entry_ms")
        if event["action"] == "enter":
            if entry_ms in entries:
                raise ValueError(f"duplicate entry event at {entry_ms}")
            entries[entry_ms] = event
        elif event["action"] == "exit":
            if entry_ms in exits:
                raise ValueError(f"duplicate exit event at {entry_ms}")
            exits[entry_ms] = event
        else:
            raise ValueError("unknown barrier fill action")
    if set(entries) != set(exits) or len(entries) != metrics["entries"]:
        raise ValueError("barrier entry/exit ledger does not pair with scenario entries")

    output = []
    for entry_ms, entry in sorted(entries.items()):
        exit_event = exits[entry_ms]
        notional = float(entry["notional"])
        net_pnl = float(exit_event["price_pnl"]) - float(entry["fee"]) - float(exit_event["fee"])
        if notional <= 0 or not math.isfinite(net_pnl):
            raise ValueError("invalid barrier operation notional or PnL")
        output.append({"entry_ms": entry_ms, "exit_ms": exit_event["bar_open_ms"],
                       "entry_notional": notional, "gross_pnl": float(exit_event["price_pnl"]),
                       "net_pnl": net_pnl, "net_return_pct": 100 * net_pnl / notional,
                       "gross_return_pct": 100 * float(exit_event["price_pnl"]) / notional,
                       "entry_fee": float(entry["fee"]), "exit_fee": float(exit_event["fee"]),
                       "exit_reason": exit_event["reason"], "ambiguous_bar": bool(exit_event["ambiguous_bar"])})

    return output


def _summary(trades: list[dict], scenario: dict | None = None) -> dict:
    returns = [row["net_return_pct"] for row in trades]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    mean_win = fmean(wins) if wins else None
    mean_loss = fmean(losses) if losses else None
    result = {"trades": len(trades), "wins": len(wins), "losses": len(losses),
              "zero_return_trades": len(returns) - len(wins) - len(losses),
              "win_rate_pct": 100 * len(wins) / len(trades) if trades else None,
              "net_payoff_ratio": mean_win / abs(mean_loss) if mean_win is not None and mean_loss is not None else None,
              "ev_net_pct_per_trade_on_entry_notional": fmean(returns) if returns else None,
              "mean_win_pct": mean_win, "mean_loss_pct": mean_loss,
              "gross_ev_pct_per_trade_on_entry_notional": fmean(row["gross_return_pct"] for row in trades) if trades else None,
              "exit_reasons": dict(Counter(row["exit_reason"] for row in trades)),
              "ambiguous_exits": sum(row["ambiguous_bar"] for row in trades)}
    if scenario is not None:
        metrics = scenario["metrics"]
        reconciled_return = math.fsum(row["net_pnl"] for row in trades)
        if abs(reconciled_return - metrics["return_pct"] / 100) > 1e-8:
            raise ValueError("paired trade PnL does not reconcile to the source portfolio return")
        result.update({"portfolio_return_pct": metrics["return_pct"],
                       "max_drawdown_pct": metrics["max_drawdown_pct"],
                       "adverse_drawdown_bound_pct": metrics["adverse_intrahour_drawdown_bound_pct"],
                       "passes_gates": result["trades"] >= MIN_TRADES and
                           result["win_rate_pct"] is not None and result["win_rate_pct"] >= 70 and
                           result["net_payoff_ratio"] is not None and result["net_payoff_ratio"] >= 1 and
                           result["ev_net_pct_per_trade_on_entry_notional"] is not None and
                           result["ev_net_pct_per_trade_on_entry_notional"] > 1.2 and
                           metrics["max_drawdown_pct"] <= 10 and
                           metrics["adverse_intrahour_drawdown_bound_pct"] <= 10})
    return result


def _run() -> dict:
    source_report = json.loads(SOURCE.read_text(encoding="utf-8"))
    summaries, by_year, ledger = [], {}, []
    for scenario in source_report["scenarios"]:
        trades = _trades(scenario)
        result = {key: scenario[key] for key in ("model", "mode", "side_cost", "allocation", "period", "status")}
        result["metrics"] = _summary(trades, scenario)
        summaries.append(result)
        if scenario["period"] == "later":
            years = defaultdict(list)
            for trade in trades:
                year = datetime.fromtimestamp(trade["entry_ms"] / 1000, timezone.utc).year
                years[str(year)].append(trade)
                ledger.append({"model": scenario["model"], "mode": scenario["mode"],
                               "side_cost": scenario["side_cost"], "allocation": scenario["allocation"],
                               "period": scenario["period"], **trade})
            by_year["|".join(str(result[key]) for key in ("model", "side_cost", "allocation"))] = {
                year: _summary(rows) for year, rows in sorted(years.items())}

    passes = [row for row in summaries if row["period"] == "later" and row["metrics"]["passes_gates"]]
    report = {"created_utc": datetime.now(timezone.utc).isoformat(),
              "source_report_sha256": _sha(SOURCE),
              "source_input_manifest_sha256": source_report["inputs_file_sha256"],
              "protocol_sha256": _sha(PROTOCOL),
              "analysis_code_sha256": _sha(Path(__file__)),
              "operation_definition": "one complete spot entry/exit pair; net return after entry and exit fees, divided by entry notional",
              "minimum_trade_count": MIN_TRADES,
              "historical_data_window": source_report["inputs"]["config"]["periods"],
              "scenarios": summaries, "later_period_by_entry_year": by_year,
              "passing_later_scenarios": passes,
              "goal_found": bool(passes),
              "limits": ["This is a reaggregation of a previously inspected real-price replay, not new validation.",
                         "The source strategy is BTCUSDT Spot long-only; no futures shorts are represented.",
                         "The original model/entry decisions and execution assumptions are unchanged.",
                         "The adverse drawdown bound uses the source replay's conservative full-bar mark."]}
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")

    lines = ["# Recontagem do replay de barreiras pelas metas por operação", "",
             "Este relatório reagrupa os fills reais arquivados no replay BTCUSDT Spot, sem recalcular sinais ou posições. EV e payoff são líquidos de taxas de entrada e saída, sobre o notional inicial.", "",
             "| Modelo | Período | Custo/lado | Alocação | Trades | Acerto | Payoff | EV/trade | DD | DD adverso | Gates |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for row in summaries:
        m = row["metrics"]
        if row["period"] != "later":
            continue
        def fmt(value, suffix=""):
            return "n/a" if value is None else f"{value:.2f}{suffix}"
        lines.append(f"| {row['model']} | {row['period']} | {100*row['side_cost']:.2f}% | {row['allocation']:.0%} | {m['trades']} | {fmt(m['win_rate_pct'],'%')} | {fmt(m['net_payoff_ratio'])} | {fmt(m['ev_net_pct_per_trade_on_entry_notional'],'%')} | {fmt(m['max_drawdown_pct'],'%')} | {fmt(m['adverse_drawdown_bound_pct'],'%')} | {'PASS' if m['passes_gates'] else 'fail'} |")
    lines += ["", "## Conclusão", "",
              f"Cenários posteriores que passaram todos os gates: {len(passes)} de {sum(row['period']=='later' for row in summaries)}.",
              "Os retornos por operação são retrospectivos. Nenhum cenário passa a ser candidato confirmado por esta recontagem.", "",
              f"Hash do replay-fonte `{report['source_report_sha256']}`; protocolo `{report['protocol_sha256']}`; código `{report['analysis_code_sha256']}`.", ""]
    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(json.dumps({"later_scenarios": sum(row["period"] == "later" for row in summaries),
                      "passing_scenarios": len(passes),
                      "hgb_later": [row for row in summaries if row["model"] == "hgb" and row["period"] == "later"],
                      "outputs": [str(OUTPUT), str(OUTPUT_MD)]}, indent=2), flush=True)
    return report


if __name__ == "__main__":
    _run()
