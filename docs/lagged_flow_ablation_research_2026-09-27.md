# Resultado da ablação de lags próprios e lags líderes

**Nenhum grupo de lags encontrou uma estratégia lucrativa e consistente.** Restringir o HGB aos retornos e ao fluxo agressor de 1, 2, 3 e 6 horas mudou a frequência das operações, mas não produziu habilidade preditiva contra retorno zero nem retornos líquidos positivos e estáveis. A grade usou os mesmos dados, cortes e executor do [estudo amplo](lagged_flow_research_2026-09-27.md), conforme o [protocolo congelado](lagged_flow_ablation_protocol_2026-09-27.md).

Esta ablação não repete o modelo horário de 114 campos: compara três painéis menores — lags do próprio ativo, lags de BTC/ETH e os dois grupos juntos, sempre com indicadores fixos de ativo. O HGB amplo próprio e o HGB amplo com líderes já estão congelados no relatório anterior e servem como referências; seus resultados não foram recalculados nem usados para selecionar parâmetros.

## Sinais preditivos

Cada comparação usa os mesmos 4.036 retornos de desenvolvimento ou 7.288 posteriores. `skill_vs_zero` é erro contra previsão de retorno zero; números negativos significam que o modelo perde para esse controle. Ativos e horários são correlacionados e os valores não têm teste de significância.

| Período | Grupo de features | MSE | MAE | Direção correta | Skill vs. zero |
|---|---|---:|---:|---:|---:|
| Desenvolvimento | Lags próprios | 0,00038350 | 0,013596 | 49,55% | -0,9760% |
| Desenvolvimento | Lags BTC/ETH | 0,00039231 | 0,013732 | 50,47% | -3,2961% |
| Desenvolvimento | Próprios + BTC/ETH | 0,00039201 | 0,013711 | 50,00% | -3,2179% |
| Posterior | Lags próprios | 0,00032883 | 0,012360 | 51,77% | -1,4521% |
| Posterior | Lags BTC/ETH | 0,00032943 | 0,012436 | 50,21% | -1,6385% |
| Posterior | Próprios + BTC/ETH | 0,00032857 | 0,012405 | 50,51% | -1,3735% |

O modelo combinado teve MSE ligeiramente menor que as duas ablações no posterior, mas não superou a previsão zero. A ordenação dos grupos muda entre 2025 e 2026: o combinado ficou com o menor MSE em 2025, enquanto os lags próprios ficaram à frente em janeiro–agosto/2026. Isso confirma que o sinal é instável no tempo, não que um grupo possa ser escolhido depois de ver cada ano.

## Retorno e drawdown

Valores em porcentagem; DD adverso inclui os extremos horários em ordem desfavorável. Cada regra começa com capital unitário por período.

| Regra | Custo/lado | Período | CAGR | DD | DD adverso | Entradas |
|---|---:|---|---:|---:|---:|---:|
| Lags próprios | 0,15% | Desenvolvimento | -8,88 | 32,75 | 33,68 | 590 |
| Lags próprios | 0,15% | Posterior | -13,33 | 27,48 | 28,58 | 519 |
| Lags próprios | 0,30% | Desenvolvimento | -25,24 | 29,98 | 31,01 | 216 |
| Lags próprios | 0,30% | Posterior | -10,41 | 20,69 | 23,25 | 116 |
| Lags BTC/ETH | 0,15% | Desenvolvimento | -62,68 | 66,00 | 66,28 | 814 |
| Lags BTC/ETH | 0,15% | Posterior | -17,95 | 29,97 | 30,42 | 675 |
| Lags BTC/ETH | 0,30% | Desenvolvimento | -26,18 | 28,71 | 29,57 | 224 |
| Lags BTC/ETH | 0,30% | Posterior | -5,74 | 19,40 | 19,77 | 202 |
| Lags próprios + líderes | 0,15% | Desenvolvimento | -55,26 | 59,56 | 59,81 | 757 |
| Lags próprios + líderes | 0,15% | Posterior | -11,74 | 24,28 | 25,17 | 624 |
| Lags próprios + líderes | 0,30% | Desenvolvimento | -26,69 | 28,38 | 29,86 | 228 |
| Lags próprios + líderes | 0,30% | Posterior | -5,85 | 20,02 | 20,30 | 206 |

O melhor CAGR posterior foi -5,74%, do modelo só com lags BTC/ETH a 0,30% por lado, com DD adverso de 19,77%. O custo mais alto aumentou o limiar de entrada e reduziu operações; portanto, a melhoria relativa não é efeito de cobrar mais pelas mesmas negociações. Nenhum modelo se aproximou simultaneamente da meta local de CAGR líquido de 50% e DD de 10%.

Mesmo as melhores combinações tiveram desempenho anual misto. A 0,30% por lado, o grupo BTC/ETH teve +0,70% em 2025 e -10,00% no trecho de 2026; o grupo combinado teve -6,65% e -3,11%; o grupo próprio teve -12,00% e -5,37%. A carteira ficou negativa em todo o posterior em cada combinação e custo.

Os controles reproduziram a referência anterior: `always` perdeu entre -92,46% e -99,88% de CAGR conforme o período/custo; `buy_hold` teve 93,87% de CAGR no desenvolvimento com 39,59% de DD adverso e -14,28% no posterior com 62,94% de DD adverso ao custo-base. O contraste entre desenvolvimento e posterior reforça o risco de classificar a fase boa como propriedade permanente do modelo.

## Diagnóstico extra de direção curta

Depois do protocolo e da grade, foi calculada uma estatística exploratória não pré-registrada: retorno médio dos sinais longos e curtos separados, com o mesmo limiar de custo. Na amostra posterior, todos os três grupos tiveram retorno médio líquido negativo ao agrupar as duas direções, em ambos os custos. A perna curta também foi negativa em 2025 e no trecho de 2026 para cada grupo e custo. Esse cálculo não é replay de futuros: omite funding, margem, liquidação e fills de venda a descoberto, e não autoriza short. Ele não justifica iniciar uma implementação de perpétuos nesta hipótese.

O cálculo converte cada retorno observado em `(1 + lado*retorno) * (1-c)/(1+c) - 1` e inclui eventos cujo módulo da previsão excede `2c/(1-c)`. Valores abaixo são a média líquida simples por episódio, não uma curva composta de carteira:

| Grupo | Custo/lado | Todos: n / retorno | Long: n / retorno | Short: n / retorno |
|---|---:|---:|---:|---:|
| Lags próprios | 0,15% | 975 / -0,270% | 519 / -0,170% | 456 / -0,383% |
| Lags próprios | 0,30% | 175 / -0,839% | 116 / -0,607% | 59 / -1,293% |
| Lags BTC/ETH | 0,15% | 1.280 / -0,275% | 675 / -0,179% | 605 / -0,382% |
| Lags BTC/ETH | 0,30% | 322 / -0,427% | 202 / -0,170% | 120 / -0,860% |
| Próprios + líderes | 0,15% | 1.201 / -0,186% | 624 / -0,117% | 577 / -0,260% |
| Próprios + líderes | 0,30% | 316 / -0,327% | 206 / -0,169% | 110 / -0,622% |

## Decisão e próximos dados

Esta família é rejeitada para negociação com a meta atual. O melhor grupo dependeu do ano e do custo, a habilidade contra retorno zero foi negativa e os drawdowns superaram em muito 10%. Todos os períodos históricos já foram amplamente pesquisados no projeto, então esse replay é exploratório e retrospectivo. Nenhum resultado foi usado para ordem real.

Para avançar com rigor, o caminho útil agora é congelar um candidato novo e medir em datas ainda não vistas, com observações prospectivas e custo/spread realistas. Não vou selecionar ativo, limiar, janela ou lado a partir deste conjunto posterior.

## Artefatos

- [Protocolo congelado](lagged_flow_ablation_protocol_2026-09-27.md).
- Resumo, parâmetros e scores: [lagged_flow_ablation_research_2026-09-27.json](lagged_flow_ablation_research_2026-09-27.json).
- Relatório local completo: `results/lagged_flow_ablation_research.json`, SHA-256 `d2ef605ea36a7f9002f528683179c7abb34874f68fa72e8315db2d78b962501d`.
- Snapshot local dos insumos: `results/lagged_flow_ablation_inputs.json`, SHA-256 `a50a619b0eaf26b659a253bf4988e1836d023504c918f21a3affb1c921557db9`.
- Replay: 340,92 segundos; 32 cortes mensais; 15.348 eventos; 20 cenários; gate de meta `false`; zero ordens, downloads ou chamadas JEV.
