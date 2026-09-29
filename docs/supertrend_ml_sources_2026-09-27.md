# Fontes: Supertrend e avaliação com custo

Pesquisa em 27/09/2026. O [material oficial do TradingView sobre Supertrend](https://www.tradingview.com/support/solutions/43000634738-supertrend/) descreve o indicador como tendência baseada em ATR, publica as bandas `HL2 ± multiplicador × ATR`, a recorrência das bandas finais e o uso da linha para detectar mudanças de tendência e posicionar stops. A [estratégia oficial Supertrend](https://www.tradingview.com/support/solutions/43000645068-supertrend-strategy/) descreve entradas compradas nas mudanças de direção definidas pelo indicador. O teste adota uma implementação explícita dessas fórmulas, com regra long/cash adequada a Spot.

O [repositório de dados públicos da Binance](https://github.com/binance/binance-public-data/blob/master/README.md) descreve os arquivos mensais, timestamps, conteúdo OHLCV e checksums. O replay usa os arquivos locais já conferidos em `data/binance/spot/1h/manifest.json`; não baixa série nova para este experimento.

A semelhança com GainzAlgo limita-se às categorias amplamente anunciadas de tendência e volatilidade/stop dinâmico. A estratégia usa fórmula pública conhecida e não afirma copiar o preset Alpha, cuja regra privada não está disponível.

O histórico de preços já foi usado na seleção de outras famílias, portanto esta avaliação é exploratória. Velas OHLC não provam fills, slippage, spread, prioridade intrabar ou impacto. Os custos de 0,15% e 0,30% por lado são cenários, não as taxas verificadas da conta.
