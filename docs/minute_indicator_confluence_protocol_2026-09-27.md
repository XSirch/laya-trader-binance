# Protocolo: confluência de RSI, MACD, Fibonacci, tendência e volume em 1 minuto

Este teste operacionaliza a ideia do usuário de combinar indicadores em um sinal buy/sell/idle. O script local aplica regras numéricas; o HGB estima probabilidade de PnL positivo. Jev não decide direção e não recebe milhares de chamadas históricas.

## Universo e indicadores

- Perpétuos USD-M: BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT.
- Candles completos de 1 minuto e funding histórico, janeiro/2024 a agosto/2026; arquivos Binance Vision mensais com SHA-256 e CRC já verificados.
- EMA200 e RSI14 de Wilder; MACD(12,26,9) e histograma; zona Fibonacci 38,2%–61,8% da faixa de máxima/mínima dos 240 minutos anteriores, usando candles até `i-5`; retorno, imbalance taker e múltiplo de volume dos cinco minutos encerrados.

## Sinais congelados

Exigir volume cotado de cinco minutos `>=1,5×` a mediana dos 144 volumes móveis anteriores, e o preço dentro da zona Fibonacci de 38,2%–61,8% da faixa prévia de quatro horas.

- LONG se preço acima da EMA200, RSI14 entre 30 e 55, histograma MACD ainda `<=0` mas crescente em cada um dos três últimos minutos e imbalance taker de cinco minutos `>=0,15`.
- SHORT se preço abaixo da EMA200, RSI14 entre 45 e 70, histograma MACD ainda `>=0` mas decrescente nos três últimos minutos e imbalance `<=-0,15`.
- No máximo um evento por direção/par até que a condição deixe de valer; entrada na próxima abertura de 1 minuto.
- Stop na mínima da faixa anterior de quatro horas para LONG e na máxima para SHORT, acrescido de 0,1 ATR(14) de 1m para fora da faixa. Ignorar risco abaixo de 1,5% ou acima de 2,0% da entrada.
- Alvo bruto de `1,9R`, prazo máximo de 60 minutos, stop primeiro em colisão e preço de abertura adverso após gap além do stop.
- Uma posição por par, cooldown de 30 minutos depois da saída, 25% do capital inicial por par, sem alavancagem. Funding atravessado entra no resultado.

## ML, períodos e critérios

Usar HGB para prever se o PnL líquido no custo-base será positivo. Features incluem os 14 campos de fluxo do protocolo de um minuto, RSI14, histograma MACD normalizado, distância da EMA200 e posição relativa na faixa Fibonacci. Hiperparâmetros fixos: `max_iter=100`, `max_leaf_nodes=7`, `learning_rate=0,05`, `l2_regularization=10`, `min_samples_leaf=40`, `random_state=548`; treino exige 400 eventos após declustering de 60 minutos.

- Treino 2024; selecionar no máximo um limiar entre 0,55 e 0,90 em passos de 0,05 usando apenas 2025; confirmar com limiar congelado em janeiro–agosto/2026.
- Custos laterais: 0,10% base e 0,15% estresse, sendo 0,05% de taker presumido mais 0,05%/0,10% de slippage.
- Passar os gates em ambos os custos: ao menos 30 operações, acerto `>=70%`, payoff líquido `>=1:1` (ideal 1,2–1,5), EV líquido `>1,2%` do notional por operação e drawdown adverso `<=10%`. Exigir 100 operações na validação e confirmação para avaliar consistência inicial.
- Se treino ou validação falhar, não ajustar thresholds, indicadores, stop, alvo ou par olhando 2026. Histórico já visto em outras pesquisas não é holdout intocado.
