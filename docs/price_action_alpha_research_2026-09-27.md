# Resultado: sweep/reclaim com confluência e HGB

## Decisão

Esta implementação independente inspirada nas categorias que GainzAlgo descreve publicamente também falhou. O sinal foi uma varredura da mínima anterior de 24 horas seguida por fechamento acima daquele nível. O HGB tentou prever o retorno bruto, em unidades de risco, da entrada atrasada até stop, alvo 2R ou saída em 24 horas. Nenhuma configuração passou o critério aspiracional de CAGR líquido de 50% com drawdown máximo de 10%.

| Modelo/controle | Custo por lado | Entradas | Retorno acumulado | DD observado | Limite adverso intrahorário |
| --- | ---: | ---: | ---: | ---: | ---: |
| HGB com gate por custo | 0,15% | 106 | -14,45% | 17,93% | 18,24% |
| HGB com gate por custo | 0,30% | 42 | -10,80% | 13,17% | 13,33% |
| Todos os sweeps elegíveis | 0,15% | 905 | -57,56% | 57,59% | 57,80% |
| Todos os sweeps elegíveis | 0,30% | 905 | -78,49% | 78,50% | 78,53% |
| Buy-and-hold igualmente ponderado | 0,15% | 4 | -12,09% | 61,53% | 61,97% |
| Buy-and-hold igualmente ponderado | 0,30% | 4 | -12,30% | 61,52% | 61,95% |
| Caixa | 0,15% / 0,30% | 0 | 0,00% | 0,00% | 0,00% |

O filtro ML reduziu fortemente as entradas e a queda frente a operar todo sweep, mas não criou retorno positivo e ainda ultrapassou o limite de drawdown. O resultado não justifica ajuste de limiar: as opções de custo mudam o número de entradas, sem mudar o sinal geral do replay.

## Reavaliação pela meta por operação

Sem repetir o replay, calculei as métricas por trade a partir das operações já gravadas no relatório integral. Vitória significa PnL líquido positivo; payoff é o ganho líquido médio dividido pela perda líquida média absoluta; EV é o retorno líquido médio por operação sobre o capital comprometido na entrada. Esse capital foi inferido da taxa de entrada e do custo por lado configurado. Mantive provisoriamente o gate de drawdown máximo de 10% da meta anterior.

| Regra/custo por lado | Trades | Acerto | Payoff | EV líquido por operação | DD máximo | Retorno da carteira |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| HGB com gate / 0,15% | 106 | 32,1% | 1,100:1 | -0,583% | 17,93% | -14,45% |
| HGB com gate / 0,30% | 42 | 23,8% | 1,090:1 | -1,080% | 13,17% | -10,80% |
| Todos os sweeps / 0,15% | 905 | 31,8% | 1,172:1 | -0,375% | 57,59% | -57,56% |
| Todos os sweeps / 0,30% | 905 | 28,2% | 0,889:1 | -0,675% | 78,50% | -78,49% |

Nenhum cenário chega perto de 70% de acerto ou EV líquido acima de 1,2%. O HGB no custo primário alcança apenas o payoff mínimo de 1:1; não atinge a faixa ideal de 1,2:1 a 1,5:1. Isso rejeita esta implementação nos dados e custos simulados, sem concluir que a meta seja impossível para outras regras. Os custos são hipóteses fixas e as velas horárias não comprovam spread, slippage nem fills executáveis.

## Capacidade preditiva

Foram encontrados 1.325 eventos válidos ao longo do histórico e o treino walk-forward gerou 905 previsões pontuadas entre abril de 2024 e agosto de 2026. As features combinaram profundidade/reclaim do sweep, forma do candle, retorno de 6/24/72h do ativo e de BTC, ATR, volatilidade realizada, volume relativo, fluxo taker e concentração/distância do maior bin de volume no perfil de 72 horas.

Nas 905 previsões, a acurácia direcional ficou em 48,95%. O MSE foi 1,8954 R², com skill de -5,55% contra a média do treino e -5,86% contra retorno bruto zero. O HGB não mostrou informação preditiva incremental nessa definição de evento.

| Período | Previsões | Direção correta | Skill contra média de treino | Skill contra zero |
| --- | ---: | ---: | ---: | ---: |
| 2024 (parcial) | 263 | 45,63% | -8,28% | -9,16% |
| 2025 | 379 | 50,13% | -5,35% | -5,50% |
| Jan–ago/2026 | 263 | 50,57% | -3,30% | -3,34% |

Os anos mais recentes se aproximam de 50% na direção, mas o erro segue pior do que os baselines. Isso não sustenta uma regra negociável.

## Integridade e limites

O protocolo estava congelado antes do replay: [price_action_alpha_protocol_2026-09-27.md](price_action_alpha_protocol_2026-09-27.md). Foram usados somente os arquivos Spot mensais locais, cobrindo BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT de janeiro/2023 a agosto/2026; zero download foi feito nesta execução. Houve 44 auditorias de ajuste mensal, sendo que os meses anteriores ao mínimo de 400 exemplos ficaram corretamente sem previsão.

O treino verificou que cada rótulo estava disponível estritamente antes do corte. Ainda assim, `historical_point_in_time_verified=false`: o histórico já foi examinado em estudos anteriores e a disponibilidade de todas as fontes no horário real não está demonstrada. Preços OHLC, stop-primeiro em colisões e custos fixos não demonstram fills reais, slippage ou spread. O prazo e os ativos também não equivalem ao preset Alpha do produto fechado.

Nenhuma ordem foi enviada; não houve chamada JEV. O relatório marca `goal_achieved=false`, `deployable=false` e `selected_winner=null`. O teste rejeita esta implementação independente e não valida nem refuta o algoritmo privado do GainzAlgo.

## Artefatos

- Implementação: [price_action_alpha.py](../src/jev_trader/price_action_alpha.py), [price_action_alpha_execution.py](../src/jev_trader/price_action_alpha_execution.py) e [price_action_alpha_research.py](../src/jev_trader/price_action_alpha_research.py).
- Resultado legível por máquina: [price_action_alpha_research_2026-09-27.json](price_action_alpha_research_2026-09-27.json).
- Relatório integral: `results/price_action_alpha_research.json`.
- SHA-256 do relatório integral: `c4495377621eba12f43c629810ce21d021a99251d0e0286ea48c68b19433ab87`.
- SHA-256 dos insumos: `1b6528ff174899f3385b156bb1a0b3c19da730f09c0ed57aceaaca4fd90173ed`.
- Tentativas e correções do replay: [price_action_alpha_run_log_2026-09-27.md](price_action_alpha_run_log_2026-09-27.md).
