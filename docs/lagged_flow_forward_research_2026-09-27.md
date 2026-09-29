# Holdout de setembro: modelos de lags

## Resultado

O replay fora da amostra de 01 a 26/09/2026 não validou uma estratégia consistente. Foram avaliados BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT, com decisões a cada oito horas, horizonte de oito horas, até 25% do capital por ativo e custos presumidos de 0,15% e 0,30% por lado. O conjunto novo contém 2.496 candles horários validados por arquivo diário e checksum; o holdout teve 308 previsões avaliadas por modelo.

| Modelo/controle | Custo por lado | Retorno acumulado | DD observado | Limite adverso intrahorário | Entradas |
| --- | ---: | ---: | ---: | ---: | ---: |
| Lags do próprio ativo | 0,15% | +0,35% | 0,75% | 1,05% | 8 |
| Lags do próprio ativo | 0,30% | -0,29% | 0,95% | 1,23% | 7 |
| Lags de BTC/ETH | 0,15% | -3,53% | 4,60% | 5,06% | 18 |
| Lags de BTC/ETH | 0,30% | -2,57% | 2,67% | 2,84% | 3 |
| Próprios + BTC/ETH | 0,15% | -2,69% | 3,46% | 3,83% | 13 |
| Próprios + BTC/ETH | 0,30% | -1,71% | 1,91% | 2,19% | 4 |
| Sempre comprado (controle) | 0,15% | -11,34% | 16,05% | 16,85% | 308 |
| Sempre comprado (controle) | 0,30% | -29,63% | 30,17% | 30,29% | 308 |
| Comprar e manter (controle) | 0,15% | +11,29% | 6,71% | 7,96% | 4 |
| Comprar e manter (controle) | 0,30% | +10,96% | 6,71% | 7,96% | 4 |

O melhor caso ML só ficou positivo por 0,35% no período, no custo menor, e passou a -0,29% com o custo estressado. Não o seleciono como vencedor: a diferença é pequena, os custos e fills não são observações reais, o período cobre apenas 25 dias e os outros modelos ML perderam. Buy-and-hold foi o controle de maior retorno nesse intervalo; isso descreve o mercado do período e não demonstra uma estratégia anual.

## Qualidade preditiva

Cada um dos três modelos gerou 308 previsões pontuadas. A acurácia direcional foi 51,95% para os lags próprios, 49,68% para os lags de BTC/ETH e 50,32% para a combinação. Os três tiveram *skill* negativo contra prever retorno zero: -3,49%, -4,39% e -4,85%, respectivamente. Portanto, a acurácia ligeiramente acima de 50% do modelo próprio não veio acompanhada de erro quadrático melhor que o baseline zero.

O replay atualizou os três modelos mensalmente com rótulos disponíveis antes do corte de cada ajuste, completando 33 ajustes walk-forward. As regras de entrada, horizonte, limites e custos foram mantidas. A janela não foi usada para escolher ativo nem reajustar parâmetros.

## Limites de evidência

- O relatório registra `historical_point_in_time_verified=false`: a disponibilidade histórica dos dados e das features antes de cada decisão ainda não está demonstrada integralmente. Os candles novos do holdout têm arquivos diários e checksums, mas isso não prova os preços que estavam disponíveis em tempo real.
- Os retornos são uma simulação por aberturas OHLC e taxas presumidas. O limite adverso intrahorário considera caminhos desfavoráveis possíveis dentro dos candles; não é uma cotação executável.
- Quatro ativos cripto têm resultados correlacionados. Uma janela curta e um mês favorável a comprar e manter não sustentam inferência de consistência anual.
- Nenhuma ordem foi enviada. O resultado marca `goal_achieved=false` e `deployable=false`; o critério anual de 50% líquido com drawdown máximo de 10% não foi satisfeito.

## Integridade e reprodução

Protocolo congelado: [lagged_flow_forward_protocol_2026-09-27.md](lagged_flow_forward_protocol_2026-09-27.md). Relatório completo: `results/lagged_flow_forward_research.json`. Resumo verificável: [lagged_flow_forward_research_2026-09-27.json](lagged_flow_forward_research_2026-09-27.json). Hash do relatório integral: `29e4a4772d94812da004973d975dc2a45e51216aec463427b2465896e2be7bae`. Hash dos insumos: `08154099d68d2929d42e167f66276699faec3b3bbcd6548275fe0b27e5dc59cb`. A documentação da Binance descreve a publicação de arquivos diários Spot e seus checksums em [Binance Public Data](https://github.com/binance/binance-public-data/blob/master/README.md).

O resultado acrescenta evidência recente contra os três modelos de lags. Não encerra a pesquisa nem autoriza negociação real.
