# Protocolo: reclaim de VWAP a favor da tendência

## Hipótese e sinal

Hipótese independente das regras de momentum e spread já avaliadas: um reclaim da VWAP móvel de 60 minutos a favor da tendência de 15 minutos pode marcar a retomada após um pullback.

Universo fixo: BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT perpétuos USD-M, candles de um minuto e funding histórico. Calcular VWAP de 60 barras até o fechamento atual, ponderando o preço de fechamento por volume-base estimado como quote volume dividido pelo fechamento. Tendência usa candles de 15 minutos completos: long somente se o último fechamento de 15m estiver acima da EMA200 de 15m e a EMA subir contra seu valor de quatro candles atrás; short com as duas condições invertidas.

Sinal long quando o fechamento de 1m cruza de baixo para cima da VWAP, com volume de quote dos últimos cinco minutos >=1,5 vezes a mediana das 144 observações anteriores, uma por minuto, da mesma janela móvel de cinco minutos (lookback de 144 minutos, excluindo a observação atual). Sinal short é simétrico. Entrada na abertura do minuto seguinte. Congelar ATR14 no sinal; stop a 1,0 ATR e alvo a 1,5 ATR da entrada. Executar o primeiro nível tocado por high/low; stop primeiro se a mesma barra tocar os dois. Gap além do stop preenche na abertura adversa; gap além do alvo preenche na abertura favorável. Se nenhum nível ocorrer, fechar na abertura após 60 minutos.

Um ativo só pode manter uma operação por vez, com cooldown de 30 minutos após saída. Notional fixo de 25% do capital por trade, sem alavancagem. PnL líquido incorpora retorno real do contrato, funding e custo de 0,10%/0,15% por ordem (ida e volta 0,20%/0,30% do notional), respectivamente em custo base e estresse.

## ML e validação

HGB prevê resultado líquido positivo no custo base. Features causais congeladas: distância/slope da EMA200 de 15m, distância da VWAP, volume relativo, imbalance taker, ATR%, volatilidade realizada de 60m, retornos de 5/15/60m e RSI14. Descartar o período inicial de cinco spans da EMA200 para reduzir efeito da inicialização. Hiperparâmetros fixos: `max_iter=100`, `max_leaf_nodes=7`, `learning_rate=0,05`, `l2_regularization=10`, `min_samples_leaf=40`, `random_state=773`.

Treino em 2024, decluster por ativo e janela de 60 minutos; seleção de um threshold entre 0,55 e 0,90 em passos de 0,05 somente em 2025; confirmação diagnóstica em janeiro–agosto/2026 apenas com threshold congelado. Treino mínimo 400 eventos; pelo menos 30 operações para triagem e 100 para validação/confirmação.

Gate simultâneo em custos base e estresse: acerto líquido >=70%, payoff >=1:1 (ideal 1,2–1,5), EV líquido >1,2% do notional por operação e drawdown adverso <=10%. Não ajustar regra pela confirmação. Não enviar ordens nem chamar Jev. Candles históricos já examinados não contam como holdout intocado.
