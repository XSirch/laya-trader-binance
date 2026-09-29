# Protocolo: classificador ML intraminuto LONG / IDLE / SHORT

Este é o teste mais próximo do fluxo pedido pelo usuário: a cada minuto, combinar indicadores e produzir LONG, IDLE ou SHORT. O classificador local seleciona a ação; Jev não toma a decisão e não faz chamadas retrospectivas.

## Universo e features

- Perpétuos USD-M BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT.
- Candles de 1 minuto e funding de janeiro/2024 a agosto/2026, usando os arquivos Binance Vision já baixados e verificados por SHA-256 e CRC.
- Features causais: imbalance e retornos de 1/5/15/60m, volume e número de trades relativos, RSI14 Wilder, MACD(12,26,9), distância da EMA200, posição relativa na faixa Fibonacci de 240 minutos, localização/corpo/pavios do candle e volatilidade de 60m.
- Treino usa um estado por hora e par, com offsets fixos 00/15/30/45 min para BTC/ETH/BNB/SOL. Os rótulos usam horizonte máximo de 60 minutos, sem sobrepor estados de treino. Inferência e replay de execução acontecem a cada minuto.

## Rótulos e negociação

No preço de entrada da próxima abertura, avaliar separadamente LONG e SHORT com stop fixo de 1,5% do preço e alvo bruto de 1,9R (2,85%). Funding atravessado entra no PnL. Se o stop e o alvo forem tocados na mesma vela, o stop conta primeiro; gaps além do stop usam a abertura adversa. O rótulo será LONG se o resultado líquido da perna long for positivo e superar o resultado short por pelo menos 0,05 ponto percentual; SHORT na condição simétrica; IDLE em qualquer outro caso. O treino exige 400 rótulos horários.

Aplicar o modelo em cada minuto. Entrar somente quando a probabilidade da classe LONG ou SHORT for pelo menos o limiar congelado e superar as outras duas classes. Uma posição por par, cooldown de 30 minutos após a saída, 25% do capital inicial por par, sem alavancagem, duração máxima 60 minutos.

## Modelo, custos e gates

HistGradientBoostingClassifier fixo: `max_iter=100`, `max_leaf_nodes=7`, `learning_rate=0,05`, `l2_regularization=10`, `min_samples_leaf=40`, `random_state=548`, sem parada antecipada. Treino em 2024; testar limiares 0,55–0,90 em passos de 0,05 e escolher no máximo um usando 2025; limiar fica congelado para confirmação de janeiro–agosto/2026.

Custos por lado: 0,10% base e 0,15% estresse, incluindo 0,05% de taker presumido e slippage de 0,05%/0,10%. Exigir nos dois custos ao menos 30 operações, acerto líquido `>=70%`, payoff líquido `>=1:1` (ideal 1,2–1,5), EV líquido `>1,2%` do notional comprometido e drawdown adverso `<=10%`. Exigir 100 operações na validação e confirmação para avaliar consistência inicial. Se 2025 falhar, não ajustar features, limiar, barreiras ou pares olhando 2026.

O stop e alvo foram fixados antes de gerar rótulos. Com 70% de acerto e risco 1,5%, a saída 1,9R produz, no cenário estressado, ganho líquido teórico de 2,55%, perda líquida de 1,80%, payoff de aproximadamente 1,42 e EV de 1,245% do notional. Isso mostra apenas viabilidade aritmética; não é uma previsão de desempenho.

Os dados foram examinados em outras pesquisas, então 2025/2026 não constituem holdout de mercado intocado. Nenhuma ordem real será enviada.
