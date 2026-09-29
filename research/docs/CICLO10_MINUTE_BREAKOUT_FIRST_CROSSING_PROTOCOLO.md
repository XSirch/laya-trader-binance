# Ciclo 10 — transição causal do estado de rompimento

Registrado em 28/09/2026 antes de gerar rótulos, treinar ou simular esta variação. Status inicial: `preregistered_before_replay`.

## Correção aprendida no Ciclo 09

O primeiro protocolo comparou o fechamento anterior com o canal atual. Esse canal contém o high/low da barra anterior, portanto a condição de entrada permaneceu verdadeira durante os rompimentos e os candidatos ficaram byte a byte idênticos ao C08. O Ciclo 09 está preservado como implementação não informativa. Este protocolo corrige a comparação de estado e adiciona teste explícito para canal móvel.

## Hipótese e única alteração

Para long, um sinal novo exige ao mesmo tempo que o fechamento anterior esteja `<=` ao Donchian high do candle anterior e que o fechamento atual esteja `>` ao Donchian high calculado no candle atual. Para short, exige fechamento anterior `>=` ao Donchian low anterior e fechamento atual `<` ao Donchian low atual. Os níveis continuam a usar apenas os 300 candles completos anteriores; a linha anterior é obtida por `shift(1)`. Assim, a barra atual precisa cruzar para fora enquanto a barra anterior ainda estava dentro/no canal. Permanecer fora não emite sinal repetido; retornar para dentro e cruzar de novo pode emitir outro.

## Elementos preservados do Ciclo 08

- Binance USD-M, BTCUSDT e ETHUSDT; resolução 1m, volume `>=1,3x` a mediana dos 300 minutos, cooldown de 1m.
- Features de 1m e contexto 1h/4h; XGBoost CUDA expansivo mensal, rótulos maduros e alvo de retorno líquido.
- Ponderação por unicidade média inversa da concorrência dentro de `[signal_time, label_end_time)`, apenas com linhas maduras por fold, normalizada para média 1.
- Stop inicial de 1 ATR do último candle completo de 15m; saída por stop ou perda da EMA21 de 15m; hold máximo de 24h.
- Uma posição global por mercado; cutoff `predicted_net_return >0,012`; custos, slippage, funding, sizing e execução inalterados.
- Mesmo dataset USD-M auditado e mesma janela de seleção: 02/01/2026 a 01/09/2026 exclusivo.

## Replay e critérios

Gerar rótulos novamente pela regra corrigida e treinar mensalmente com `signal_time < início_do_mês - 24h` e `label_end_time < início_do_mês`. Reportar contagens por ativo/lado, sobreposição de rótulos, tamanho efetivo ponderado, score, trades efetivamente executados, semanas ativas, EV, taxa de acerto, payoff, PF, drawdown e stress.

Gates Rev02: EV líquido por trade `>1,2%`, payoff `>=1`, PF `>=1,25`, no mínimo 200 trades completos em oito semanas ativas e PnL positivo com taxa e slippage dobrados. Acerto de aproximadamente 70% é preferência sem piso; drawdown é medido sem teto. Nenhum resultado abaixo da amostra pode ser declarado consistente.

O replay é retrospectivo. Se houver avanço, ainda será necessária validação prospectiva congelada com ao menos oito semanas ativas e 200 trades completos. Nenhuma ordem real será enviada.

## Integridade

- Script: `research/scripts/cycle10_minute_breakout_first_crossing.py`.
- Testes: `research/tests/test_cycle10_minute_breakout_first_crossing.py`.
- Saída ausente antes do replay: `research/results/cycle10_minute_breakout_first_crossing_2026-09-28/`.
- Validar os hashes de dados, manifesto, C09 (tentativa inválida), C02 e motores.
- Todos os folds devem confirmar `device=cuda:0` e `tree_method=hist`; interromper sem fallback.
