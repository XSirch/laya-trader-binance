# Ciclo 09 — exigir o primeiro cruzamento do canal

Registrado em 28/09/2026 antes de gerar rótulos, treinar ou simular esta variação. Status inicial: `preregistered_before_replay`.

## Pergunta

O Ciclo 07 gerou 15.410 eventos com cooldown de 1m, mas o modelo preservou somente 19 candidatos e o portfólio executou 11 trades. Os rótulos tiveram 78,41% de sobreposição. O Ciclo 08 usou pesos por unicidade: a discriminação do score melhorou ligeiramente, mas todos os scores ficaram abaixo do corte fixo de 1,2%. A hipótese seguinte é que os sinais de estado acima/abaixo do canal repetem o mesmo rompimento; exigir uma passagem efetiva pelo nível pode formar eventos mais distintos.

## Única alteração

Para direção longa, emitir candidato somente quando o fechamento anterior estiver `<=` ao canal superior de 300 minutos calculado no candle atual e o fechamento atual ficar `>` a esse nível. Para direção curta, o fechamento anterior deve estar `>=` ao canal inferior do candle atual e o atual ficar `<` a esse nível. O canal continua usando apenas os 300 candles completos anteriores. Depois de sair do canal, novos candidatos só podem surgir após cruzar de volta para dentro e cruzar novamente para fora.

## Elementos preservados do Ciclo 08

- Binance USD-M, BTCUSDT e ETHUSDT; resolução de entrada 1m; volume `>=1,3x` a mediana dos 300 minutos anteriores; cooldown de 1m.
- Features 1m e contexto 1h/4h; XGBoost CUDA expansivo mensal no alvo líquido.
- Pesos por unicidade temporal por rótulo maduro, normalizados para média 1 por fold.
- Stop inicial ATR15 completo, saída `trend_loss` pela EMA21 completa de 15m, hold máximo de 24h e uma posição global.
- Cutoff `predicted_net_return >0,012`, universo, dados, funding, sizing, custos e execução iguais.
- Janela de seleção de 02/01/2026 até 01/09/2026 exclusivo e os mesmos gates Rev02.

## Replay e critérios

Treinar somente com rótulos maduros em cada início mensal: `signal_time < início_do_mês - 24h` e `label_end_time < início_do_mês`. Recalcular pesos de unicidade somente dentro desse conjunto de treino. Reportar baseline sem filtro, sobreposição de rótulos, tamanho efetivo dos folds, scores, trades completos, semanas ativas, EV, taxa de acerto, payoff, PF, drawdown e PnL sob stress.

Gates: EV líquido por trade `>1,2%`, payoff `>=1`, PF `>=1,25`, ao menos 200 trades concluídos em oito semanas ativas e PnL positivo com taxa e slippage dobrados. A taxa de acerto próxima de 70% é preferência, sem piso; sem teto fixo de drawdown. Candidato abaixo de amostra não pode ser declarado consistente, mesmo se EV for positivo.

O replay é retrospectivo e os preços já foram examinados. Se houver sinal promissor, ainda será exigido paper prospectivo congelado com oito semanas ativas e 200 trades antes de qualquer alegação de consistência. Nenhuma ordem real será enviada.

## Integridade

- Script: `research/scripts/cycle09_minute_breakout_first_crossing.py`.
- Testes: `research/tests/test_cycle09_minute_breakout_first_crossing.py`.
- Saída ausente antes do replay: `research/results/cycle09_minute_breakout_first_crossing_2026-09-28/`.
- Validar dataset, manifesto, relatório-pai do C08, protocolo, script e motores por SHA-256.
- Todos os folds devem confirmar `device=cuda:0` e `tree_method=hist`; interromper sem fallback se CUDA falhar.
