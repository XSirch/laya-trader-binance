# Supertrend horário com filtro ML

Execução 2026-09-27T16:11:38.071389Z. Resultado histórico exploratório; `deployable=false`.

## Eventos e previsões ML

O detector encontrou 1412 sinais de alta e 1412 operações completas para rótulos. O primeiro filtro treinado apareceu em 2023-06-27T12:00:00Z.
O alvo é o retorno líquido até a próxima transição para baixa. MAE menor é melhor; a tabela compara com zero e média móvel do treino.

| Janela | custo/lado | previsões | operações aceitas | MAE | MAE zero | MAE média treino | acerto direção | retorno médio realizado aceito |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| walk_forward | 0.15% | 1312 | 611 | 0.03149 | 0.02934 | 0.02941 | 50.4% | -0.09% |
| walk_forward | 0.30% | 1312 | 476 | 0.03140 | 0.03036 | 0.02932 | 54.8% | -0.47% |
| holdout_2025_plus | 0.15% | 721 | 319 | 0.02874 | 0.02724 | 0.02723 | 50.8% | -0.49% |
| holdout_2025_plus | 0.30% | 721 | 226 | 0.02866 | 0.02839 | 0.02715 | 57.7% | -0.88% |

## Carteiras Spot long/cash

Drawdown adverso marca a máxima antes da mínima de cada hora. Buy-and-hold e caixa usam a mesma janela e capital inicial.

| Janela | custo/lado | estratégia | retorno líquido | CAGR | DD aberturas | DD adverso | alocação média | operações |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| walk_forward | 0.15% | supertrend | -48.20% | -17.45% | 71.23% | 71.38% | 49.08% | 1412 |
| walk_forward | 0.15% | supertrend_ml | -19.39% | -6.09% | 45.10% | 45.70% | 20.77% | 611 |
| walk_forward | 0.15% | buy_hold | 176.24% | 34.47% | 65.63% | 66.13% | 100.00% | 4 |
| walk_forward | 0.15% | cash | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0 |
| walk_forward | 0.30% | supertrend | -82.02% | -39.36% | 86.79% | 86.86% | 49.08% | 1412 |
| walk_forward | 0.30% | supertrend_ml | -46.27% | -16.56% | 51.42% | 51.83% | 16.40% | 476 |
| walk_forward | 0.30% | buy_hold | 175.42% | 34.36% | 65.63% | 66.13% | 100.00% | 4 |
| walk_forward | 0.30% | cash | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0 |
| holdout_2025_plus | 0.15% | supertrend | -53.55% | -37.20% | 65.01% | 65.50% | 47.85% | 721 |
| holdout_2025_plus | 0.15% | supertrend_ml | -35.69% | -23.50% | 47.21% | 47.83% | 19.42% | 319 |
| holdout_2025_plus | 0.15% | buy_hold | -27.80% | -17.93% | 62.31% | 62.72% | 100.00% | 4 |
| holdout_2025_plus | 0.15% | cash | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0 |
| holdout_2025_plus | 0.30% | supertrend | -72.94% | -54.76% | 79.20% | 79.50% | 47.85% | 721 |
| holdout_2025_plus | 0.30% | supertrend_ml | -40.58% | -27.08% | 48.33% | 49.00% | 14.02% | 226 |
| holdout_2025_plus | 0.30% | buy_hold | -28.02% | -18.08% | 62.31% | 62.72% | 100.00% | 4 |
| holdout_2025_plus | 0.30% | cash | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0 |

## Decisão

O Supertrend com filtro ML não passou retorno líquido positivo e drawdown adverso máximo de 10% em todos os períodos e custos. Não retunar esta amostra.

A simulação usa candles OHLC e custos hipotéticos. Ela não mede spread observado, slippage, latência, execução real, impostos ou impacto. O histórico posterior já foi visto em outros experimentos e não é um holdout global intocado.

Referências: [fórmula Supertrend do TradingView](https://www.tradingview.com/support/solutions/43000634738-supertrend/); [protocolo congelado](supertrend_ml_protocol_2026-09-27.md).
