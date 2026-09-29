# Ciclo 03 — regressão direta de retorno líquido

Execução concluída em 28/09/2026. Resultado: `target_not_demonstrated`; nenhuma variante passou os gates Rev02.

## Desenho e integridade

O [protocolo congelado](CICLO03_DIRECT_NET_EV_PROTOCOLO.md) transferiu a regressão de retorno líquido já usada no estudo de baixa volatilidade para os mesmos 24 conjuntos de candidatos multi-timeframe do Ciclo 02. HGB CPU e XGBoost CUDA foram treinados por variante, com um corte fixo `predicted_net_return > 0,012`. Não houve busca de limiar, novas features, ajuste de hiperparâmetros nem alteração de entrada ou saída.

Foram ajustados 48 regressores: 24 HGB e 24 XGBoost. Os 24 boosters XGBoost registraram `device=cuda:0` e `tree_method=hist`; não houve fallback para CPU. Os 24 arquivos de rótulos e os dois datasets foram verificados contra os hashes do relatório corrigido do Ciclo 02. O treino usou os blocos já definidos, e a avaliação ocorreu de 02/01/2026 a 01/09/2026 (fim exclusivo), janela histórica que já havia sido observada. Portanto, o resultado é exploratório e não independente.

## Resultado

Só 8 dos 48 modelos selecionaram ao menos um candidato; 40 selecionaram zero. Nenhum dos 48 replays passou os gates. O maior EV médio observado foi **+0,788% por trade**, abaixo do piso estrito de +1,2%, e veio de apenas 18 operações:

| Mercado / variante | Modelo | Candidatos selecionados | Trades base | Semanas ativas | EV base | Payoff | PF | DD máximo | PnL líquido stress |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| USD-M, rompimento/continuação, 24h, saída por perda da EMA21 | XGBoost CUDA | 35 | 18 | 14 | +0,788% | 10,43 | 2,78 | 2,02% | +US$ 214,06 |
| USD-M, rompimento/continuação, 24h, saída por perda da EMA21 | HGB CPU | 46 | 23 | 15 | +0,670% | 10,55 | 2,36 | 2,40% | +US$ 164,35 |
| Spot, rompimento/continuação, 24h, saída por perda da EMA21 | XGBoost CUDA | 43 | 22 | 12 | +0,567% | 7,51 | 2,06 | 2,61% | −US$ 55,41 |

O primeiro caso tem PnL agregado positivo sob custos estressados, mas falha o EV e a amostra: 18 trades, contra 200 requeridos. O segundo também falha EV e amostra. A linha Spot falha EV, amostra e stress. Os demais modelos tiveram EV negativo ou amostras ainda menores. Não somar modelos, saídas ou mercados para aumentar a contagem.

Como diagnóstico do regressor, o MAE de calibração foi menor que o baseline constante pela média do treino em apenas 4/24 variantes para cada backend. A mediana do R² de calibração foi −0,108 no HGB e −0,124 no XGBoost. Esses números não provam ausência de qualquer sinal, mas não sustentam capacidade preditiva estável neste teste.

## Decisão

Rejeitar esta transferência do regressor estático para a janela e o corte testados: zero variantes passou os gates. Isso não apaga o achado exploratório de que os dois backends produziram portfólios USD-M positivos nessa mesma configuração. Não reduzir o corte nem escolher outra variante usando esse bloco histórico.

### O que preservar e o que precisa mudar

Preservar como hipótese a combinação USD-M, breakout/continuação de 24h e saída `trend_loss` (perda da EMA21). HGB e XGBoost tiveram EV-base positivo e PnL positivo sob stress nessa combinação; ambos capturaram os mesmos grandes movimentos de ETHUSDT em 07/04 e 19/08. Isso é um padrão exploratório repetido entre dois estimadores, não uma validação independente: os dados, features, rótulos e período são os mesmos.

O setup sem filtro continuou negativo (EV-base −0,222%, PF 0,464 e drawdown 45,94%; sob stress, EV −0,444%). Portanto, não há evidência para usar o rompimento sem seleção. A parte mais fraca da tentativa foi a estimativa estática de EV: os modelos foram treinados até 01/07/2025 e mantidos sem atualização durante uma seleção de oito meses; na janela de calibração, o decil de maiores scores teve retorno médio realizado negativo tanto no HGB (−0,374%) quanto no XGBoost (−0,406%), apesar das previsões médias positivas. Só 18 e 23 operações foram executadas pelos portfólios filtrados. Ao remover o maior vencedor, o EV cai para +0,077% no XGBoost e +0,116% no HGB; os ganhos dependem de poucos episódios de tendência.

Assim, a próxima mudança fica limitada à atualização do modelo: reestimar mensalmente o mesmo XGBoost com rótulos já encerrados e dados disponíveis à época. Entrada, saída, features, alvo, hiperparâmetros, cutoff, sizing e execução ficam congelados. A rodada será walk-forward retrospectiva e exploratória, pois reutiliza o período já observado; mesmo um resultado melhor não conta como validação independente nem autoriza paper ou ordens reais.

## Artefatos e proveniência

- Relatório completo, pesos, scores selecionados, trades base/stress e bins de calibração: [`cycle03_direct_net_ev_2026-09-28`](../results/cycle03_direct_net_ev_2026-09-28/).
- SHA-256 de `research.json`: `bed6b62195fd4f4f333c52e945580014c642bb8a1195b4a042debab591252cc6`.
- SHA-256 do protocolo: `fba3b7b0be89a2aa6acc8298c0bc67d7c1c6318125a6be2a1861a2a54f6f1cf8`.
- SHA-256 do script: `c65cd54f2add047a949c85dc84bf0d21e345df8e0c3c90a6d3d459050b7e37e7`.
- Tentativa registrada em `research/EXPERIMENTS.jsonl`; treino GPU concluído, sem ordens reais.
