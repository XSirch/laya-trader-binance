# Ciclo 13 — capacidade retrospectiva das oportunidades C06

**Estado:** `capacity_possible_only_in_pooled_universe`; nenhuma estratégia foi aprovada. Diagnóstico calculado em 28/09/2026 com o [protocolo pré-registrado](OPPORTUNITY_CAPACITY_PROTOCOL_2026-09-28.md), a partir dos candles oficiais USD-M já usados pelo Ciclo 06. Não houve retreino, chamada paga ou ordem real.

## Resposta

O scanner C06 gerou 1.977 candidatos completos e únicos na janela de seleção, antes do filtro XGBoost. A média dos 200 maiores retornos líquidos foi **+2,029%** na base e **+1,502%** sob taxas e slippage dobrados, usando os mesmos 200 eventos escolhidos pelo retorno-base. Isso mostra apenas capacidade retrospectiva potencial no universo USD-M agrupado de BTCUSDT e ETHUSDT.

O resultado não se mantém ao separar os pares: a média dos 200 maiores foi **+0,850% em BTCUSDT** e **+1,115% em ETHUSDT**, ambas abaixo de 1,2%. As quatro divisões por par/direção também ficaram abaixo do piso. Portanto, somente a combinação dos dois pares deixa o teto acima do alvo; o resultado agregado não prova capacidade em cada par.

## Medidas por universo

| Grupo C06 / USD-M | Candidatos completos | EV de todos na base | EV dos 200 maiores na base | EV sob stress da mesma coorte | Semanas ativas dos 200 | Eventos dos 200 com sobreposição |
|---|---:|---:|---:|---:|---:|---:|
| BTCUSDT + ETHUSDT, long e short | 1.977 | −0,215% | **+2,029%** | **+1,502%** | 32 | 169/200; máximo de 10 simultâneos |
| BTCUSDT, long e short | 1.111 | −0,224% | +0,850% | +0,455% | 34 | 125/200; máximo de 7 simultâneos |
| ETHUSDT, long e short | 866 | −0,205% | +1,115% | +0,725% | 33 | 115/200; máximo de 5 simultâneos |

O conjunto de todos os candidatos teve acerto de 13,76% e profit factor de 0,494 na base; seu EV foi negativo. Em cada par/direção, o teto de EV-base também ficou aquém de 1,2%: BTC long +0,177%, BTC short +0,387%, ETH long +0,374% e ETH short +0,358%.

Na coorte agrupada dos 200 maiores, todos os retornos-base foram positivos. Por isso, payoff e profit factor da base são indefinidos por falta de perdas; não devem ser interpretados como métricas aprovadas. Sob stress, essa mesma coorte teve acerto de 84%, payoff 3,346 e profit factor 17,569. Uma seleção independente dos 200 maiores retornos de stress produziu EV de +1,591%; é outro limite-oráculo, não a mesma carteira.

## O que isso demonstra — e o que não demonstra

O protocolo ordenou retornos conhecidos depois de observar cada desfecho. Os 200 escolhidos são, portanto, uma seleção-oráculo. Além disso, 169 eventos se sobrepõem temporalmente, formando 316 pares sobrepostos e até 10 intervalos simultâneos. A gestão C06 limita a uma posição global; esses resultados não representam 200 operações executáveis nem fornecem uma curva de carteira ou drawdown.

O teto relaxado responde que o conjunto combinado contém uma cauda retrospectiva capaz de exceder 1,2%. Ele **não** demonstra que o classificador identifica essa cauda antes da entrada. O relatório C06 já registra score fraco (correlação 0,140; retorno realizado médio de −0,088% no decil de maior previsão) e apenas 11 trades efetivamente executados em seis semanas. Nenhum dos gates completos — amostra executável, oito semanas, EV, payoff/PF, stress e risco de carteira — foi aprovado.

As estatísticas agrupadas não devem esconder o resultado por par. Como a estratégia C06 define BTC e ETH como um universo USD-M fixo com risco compartilhado, a tabela mostra o agrupamento previsto e também os limites de cada par; qualquer próxima avaliação precisa conservar essa distinção e contabilizar a restrição de uma posição global.

## Integridade e artefatos

- A rotina existente de carga confirmou o SHA-256 do arquivo consolidado contra o manifesto e validou a continuidade dos candles. Os recibos dos ZIPs mensais não foram baixados nem revalidados nesta execução; a verificação foi do dataset normalizado já disponível.
- 1.977 IDs únicos; zero duplicados, zero resultados incompletos, zero valores não finitos e zero saídas após o limite temporal. Cada retorno tem custos e funding observados, pela mesma rotina de simulação C06.
- [Ledger por candidato](../results/opportunity_capacity_candidates_2026-09-28.csv) e [resultado JSON](../results/opportunity_capacity_2026-09-28.json) preservam os retornos-base e stress, timestamps, direção e saída.
- O resultado original do Cycle 06 (`research/results/cycle06_minute_breakout_stop15m_2026-09-28/`) não existe no worktree atual. Os resumos do Ciclo 06 foram usados para contexto, não para reconstruir os scores. O ZIP local do handoff também não contém scores nem labels C06.

## Próximo passo

O primeiro passo da proposta C12 foi concluído. O passo de ordenação requer previsões walk-forward C06 por candidato para comparar os grupos de score a controles aleatórios/simples; esses arquivos não estão disponíveis no checkout nem no ZIP inspecionado. Não repetir o treino C06 só para reconstruir artefatos ausentes. Preservar o diagnóstico negativo do ranking C06 e avançar para uma hipótese de entrada distinta, congelada antes do cálculo de retornos, com regra de saída e custos fixos, teste temporal e abstenção explícita. A família de falha de rompimento com retomada de nível descrita na proposta é uma próxima hipótese possível, ainda não testada nem presumida lucrativa.

O protocolo, a proposta C12, os critérios atuais e este resultado permanecem em pesquisa retrospectiva. A estratégia continua `target_not_demonstrated`; não há autorização para ordens reais.
