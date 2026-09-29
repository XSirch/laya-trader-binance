# Ciclo 08 — ponderação por unicidade temporal no treino

Registrado em 28/09/2026 antes de regenerar rótulos, treinar ou simular esta variação. Status inicial: `preregistered_before_replay`.

## Pergunta

O Ciclo 07 ampliou os eventos de seleção de 1.977 para 4.441, mas 78,41% dos rótulos se sobrepunham no tempo, a correlação do score caiu para 0,038 e o portfólio não ficou maior. A mudança de cooldown também tornou o treino mensal mais denso. O Ciclo 08 mantém o scanner e testa se ponderar cada exemplo pela sua unicidade reduz a influência de rótulos quase repetidos.

## Fórmula congelada

Para cada rótulo de treino maduro `i`, considerar o intervalo semiaberto `[signal_time_i, label_end_time_i)`. Em cada minuto desse intervalo, calcular a concorrência `c(t)` entre rótulos maduros do mesmo ativo e da mesma direção. A unicidade bruta será:

`u_i = média_t(1 / c(t))` dentro do intervalo do rótulo `i`.

Normalizar `u_i` para média 1 dentro de cada fold mensal e passar esses valores como `sample_weight` ao mesmo XGBoost. Pesos usam somente o conjunto que já passou a regra de maturação do fold (`signal_time < mês - 24h` e `label_end_time < início do mês`). Intervalos têm precisão de minuto; intervalos inválidos devem interromper a execução. Reportar min, mediana, máximo, tamanho efetivo da amostra `(soma dos pesos)^2 / soma dos pesos^2` e média-alvo ponderada por fold.

## Elementos preservados

- Binance USD-M, BTCUSDT e ETHUSDT; scanner avalia cada fechamento válido de 1m, cooldown de 1 minuto.
- Breakout/volume com lookback de 300 minutos e volume `>=1,3x` a mediana; features/contexto iguais ao C07.
- Stop ATR de 15m, saída pela EMA21 completa de 15m, limite de hold de 24h e posição única.
- Atualização mensal expansiva, alvo líquido, hiperparâmetros XGBoost CUDA, cutoff fixo `predicted_net_return > 0,012`.
- Dados, janela de seleção, sizing, custos, slippage, funding, execução e gates iguais ao C07.

## Única alteração

O ajuste do XGBoost passa de peso igual por linha para peso de unicidade temporal por intervalo. Todos os candidatos e rótulos continuam disponíveis para score e para a seleção; nada é removido do conjunto de avaliação. O C07 sem ponderação é o controle imediato. Não mudar cutoff, features, stops, lado, timeframe, thresholds ou mercado.

## Replay, gates e limites

Usar a janela já registrada de 02/01/2026 até 01/09/2026 exclusivo e folds mensais, com todos os rótulos de treino amadurecidos e purgados. Aplicar os gates Rev02: EV líquido `>1,2%`, payoff `>=1`, PF `>=1,25`, pelo menos 200 trades concluídos em oito semanas ativas e PnL positivo sob custos dobrados. Acerto próximo a 70% é preferência; drawdown deve ser reportado e minimizado entre candidatos aprovados. Somente trades executados e sem sobreposição contam na amostra operacional; tamanho efetivo descreve treino, não trades.

Esta janela histórica já foi vista. Resultado positivo ainda precisa de validação prospectiva congelada por pelo menos oito semanas ativas e 200 trades antes de qualquer alegação de consistência. Não enviar ordens reais.

## Integridade

- Script: `research/scripts/cycle08_minute_breakout_uniqueness_weights.py`.
- Testes: `research/tests/test_cycle08_minute_breakout_uniqueness_weights.py`.
- Saída ausente antes do replay: `research/results/cycle08_minute_breakout_uniqueness_weights_2026-09-28/`.
- Verificar hash do dataset, do C07 e do motor; salvar pesos/diagnósticos por fold no relatório.
- Confirmar `device=cuda:0` e `tree_method=hist` em cada fold; sem fallback para CPU.
