# Recontagem do replay de barreiras pelas metas por operação

Este relatório reagrupa os fills reais arquivados no replay BTCUSDT Spot, sem recalcular sinais ou posições. EV e payoff são líquidos de taxas de entrada e saída, sobre o notional inicial.

| Modelo | Período | Custo/lado | Alocação | Trades | Acerto | Payoff | EV/trade | DD | DD adverso | Gates |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| rolling_mean | later | 0.12% | 50% | 0 | n/a | n/a | n/a | 0.00% | 0.00% | fail |
| rolling_mean | later | 0.12% | 100% | 0 | n/a | n/a | n/a | 0.00% | 0.00% | fail |
| rolling_mean | later | 0.24% | 50% | 0 | n/a | n/a | n/a | 0.00% | 0.00% | fail |
| rolling_mean | later | 0.24% | 100% | 0 | n/a | n/a | n/a | 0.00% | 0.00% | fail |
| hgb | later | 0.12% | 50% | 394 | 35.53% | 1.26 | -0.24% | 38.75% | 38.96% | fail |
| hgb | later | 0.12% | 100% | 394 | 35.53% | 1.26 | -0.24% | 63.31% | 63.56% | fail |
| hgb | later | 0.24% | 50% | 156 | 35.90% | 1.08 | -0.40% | 29.29% | 29.56% | fail |
| hgb | later | 0.24% | 100% | 156 | 35.90% | 1.08 | -0.40% | 50.66% | 51.04% | fail |
| always | later | 0.12% | 50% | 5397 | 34.46% | 1.03 | -0.24% | 99.85% | 99.86% | fail |
| always | later | 0.12% | 100% | 5397 | 34.46% | 1.03 | -0.24% | 100.00% | 100.00% | fail |
| always | later | 0.24% | 50% | 5397 | 29.44% | 0.72 | -0.48% | 100.00% | 100.00% | fail |
| always | later | 0.24% | 100% | 5397 | 29.44% | 0.72 | -0.48% | 100.00% | 100.00% | fail |
| buy_hold | later | 0.12% | 50% | 1 | 100.00% | n/a | 85.53% | 40.23% | 40.58% | fail |
| buy_hold | later | 0.12% | 100% | 1 | 100.00% | n/a | 85.53% | 53.74% | 54.20% | fail |
| buy_hold | later | 0.24% | 50% | 1 | 100.00% | n/a | 85.19% | 40.22% | 40.57% | fail |
| buy_hold | later | 0.24% | 100% | 1 | 100.00% | n/a | 85.19% | 53.74% | 54.20% | fail |

## Conclusão

Cenários posteriores que passaram todos os gates: 0 de 16.
Os retornos por operação são retrospectivos. Nenhum cenário passa a ser candidato confirmado por esta recontagem.

Hash do replay-fonte `ab5c92a8a7c61052685259a16e2fa35f77269972ce0e9e64511d902502e5afd2`; protocolo `5b5ad97e48398352c3ec624d00165bde5323913c78fb6c7d224aa885e0e6b56e`; código `db7130ecba0d815862d28f1ac6a8864e4e4d0dbd7c203de6e57ab0f3c50626d7`.
