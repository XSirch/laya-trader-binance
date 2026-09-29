# Protocolo: varredura e reclaim de liquidez intraminuto

Hipótese: um rompimento temporário da máxima ou mínima anterior de 60 minutos que fecha de volta dentro da faixa em cinco minutos pode indicar rejeição do preço extremo. Diferencia-se do rompimento da faixa anterior e do sweep/reclaim de mínima de 24 horas avaliado em barras horárias.

## Universo e dados

- Perpétuos USD-M: BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT.
- Candles completos de 1 minuto e funding histórico, janeiro/2024 a agosto/2026, com arquivos mensais Binance Vision já verificados por SHA-256 e CRC.
- Treino 2024; seleção de limiar ML apenas em 2025; confirmação diagnóstica janeiro–agosto/2026.
- Os dados já foram vistos em outras resoluções e hipóteses de um minuto; nenhum período é um holdout de mercado totalmente intocado.

## Gatilho e execução congelados

No fechamento do minuto `i`, a faixa de 60 minutos usa candles `i-64` a `i-5`, excluindo o bloco atual de cinco candles (`i-4` a `i`). Exigir volume financeiro no bloco atual de 5 minutos >= 1,5 vez a mediana dos 144 volumes móveis anteriores.

- LONG: mínima do bloco de cinco minutos perfura a mínima da faixa anterior de 60 minutos; o fechamento recupera essa mínima, o retorno dos cinco minutos é positivo e o imbalance de taker é `>= 0,20`.
- SHORT: máxima do bloco perfura a máxima anterior; o fechamento volta abaixo dela, o retorno de cinco minutos é negativo e imbalance de taker `<= -0,20`.
- Entrada na próxima abertura de 1 minuto. Stop 0,1 ATR(14) além do extremo do bloco de varredura. Descartar risco menor que 1,5% ou maior que 2,0% da entrada.
- Alvo bruto `1,9R`; fechar no stop, alvo ou após no máximo 60 minutos. Stop primeiro em colisão na mesma vela; gaps além do stop preenchem pela abertura adversa.
- Uma posição por par, cooldown de 30 minutos após a saída, 25% do capital inicial por par, sem alavancagem; funding histórico atravessado entra no PnL.

O piso de stop e alvo foram escolhidos por aritmética antes de consultar os rótulos: com 70% de acerto, risco médio de 1,5%, alvo 1,9R e custo de estresse de 0,15% por lado, o ganho líquido teórico é 2,55%, a perda média líquida 1,80%, payoff 1,42:1 e EV 1,245% do notional. São limites de viabilidade, não previsões de resultado.

## ML e gates

HistGradientBoostingClassifier fixo prevê PnL líquido positivo no custo-base usando as 14 features causais do protocolo de fluxo de um minuto. Hiperparâmetros: `max_iter=100`, `max_leaf_nodes=7`, `learning_rate=0,05`, `l2_regularization=10`, `min_samples_leaf=40`, `random_state=548`. Exigir 400 eventos de treino após declustering de 60 minutos. Testar somente thresholds 0,55 a 0,90 em passos de 0,05, escolhendo no máximo um em 2025.

Custos: 0,10% por lado base e 0,15% estresse, incluindo taxa taker presumida de 0,05% e slippage de 0,05%/0,10%. Um limiar só passa se ambos os custos produzirem ao menos 30 operações, acerto líquido `>=70%`, payoff líquido `>=1:1` (alvo ideal `1,2–1,5`), EV líquido `>1,2%` por operação sobre notional e drawdown adverso `<=10%`. Exigir ao menos 100 operações na validação e confirmação para discutir consistência inicial.

Se o treino for insuficiente ou a validação falhar, não selecionar limiar, par, stop ou alvo com a confirmação de 2026. Nenhuma ordem real ou chamada Jev será enviada.
