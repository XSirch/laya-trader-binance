# Sizing semanal com previsão de perda de cauda

Execução 2026-09-27T15:25:58.395281Z. O estudo é retrospectivo e não autoriza negociação.

## Validade da previsão de risco

A amostra OOS comum tem 97 semanas UTC e previsões por ativo. A perda pinball do quantil 10% é melhor quanto menor; cobertura próxima de 10% é desejável, mas não significa lucro.

| Período | modelo | ativo-semanas | semanas UTC | pinball | pinball zero | pinball quantil treino | cobertura q10 | q10 médio | perda real média |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| walk_forward | price_only | 388 | 97 | 0.014699 | 0.059504 | 0.014463 | 13.1% | -13.77% | -6.61% |
| walk_forward | price_plus_macro | 388 | 97 | 0.015036 | 0.059504 | 0.014219 | 14.4% | -13.83% | -6.61% |
| walk_forward | macro pinball skill vs price_only | — | — | -2.30% | — | — | — | — | — |
| development_2024 | price_only | 44 | 11 | 0.011110 | 0.057568 | 0.011104 | 11.4% | -13.26% | -6.40% |
| development_2024 | price_plus_macro | 44 | 11 | 0.016141 | 0.057568 | 0.011288 | 31.8% | -10.76% | -6.40% |
| development_2024 | macro pinball skill vs price_only | — | — | -45.28% | — | — | — | — | — |
| holdout_2025_plus | price_only | 344 | 86 | 0.015158 | 0.059751 | 0.014893 | 13.4% | -13.84% | -6.64% |
| holdout_2025_plus | price_plus_macro | 344 | 86 | 0.014895 | 0.059751 | 0.014593 | 12.2% | -14.22% | -6.64% |
| holdout_2025_plus | macro pinball skill vs price_only | — | — | 1.73% | — | — | — | — | — |

## Sizing e carteira

A exposição alvo é `min(100%, 4% / max(1%, -q10))` do saldo de cada conta. O replay reequilibra na abertura de segunda-feira; o drawdown adverso considera a máxima e a mínima da hora como se a máxima viesse primeiro.

| janela | custo/lado | modelo | retorno líquido | CAGR | DD nas aberturas | DD adverso | alocação média | horas com posição | ordens | semanas com perda prevista <4% |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| walk_forward | 0.15% | price_plus_macro | 16.78% | 8.70% | 24.57% | 24.81% | 34.6% | 100.0% | 392 | 44.1% |
| walk_forward | 0.15% | price_only | 4.67% | 2.49% | 24.80% | 25.10% | 31.1% | 100.0% | 392 | 44.1% |
| walk_forward | 0.15% | buy_hold | -6.70% | -3.66% | 62.21% | 62.60% | 100.0% | 100.0% | 8 | — |
| walk_forward | 0.15% | cash | 0.00% | 0.00% | 0.00% | 0.00% | 0.0% | 0.0% | 0 | — |
| walk_forward | 0.30% | price_plus_macro | 14.39% | 7.50% | 25.08% | 25.32% | 34.6% | 100.0% | 392 | 44.1% |
| walk_forward | 0.30% | price_only | 4.09% | 2.18% | 24.90% | 25.20% | 31.1% | 100.0% | 392 | 44.1% |
| walk_forward | 0.30% | buy_hold | -6.98% | -3.82% | 62.21% | 62.60% | 100.0% | 100.0% | 8 | — |
| walk_forward | 0.30% | cash | 0.00% | 0.00% | 0.00% | 0.00% | 0.0% | 0.0% | 0 | — |
| holdout_2025_plus | 0.15% | price_plus_macro | -1.57% | -0.96% | 24.56% | 24.80% | 32.8% | 100.0% | 348 | 44.8% |
| holdout_2025_plus | 0.15% | price_only | -4.43% | -2.71% | 24.79% | 25.09% | 30.9% | 100.0% | 348 | 44.8% |
| holdout_2025_plus | 0.15% | buy_hold | -27.80% | -17.93% | 62.31% | 62.72% | 100.0% | 100.0% | 8 | — |
| holdout_2025_plus | 0.15% | cash | 0.00% | 0.00% | 0.00% | 0.00% | 0.0% | 0.0% | 0 | — |
| holdout_2025_plus | 0.30% | price_plus_macro | -3.17% | -1.94% | 25.07% | 25.31% | 32.8% | 100.0% | 348 | 44.8% |
| holdout_2025_plus | 0.30% | price_only | -4.88% | -2.99% | 24.88% | 25.18% | 30.9% | 100.0% | 348 | 44.8% |
| holdout_2025_plus | 0.30% | buy_hold | -28.02% | -18.08% | 62.31% | 62.72% | 100.0% | 100.0% | 8 | — |
| holdout_2025_plus | 0.30% | cash | 0.00% | 0.00% | 0.00% | 0.00% | 0.0% | 0.0% | 0 | — |

## Resultado por ativo no holdout

| custo/lado | modelo | ativo | retorno | CAGR | DD adverso | alocação média | horas com posição | ordens |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 0.15% | price_plus_macro | BTCUSDT | -7.50% | -4.62% | 26.08% | 39.5% | 100.0% | 87 |
| 0.15% | price_plus_macro | ETHUSDT | 0.08% | 0.05% | 26.05% | 28.8% | 100.0% | 87 |
| 0.15% | price_plus_macro | BNBUSDT | 10.69% | 6.35% | 25.42% | 37.9% | 100.0% | 87 |
| 0.15% | price_plus_macro | SOLUSDT | -9.55% | -5.91% | 27.96% | 25.1% | 100.0% | 87 |
| 0.15% | price_only | BTCUSDT | -9.92% | -6.14% | 26.57% | 39.6% | 100.0% | 87 |
| 0.15% | price_only | ETHUSDT | -1.70% | -1.04% | 24.55% | 26.8% | 100.0% | 87 |
| 0.15% | price_only | BNBUSDT | 3.23% | 1.95% | 27.53% | 35.6% | 100.0% | 87 |
| 0.15% | price_only | SOLUSDT | -9.34% | -5.77% | 26.64% | 21.7% | 100.0% | 87 |
| 0.30% | price_plus_macro | BTCUSDT | -8.81% | -5.44% | 26.52% | 39.5% | 100.0% | 87 |
| 0.30% | price_plus_macro | ETHUSDT | -1.53% | -0.93% | 26.46% | 28.8% | 100.0% | 87 |
| 0.30% | price_plus_macro | BNBUSDT | 8.40% | 5.01% | 26.15% | 37.9% | 100.0% | 87 |
| 0.30% | price_plus_macro | SOLUSDT | -10.75% | -6.67% | 28.76% | 25.1% | 100.0% | 87 |
| 0.30% | price_only | BTCUSDT | -10.30% | -6.38% | 26.65% | 39.6% | 100.0% | 87 |
| 0.30% | price_only | ETHUSDT | -2.20% | -1.34% | 24.62% | 26.8% | 100.0% | 87 |
| 0.30% | price_only | BNBUSDT | 2.51% | 1.51% | 27.71% | 35.6% | 100.0% | 87 |
| 0.30% | price_only | SOLUSDT | -9.55% | -5.91% | 26.74% | 21.7% | 100.0% | 87 |

## Conclusão

Meta retrospectiva de 50% CAGR líquido e limite adverso de drawdown de 10%, nos dois custos e nas duas janelas: **não atingida**. O objetivo de lucratividade consistente continua **não comprovado**; `deployable=false`. A previsão de cauda não passou todos os limites retrospectivos congelados. Registrar a hipótese como rejeitada ou inconclusiva; não ajustar esta amostra.

O estudo MCQRNN publicado usou 1.500 observações diárias, janela de treino de 1.000 e 500 previsões OOS; esta avaliação tem muito menos semanas e usa outro alvo. Ver [protocolo](macro_tail_risk_protocol_2026-09-27.md) e [fonte primária Springer](https://link.springer.com/article/10.1007/s11135-023-01761-1).

Snapshots usados: 537; hash agregado `d4b50248fe787aaf9952f1fc451994bc05a1eacf7af26f6c3a3f726735a19a3e`. Binance manifest: `5eba664095505668a66a6ba152a0af3c516b6a2a0d09ba58687120b91dee8e05`.
