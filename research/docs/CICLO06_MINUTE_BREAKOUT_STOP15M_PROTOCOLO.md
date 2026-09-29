# Ciclo 06 — breakout de um minuto com stop ATR de 15 minutos

Registrado em 28/09/2026 antes de gerar rótulos, treinar ou simular a variação. Status inicial: `preregistered_before_replay`.

## Pergunta

O Ciclo 05 mudou o scanner de 15m para 1m e, por consequência, usou ATR de 1m no stop. O resultado ficou negativo: 1.476 operações sem filtro tiveram EV de −0,202% e acerto de 2,17%; o filtro XGBoost executou duas operações perdedoras. Como scanner, features e escala do stop mudaram em conjunto, não é possível atribuir a falha a um fator. O Ciclo 06 isola o stop: mantém scanner e features de 1m e restaura o ATR de 15m do núcleo de breakout que ficou positivo no Ciclo 04.

## Núcleo mantido

- Binance USD-M: BTCUSDT e ETHUSDT; família breakout/continuação.
- Avaliar depois de cada candle fechado de 1m; entrada na abertura seguinte disponível.
- High/low do breakout e mediana de volume usam os 300 minutos completos anteriores; confirmação de volume `>=1,3x` a mediana.
- Intervalo mínimo de 15 minutos entre candidatos repetidos do mesmo ativo/direção.
- Features base 1m e contexto completo 1h/4h, iguais ao Ciclo 05.
- Saída `trend_loss`: stop inicial ou perda da EMA21 de candles completos de 15m. Limite de hold de 24h e funding observado continuam iguais.
- Atualização mensal expansiva de XGBoost CUDA com rótulos maduros conforme Ciclo 04.
- Mesmo cutoff `predicted_net_return >0,012`, uma posição global por mercado, sizing, taxas e slippage.

## Única alteração

O stop inicial volta a ser `1 ATR` de candles completos de 15 minutos. Em cada sinal de 1m, usar o último valor ATR15 já fechado; nunca usar a barra de 15m ainda aberta. Permanecem inalterados o scanner de 1m, as features base de 1m, o alvo, o modelo, o corte e os demais parâmetros. O campo ATR cru que define a distância do stop usa a escala de 15m; a feature `atr_pct` do modelo permanece calculada em 1m, como no Ciclo 05.

## Replay, gates e limites

Gerar rótulos nos candles auditados de 13/08/2024 até 01/09/2026 exclusivo. Treinar o modelo em folds mensais usando somente labels maduros: `signal_time < início_do_mês - 24h` e `label_end_time < início_do_mês`. Seleção permanece 02/01/2026 até 01/09/2026 exclusivo, com o buffer de 24h de saída.

Reportar regra sem filtro e filtro mensal separadamente; comparar com o Ciclo 05 como ablação pareada do stop e com o Ciclo 04 apenas como referência não pareada, pois a entrada é diferente. Gates Rev02: EV-base `>1,2%`, payoff `>=1`, PF `>=1,25`, pelo menos 200 trades completos em oito semanas ativas e PnL líquido positivo sob custos dobrados. Acerto próximo a 70% é preferência; drawdown deve ser medido, sem teto. Não ajustar thresholds, features ou outros parâmetros com esta janela.

A janela de seleção é histórica e já foi observada. Mesmo que os gates sejam atingidos, isso não é validação independente nem autoriza paper ou ordens reais. Nenhuma ordem real será enviada.

## Integridade

- Script: `research/scripts/cycle06_minute_breakout_stop15m.py`.
- Testes: `research/tests/test_cycle06_minute_breakout_stop15m.py`.
- Saída ausente antes da execução: `research/results/cycle06_minute_breakout_stop15m_2026-09-28/`.
- Conferir hash do dataset USD-M e manifesto, relatórios dos Ciclos 02 e 05, motor, script e protocolo.
- Confirmar `device=cuda:0` e `tree_method=hist` em cada mês; abortar sem fallback se CUDA falhar.
