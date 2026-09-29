"""Exploratory BTC regime split for the frozen short-only episode ledger."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .broad_data import load
from .broad_research import features
from .cli import RESULTS
from .target50_research import _offline_inputs

ROOT = Path(__file__).resolve().parents[2]
LEDGER = RESULTS / "low_volatility_short_only_ledger_20260928.csv"
SOURCE_RESULT = RESULTS / "low_volatility_short_only_20260928.json"
SOURCE_REANALYSIS = RESULTS / "broad_trade_target_reanalysis_20260927.json"
DATA_QUALITY = ROOT / "data" / "binance" / "broad" / "data_quality.json"
PROTOCOL = ROOT / "docs" / "low_volatility_short_only_protocol_2026-09-28.md"
OUTPUT_JSON = RESULTS / "short_only_btc_regime_audit_20260928.json"
OUTPUT_MD = ROOT / "docs" / "short_only_btc_regime_audit_2026-09-28.md"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _summarize(rows: list[dict]) -> dict:
    returns = [row["net_return_pct_on_entry_notional"] for row in rows]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    return {
        "episodes": len(returns),
        "wins": len(wins),
        "win_rate_pct": 100 * len(wins) / len(returns) if returns else None,
        "net_payoff_ratio": (sum(wins) / len(wins)) / abs(sum(losses) / len(losses))
        if wins and losses else None,
        "ev_net_pct_per_episode_on_entry_notional": sum(returns) / len(returns)
        if returns else None,
    }


def _run() -> dict:
    with _offline_inputs():
        data, _, _ = load()
    states = features(data)

    rows: list[dict] = []
    missing_btc_state = 0
    with LEDGER.open("r", encoding="utf-8", newline="") as handle:
        for source in csv.DictReader(handle):
            if source["cost"] != "stress" or source["period"] == "combined":
                continue
            timestamp = int(source["entry_ms"])
            btc = states.get("BTCUSDT", {}).get(timestamp)
            if btc is None:
                missing_btc_state += 1
                continue
            rows.append({
                "period": source["period"],
                "symbol": source["symbol"],
                "entry_ms": timestamp,
                "net_return_pct_on_entry_notional": float(source["net_return_pct_on_entry_notional"]),
                "btc_momentum30": float(btc["momentum30"]),
                "btc_momentum90": float(btc["momentum90"]),
                "btc_time_series_ensemble": float(btc["time_series_ensemble"]),
            })

    regimes = {
        "all_separate_period_episodes": lambda row: True,
        "btc_momentum30_negative": lambda row: row["btc_momentum30"] < 0,
        "btc_momentum30_nonnegative": lambda row: row["btc_momentum30"] >= 0,
        "btc_momentum90_negative": lambda row: row["btc_momentum90"] < 0,
        "btc_momentum90_nonnegative": lambda row: row["btc_momentum90"] >= 0,
        "btc_ema_ensemble_negative": lambda row: row["btc_time_series_ensemble"] < 0,
        "btc_ema_ensemble_nonnegative": lambda row: row["btc_time_series_ensemble"] >= 0,
    }
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "post-hoc regime diagnostic; not a parameter search or an independent holdout",
        "hypothesis": "A broad BTC trend gate could explain the short-only strategy's weak earlier periods.",
        "metric_basis": {
            "win": "positive net episode PnL after the frozen stress cost",
            "payoff": "mean positive net return divided by the absolute mean negative net return",
            "ev": "mean net return as a percentage of entry notional",
            "drawdown": "not recalculated for these trade subsets",
        },
        "frozen_goals": {
            "win_rate_minimum_pct": 70,
            "payoff_minimum": 1.0,
            "ev_strictly_above_pct": 1.2,
            "account_drawdown_maximum_pct": 10.0,
        },
        "sample": {
            "cost": "stress, 0.15% per side",
            "episodes_from_separately_replayed_windows": len(rows),
            "periods": sorted({row["period"] for row in rows}),
            "missing_btc_state": missing_btc_state,
            "why_separate_window_count_differs_from_combined": (
                "A position crossing a period boundary is closed/restarted in separate-window replays; "
                "the combined replay merges some same-direction episodes."
            ),
        },
        "regimes": {
            name: _summarize([row for row in rows if predicate(row)])
            for name, predicate in regimes.items()
        },
        "by_period": {
            period: _summarize([row for row in rows if row["period"] == period])
            for period in sorted({row["period"] for row in rows})
        },
        "source_sha256": {
            "candidate_protocol": _sha256(PROTOCOL),
            "short_only_result": _sha256(SOURCE_RESULT),
            "short_only_ledger": _sha256(LEDGER),
            "broad_target_reanalysis": _sha256(SOURCE_REANALYSIS),
            "data_quality": _sha256(DATA_QUALITY),
            "broad_manifest_sha256": json.loads(SOURCE_REANALYSIS.read_text(encoding="utf-8"))[
                "source_manifest_sha256"],
            "analysis_code": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        "limits": [
            "The short-only direction and the periods were inspected before this split.",
            "The binary BTC regime cuts are descriptive and were computed after viewing the episode outcomes.",
            "Trade subsets are not a complete portfolio replay; this analysis cannot pass the drawdown gate.",
            "No entry, exit, threshold, or allocation was changed, and no orders were sent.",
        ],
    }
    OUTPUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
                           encoding="utf-8", newline="\n")

    def fmt(value: float | None, digits: int = 2) -> str:
        return "n/a" if value is None else f"{value:.{digits}f}"

    lines = [
        "# Auditoria exploratória de regime BTC para o candidato short-only",
        "",
        "## Resultado",
        "",
        "A hipótese era que uma condição ampla de tendência do BTC explicaria as perdas do short-only "
        "nas janelas anteriores. Os cortes binários testados não atendem juntos a acerto de 70%, "
        "payoff mínimo 1:1 e EV acima de 1,2% do notional. O drawdown não foi refeito por subconjunto, "
        "portanto nenhum corte pode passar o gate completo.",
        "",
        "| Condição na entrada | Episódios | Acerto | Payoff | EV líquido/operação |",
        "|---|---:|---:|---:|---:|",
    ]
    labels = {
        "all_separate_period_episodes": "Todas as janelas em separado",
        "btc_momentum30_negative": "BTC: retorno 30d negativo",
        "btc_momentum30_nonnegative": "BTC: retorno 30d não negativo",
        "btc_momentum90_negative": "BTC: retorno 90d negativo",
        "btc_momentum90_nonnegative": "BTC: retorno 90d não negativo",
        "btc_ema_ensemble_negative": "BTC: conjunto de EMAs negativo",
        "btc_ema_ensemble_nonnegative": "BTC: conjunto de EMAs não negativo",
    }
    for key, metrics in report["regimes"].items():
        lines.append(
            f"| {labels[key]} | {metrics['episodes']} | {fmt(metrics['win_rate_pct'])}% | "
            f"{fmt(metrics['net_payoff_ratio'], 3)} | {fmt(metrics['ev_net_pct_per_episode_on_entry_notional'])}% |"
        )
    lines += [
        "",
        "## Leitura por janela",
        "",
        "| Janela | Episódios | Acerto | Payoff | EV líquido/operação |",
        "|---|---:|---:|---:|---:|",
    ]
    for period, metrics in report["by_period"].items():
        lines.append(
            f"| {period} | {metrics['episodes']} | {fmt(metrics['win_rate_pct'])}% | "
            f"{fmt(metrics['net_payoff_ratio'], 3)} | {fmt(metrics['ev_net_pct_per_episode_on_entry_notional'])}% |"
        )
    lines += [
        "",
        "## Método e limites",
        "",
        f"A amostra tem {len(rows)} episódios das quatro janelas em separado, somente no custo stress "
        "de 0,15% por lado. Cada retorno foi associado ao estado BTC disponível na entrada: "
        "momentum de 30 dias, momentum de 90 dias e sinal do ensemble EMA. Acerto considera PnL "
        "líquido positivo; payoff é ganho médio dividido pela perda média absoluta; EV é retorno "
        "líquido médio como percentual do notional de entrada.",
        "",
        "A soma das janelas separadas difere do replay combinado porque operações que cruzam fronteiras "
        "de período são fechadas e reiniciadas nos recortes separados. Os 96 episódios desta análise "
        "não devem ser confundidos com os 88 episódios do replay combinado.",
        "",
        "Este é um diagnóstico posterior sobre filtros simples, não confirmação independente. As janelas "
        "e a direção short já tinham sido examinadas. Os subconjuntos não tiveram replay de carteira, "
        "logo não há evidência de drawdown abaixo de 10%. Nenhuma regra foi ajustada e nenhuma ordem "
        "foi enviada.",
        "",
        "Os dados locais de futuros usados no candidato estão desatualizados para novas decisões: "
        "18 de 20 contratos chegam somente ao candle de 31/08/2026; EOSUSDT termina em 21/05/2025 "
        "e MKRUSDT em 08/09/2025. A próxima etapa operacional exige atualizar candles e mark price "
        "diários e funding antes de gerar qualquer sinal. A Binance documenta os endpoints USDⓈ-M "
        "de klines, mark-price klines, funding e exchange info [na referência oficial da API]"
        "(https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data). "
        "Os arquivos públicos diários ficam disponíveis no dia seguinte e trazem o formato de klines "
        "USD-M [na documentação oficial do arquivo](https://github.com/binance/binance-public-data/blob/master/README.md).",
        "",
        "## Artefatos de entrada",
        "",
        f"- Protocolo short-only: `docs/low_volatility_short_only_protocol_2026-09-28.md` "
        f"(SHA-256 `{report['source_sha256']['candidate_protocol']}`).",
        f"- Resultado e ledger: `results/low_volatility_short_only_20260928.json` e "
        f"`results/low_volatility_short_only_ledger_20260928.csv`.",
        f"- Manifesto histórico: SHA-256 `{report['source_sha256']['broad_manifest_sha256']}`.",
        f"- Qualidade/frescor diário: `data/binance/broad/data_quality.json` "
        f"(SHA-256 `{report['source_sha256']['data_quality']}`).",
        f"- Código deste diagnóstico: SHA-256 `{report['source_sha256']['analysis_code']}`.",
        "",
    ]
    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(json.dumps({"output": str(OUTPUT_MD), "regimes": report["regimes"],
                      "by_period": report["by_period"], "missing_btc_state": missing_btc_state},
                     indent=2, sort_keys=True), flush=True)
    return report


if __name__ == "__main__":
    _run()
