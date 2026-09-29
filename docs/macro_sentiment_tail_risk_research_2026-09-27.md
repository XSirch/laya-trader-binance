# Fear & Greed como feature de risco semanal

Execução 2026-09-27T15:52:32.336704Z. Resultado retrospectivo; `deployable=false`.

## Integridade dos dados e alinhamento

A API devolveu 3157 observações entre 2018-02-01T00:00:00Z e 2026-09-27T00:00:00Z; SHA-256 do payload `66dcb98fd7553cd01cb5389aa659e986ee8af934f0551f80ddd457cac3addf5f`. Decisões usam o registro mais recente datado até 48 horas antes do domingo 23:00 UTC. A API não fornece vintages históricas; o atraso limita lookahead de publicação, mas não exclui revisões retrospectivas.

## Previsão do quantil 10%

Menor perda pinball é melhor. Todos os modelos são medidos nas mesmas combinações de ativo e semana.

| Janela | Modelo | ativo-semanas | semanas | pinball | q10 treino | cobertura | q10 médio | pior retorno semanal médio |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| walk_forward | price_only | 388 | 97 | 0.014699 | 0.014463 | 13.1% | -13.77% | -6.61% |
| walk_forward | price_plus_macro | 388 | 97 | 0.015036 | 0.014219 | 14.4% | -13.83% | -6.61% |
| walk_forward | price_plus_fgi | 388 | 97 | 0.015572 | 0.014463 | 13.7% | -13.40% | -6.61% |
| walk_forward | price_plus_macro_fgi | 388 | 97 | 0.015939 | 0.014219 | 18.3% | -13.23% | -6.61% |
| walk_forward | FGI skill: preço+FGI vs preço | — | — | -5.94% | — | — | — | — |
| walk_forward | FGI skill: macro+FGI vs macro | — | — | -6.00% | — | — | — | — |
| development_2024 | price_only | 44 | 11 | 0.011110 | 0.011104 | 11.4% | -13.26% | -6.40% |
| development_2024 | price_plus_macro | 44 | 11 | 0.016141 | 0.011288 | 31.8% | -10.76% | -6.40% |
| development_2024 | price_plus_fgi | 44 | 11 | 0.013086 | 0.011104 | 13.6% | -13.73% | -6.40% |
| development_2024 | price_plus_macro_fgi | 44 | 11 | 0.018976 | 0.011288 | 36.4% | -10.71% | -6.40% |
| development_2024 | FGI skill: preço+FGI vs preço | — | — | -17.78% | — | — | — | — |
| development_2024 | FGI skill: macro+FGI vs macro | — | — | -17.57% | — | — | — | — |
| holdout_2025_plus | price_only | 344 | 86 | 0.015158 | 0.014893 | 13.4% | -13.84% | -6.64% |
| holdout_2025_plus | price_plus_macro | 344 | 86 | 0.014895 | 0.014593 | 12.2% | -14.22% | -6.64% |
| holdout_2025_plus | price_plus_fgi | 344 | 86 | 0.015890 | 0.014893 | 13.7% | -13.36% | -6.64% |
| holdout_2025_plus | price_plus_macro_fgi | 344 | 86 | 0.015551 | 0.014593 | 16.0% | -13.55% | -6.64% |
| holdout_2025_plus | FGI skill: preço+FGI vs preço | — | — | -4.83% | — | — | — | — |
| holdout_2025_plus | FGI skill: macro+FGI vs macro | — | — | -4.40% | — | — | — | — |

## Carteiras com sizing idêntico

O orçamento segue o protocolo anterior: exposição `min(100%, 4% / max(1%, -q10))` por parcela. O drawdown adverso assume a máxima antes da mínima da hora.

| Janela | custo/lado | modelo | retorno líquido | CAGR | DD adverso | alocação média | ordens |
|---|---:|---|---:|---:|---:|---:|---:|
| walk_forward | 0.15% | price_only | 4.67% | 2.49% | 25.10% | 31.08% | 392 |
| walk_forward | 0.15% | price_plus_macro | 16.78% | 8.70% | 24.81% | 34.56% | 392 |
| walk_forward | 0.15% | price_plus_fgi | 1.34% | 0.72% | 27.03% | 32.71% | 392 |
| walk_forward | 0.15% | price_plus_macro_fgi | 10.45% | 5.49% | 28.22% | 36.21% | 391 |
| walk_forward | 0.15% | buy_hold | -6.70% | -3.66% | 62.60% | — | 8 |
| walk_forward | 0.15% | cash | 0.00% | 0.00% | 0.00% | — | 0 |
| walk_forward | 0.30% | price_only | 4.09% | 2.18% | 25.20% | 31.08% | 392 |
| walk_forward | 0.30% | price_plus_macro | 14.39% | 7.50% | 25.32% | 34.57% | 392 |
| walk_forward | 0.30% | price_plus_fgi | 0.31% | 0.17% | 27.18% | 32.72% | 392 |
| walk_forward | 0.30% | price_plus_macro_fgi | 7.94% | 4.20% | 28.81% | 36.22% | 391 |
| walk_forward | 0.30% | buy_hold | -6.98% | -3.82% | 62.60% | — | 8 |
| walk_forward | 0.30% | cash | 0.00% | 0.00% | 0.00% | — | 0 |
| holdout_2025_plus | 0.15% | price_only | -4.43% | -2.71% | 25.09% | 30.94% | 348 |
| holdout_2025_plus | 0.15% | price_plus_macro | -1.57% | -0.96% | 24.80% | 32.83% | 348 |
| holdout_2025_plus | 0.15% | price_plus_fgi | -7.13% | -4.39% | 27.02% | 32.53% | 348 |
| holdout_2025_plus | 0.15% | price_plus_macro_fgi | -5.20% | -3.19% | 28.26% | 34.65% | 347 |
| holdout_2025_plus | 0.15% | buy_hold | -27.80% | -17.93% | 62.72% | — | 8 |
| holdout_2025_plus | 0.15% | cash | 0.00% | 0.00% | 0.00% | — | 0 |
| holdout_2025_plus | 0.30% | price_only | -4.88% | -2.99% | 25.18% | 30.94% | 348 |
| holdout_2025_plus | 0.30% | price_plus_macro | -3.17% | -1.94% | 25.31% | 32.84% | 348 |
| holdout_2025_plus | 0.30% | price_plus_fgi | -7.84% | -4.83% | 27.18% | 32.53% | 348 |
| holdout_2025_plus | 0.30% | price_plus_macro_fgi | -6.92% | -4.26% | 28.84% | 34.66% | 347 |
| holdout_2025_plus | 0.30% | buy_hold | -28.02% | -18.08% | 62.72% | — | 8 |
| holdout_2025_plus | 0.30% | cash | 0.00% | 0.00% | 0.00% | — | 0 |

## Decisão

A ablação FGI não passou o critério congelado de previsão e carteira. Não ajustar esta amostra; a meta de lucratividade consistente permanece não atingida.

O FGI não é uma fonte comprovadamente point-in-time nesta série. Mesmo resultado positivo precisaria ser reavaliado prospectivamente com snapshots arquivados antes de qualquer interpretação operacional. O estudo não chama JEV, não altera o paper watcher e não envia ordens.

Arquivos: protocolo [macro_sentiment_tail_risk_protocol_2026-09-27.md](macro_sentiment_tail_risk_protocol_2026-09-27.md), fonte [macro_sentiment_tail_risk_sources_2026-09-27.md](macro_sentiment_tail_risk_sources_2026-09-27.md). Binance manifest `5eba664095505668a66a6ba152a0af3c516b6a2a0d09ba58687120b91dee8e05`; vintages ALFRED `d4b50248fe787aaf9952f1fc451994bc05a1eacf7af26f6c3a3f726735a19a3e`.
