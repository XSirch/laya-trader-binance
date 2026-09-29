# Ciclo 05 — breakout USD-M avaliado em candles de um minuto

Registrado em 28/09/2026 antes de gerar rótulos, treinar ou simular a nova resolução. Status inicial: `preregistered_before_replay`.

## Hipótese e evidência anterior

O Ciclo 04 preservou EV-base de +2,199% e stress positivo ao atualizar o modelo mensalmente, mas executou apenas sete trades em seis semanas ativas; dois movimentos de ETHUSDT concentraram os ganhos. O scanner anterior só criava candidatos em candles de 15 minutos. Esta rodada testa se avaliar o mesmo tipo de breakout em cada fechamento de um minuto melhora a cobertura temporal sem reduzir EV líquido.

Há evidência contrária que precisa permanecer visível: a regra de confluência de indicadores de um minuto teve EV de −0,210% em 2025 e só +0,225% em 27 operações no diagnóstico de 2026 ([resultado anterior](../../docs/minute_indicator_confluence_research_2026-09-27.md)); o classificador LONG/IDLE/SHORT de um minuto teve EV −0,259% em 209 operações de 2025 ([resultado anterior](../../docs/minute_ml_buy_idle_sell_research_2026-09-27.md)). Esses resultados usaram gatilhos, duração e stops diferentes; justificam cautela, não descarte automático do breakout com contexto 1h/4h e saída de tendência.

## Setup congelado

- Mercado: Binance USD-M; apenas BTCUSDT e ETHUSDT.
- Família: breakout/continuação na direção do alinhamento de tendência 1h/4h.
- O estado de entrada é atualizado depois de cada candle de um minuto fechado; a entrada é na abertura seguinte disponível.
- Donchian high/low e baseline de volume usam 300 minutos anteriores completos. O candle atual não entra nesses níveis. O volume atual precisa exceder 1,3 vezes a mediana de volume dos 300 candles anteriores.
- Manter o intervalo mínimo de 15 minutos entre candidatos repetidos do mesmo ativo/direção, igual ao espaçamento em tempo de parede do scanner anterior.
- Features de entrada de 1 minuto e contexto completo de 1h/4h. Stop inicial de 1 ATR calculado em candles de 1 minuto; limite de hold de 24 horas.
- Saída continua sendo stop inicial ou perda da EMA21 de candles completos de 15 minutos, conforme o motor validado do Ciclo 02. Funding observado continua incluído.
- Reajuste mensal expansivo do XGBoost CUDA, igual ao Ciclo 04, só com linhas maduras: `signal_time < início_do_mês - 24h` e `label_end_time < início_do_mês`.
- Um único cutoff imutável: `predicted_net_return > 0.012`. Não avaliar outra faixa, feature, horizonte, cutoff ou exit.
- Sizing, posição global única, taxas, slippage, custos dobrados, funding e gates Rev02 mantidos.

A resolução altera naturalmente indicadores calculados por candle e o stop baseado em ATR: features rápidas passam a descrever minutos e o ATR passa a medir a vela de 1m. Essas consequências fazem parte da única intervenção de resolução; o período de lookback do rompimento/volume fica ancorado em 300 minutos para não encurtar a janela de mercado.

## Janela, replay e gates

Gerar rótulos nos candles auditados de 13/08/2024 até 01/09/2026 exclusivo. Treino walk-forward usa apenas resultados disponíveis antes de cada fold mensal. Seleção histórica mantém 02/01/2026 até 01/09/2026 exclusivo, com buffer de 24h para completar trades. Em cada mês, o modelo produz score uma vez por evento; o portfólio respeita uma posição global por mercado.

Comparar com a regra sem filtro gerada pela mesma nova configuração e reportar o Ciclo 04 apenas como referência não pareada. Gates Rev02 por USD-M: EV-base estritamente acima de 1,2% por trade, payoff mínimo 1:1, PF ≥1,25, pelo menos 200 trades completos em oito semanas ativas, e PnL líquido positivo sob custos dobrados. Acerto próximo a 70% é preferência; drawdown deve ser medido, sem teto.

As faixas de score e as métricas do mesmo bloco de seleção são diagnósticos, não parâmetros para a próxima reexecução. Todos os candles de seleção já foram examinados em estudos anteriores: qualquer resultado continua retrospectivo e exploratório. Nenhum resultado autoriza paper ou ordens reais.

## Integridade e artefatos

- Script: `research/scripts/cycle05_minute_breakout.py`.
- Testes: `research/tests/test_cycle05_minute_breakout.py`.
- Saída prevista: `research/results/cycle05_minute_breakout_2026-09-28/`, ausente antes da execução.
- Confirmar hashes do dataset USD-M, manifesto, relatório-fonte, relatório do Ciclo 04, motor, script e protocolo.
- Cada reajuste precisa registrar `device=cuda:0` e `tree_method=hist`; erro de CUDA aborta a execução, sem fallback.
- Nenhuma ordem real será enviada.
