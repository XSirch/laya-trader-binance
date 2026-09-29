# CICLO 02 — resultados do treino e da sensibilidade ML

Atualizado em 28/09/2026.

> **INVALIDADO: somente a primeira execução e seus derivados descritos nas seções abaixo.** As chamadas passaram descrições dos exits quando o simulador exigia modos canônicos; os trades usaram stop inicial e saída por tempo. Esses modelos, limiares e diagnósticos não representam as saídas registradas e servem apenas à auditoria. A reexecução corrigida e a sensibilidade sobre seus modelos aparecem nas seções iniciais deste documento.

## Reexecução corrigida — concluída, sem candidata aprovada

O protocolo preservou entradas, dados, folds, custos, sizing, thresholds e gates; corrigiu apenas o roteamento e a validação estrita dos modos de saída. Os 2 testes determinísticos passaram; o smoke dos dois mercados já havia passado. Antes de treinar, os rótulos foram calculados em separado e tiveram hashes distintos nos 8 grupos mercado/família/horizonte (3 modos por grupo).

Foram produzidas 72 comparações: 24 regras, 24 HGB CPU e 24 XGBoost CUDA. Os dados de Spot e USD-M foram verificados (2.157.120 candles de 1m por mercado, 13/08/2024 a 01/09/2026 exclusivo). Os 48 artefatos de modelo foram preservados; os 24 boosters XGBoost foram relidos e confirmaram `device=cuda:0` e `tree_method=hist` em seus classificadores e regressores. GPU: NVIDIA GeForce RTX 4070 Laptop, driver 617.14, 8.188 MiB. Nenhuma ordem real foi enviada.

**Resultado:** zero de 72 comparadores e zero de 480 combinações de ML/threshold passaram todos os gates. Nenhuma combinação ML chegou a 200 trades; o maior número foi 99. Só 17/480 tiveram EV base positivo e 2/480 também ficaram positivos no stress. O maior EV observado foi +0,590% em 1 trade e 1 semana ativa, com +0,289% no stress; está abaixo do gate EV >1,2% e não fornece amostra. Nas regras, o EV base ficou entre −0,319% e −0,243% em Spot e entre −0,226% e −0,195% em USD-M; o stress continuou negativo. Nenhuma estratégia foi encontrada.

Os limiares foram avaliados no bloco histórico de seleção, já observado em pesquisas anteriores; isto não é holdout independente nem evidência prospectiva. A pasta completa é [cycle02_multiframe_corrected_2026-09-28](../results/cycle02_multiframe_corrected_2026-09-28/), com sumário em [research.json](../results/cycle02_multiframe_corrected_2026-09-28/research.json). Hash do relatório: `3d0a1c6a3bf8e2275fd3f4444920a4c1f5a8f776b094283e316b5b20234e680d`. A análise de thresholds 0,05–0,30 está pré-registrada em [CICLO02_SENSIBILIDADE_CORRIGIDA_PROTOCOLO.md](CICLO02_SENSIBILIDADE_CORRIGIDA_PROTOCOLO.md); continua exploratória e não independente.

## Sensibilidade corrigida — sem candidata

Foram reutilizados os 48 modelos e os rótulos corrigidos, sem refit, em 288 combinações (seis thresholds de 0,05 a 0,30). Os hashes-fonte de todos os modelos e 24 conjuntos de rótulos foram conferidos. Treze combinações tiveram EV base positivo, nenhuma ficou positiva no stress e nenhuma passou todos os gates.

Os limiares baixos ampliaram a amostra em 16 combinações para pelo menos 200 trades e oito semanas, mas todas tiveram EV base negativo. A melhor delas foi USD-M, breakout de 24h, saída `trend_loss`, XGBoost, threshold 0,15: 201 trades, 34 semanas, EV −0,162% e EV no stress −0,376%. O maior volume foi 397 trades e 34 semanas, com EV −0,254% e stress −0,465%. O melhor EV bruto entre todas as combinações foi +0,106%, mas em apenas cinco trades e quatro semanas, com stress −0,185%. Portanto, afrouxar o cutoff aumentou a frequência sem produzir expectativa líquida suficiente.

Esse replay usa a mesma janela retrospectiva de seleção e não é holdout independente. Não houve treino novo nem ordens reais. Os detalhes completos estão em [research.json](../results/cycle02_corrected_threshold_sensitivity_2026-09-28/research.json), SHA-256 `6c6021166aaf9a0484ff69cef786d82c3cd7cb00c8f088926a14801b1a773208`.

## Feature gain corrigido — descritivo, sem edge

Nos 24 classificadores XGBoost corrigidos, todos tiveram divisões por features. A extração cobriu 1.152 linhas (48 features por modelo) e não fez treino, previsão, threshold ou replay de trades. Nos 12 modelos de retomada de tendência, `atr_pct` ficou entre as três features de maior ganho em todos os exits, nos quatro grupos mercado/horizonte. Em rompimentos Spot, `vol_ratio` também ficou no top 3 em todos os exits nos dois horizontes. Esses padrões descrevem decisões internas do classificador no treino; não mostram se a relação é positiva, causal ou rentável.

Os CSVs por modelo e o resumo por grupo estão em [cycle02_corrected_feature_diagnostics_2026-09-28](../results/cycle02_corrected_feature_diagnostics_2026-09-28/), conforme [protocolo](CICLO02_FEATURE_DIAGNOSTICS_CORRIGIDO_PROTOCOLO.md). A primeira extração, feita sobre modelos com exits mal ligados, continua inválida e não foi reutilizada. A hipótese seguinte partiu do mecanismo econômico sugerido pelo handoff: medir custos de ida e volta em relação à distância causal do stop inicial de 1 ATR.

## Filtro de custo relativo ao stop — sem candidata

Foi testado o filtro único pré-registrado `custo ida e volta / distância do stop inicial <= 0,25`, com custos conhecidos no sinal, em 24 variantes fixas de BTCUSDT/ETHUSDT Spot e USD-M. O replay permaneceu na janela de seleção histórica já observada; é exploratório, sem validação independente. O protocolo está em [CICLO02_CUSTO_STOP_FILTER_PROTOCOLO.md](CICLO02_CUSTO_STOP_FILTER_PROTOCOLO.md).

O filtro manteve 1 de 5.871 candidatos Spot e 598 de 11.384 USD-M. Nenhuma variante atingiu 200 operações completas; o máximo foi 61, e zero de 24 passou os gates. Em Spot, a única operação elegível teve EV base de +1,607% e stress de +1,353%, mas payoff e profit factor não são estimáveis com uma operação. A mesma operação reaparece em linhas de variantes com horizontes/saídas diferentes, portanto não constitui evidência replicada. Em USD-M, as variantes de retomada de tendência ficaram entre +0,055% e +0,108% de EV base, com stress negativo e amostra de 50–60 operações; as demais também foram insuficientes ou negativas. O filtro rejeita-se nesta janela; não será ajustado outro cutoff sobre os mesmos dados.

O relatório completo tem SHA-256 `6688dbd5180e002cf4087f59ce2377ec2940835cfadd4940e4e6b925705fb370`; o ledger com 1.326 linhas tem SHA-256 `4b90550c3d567a00f2cba09a6c9ac4336861da46d82f15fd2aee3e8361d41717`. Não houve treinamento, uso da GPU ou ordens reais.

O protocolo congelado desse replay também exigia EV médio positivo e payoff ≥1 no stress, condições mais rígidas que a Rev02, cujo gate de stress é PnL líquido agregado positivo. Elas ficam preservadas como parte do registro do experimento; não alteram a conclusão porque nenhuma variante alcançou sequer os gates-base de amostra e EV. A implementação futura foi alinhada à Rev02 em [CICLO02_ALINHAMENTO_GATES_REV02.md](CICLO02_ALINHAMENTO_GATES_REV02.md).

## Diagnóstico de trajetória corrigido — informativo, sem estratégia

O primeiro arquivo de trajetória foi invalidado antes da interpretação porque tratava a saída `stop_gap` como candle completo. A correção também classifica `target_gap` como ambíguo. Os artefatos da primeira extração permanecem em `cycle02_path_diagnostics_2026-09-28/` apenas para auditoria; não usar suas métricas. A correção foi pré-registrada em [CICLO02_PATH_DIAGNOSTICS_CORRECAO_PROTOCOLO.md](CICLO02_PATH_DIAGNOSTICS_CORRECAO_PROTOCOLO.md), seguindo o [protocolo original](CICLO02_PATH_DIAGNOSTICS_PROTOCOLO.md).

A extração corrigida cobre 24 variantes fixas, em cenário-base e stress, com 40.241 linhas de trades. Ela separa excursões de candles completos das barras de saída por `stop`, `target`, `stop_gap` e `target_gap`. Trades repetidos entre horizonte/saída/mercado continuam sendo observações dependentes; os totais não representam 40.241 operações independentes nem contam para gates.

Nos candles completos anteriores à saída, a mediana MFE dos vencedores foi 1,532R no cenário-base, contra 0,267R dos perdedores; a mediana MAE foi 0,485R para vencedores e 0,865R para perdedores. Sob stress, vencedores tiveram mediana MFE 1,494R e perdedores 0,089R. A fricção estimada mediana consumiu 1,11–1,18R nas variantes Spot base e 0,65–0,69R nas USD-M; com custos dobrados, 2,23–2,46R e 1,31–1,43R, respectivamente. Funding está separado, positivo quando pago e negativo quando recebido. Esses números descrevem a janela histórica, não causalidade nem edge.

Stops/gaps foram a causa dominante nas saídas fixas e trailing. O trailing quase sempre saiu por stop e não melhorou a expectativa negativa; a saída por perda da EMA21 predominou nas variantes de retomada de tendência, também sem produzir EV positivo. A fricção alta e MFE reduzida entre perdedores apontam que trocar somente a saída não resolveu as entradas/custos. Nenhuma variante passou os gates e não foi executado treino, uso da GPU ou envio de ordens.

Relatório: [research.json](../results/cycle02_path_diagnostics_corrected_2026-09-28/research.json), SHA-256 `5a8e584fc872fd5bf3742db5ef590dbe25b53527a5539fb39ce1e1576cf9407d`; ledger por trade: SHA-256 `39e0a6194778834a3122921755fbf14ff6f7ebb9864eca9d84027af0662dad18`; sumário por variante/cenário: SHA-256 `d01ef7b62337ecc278b1f140011809037abc58f0f346ee76307babd79465db28`. A execução é post hoc e não constitui validação independente.

## Primeira execução — INVALIDADA; preservar apenas para auditoria

- Protocolo principal congelado antes da execução: [CICLO02_PRE_REGISTRO.md](CICLO02_PRE_REGISTRO.md).
- Resultado completo do treino e dos 72 comparadores: [research.json](../results/cycle02_multiframe_2026-09-28/research.json).
- Sensibilidade de limiar pós-hoc com os modelos congelados: [research.json](../results/cycle02_threshold_sensitivity_2026-09-28/research.json), conforme [protocolo suplementar](CICLO02_SENSIBILIDADE_LIMIAR_PROTOCOLO.md).
- Diagnósticos de ganho do XGBoost: [ganho por modelo](../results/cycle02_ml_pattern_diagnostics_2026-09-28/xgb_gain_by_model.csv), [resumo por mercado/família/horizonte](../results/cycle02_ml_pattern_diagnostics_2026-09-28/xgb_gain_pattern_summary.csv) e [configuração dos boosters](../results/cycle02_ml_pattern_diagnostics_2026-09-28/xgb_device_config.json).
- Motores de pesquisa: [multi-timeframe](../scripts/cycle02_multiframe_research.py), [sensibilidade de limiar](../scripts/cycle02_threshold_sensitivity.py) e [diagnóstico de padrões](../scripts/cycle02_ml_pattern_diagnostics.py).

Foram treinados 24 modelos HGB em CPU e 24 modelos XGBoost CUDA para BTCUSDT e ETHUSDT em Spot e USD-M. O XGBoost confirmou build CUDA antes do treino e recusaria fallback para CPU; todos os 24 modelos gravaram `device=cuda:0` e `tree_method=hist`. A GPU reportada pelo sistema é NVIDIA GeForce RTX 4070 Laptop GPU, com 8.188 MiB e driver 617.14. Nenhuma ordem real foi enviada.

Os dados verificados têm 2.157.120 candles de 1m por mercado, de 13/08/2024 até 01/09/2026 exclusivo. Treino encerra em 01/07/2025, calibração em 01/01/2026 e seleção em 01/09/2026, com purge/embargo de 24h. São datas históricas já examinadas em outras pesquisas, não um holdout intocado.

## Resultado da primeira execução — INVALIDADO

Foram executadas as 12 variantes registradas por mercado: retomada de tendência e breakout/continuação, horizontes máximos de 6h e 24h, e três planos de saída. Cada variante foi comparada por regra fixa, HGB CPU e XGBoost CUDA, totalizando 72 linhas. Nenhuma combinação mercado/modelo/saída passou os gates.

O classificador com limiar mínimo 0,35 praticamente não abriu operações: HGB não encontrou score suficiente em nenhuma variante; XGBoost Spot também não; no USD-M, três variantes de saída reutilizaram o mesmo único trade perdedor. O sinal discreto não representa três confirmações independentes. Nenhum dos 48 modelos ML passou gate.

As regras sem ML também falharam em todas as variantes. O EV base variou de −0,314% a −0,182% em Spot e de −0,222% a −0,137% em USD-M. O EV mediano foi −0,264% em Spot e −0,178% em USD-M. No stress, a mediana foi −0,587% e −0,380%, respectivamente.

## Sensibilidade da primeira execução — INVALIDADA

Depois de observar a falta de scores acima de 0,35, foi registrado um protocolo suplementar para examinar 0,05–0,35 em passos de 0,05. O replay reutilizou os mesmos 48 modelos, rótulos, entradas, saídas, sizing, custos, funding e janela de seleção; nenhum modelo foi ajustado novamente. Como a faixa foi escolhida após inspecionar essa janela, os resultados são somente diagnósticos retrospectivos.

Nas 336 combinações modelo/threshold, zero passou os gates completos. Houve 177 resultados de portfólio com ao menos um trade; 18 tiveram EV base positivo, nenhum excedeu 1,2%, e seis tiveram EV positivo no stress. Nenhum deles aprovou os gates de EV, amostra, frequência, payoff, profit factor e stress em conjunto.

| Mercado e modelo | EV selecionado min/médio/máx | Trades selecionados min/médio/máx | Stress EV médio | Modelos com EV base positivo | Modelos com ≥200 trades e ≥8 semanas | Gates completos |
|---|---:|---:|---:|---:|---:|---:|
| Spot HGB | −0,309% / −0,146% / +0,121% | 53 / 81 / 135 | −0,481% | 3/12 | 0/12 | 0/12 |
| Spot XGBoost CUDA | −0,320% / −0,118% / +0,188% | 32 / 70 / 135 | −0,442% | 3/12 | 0/12 | 0/12 |
| USD-M HGB | −0,320% / −0,027% / +0,222% | 1 / 105 / 364 | −0,215% | 6/12 | 3/12 | 0/12 |
| USD-M XGBoost CUDA | −0,268% / +0,044% / +0,336% | 1 / 116 / 346 | −0,136% | 6/12 | 3/12 | 0/12 |

Médias e extremos da tabela resumem modelos diferentes; não são um portfólio combinado. Os limiares de cada modelo foram escolhidos sobre o mesmo bloco histórico de seleção.

O melhor resultado retrospectivo foi USD-M, breakout/continuação com prazo de 24h, XGBoost CUDA e limiar 0,15. Os três planos de saída selecionaram o mesmo conjunto de trades, portanto contam como uma só descoberta, não três réplicas:

| Métrica | Resultado | Gate |
|---|---:|---:|
| Trades / semanas ativas | 39 / 17 | ≥200 / ≥8 |
| EV líquido por nocional inicial | +0,336% | >+1,2% |
| EV no stress integral | +0,153% | >0% |
| Acerto | 17,95% (7 vencedores) | preferência próxima a 70%, sem piso |
| Payoff / profit factor | 7,61 / 1,57 | ≥1 / ≥1,25 |
| Drawdown máximo | 4,38% | medir e minimizar |

Apesar de payoff e profit factor acima dos mínimos, o EV ficou 0,864 ponto percentual abaixo da meta e houve só 39 trades. A distribuição também é concentrada: o maior vencedor teve retorno de +13,97%; removê-lo reduz o EV médio a −0,023%. Remover os três maiores vencedores reduz o EV a −0,363%. Ao baixar o limiar para 0,05, o mesmo modelo chegou a 186 trades e 35 semanas, mas o EV caiu a −0,117%, o stress a −0,360%, o profit factor a 0,81 e o drawdown a 17,72%. Mais sinais não resolveram a falta de expectativa.

## Feature gain da primeira execução — INVALIDADO

Os números de feature gain desta seção vieram dos rótulos cujos modos de saída estavam ligados incorretamente. Eles são inválidos para formular ou escolher uma hipótese e não devem ser reutilizados.

Mesmo em treino válido, ganho em árvores seria estatística descritiva de divisão, não causalidade. Os resultados desta execução específica estão invalidados; não usar o destaque de Fibonacci/volatilidade/tendência como pista empírica. O pré-registro principal já lista estudos próximos para evitar repetir entradas de varredura/reclaim, rompimento de 60m com fluxo, classificador LONG/IDLE/SHORT de 1m, VWAP/pullback e short-only de baixa volatilidade.

## Decisão registrada pela primeira execução — INVALIDADA

As conclusões desta execução foram invalidadas junto com seus rótulos e modelos. Não usar o candidato de +0,336% nem a proposta de filtro derivada do feature gain para escolher ou rejeitar uma estratégia. Os resultados válidos são os da reexecução e da sensibilidade corrigidas acima; qualquer hipótese seguinte deve ser registrada antes do replay e permanecer retrospectiva enquanto usar o mesmo bloco de seleção.

Também permanecem as limitações de candle de 1m (ordem intraminuto ambígua, stop priorizado quando stop e alvo ocorrem no mesmo candle), custos configurados em vez de verificados na conta, ausência de liquidação simulada em USD-M e uso retrospectivo de datas já observadas.
