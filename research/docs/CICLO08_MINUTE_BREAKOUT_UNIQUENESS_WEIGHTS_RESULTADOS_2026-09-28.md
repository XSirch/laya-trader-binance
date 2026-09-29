# Ciclo 08 — resultados da ponderação por unicidade

Executado em 28/09/2026 conforme o [protocolo congelado](CICLO08_MINUTE_BREAKOUT_UNIQUENESS_WEIGHTS_PROTOCOLO.md). Resultado operacional: `no_trade_after_fixed_cutoff`; a ponderação melhora alguns diagnósticos do score, mas não apresenta estratégia negociável na janela.

## Resultado

O scanner, conjunto de avaliação e execução são os mesmos do C07. Apenas as linhas de treino mensal passaram a usar peso de unicidade temporal.

| Métrica | C07: peso igual | C08: unicidade | Leitura |
|---|---:|---:|---|
| Eventos na seleção | 4.441 | 4.441 | inalterado |
| Fração dos rótulos sobreposta | 78,41% | 78,41% | candidatos inalterados |
| Trades filtrados | 11 | 0 | cutoff fixo não selecionou trades |
| Maior score previsto | +3,354% | +0,668% | C08 ficou abaixo do cutoff +1,2% |
| Correlação score/retorno | 0,038 | 0,145 | maior em C08 |
| R² | −0,054 | +0,010 | pequeno ganho em C08 |
| MAE | 0,551% | 0,459% | C08 abaixo do baseline 0,535% |
| RMSE | 1,181% | 1,145% | C08 abaixo do baseline 1,151% |

Sem score acima do cutoff, não há EV, payoff, profit factor ou taxa de acerto de trades para avaliar. Zero operações e zero drawdown não significam retorno positivo. O baseline sem filtro, mantido para diagnóstico, perdeu EV de −0,182% com 749 trades; no stress, EV −0,395%, PF 0,197 e drawdown 78,69%. Portanto, o stop ATR15 por si só não compensa uma entrada sem filtro.

## O que funcionou e o que não

Os pesos foram efetivamente não uniformes e reduziram o tamanho efetivo dos dados de treino. No primeiro fold, 10.949 linhas tiveram tamanho efetivo de 6.104; no último, 14.767 linhas tiveram tamanho efetivo de 8.415. O score ficou menos impreciso que o modelo sem pesos do C07, mas retornos previstos ficaram conservadores: nenhum de 4.441 sinais atingiu o cutoff congelado. Não baixar o cutoff para forçar trades, pois isso mudaria a meta e não provaria EV acima de 1,2%.

O C08 preserva como hipótese útil a ponderação por unicidade para evitar confiança excessiva em candidatos repetidos. Ele não valida a estratégia nem substitui a evidência do C06; aquele C06 ainda é o único replay 1m desta sequência com EV-base +1,262% e stress positivo, mas depende de 11 trades e três grandes vencedores.

## Decisão e próximo teste

Não aprovar o C08 como sistema de entrada, pois não abriu trade. Preservar a ponderação para o próximo teste e manter o cutoff. A alteração seguinte será exigir um cruzamento causal do nível Donchian: fechamento anterior dentro ou no canal e fechamento atual além do canal. A regra deve emitir apenas a primeira passagem para fora enquanto preço permanecer no mesmo movimento, reduzindo rótulos redundantes. Stop ATR15, saída EMA21/15m, cooldown de 1m, features do modelo, pesos, cutoff, execução, custos e janela permanecem congelados.

Toda a janela foi vista em replays anteriores; os resultados são retrospectivos. Nenhuma ordem real foi enviada nem autorizada.

## Proveniência

- Relatório JSON: [`cycle08_minute_breakout_uniqueness_weights_2026-09-28/research.json`](../results/cycle08_minute_breakout_uniqueness_weights_2026-09-28/research.json); hashes completos no `research/EXPERIMENTS.jsonl`.
- Oito modelos XGBoost confirmaram `device=cuda:0` e `tree_method=hist`.
- Três testes de unicidade passaram antes do replay.
