# Hipótese de sazonalidade de fim de semana

Consulta em 27/09/2026. Escopo: novidade frente à pesquisa local, evidência primária sobre retornos/atividade sazonais e avaliação da regra proposta de zerar Spot aos sábados e recomprar às segundas, às 00:00 UTC. Nenhum código, backtest ou teste foi executado.

## Conclusão

A regra de calendário ainda não aparece nos relatórios anteriores deste projeto. É uma hipótese nova para o repositório, não uma descoberta inédita: retornos por dia da semana e fim de semana foram estudados na literatura. A evidência mais recente consultada não sustenta tratar o efeito de retorno de segunda-feira como robusto. O padrão com apoio mais consistente é de menor atividade e volatilidade no fim de semana; isso, sozinho, não diz se os preços cairão enquanto a carteira estiver fora.

## O que os estudos mostram

- Caporale e Plastun estudaram retornos diários de BTC, LTC, XRP e DASH em 2013–2017 e simularam compra de BTC na segunda-feira e venda no fim do dia. A amostra completa foi lucrativa no simulador, mas o resultado não foi estatisticamente distinto do acaso na maioria dos anos. O relatório de simulação registra spread fixo de 2 pontos; não é estimativa das tarifas, spread e slippage atuais da Binance. A escolha de segunda veio da mesma amostra usada para avaliar a regra, portanto o estudo não demonstra desempenho prospectivo independente. [Artigo original e simulação](https://www.ifo.de/DocDL/cesifo1_wp6716.pdf).
- A revisão de Müller (2024), sobre 500 moedas, conclui que o efeito positivo de segunda do Bitcoin não persiste depois de 2015 e não encontra anomalia robusta de retorno; encontra atividade menor no fim de semana. O resumo também relata efeito médio de segunda geralmente negativo no corte transversal, com intervalos de confiança largos. [Artigo original](https://doi.org/10.1016/j.frl.2024.105429).
- Hansen, Kim e Kimbrough analisaram BTC/ETH em Binance, Coinbase Pro e Uniswap. Encontraram menor volume e volatilidade no fim de semana; incluir periodicidade semanal melhora previsões de volatilidade fora da amostra em modelos GARCH. Isso apoia testar previsão de risco/execução por dia, mas não comprova retorno direcional negociável nem lucro após custos. [Estudo dos autores](https://arxiv.org/abs/2109.12142). Kinateder e Papavassiliou igualmente não encontraram efeito clássico de dia da semana nos retornos de BTC em 2013–2019, embora encontrem risco condicional menor no fim de semana. [Artigo](https://doi.org/10.1016/j.frl.2019.101420).

## Novidade no histórico local

Os relatórios locais descrevem regras técnicas diárias, previsões de retorno de sete dias decididas no fechamento de domingo e executadas na segunda, e uma combinação com rebalanceamento na segunda. Nenhum deles usa o dia da semana como sinal de retorno ou manda a carteira ficar em caixa todo o fim de semana. A coincidência do horário de decisão/execução com segunda-feira não equivale a testar sazonalidade. [Rodada diária e semanal](extended_research_2026-09-26.md), [combinação multifatorial](multifactor_research_2026-09-26.md), [comparação de regras](research_2026-09-26.md).

## Regra a avaliar e limites

Regra fixa candidata: para a cesta Spot BTCUSDT/ETHUSDT/BNBUSDT/SOLUSDT, manter os pesos do benchmark; vender a cesta na abertura de sábado 00:00 UTC e recomprá-la na abertura de segunda 00:00 UTC. Comparar com a mesma cesta comprada e mantida, incluindo controle com rebalanceamento semanal definido antes do replay. Sinais e ordens simuladas devem usar a abertura seguinte a candles já completos; não usar fechamento ou preço idealizado. Horário UTC e timestamps devem ser verificados contra os arquivos oficiais da Binance. [Formato e arquivos públicos oficiais](https://github.com/binance/binance-public-data/blob/master/README.md).

O custo é o risco central: a regra acrescenta, por ativo, uma venda e uma recompra por semana (104 lados de ordem por ano). Aos custos hipotéticos locais de 0,15%/0,25% por lado, a fricção simples de primeira ordem equivale a cerca de 15,6%/26% do capital inicialmente exposto por ano, antes de slippage adicional e variação do notional. O benefício só existe se a perda média evitada durante as 48 horas superar esse giro, os demais custos e o custo de oportunidade de altas no fim de semana. Esses números são aproximações, não PnL.

O replay de 2023–agosto/2026 pode medir histórico, mas esse período já foi examinado em outros estudos e não é um holdout intocado. Relatar contribuição de retorno das 48 horas, custos, turnover, drawdown, resultados por ano/ativo e intervalos de incerteza; não ajustar regra ou cesta ao resultado. Se houver resultado histórico favorável, congelar a versão e confirmar prospectivamente em paper com preços executáveis e tarifas da conta. Até lá, não há evidência de vantagem líquida ou consistência para esta regra.
