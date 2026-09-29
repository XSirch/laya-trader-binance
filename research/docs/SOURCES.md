# Fontes consultadas em 27/09/2026

## Binance — fontes primárias

- Arquivos públicos, formato de candles, checksums e mudança de timestamp Spot para
  microssegundos a partir de 2025: https://github.com/binance/binance-public-data
- Spot trailing stop, trailingDelta/BIPS, ordens compatíveis e filtros:
  https://developers.binance.com/en/docs/products/spot/faqs/trailing-stop-faq
- USD-M REST Trade / New Algo Order, parâmetros e endpoint de condicionais:
  https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade

A documentação da Binance confirmou diferenças entre Spot e futuros. O pacote NÃO
implementa ordens reais; as referências servem à especificação do adaptador pendente.

## scikit-learn — fontes primárias

- Calibração de probabilidades e separação entre treino e calibração:
  https://scikit-learn.org/stable/modules/calibration.html
- Divisões temporais e gap, como contexto do protocolo causal:
  https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html

O código usa janelas explícitas com purging por fim do rótulo e embargo; não declara
que TimeSeriesSplit sozinho resolveria o problema de rótulos de trades sobrepostos.

## Contexto verificado do projeto existente

Repositório consultado via conector GitHub: https://github.com/XSirch/laya-trader-binance

Arquivos lidos: README.md, pyproject.toml, src/jev_trader/derivatives_data.py; árvore
consultada na revisão `a2c9d6e8c978e39f10b160410c1ba4ff033e0714`.
O README identifica a pipeline atual como Jev Binance Research, sem envio de ordens,
e avisa que parte de 2025–2026 já foi inspecionada. O módulo derivatives_data foi usado
como referência de caminhos de arquivos oficiais de funding/mark; nenhum resultado
histórico dele foi apresentado como resultado deste novo modelo.

## O que as fontes não demonstram

Nenhuma fonte prova que as oito hipóteses implementadas sejam lucrativas ou que obtenham
70% de acerto. Isso requer os próprios experimentos reproduzíveis e um teste reservado.
