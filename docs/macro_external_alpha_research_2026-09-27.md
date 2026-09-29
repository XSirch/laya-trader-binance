# Replay de sinais macro externos em horizonte semanal

Execução: 2026-09-27T09:00:29.561147Z. O resultado é exploratório e não autoriza ordens.

## Desenho

Comparamos Ridge de lags cripto (`price_only`) com o mesmo Ridge acrescido de Nasdaq Composite, VIX e índice amplo do dólar Fed (`price_plus_macro`). O treino é expansivo, por ativo, com no mínimo 52 semanas completas. As vintages ALFRED são consultadas para cada domingo de decisão. A decisão ocorre domingo às 23:00 UTC e pode ser executada somente na abertura da segunda-feira às 00:00 UTC.

Período de entradas: 2024-10-21T00:00:00Z a 2026-08-24T00:00:00Z; liquidação final em 2026-08-31T00:00:00Z. Previsões por modelo: {'price_only': 452, 'price_plus_macro': 388}.

Arquivos de dados: 176 manifest entries; 30073 timestamps horários comuns; hash agregado do manifesto `5eba664095505668a66a6ba152a0af3c516b6a2a0d09ba58687120b91dee8e05`. Vintages consultadas: 537 (532 lidas do cache local). Semanas com as três séries frescas e histórico suficiente: 163; primeira semana elegível: 2023-03-27T00:00:00Z.

## Erro preditivo

MSE e MAE são retornos simples ao quadrado/absolutos; MSE menor é melhor. A habilidade direcional não equivale a lucro.

| Período | Modelo | ativo-semanas | semanas UTC únicas | MSE | MAE | MSE zero | MSE média treino | direção correta |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| walk_forward | price_only | 388 | 97 | 0.007870948 | 6.44230% | 0.007398061 | 0.007688254 | 47.94% |
| walk_forward | price_plus_macro | 388 | 97 | 0.008952316 | 6.90005% | 0.007398061 | 0.00753783 | 48.20% |
| walk_forward | macro MSE skill vs price_only | — | — | -13.74% | — | — | — | — |
| development_2024 | price_only | 44 | 11 | 0.00994213 | 7.49991% | 0.01041317 | 0.009954968 | 52.27% |
| development_2024 | price_plus_macro | 44 | 11 | 0.01143359 | 8.20328% | 0.01041317 | 0.0100432 | 54.55% |
| development_2024 | macro MSE skill vs price_only | — | — | -15.00% | — | — | — | — |
| holdout_2025_plus | price_only | 344 | 86 | 0.007606029 | 6.30702% | 0.007012408 | 0.007398325 | 47.38% |
| holdout_2025_plus | price_plus_macro | 344 | 86 | 0.008634943 | 6.73336% | 0.007012408 | 0.007217375 | 47.38% |
| holdout_2025_plus | macro MSE skill vs price_only | — | — | -13.53% | — | — | — | — |

## Carteiras

Cada cenário começa com quatro saldos iguais. Compras e vendas são executadas na abertura semanal com custos fixos assumidos. O drawdown adverso usa a máxima antes da mínima de cada candle horário, mesmo quando essa ordem não ocorreu; é um limite compatível com OHLC, não um percurso observado.

| Janela | custo/lado | regra | retorno líquido | CAGR | DD nas aberturas | limite adverso | % tempo exposto | ordens | retorno ativo semanal positivo |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| walk_forward | 0.15% | price_plus_macro | -22.60% | -12.87% | 58.41% | 59.12% | 56.7% | 154 | 45.9% |
| walk_forward | 0.15% | price_only | -9.51% | -5.24% | 59.68% | 60.32% | 74.5% | 96 | 47.1% |
| walk_forward | 0.15% | buy_hold | -6.70% | -3.66% | 62.21% | 62.60% | 100.0% | 8 | — |
| walk_forward | 0.15% | cash | 0.00% | 0.00% | 0.00% | 0.00% | 0.0% | 0 | — |
| walk_forward | 0.30% | price_plus_macro | -30.58% | -17.83% | 59.68% | 60.38% | 52.3% | 160 | 46.3% |
| walk_forward | 0.30% | price_only | -4.42% | -2.40% | 55.14% | 55.70% | 68.3% | 110 | 46.8% |
| walk_forward | 0.30% | buy_hold | -6.98% | -3.82% | 62.21% | 62.60% | 100.0% | 8 | — |
| walk_forward | 0.30% | cash | 0.00% | 0.00% | 0.00% | 0.00% | 0.0% | 0 | — |
| holdout_2025_plus | 0.15% | price_plus_macro | -34.59% | -22.71% | 58.55% | 59.31% | 54.4% | 138 | 43.9% |
| holdout_2025_plus | 0.15% | price_only | -25.50% | -16.36% | 59.86% | 60.53% | 72.4% | 84 | 45.8% |
| holdout_2025_plus | 0.15% | buy_hold | -27.80% | -17.93% | 62.31% | 62.72% | 100.0% | 8 | — |
| holdout_2025_plus | 0.15% | cash | 0.00% | 0.00% | 0.00% | 0.00% | 0.0% | 0 | — |
| holdout_2025_plus | 0.30% | price_plus_macro | -41.10% | -27.47% | 59.93% | 60.68% | 49.4% | 142 | 44.1% |
| holdout_2025_plus | 0.30% | price_only | -24.85% | -15.91% | 54.89% | 55.50% | 66.3% | 92 | 45.2% |
| holdout_2025_plus | 0.30% | buy_hold | -28.02% | -18.08% | 62.31% | 62.72% | 100.0% | 8 | — |
| holdout_2025_plus | 0.30% | cash | 0.00% | 0.00% | 0.00% | 0.00% | 0.0% | 0 | — |

## Resultado por ativo no holdout

Cada coluna usa uma conta isolada iniciada com 25% do capital total; drawdowns são calculados sobre essa conta.

| custo/lado | ativo | retorno | CAGR | DD nas aberturas | limite adverso | % horas exposto | ordens |
|---:|---|---:|---:|---:|---:|---:|---:|
| 0.15% | BTCUSDT | -32.63% | -21.31% | 56.65% | 58.71% | 57.0% | 34 |
| 0.15% | ETHUSDT | -42.15% | -28.26% | 64.05% | 64.51% | 48.8% | 32 |
| 0.15% | BNBUSDT | -9.96% | -6.17% | 61.46% | 61.72% | 54.7% | 28 |
| 0.15% | SOLUSDT | -53.63% | -37.27% | 75.42% | 76.04% | 57.0% | 44 |
| 0.30% | BTCUSDT | -52.39% | -36.25% | 58.01% | 60.15% | 46.5% | 34 |
| 0.30% | ETHUSDT | -40.25% | -26.84% | 61.74% | 62.23% | 47.7% | 34 |
| 0.30% | BNBUSDT | -25.21% | -16.16% | 63.24% | 63.61% | 50.0% | 28 |
| 0.30% | SOLUSDT | -46.57% | -31.63% | 72.18% | 72.76% | 53.5% | 46 |

## Diferença do sinal macro sobre o controle cripto

| Janela | custo/lado | delta retorno líquido (macro - cripto) | delta MSE % |
|---|---:|---:|---:|
| walk_forward | 0.15% | -13.09 p.p. | -13.74% |
| walk_forward | 0.30% | -26.16 p.p. | -13.74% |
| holdout_2025_plus | 0.15% | -9.09 p.p. | -13.53% |
| holdout_2025_plus | 0.30% | -16.26 p.p. | -13.53% |

## Limitações e decisão

As vintages ALFRED são diárias; elas não provam o minuto de publicação. A decisão é deliberadamente domingo 23:00 UTC, após o último fechamento norte-americano que a vintage contém, e antes da abertura cripto usada. O índice Fed H.10 tem cadência semanal e é avaliado apenas com a série que já aparece na vintage. Preços de abertura e OHLC horário não garantem execução; spread, impacto, imposto, juros sobre caixa e restrições de redistribuição dos índices não foram modelados.

Meta retrospectiva (CAGR líquido ≥50% e limite adverso de drawdown ≤10% nos dois custos, no walk-forward e no holdout): **não atingida**. O objetivo de encontrar uma estratégia lucrativa e consistente permanece **não comprovado**; negociação real: **não**. O filtro macro não passou todos os limites retrospectivos congelados; registrar a hipótese como rejeitada ou inconclusiva conforme erro e PnL, sem retunar esta amostra..

Arquivos reproduzíveis: `docs/macro_external_alpha_research_2026-09-27.md`, `results/macro_external_alpha_research.json`, `results/macro_external_alpha_forecasts.csv`, `results/macro_external_alpha_curves.csv`, `results/macro_external_alpha_fills.csv`. Dados macro brutos permanecem somente em cache local ignorado.

Fontes de dados e contexto: [FRED/ALFRED](https://alfred.stlouisfed.org/help/downloaddata), [Nasdaq Composite](https://fred.stlouisfed.org/series/NASDAQCOM), [VIX](https://fred.stlouisfed.org/series/VIXCLS), [índice amplo do dólar](https://fred.stlouisfed.org/series/DTWEXBGS), [nota de pesquisa](macro_crypto_sources_2026-09-27.md).
