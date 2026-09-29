# Ciclo 07 — breakout de um minuto sem cooldown adicional

Registrado em 28/09/2026 antes de gerar rótulos, treinar ou simular esta variação. Status inicial: `preregistered_before_replay`.

## Pergunta

O Ciclo 06 preservou a expectativa e o PnL sob stress depois de trocar o stop inicial de ATR de 1m para ATR de 15m, mas o modelo escolheu 19 candidatos e o portfólio executou 11 trades em seis semanas ativas. O ledger mostra que oito candidatos selecionados foram ignorados porque uma posição já estava aberta. Isso não demonstra que o cooldown adicional de 15 minutos seja a causa; ele pode reduzir oportunidades após uma saída, enquanto a posição única explica parte da diferença. O Ciclo 07 mede o efeito isolado do cooldown para verificar se aceitar cada candle elegível de 1m altera seleção, amostra e economia.

## Núcleo preservado do Ciclo 06

- Binance USD-M, BTCUSDT e ETHUSDT, breakout/continuação, uma posição global por mercado.
- Avaliação causal após cada candle fechado de 1m; entrada na abertura seguinte disponível.
- Breakout e volume usam os 300 minutos completos anteriores; volume `>=1,3x` a mediana.
- Features de 1m e contexto completo 1h/4h; direção alinhada à tendência.
- Stop inicial de 1 ATR do último candle completo de 15m; saída por perda da EMA21 de 15m ou stop; limite de 24h.
- XGBoost CUDA com expansão mensal, apenas rótulos maduros, alvo de retorno líquido e cutoff congelado `predicted_net_return > 0,012`.
- Custos, slippage, funding observado, sizing, mercado, dados e janela de seleção iguais ao Ciclo 06.

## Única alteração

O intervalo mínimo entre candidatos repetidos do mesmo ativo e direção cai de 15 minutos para 1 minuto. Assim, todo fechamento de 1m que continue satisfazendo as regras pode gerar um candidato. Nenhum outro parâmetro ou threshold será ajustado.

Esta alteração aumenta rótulos com janelas futuras sobrepostas. O protocolo conta como operação somente cada entrada realmente executada pelo simulador de posição única. Também serão reportados o número e a fração de janelas de rótulos que se sobrepõem; candidatos sobrepostos não serão descritos como observações independentes nem usados para cumprir o gate de trades.

## Replay e critérios

Usar o arquivo USD-M auditado do Ciclo 02 e o mesmo intervalo de 13/08/2024 até 01/09/2026 exclusivo. Treinar mensalmente com rótulos maduros: `signal_time < início_do_mês - 24h` e `label_end_time < início_do_mês`. A janela de seleção continua de 02/01/2026 até 01/09/2026 exclusivo, com o mesmo buffer de saída.

Reportar baseline sem filtro e portfólio filtrado, ambos em cenário-base e stress. Aplicar os mesmos gates Rev02: EV líquido por trade `>1,2%`, payoff `>=1`, PF `>=1,25`, pelo menos 200 trades concluídos em oito semanas ativas e PnL agregado positivo com taxa e slippage dobrados. Acerto próximo a 70% é uma preferência. Medir drawdown sem teto e minimizar apenas entre candidatas que cumpram os demais gates.

O Ciclo 06 selecionou a combinação por já ter atingido os gates econômicos pontuais com poucos trades. Esta nova janela histórica já foi observada e não é validação independente. Mesmo se passar os gates, não autoriza paper nem ordens reais; será necessário congelar a regra e observar período prospectivo de pelo menos oito semanas ativas e 200 trades completos.

## Integridade

- Script: `research/scripts/cycle07_minute_breakout_no_cooldown.py`.
- Testes: `research/tests/test_cycle07_minute_breakout_no_cooldown.py`.
- Saída precisa estar ausente antes do replay: `research/results/cycle07_minute_breakout_no_cooldown_2026-09-28/`.
- Conferir hashes dos dados, protocolo, script, motor, Ciclo 02 e relatório-pai do Ciclo 06.
- Confirmar `device=cuda:0` e `tree_method=hist` em cada fold; abortar se CUDA falhar, sem fallback.
- Nenhuma ordem real será enviada.
