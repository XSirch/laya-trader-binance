# CICLO 03 — filtro ML de expectativa líquida por nocional

Pré-registro de 28/09/2026, anterior ao treino e ao replay. Esta rodada transfere a regressão de retorno líquido já usada no estudo de baixa volatilidade para o fluxo de candidatos multi-timeframe do Ciclo 02. É uma hipótese de transferência para outro conjunto de sinais, não uma família de ML inédita nem validação independente.

## Hipótese única

Nos candidatos congelados de retomada de tendência e rompimento/continuação, treinar um regressor para prever o retorno líquido por operação sobre o nocional inicial (`net_return`). Selecionar, sem busca de limiar, apenas eventos com previsão **estritamente maior que 0,012**. A pergunta é se essa seleção fixa melhora as operações efetivamente reproduzidas o suficiente para cumprir todos os gates Rev02.

O corte previsto é uma regra de seleção que será testada; não é o gate de aprovação nem prova de EV realizado. A aprovação depende do EV médio observado no replay integral e dos demais gates. Não interpretar score como probabilidade ou retorno garantido.

## Universo e entradas congelados

- Binance Spot e perpétuos USD-M, BTCUSDT e ETHUSDT; Spot só compra. Mercados permanecem separados.
- Reutilizar exatamente os 24 conjuntos de candidatos, features causais, entradas, saídas, custos, sizing e splits do relatório corrigido do Ciclo 02. Nenhuma regra ou label será alterado.
- Fonte: `research/results/cycle02_multiframe_corrected_2026-09-28/research.json` e os 24 arquivos `candidate_labels.csv`, com SHA-256 verificado antes do treino. Manifestos e dados Spot/USD-M também devem coincidir com os hashes do relatório.
- Treino termina em 01/07/2025; calibração diagnóstica vai até 01/01/2026; seleção vai até 01/09/2026, fim exclusivo, com os cortes/purga/embargo implementados em `engine.split_labels` (24 horas). Essas datas já foram examinadas: todo resultado é retrospectivo e exploratório.
- Previsores: exatamente as 48 features registradas no relatório corrigido. `net_return` é o alvo; `net_r` e `label` não entram nas features.

## Modelos e seleção

Treinar, separadamente em cada uma das 24 variantes, um HistGradientBoostingRegressor CPU e um XGBoostRegressor CUDA. Reutilizar os hiperparâmetros registrados do Ciclo 02: HGB `max_iter=160`, `learning_rate=0.05`, `max_leaf_nodes=15`, `min_samples_leaf=60`, `l2_regularization=10`, sem early stopping, `random_state=27`; XGBoost `n_estimators=320`, `max_depth=4`, `learning_rate=0.04`, `subsample=0.8`, `colsample_bytree=0.8`, `min_child_weight=40`, `reg_lambda=10`, `max_bin=256`, `tree_method=hist`, `device=cuda:0`, `n_jobs=4`, `random_state=27`. Se CUDA não estiver disponível, encerrar sem fallback de XGBoost para CPU.

O bloco de calibração será usado apenas para diagnósticos fora do treino: MAE, RMSE, R², correlação, média prevista/observada, baseline constante da média do treino e faixas ordenadas por score. Nenhuma dessas medidas muda o modelo ou o corte. Seleção aplica uma única condição `predicted_net_return > 0.012`; não testar grids, subgrupos, outros thresholds, features ou hiperparâmetros.

As previsões ordenam candidatos simultâneos. O replay permite uma posição global por mercado e reexecuta a mesma seleção uma vez no cenário-base e uma vez com taxa/slippage dobrados, mantendo funding observado. Arquivos de score servem à rastreabilidade; métricas de labels não substituem o replay integral.

## Decisão e limites

Aplicar por variante, mercado e backend, sem juntar amostras. No base: EV médio líquido por nocional inicial `>1.2%`, payoff `>=1`, profit factor `>=1.25`, `>=200` operações completas não duplicadas e `>=8` semanas ativas. No stress, exigir somente PnL líquido agregado positivo, conforme Rev02. Acerto próximo de 70% é preferência; drawdown será medido sem teto.

Comparar com a regra-base correspondente, sem agregar variantes. Uma seleção que falhe qualquer gate continua `target_not_demonstrated`. Mesmo que passe retrospectivamente, as datas históricas não são holdout independente e o resultado não autoriza ordens nem paper automaticamente. A próxima confirmação exige versão e parâmetros congelados e coleta prospectiva independente, com pelo menos 200 trades completos em oito semanas ativas.

## Registro da execução

Antes do treino, registrar hashes do protocolo, script, engine, relatório-fonte, labels, datasets e manifests; confirmar que a pasta de saída não existe. Preservar os relatórios e pesos originais. Registrar tempo, backend/dispositivo efetivo, configuração XGBoost, artefatos, métricas completas e falhas. Não enviar ordens reais.
