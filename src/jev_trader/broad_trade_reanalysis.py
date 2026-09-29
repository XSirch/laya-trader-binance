"""Re-aggregate existing broad futures portfolio rules into trade episodes."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from .binance_data import utc_ms
from .broad_data import load
from .broad_research import DAY_MS, PERIODS, evaluate, features, sign, target_weights
from .cli import RESULTS
from .target50_research import _offline_inputs

ROOT = Path(__file__).resolve().parents[2]
SOURCE_REPORT = RESULTS / "broad_research.json"
OUTPUT = RESULTS / "broad_trade_target_reanalysis_20260927.json"
OUTPUT_CSV = RESULTS / "broad_trade_ledger_20260927.csv"
OUTPUT_MD = ROOT / "docs" / "broad_trade_target_reanalysis_2026-09-27.md"
COSTS = {"base": 0.001, "stress": 0.0015}
RECONCILE_FIELDS = {
    "return_pct": "return_pct",
    "max_drawdown_pct": "max_drawdown_pct",
    "fees_pct_initial": "fees_pct_initial",
    "funding_pct_initial": "funding_pct_initial",
}


def _simulate_episodes(data, states, factor: str, start: str, end: str,
                       side_cost: float) -> tuple[list[dict], dict]:
    """Mirror broad_research.evaluate while keeping a per-symbol trade ledger."""
    start_ms, end_ms = utc_ms(start), utc_ms(end)
    bars = {s: {b.open_ms: b for b in values} for s, values in data["klines"].items()}
    marks = {s: {b.open_ms: b for b in values} for s, values in data["markPriceKlines"].items()}
    funding = {s: {} for s in bars}
    for symbol, rows in data["fundingRate"].items():
        for row in rows:
            funding[symbol].setdefault(row.timestamp_ms // DAY_MS * DAY_MS, []).append(row)

    quantity: dict[str, float] = {}
    previous_price: dict[str, float] = {}
    active: dict[str, dict] = {}
    episodes: list[dict] = []
    equity = 1.0
    fees = funding_pnl = 0.0
    path: list[tuple[int, float]] = []
    unresolved_count = 0

    def close_episode(symbol: str, timestamp: int, price: float, reason: str,
                      unresolved: bool = False) -> dict | None:
        row = active.pop(symbol, None)
        if row is None:
            return None
        row.update({
            "exit_ms": timestamp,
            "exit_price": price,
            "exit_reason": reason,
            "unresolved_proxy_exit": unresolved,
            "hold_days": (timestamp - row["entry_ms"]) / DAY_MS,
        })
        row["net_return_pct_on_entry_notional"] = 100 * row["net_pnl"] / row["entry_notional"]
        episodes.append(row)
        return row

    for timestamp in range(start_ms, end_ms + 1, DAY_MS):
        for symbol in list(quantity):
            current_quantity = quantity[symbol]
            bar = bars[symbol].get(timestamp)
            if bar is None:
                prior = bars[symbol].get(timestamp - DAY_MS)
                if prior is None:
                    raise ValueError(f"cannot value unresolved disappearance: {symbol} {timestamp}")
                price_pnl = current_quantity * (prior.close - previous_price[symbol])
                charge = abs(current_quantity) * prior.close * (side_cost + 0.02)
                equity += price_pnl - charge
                active[symbol]["net_pnl"] += price_pnl - charge
                active[symbol]["price_pnl"] += price_pnl
                active[symbol]["fees"] += charge
                close_episode(symbol, timestamp, prior.close, "unresolved_listing_exit_proxy", True)
                quantity.pop(symbol)
                previous_price.pop(symbol, None)
                fees += charge
                unresolved_count += 1
                continue
            price_pnl = current_quantity * (bar.open - previous_price[symbol])
            equity += price_pnl
            active[symbol]["net_pnl"] += price_pnl
            active[symbol]["price_pnl"] += price_pnl
            previous_price[symbol] = bar.open

        path.append((timestamp, equity))
        terminal = timestamp == end_ms
        old_quantity = dict(quantity)
        old_active = dict(active)
        rebalanced = (factor.startswith("reversal1") or
                      datetime.fromtimestamp(timestamp / 1000, timezone.utc).weekday() == 0)
        if rebalanced or terminal:
            current_state = {s: values[timestamp] for s, values in states.items() if timestamp in values}
            targets = target_weights(current_state, factor) if not terminal else {}
            if any(s not in bars or timestamp not in bars[s] for s in targets):
                targets = {s: value for s, value in targets.items() if timestamp in bars[s]}
            starting_equity = equity
            for symbol in sorted(set(quantity) | set(targets)):
                price = bars[symbol][timestamp].open
                desired = targets.get(symbol, 0.0) * starting_equity / price
                previous = quantity.get(symbol, 0.0)
                charge = abs(desired - previous) * price * side_cost
                equity -= charge

                if previous and desired and sign(previous) != sign(desired):
                    close_fee = abs(previous) * price * side_cost
                    open_fee = abs(desired) * price * side_cost
                    old_row = active[symbol]
                    old_row["net_pnl"] -= close_fee
                    old_row["fees"] += close_fee
                    close_episode(symbol, timestamp, price, "signal_reversal")
                    active[symbol] = {
                        "symbol": symbol,
                        "direction": sign(desired),
                        "entry_ms": timestamp,
                        "entry_price": price,
                        "entry_notional": abs(desired) * price,
                        "net_pnl": -open_fee,
                        "price_pnl": 0.0,
                        "fees": open_fee,
                        "funding_pnl": 0.0,
                        "unresolved_proxy_exit": False,
                    }
                elif not previous and desired:
                    active[symbol] = {
                        "symbol": symbol,
                        "direction": sign(desired),
                        "entry_ms": timestamp,
                        "entry_price": price,
                        "entry_notional": abs(desired) * price,
                        "net_pnl": -charge,
                        "price_pnl": 0.0,
                        "fees": charge,
                        "funding_pnl": 0.0,
                        "unresolved_proxy_exit": False,
                    }
                elif previous and not desired:
                    active[symbol]["net_pnl"] -= charge
                    active[symbol]["fees"] += charge
                    close_episode(symbol, timestamp, price, "signal_flat_or_terminal")
                elif previous and desired:
                    active[symbol]["net_pnl"] -= charge
                    active[symbol]["fees"] += charge

                if desired:
                    quantity[symbol], previous_price[symbol] = desired, price
                else:
                    quantity.pop(symbol, None)
                    previous_price.pop(symbol, None)
                fees += charge

        if terminal:
            path[-1] = (timestamp, equity)
            break

        worst_equity = equity
        for symbol, current_quantity in quantity.items():
            bar, mark = bars[symbol][timestamp], marks[symbol][timestamp]
            worst_equity += current_quantity * ((bar.low if current_quantity > 0 else bar.high) - bar.open)
        for symbol in set(old_quantity) | set(quantity):
            mark = marks[symbol].get(timestamp)
            if mark is None:
                continue
            for event in funding[symbol].get(timestamp, []):
                new_scalar = -quantity.get(symbol, 0.0) * event.rate
                old_scalar = -old_quantity.get(symbol, 0.0) * event.rate
                scalar = new_scalar
                recipient = active.get(symbol)
                if event.timestamp_ms - timestamp < 60_000 and old_scalar < new_scalar:
                    scalar = old_scalar
                    recipient = old_active.get(symbol)
                payment = scalar * (mark.low if scalar >= 0 else mark.high)
                equity += payment
                funding_pnl += payment
                worst_equity += min(payment, 0.0)
                if recipient is not None:
                    recipient["net_pnl"] += payment
                    recipient["funding_pnl"] += payment

        if equity <= 0:
            raise ValueError(f"insolvent broad portfolio at {timestamp}")

    peak, drawdown = 1.0, 0.0
    for _, value in path:
        peak = max(peak, value)
        drawdown = max(drawdown, 1 - value / peak)
    portfolio = {
        "return_pct": 100 * (equity - 1),
        "max_drawdown_pct": 100 * drawdown,
        "fees_pct_initial": 100 * fees,
        "funding_pct_initial": 100 * funding_pnl,
        "unresolved_exits": unresolved_count,
    }
    return episodes, portfolio


def _wilson_interval(wins: int, count: int) -> list[float] | None:
    if count == 0:
        return None
    z = 1.959963984540054
    p = wins / count
    denominator = 1 + z * z / count
    center = (p + z * z / (2 * count)) / denominator
    radius = z * math.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / denominator
    return [100 * max(0.0, center - radius), 100 * min(1.0, center + radius)]


def _summarize(episodes: list[dict]) -> dict:
    values = [row["net_return_pct_on_entry_notional"] for row in episodes]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    mean_win = math.fsum(wins) / len(wins) if wins else None
    mean_loss = math.fsum(losses) / len(losses) if losses else None
    payoff = mean_win / abs(mean_loss) if mean_win is not None and mean_loss is not None else None
    return {
        "episodes": len(values),
        "wins": len(wins),
        "losses": len(losses),
        "flats": len(values) - len(wins) - len(losses),
        "win_rate_pct": 100 * len(wins) / len(values) if values else None,
        "win_rate_wilson_95_pct": _wilson_interval(len(wins), len(values)),
        "mean_win_pct": mean_win,
        "mean_loss_pct": mean_loss,
        "net_payoff_ratio": payoff,
        "ev_net_pct_per_episode_on_entry_notional": math.fsum(values) / len(values) if values else None,
        "median_hold_days": (sorted(row["hold_days"] for row in episodes)[len(episodes) // 2]
                             if episodes else None),
        "unresolved_proxy_episodes": sum(row["unresolved_proxy_exit"] for row in episodes),
    }


def _reconcile(actual: dict, expected: dict, factor: str, period: str, cost: str) -> None:
    for ours, theirs in RECONCILE_FIELDS.items():
        difference = abs(actual[ours] - expected[theirs])
        if difference > 1e-8:
            raise ValueError(f"portfolio replay mismatch {factor}/{period}/{cost}/{ours}: {difference}")


def _goal_gates(metrics: dict, minimum_episodes: int = 30) -> dict:
    return {
        "win_rate_at_least_70_pct": metrics["win_rate_pct"] is not None and metrics["win_rate_pct"] >= 70,
        "payoff_at_least_1_to_1": metrics["net_payoff_ratio"] is not None and metrics["net_payoff_ratio"] >= 1,
        "ev_above_1_2_pct": (metrics["ev_net_pct_per_episode_on_entry_notional"] is not None and
                             metrics["ev_net_pct_per_episode_on_entry_notional"] > 1.2),
        "drawdown_at_most_10_pct": metrics["portfolio_replay"]["max_drawdown_pct"] <= 10,
        "minimum_episodes": metrics["episodes"] >= minimum_episodes,
        "resolved_exits_only": metrics["unresolved_proxy_episodes"] == 0,
    }


def _pct(value: float | None, signed: bool = True) -> str:
    if value is None:
        return "indefinido"
    return (f"{value:+.2f}%" if signed else f"{value:.2f}%").replace(".", ",")


def _fmt_cell(metrics: dict) -> str:
    payoff = "indefinido" if metrics["net_payoff_ratio"] is None else f"{metrics['net_payoff_ratio']:.2f}".replace(".", ",")
    return (f"n={metrics['episodes']}; {metrics['win_rate_pct']:.1f}%".replace(".", ",") +
            f"; payoff {payoff}; EV {_pct(metrics['ev_net_pct_per_episode_on_entry_notional'])}; " +
            f"DD {_pct(metrics['portfolio_replay']['max_drawdown_pct'], signed=False)}")


def run() -> dict:
    prior = json.loads(SOURCE_REPORT.read_text(encoding="utf-8"))
    with _offline_inputs():
        data, manifest, cohort = load()
    states = features(data)
    analysis = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "per-episode reaggregation of every existing broad daily futures rule; no signal or parameter changes",
        "metric_basis": "net realized episode PnL divided by initial gross episode notional",
        "costs_per_side": COSTS,
        "candidate_names": sorted(prior["candidates"]),
        "selected_on_2022_2023_in_source": prior["selected_on_2022_2023"],
        "source_report_sha256": hashlib.sha256(SOURCE_REPORT.read_bytes()).hexdigest(),
        "source_manifest_sha256": prior["source_manifest_sha256"],
        "analysis_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "input_manifest_entries": len(manifest),
        "periods": {},
        "limits": [
            "Historical crypto futures data and previously reviewed windows; no untouched future holdout.",
            "An episode spans one same-direction position from entry until flat or sign reversal; same-side weekly rebalances remain in the episode.",
            "Daily open accounting and assumed fees/slippage/funding are not executable fills.",
            "EV is over initial episode notional, not account equity or futures margin; portfolio drawdown is measured separately.",
            "Any unresolved delisting exit uses the source research adverse proxy and is disqualified from a goal pass.",
            "The portfolio's historical constituent cohort is based on available Binance archive history, not a complete point-in-time listing record.",
        ],
    }
    ledger_rows = []
    for period, (start, end) in PERIODS.items():
        analysis["periods"][period] = {}
        for factor in sorted(prior["candidates"]):
            by_cost = {}
            for cost_name, side_cost in COSTS.items():
                episodes, portfolio = _simulate_episodes(data, states, factor, start, end, side_cost)
                source_metrics = evaluate(data, states, factor, start, end, side_cost)
                _reconcile(portfolio, source_metrics, factor, period, cost_name)
                metrics = _summarize(episodes)
                metrics["portfolio_replay"] = portfolio
                metrics["goal_gates_30_episode_screen"] = _goal_gates(metrics)
                by_cost[cost_name] = metrics
                for row in episodes:
                    ledger_rows.append({
                        "factor": factor, "period": period, "cost": cost_name,
                        "symbol": row["symbol"], "direction": row["direction"],
                        "entry_ms": row["entry_ms"], "exit_ms": row["exit_ms"],
                        "entry_price": row["entry_price"], "exit_price": row["exit_price"],
                        "hold_days": row["hold_days"], "entry_notional": row["entry_notional"],
                        "price_pnl": row["price_pnl"], "funding_pnl": row["funding_pnl"],
                        "fees": row["fees"], "net_pnl": row["net_pnl"],
                        "net_return_pct_on_entry_notional": row["net_return_pct_on_entry_notional"],
                        "exit_reason": row["exit_reason"],
                        "unresolved_proxy_exit": row["unresolved_proxy_exit"],
                    })
                if abs(math.fsum(row["net_pnl"] for row in episodes) -
                       (portfolio["return_pct"] / 100)) > 1e-8:
                    raise ValueError(f"episode PnL does not reconcile: {factor}/{period}/{cost_name}")
            analysis["periods"][period][factor] = {"by_cost": by_cost}

    for factor in analysis["candidate_names"]:
        val = analysis["periods"]["validation_2025h2"][factor]["by_cost"]["stress"]
        conf = analysis["periods"]["confirmation_2026"][factor]["by_cost"]["stress"]
        combined = analysis["periods"]["combined"][factor]["by_cost"]["stress"]
        analysis["periods"]["combined"][factor]["candidate_gates"] = {
            "validation_2025h2": _goal_gates(val),
            "confirmation_2026": _goal_gates(conf),
            "combined_drawdown_at_most_10_pct": combined["portfolio_replay"]["max_drawdown_pct"] <= 10,
            "all_gates_both_windows_and_combined_drawdown": all(_goal_gates(val).values()) and
                all(_goal_gates(conf).values()) and combined["portfolio_replay"]["max_drawdown_pct"] <= 10,
        }

    OUTPUT.write_text(json.dumps(analysis, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    fields = ["factor", "period", "cost", "symbol", "direction", "entry_ms", "exit_ms", "entry_price",
              "exit_price", "hold_days", "entry_notional", "price_pnl", "funding_pnl", "fees", "net_pnl",
              "net_return_pct_on_entry_notional", "exit_reason", "unresolved_proxy_exit"]
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(ledger_rows)

    lines = [
        "# Reanálise por operação das regras amplas de futuros", "", "## Resultado", "",
        "Reagrupei as 24 regras já existentes do universo Binance USDT perpétuo; não mudei filtros, sinais, rebalanceamento ou parâmetros. A tabela usa custo de estresse de 0,15% por lado. Cada célula mostra episódios, acerto, payoff, EV líquido por episódio e drawdown da carteira.", "",
        "O payoff é ganho médio líquido dividido pela perda média absoluta. O EV é PnL líquido médio como percentual do notional bruto inicial do episódio. Para a triagem, usei acerto ≥70%, payoff ≥1:1, EV >1,2%, drawdown ≤10%, ao menos 30 episódios e nenhuma saída proxy não resolvida; a regra também precisa manter esses gates nas duas janelas e drawdown combinado ≤10%.", "",
        "| Regra já testada | Validação H2/2025 | Confirmação jan–jul/2026 | Combinado jan/2024–ago/2026 |", "|---|---|---|---|",
    ]
    for factor in analysis["candidate_names"]:
        val = analysis["periods"]["validation_2025h2"][factor]["by_cost"]["stress"]
        conf = analysis["periods"]["confirmation_2026"][factor]["by_cost"]["stress"]
        combined = analysis["periods"]["combined"][factor]["by_cost"]["stress"]
        lines.append(f"| `{factor}` | {_fmt_cell(val)} | {_fmt_cell(conf)} | {_fmt_cell(combined)} |")
    passing = [name for name in analysis["candidate_names"]
               if analysis["periods"]["combined"][name]["candidate_gates"]["all_gates_both_windows_and_combined_drawdown"]]
    lines += ["", "## Decisão", "",
              "Nenhuma regra aprovada nos gates completos." if not passing else
              "Regras que passaram os gates numéricos e de amostra: " + ", ".join(f"`{name}`" for name in passing) + ".",
              "Mesmo um resultado aprovado nesta tabela continua retrospectivo: todas as janelas foram examinadas no programa anterior e a confirmação não é prospectiva. Uma candidata só deve ser promovida depois de dados futuros com sinais e custos congelados.", "",
              "## Método e proveniência", "",
              "- Um episódio começa ao sair de caixa para long/short e termina ao voltar a caixa ou inverter o sinal; reequilíbrios semanais na mesma direção ficam no mesmo episódio.",
              "- O reprocessamento reproduziu retorno, drawdown, taxas e funding do avaliador original para todas as regras, períodos e custos, com tolerância de `1e-8`; PnL líquido dos episódios fecha com o retorno total da carteira.",
              "- O modelo cobra taxas no giro de cada rebalanceamento, usa os mesmos pagamentos de funding e proxies adversos do relatório original, e sinaliza saídas não resolvidas.",
              f"- Relatório original: SHA-256 `{analysis['source_report_sha256']}`; manifesto de dados `{analysis['source_manifest_sha256']}`.",
              f"- Reanalisador: SHA-256 `{analysis['analysis_code_sha256']}`.",
              f"- Ledgers por episódio: [CSV](../results/{OUTPUT_CSV.name}); métricas completas: [JSON](../results/{OUTPUT.name}).", "",
              "Nenhuma ordem real foi enviada.", ""]
    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(json.dumps({
        "factors": len(analysis["candidate_names"]),
        "periods": list(PERIODS),
        "ledger_rows": len(ledger_rows),
        "passing": passing,
        "outputs": [str(OUTPUT), str(OUTPUT_CSV), str(OUTPUT_MD)],
    }, ensure_ascii=True))
    return analysis


if __name__ == "__main__":
    run()
