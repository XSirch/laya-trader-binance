# Protocolo: absorção de fluxo agressor em futuros de um minuto

Congelado em 27/09/2026 antes de obter ou rotular os candles de 1m. Esta hipótese acrescenta granularidade e fluxo agressor em futuros; não retuna RSI, Supertrend, sweep/reclaim, funding carry, lags horários ou o modelo Jev já testados.

## Hipótese e universo

Quando um fluxo comprador ou vendedor extremo não consegue mover o preço na mesma direção, uma contraparte pode estar absorvendo as ordens. O retorno subsequente pode favorecer uma entrada contra o fluxo. Volume de takers é somente um proxy de agressão; não será descrito como liquidação nem como fluxo do livro de ofertas.

- Mercado: contratos perpétuos USDⓈ-M Futures, pares BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT.
- Fonte de barras: arquivos mensais Binance Vision de klines de 1m, janeiro/2024 a agosto/2026; conferir SHA-256 publicado e CRC do ZIP.
- Funding: taxas históricas já arquivadas no repositório; debitar ou creditar cada evento de funding atravessado pela posição.
- Sem ETFs, ações ou outros produtos; sem ordens reais, alavancagem ou margem simulada.

## Sinal congelado

Em cada fechamento de minuto, usar os cinco minutos encerrados mais recentes. Calcular `imbalance5 = 2 * taker_buy_quote_5m / quote_volume_5m - 1`, retorno open-to-close de cinco minutos e volume cotado acumulado.

- Fluxo comprador absorvido: `imbalance5 >= 0,55` e retorno de cinco minutos `<= 0`; sinal SHORT.
- Fluxo vendedor absorvido: `imbalance5 <= -0,55` e retorno de cinco minutos `>= 0`; sinal LONG.
- Em ambos os casos, `quote_volume_5m` deve ser pelo menos 1,5 vezes a mediana dos 144 volumes móveis de cinco minutos anteriores, sem incluir o atual.
- A entrada ocorre na próxima abertura de 1m. Só pode haver uma posição por par; após o fechamento, aguardar 30 minutos antes de aceitar outro sinal.
- Stop fica além da mínima/máxima do bloco de cinco minutos por `0,1 × ATR(14)` de 1m. Ignorar distância de stop menor que 0,15% ou maior que 1,5% do preço de entrada. Alvo fixo em `1,8R` bruto; saída temporal ao fechar a 60ª vela após a entrada.
- Se stop e alvo forem tocados na mesma vela, considerar o stop primeiro. Se a abertura saltar além do stop, usar o preço de abertura como preenchimento adverso.

## Modelo ML e cortes temporais

Um `HistGradientBoostingClassifier` fixo estima se cada operação terminará com PnL líquido positivo. Features causais: retornos de 1/5/15/60m, desequilíbrio de takers de 1/5/15m, múltiplos de volume cotado e contagem de trades, localização do fechamento na faixa, corpo/pavios, amplitude e volatilidade realizada. Sem data, símbolo ou resultado futuro entre as features. Fixar `max_iter=100`, `max_leaf_nodes=7`, `learning_rate=0,05`, `l2_regularization=10`, `min_samples_leaf=40` e `random_state=548`; exigir 400 operações rotuladas no treino ou registrar amostra insuficiente.

- Treino: sinais de 2024; estimador único, sem busca de hiperparâmetros.
- Validação: 2025; único período usado para selecionar limiar de probabilidade entre 0,55 e 0,90, em passos de 0,05.
- Confirmação: janeiro a agosto/2026; limiar fica congelado depois da validação. Não selecionar símbolo nem regra olhando a confirmação.
- Exigir pelo menos 30 operações fechadas na validação para uma triagem. Se nenhum limiar cumprir a meta conjunta, rejeitar esta hipótese; não ajustar stops, filtros ou datas nesta amostra.

## Custos e gates

Retorno por operação será líquido de taxas, slippage fixo e funding, expresso sobre o notional comprometido na entrada. Como a taxa individual varia por conta e programa, usar cenários por lado: 0,10% (0,05% taker mais 0,05% slippage) e estresse de 0,15% (0,05% taker mais 0,10% slippage). O custo de taker de 0,05% é uma hipótese de conta regular, não uma cotação da conta do usuário.

Meta conjunta da validação e confirmação: acerto de pelo menos 70%, payoff líquido mínimo 1:1 (faixa desejada 1,2:1 a 1,5:1), EV líquido superior a 1,2% por operação e drawdown adverso da carteira de no máximo 10%. Dimensionar cada par em um notional fixo igual a 25% do capital inicial, sem alavancagem ou composição. O funding é calculado sobre o notional de entrada. A triagem não comprova consistência; buscar ao menos 100 operações e estabilidade entre períodos antes de considerar qualquer mudança de estado.

## Limites de execução

OHLC de 1m não prova fila, spread ou preenchimento real. O slippage fixo é uma hipótese e o stop pode preencher pior durante gaps. Dados passados de preço já foram vistos no projeto em resoluções maiores, então a confirmação mede novidade de granularidade/fluxo, não um holdout intocado de mercado. Evidência histórica não autoriza ordens reais.

Fontes de formato e integridade: [Binance Public Data](https://github.com/binance/binance-public-data) e [tarifas de USDⓈ-M Futures](https://www.binance.com/en/support/faq/detail/360033544231).
