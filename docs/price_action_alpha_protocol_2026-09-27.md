# Protocolo: confluência de ação de preço com modelo de retorno em R

## Propósito e limite

Esta é uma hipótese nova inspirada somente nas categorias que o fornecedor do GainzAlgo descreve publicamente: pressão de volume, tendência multitemporal, níveis de estrutura/preço e alvos/stop por volatilidade. As páginas do fornecedor não publicam as regras nem os parâmetros do Alpha. Este estudo implementa uma estratégia independente e explicável; não é uma cópia nem uma reconstrução do indicador. Consulte [a avaliação GainzAlgo](gainzalgo_v2_alpha_assessment_2026-09-27.md).

O histórico 1h de Binance Spot para BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT, de 2023-01 até 2026-08, já foi consultado em outras pesquisas neste projeto. Este replay será walk-forward e causal, mas todo resultado histórico é exploratório sob risco de múltiplas tentativas. Não é um holdout intocado nem pode autorizar negociação real. Nenhuma ordem ou chamada JEV é permitida.

## Hipótese congelada

Uma varredura e recuperação confirmada de uma mínima recente, acompanhada por contexto de tendência, fluxo comprador e volatilidade apropriada, pode distinguir algumas entradas de reversão de ruído. Um modelo HGB treinado somente em episódios anteriores pode estimar o retorno bruto de cada evento em unidades de risco e evitar entradas cujo retorno esperado não cobre os custos.

## Dados e relógio

- Carregar apenas os arquivos mensais Spot 1h já armazenados e verificados pelo `manifest.json` e pelos `.CHECKSUM` originais, de 2023-01 a 2026-08.
- Começar a curva de carteira no primeiro timestamp comum sem lacunas depois da última quebra conhecida do arquivo, para que buy-and-hold e os replays de eventos sejam marcados em uma linha temporal contínua. Features e eventos anteriores ainda podem entrar no treino apenas se cada lookback e cada label estiverem completos.
- Calcular cada feature com candles fechados até o candle do sinal. Para executar, esperar um candle horário completo após o fechamento do sinal e entrar na abertura seguinte. Se o stop estrutural for tocado durante essa hora de espera, cancelar a entrada.
- Excluir eventos sem 72 candles consecutivos anteriores, sem volume taker válido, com qualquer lacuna no episódio futuro de 24 horas ou sem candle de entrada/saída completo.
- Gerar no máximo um evento por ativo a cada 24 horas; a cadência vale mesmo quando o modelo não compra.

## Sinal e features

Para cada candle de sinal, definir `support24` como a menor mínima dos 24 candles anteriores. O evento long acontece se a mínima do candle atual ficar abaixo de `support24` e seu fechamento terminar acima de `support24`. A carteira é Spot long/caixa. BUY abre a posição; não há short.

Usar uma lista fechada de features causais: profundidade do sweep e reclaim em unidades ATR14; corpo, amplitude, posição do fechamento e pavio inferior do candle; retorno do próprio ativo e BTC nos horizontes de 6/24/72 horas; ATR14 e amplitude realizada de 24 horas; volume de cotação do evento relativo à média anterior de 24 horas; fração de compras taker (`2*taker_buy_base/volume - 1`); distância em ATR ao nó de maior volume entre bins de preço calculados sobre as 72 horas anteriores; proporção do volume do bin dominante. Sem indicadores futuros, notícias, símbolos escolhidos após os resultados ou features perp/funding.

## Barreira, alvo ML e execução

No candle do sinal, `stop = signal_low - 0.10 * ATR14`. Na abertura de entrada, `R = entry - stop`; descartar se `R <= 0`, se `R/entry > 2 * ATR14_pct` ou se o período de espera tocou o stop. Fixar alvo em `entry + 2R` e saída temporal em 24 horas.

O rótulo do modelo é o retorno bruto final dividido por `R`: +2 se o alvo for atingido, aproximadamente -1 no stop (pior se houver gap), ou o retorno aberto-a-aberto observado no limite temporal. Se stop e alvo forem ambos atingidos no mesmo candle, assumir stop primeiro. Um stop aberto além do nível é executado na abertura adversa; o alvo não recebe melhoria além do preço observado na abertura. O rótulo só fica disponível depois do candle que determina a saída estar fechado.

Treinar `HistGradientBoostingRegressor` uma vez no início de cada mês, usando todos os eventos passados cujo resultado estava disponível estritamente antes do corte, com mínimo de 400 rótulos; sem treino suficiente, ficar em caixa. Parâmetros congelados: loss quadrática, profundidade 3, 100 iterações, learning rate 0,05, 7 folhas, mínimo 40 amostras por folha, regularização L2 10, 64 bins, seed 548, sem early stopping. Não otimizar parâmetros com os resultados posteriores.

Entrar somente quando `predicted_gross_R * (R/entry) > 2 * side_cost`, isto é, quando o retorno bruto estimado exceder o custo estimado de entrada e saída. Comparar com o controle que opera todos os eventos. Custos fixos presumidos: 0,15% e 0,30% por lado. Cada entrada aloca 25% do equity disponível, no máximo uma posição por símbolo e sem alavancagem; o total não pode superar 100% do equity. Não há piramidagem.

## Métricas, controles e decisão

Reportar por custo e por ano: contagem de eventos/sinais/entradas, frequência de cada motivo de descarte, MAE/MSE e skill contra média de treino e zero, retorno líquido, CAGR apenas descritivo, drawdown horário e limite adverso intrahorário, giro, taxas, exposição, payoff/R médio, turnover e distribuição dos resultados por ativo. Controles: operar todo sweep qualificado sem gate ML, buy-and-hold igualmente ponderado dos quatro ativos, caixa. Conservar cada cenário e cada erro do replay.

O gate geral existente é retorno líquido anual de 50% e drawdown máximo de 10%; o replay histórico exploratório não pode por si só satisfazer consistência nem o gate. Mesmo um resultado positivo só justificará congelar uma nova versão e observá-la prospectivamente em paper. Sem resultados ainda observados, não selecionar o ativo que liderou.

## Comparação contra famílias já testadas

Já foram testados RSI/indicadores técnicos, modelos com dezenas de fatores de momento/fluxo/volatilidade/estrutura, confluência de breakout, HGB amplo e previsões com lags. Também foram testados rótulos genéricos de barreira stop/target e gestão de risco/trailing. Não repetir essas grades. A diferença específica deste protocolo é restringir os exemplos ao evento causal `varreu e recuperou a mínima de 24h`, acrescentar histograma de volume por preço no contexto do evento e prever diretamente o retorno do plano de saída, sob entrada atrasada. A sobreposição de features e resultados anteriores continua declarada como risco de seleção.
