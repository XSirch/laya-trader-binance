# Protocolo: Supertrend horário com filtro ML de operações

## Motivo e hipótese

O inventário pesquisado não contém a regra Supertrend. Ele já contém médias, rompimentos, RSI, momentum, fatores amplos de ATR/ADX/volume/fluxo, modelos ML semanais, stops e barreiras. Para não repetir essas grades, este teste fixa uma única regra ATR de tendência e pergunta se um modelo de retorno por operação consegue filtrar falsos sinais sem alterar a regra base.

O indicador combina direção de tendência com uma linha trailing por ATR, aproximação transparente das categorias gerais de tendência, volatilidade e SL/TP divulgadas pelo GainzAlgo V2 Alpha. Não é o indicador privado nem uma inferência de sua implementação.

## Sinais e modelo

- Usar exclusivamente candles Spot de 1 hora de BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT. O estudo começa na primeira segunda-feira 00:00 UTC sem lacunas depois da lacuna documental de março de 2023 e termina em 31/08/2026 00:00 UTC.
- Calcular Supertrend padrão com ATR de Wilder de 10 candles, multiplicador 3, bandas base `HL2 ± 3 × ATR` e bandas finais conforme a fórmula publicada pelo TradingView. Fixar os parâmetros; não testar grades.
- Gerar sinal ao fechamento horário confirmado. Uma transição para alta compra Spot na abertura da hora seguinte; transição para baixa fecha a posição na próxima abertura. Spot long/cash, sem short, alavancagem, stop separado ou reentrada intrabar.
- Comparar a regra Supertrend sem filtro a uma variante com HistGradientBoostingRegressor que prevê o retorno líquido de uma operação completa, da próxima abertura após o flip de alta até a abertura após o próximo flip de baixa.
- O modelo é ajustado conjuntamente entre ativos, em ordem cronológica, somente com operações cuja saída executável já ocorreu antes do sinal atual. Exigir pelo menos 100 operações fechadas. Features fixas no sinal: distância do fechamento à linha Supertrend em ATR, ATR/preço, retornos de 4 e 24 horas, volatilidade realizada de 24 horas e volume horário relativo à média anterior de 24 horas. Não incluir nome do ativo, timestamp absoluto ou features futuras.
- Fixar `HistGradientBoostingRegressor(max_iter=100, max_leaf_nodes=7, learning_rate=0.05, l2_regularization=1.0, min_samples_leaf=20, early_stopping=False)`. Treinar uma instância para cada custo com alvos líquidos já descontando ida e volta. Entrar apenas quando a previsão de retorno líquido for maior que zero.

## Replay e avaliação

Cada ativo recebe 25% do capital inicial em conta isolada. Comparar compra e manutenção, caixa, Supertrend sem ML e Supertrend com filtro ML a custos de 0,15% e 0,30% por lado. Reportar retorno líquido, CAGR, drawdown nas aberturas, drawdown adverso intrahorário, operações, custos, exposição média, contagem de previsões, erro contra retorno zero e média de treino, resultados por ativo e ano.

Avaliar o período walk-forward completo e o período posterior iniciado em 06/01/2025, terminando em 31/08/2026. O histórico posterior já foi inspecionado em outras estratégias e não é holdout global intocado. Um resultado positivo aqui é apenas hipótese para paper prospectivo; não autoriza negociar.

Não ajustar indicadores, modelo, limiar de entrada ou custos após observar os resultados. Não enviar ordens, chamar JEV ou alterar o watcher paper.
