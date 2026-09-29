# C19 — Microestrutura: fontes de profundidade e viabilidade

**Data:** 2026-09-29  
**Estado:** pesquisa de fontes; nenhuma estratégia foi treinada ou validada neste documento.

## Síntese

O livro de ofertas L2 é uma fonte de informação genuinamente distinta do fluxo taker testado nos ciclos anteriores. As features existentes que usam “imbalance” calculam compras taker versus volume negociado em candles; elas não medem ordens limite ainda em repouso, alterações de fila nem cancelamentos. A busca estática no código ativo também encontrou `bookTicker` usado como cotação de execução paper, mas não encontrou ingestão/feature de L2 `depth` nos pipelines consultados. Consulte [futures_flow_absorption_research.py](../../src/jev_trader/futures_flow_absorption_research.py), [price_action_alpha.py](../../src/jev_trader/price_action_alpha.py) e [lowvol_hgb_paper.py](../../src/jev_trader/lowvol_hgb_paper.py). A conclusão limita-se aos fontes pesquisados; não prova ausência de dados externos ao checkout.

**Veredito:** vale como fonte candidata nova, mas ainda não como estratégia. A Binance documenta dados ao vivo em Spot e USDⓈ-M. O acesso histórico multiativo, contínuo e auditável é o principal bloqueio: o catálogo público de arquivos da Binance lista trades, aggTrades e klines, sem documentar arquivos L2. Uma documentação legada de histórico Futures descreve gaps, snapshots restritos e download sujeito a autorização. Assim, a disponibilidade adequada para backtest deve ser demonstrada antes de escrever o pipeline de experimento. [Binance Public Data](https://github.com/binance/binance-public-data), [documentação legada de L2 Futures](https://github.com/binance/binance-public-data/diffs/0?commit=e8cdb38250d443e8b948f6cf7e37207614a7ad43&name=master&sha1=4d66fc593d6afa301c9266aed28598f8fc76d6a4&sha2=e8cdb38250d443e8b948f6cf7e37207614a7ad43&short_path=eefa7af&w=false).

## O que é novo em relação aos experimentos existentes

O imbalance taker responde “quanto do volume executado foi iniciado por compradores ou vendedores?”. O estado L2 responde “quanta quantidade limite está atualmente exposta em cada lado e como as filas estão mudando?”. Em L2, adições, reduções/cancelamentos e consumo de liquidez podem alterar o sinal antes de serem resumidos como volume negociado. A distinção entre OFI de eventos de livro e volume de trades é parte explícita da literatura de microestrutura. [Cont, Kukanov e Stoikov](https://arxiv.org/abs/1011.6402).

Features mínimas para uma hipótese C19, todas causais e normalizadas por preço, spread ou profundidade local:

- Imbalance das filas no melhor bid/ask e soma ponderada nos primeiros 5–10 níveis.
- Order-flow imbalance (OFI) por atualização do livro, com adições e remoções em bid/ask; agregar em janelas fixas de 100 ms ou 1 s.
- Microprice menos mid-price, spread em bps e profundidade/notional acumulado em bandas fixas (por exemplo, ±5 e ±10 bps do mid).
- Velocidade de retirada e reposição da profundidade próxima ao melhor preço, separadas por lado.

Essas variáveis não identificam o dono de cada ordem nem permitem assumir que liquidez exibida continuará disponível. Portanto, imbalance instantâneo não deve ser tratado como ordem executável nem como volume efetivamente negociado. A API documenta níveis agregados de preço e quantidade, e não um identificador de participante. [Spot REST depth](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints#order-book), [Spot depth stream](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md#diff-depth-stream).

## Disponibilidade Binance e integridade da reconstrução

### Spot

A API Spot oferece snapshot atual em `GET /api/v3/depth`, com até 5.000 níveis por lado; o peso IP cresce até 250 para limites de 1.001–5.000. O WebSocket difusor de profundidade publica mudanças a cada 100 ms ou 1.000 ms e inclui intervalos de IDs de atualização. A documentação instrui iniciar o WebSocket, guardar eventos, obter snapshot REST e reconciliar IDs; se faltar atualização, descartar o livro local e reconstruí-lo. Níveis fora do snapshot inicial não ficam integralmente conhecidos até que mudem. Logo, snapshots REST consultados isoladamente não formam um histórico de mudanças e polling simples não substitui a sequência do WebSocket. [REST Spot](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints#order-book), [reconstrução oficial do livro Spot](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md#how-to-manage-a-local-order-book-correctly).

### USDⓈ-M Futures

O endpoint público `GET /fapi/v1/depth` fornece snapshot de até 1.000 níveis e inclui `lastUpdateId`, horário de evento e horário de transação. A documentação atual alerta que ordens Retail Price Improvement não aparecem no endpoint padrão de profundidade; `rpiDepth` é separado. Essa cobertura parcial precisa ser considerada na medição de liquidez e execução simulada. [Binance USDⓈ-M Market Data](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Order-Book).

### Histórico

O README oficial do catálogo público detalha Spot/Futures trades, aggTrades e klines, mas não descreve arquivo de profundidade. Um documento antigo no repositório Binance descreve Futures L2 `T_DEPTH` como sujeito a gaps, `S_DEPTH` como snapshot de aproximadamente 1 segundo/20 níveis apenas para BTCUSDT, e `T_DEPTH_BACKFILL` como interrompido desde julho de 2021. O mesmo documento exige chave autorizada para baixar, conta Futures para dados Futures e intervalos menores que sete dias por requisição. A página é legada e pode não refletir a política ou cobertura atual; portanto, esses detalhes são um alerta de disponibilidade, não uma confirmação de que o endpoint continua utilizável. [README oficial Binance Public Data](https://github.com/binance/binance-public-data), [documento histórico versionado](https://github.com/binance/binance-public-data/diffs/0?commit=e8cdb38250d443e8b948f6cf7e37207614a7ad43&name=master&sha1=4d66fc593d6afa301c9266aed28598f8fc76d6a4&sha2=e8cdb38250d443e8b948f6cf7e37207614a7ad43&short_path=eefa7af&w=false).

Se esse acesso não for confirmado sem usar credenciais de negociação, a alternativa honesta é coletar WebSocket público prospectivamente e validar somente sobre esse período. Isso não oferece retrospectiva para treino nem autoriza preencher lacunas; a cobertura e a duração precisam ser relatadas antes de avaliar desempenho.

## Evidência publicada e limite econômico

A motivação estatística existe, mas não prova a meta do projeto. Cont, Kukanov e Stoikov estudaram ações dos EUA: em intervalos curtos, encontraram relação aproximadamente linear entre OFI nos melhores preços e variação do preço, com impacto maior quando a profundidade é menor; o estudo não demonstra retorno cripto executável. [Artigo primário](https://arxiv.org/abs/1011.6402).

Gould e Bonart estudaram imbalance de fila como previsor de movimento de um tick à frente em dez ações Nasdaq. O poder fora da amostra variou bastante por ativo/regime de tick (AUC aproximadamente 0,58–0,81), com resultados mais fortes em ações de tick grande. Isso é previsão de movimento de tick, não EV líquido por operação. [Artigo primário](https://arxiv.org/abs/1512.03492).

Um preprint recente usa order book e trades da Binance Futures, amostrados a cada segundo entre 2022 e 2025, para prever retorno de mid-price em três segundos. Os próprios autores dizem que a latência não está modelada e que os resultados representam um limite superior no regime mais rápido. Seus testes também variam por ativo; BTC e LTC não têm significância estatística na comparação reportada, e o retorno taker extremo de ROSE é atribuído em parte ao crash de 10 de outubro de 2025. É uma evidência diretamente relevante ao mercado Binance, porém não revisada por pares e não equivalente ao critério EV por operação do Ciclo 12. [Bieganowski e Ślepaczuk, preprint e backtest](https://arxiv.org/html/2602.00776).

**Inferência para esta meta:** sinais de um tick ou 3 segundos parecem desalinhados com EV médio líquido superior a 1,2% por operação. A profundidade pode ser mais útil primeiro como previsão de custo/adverse selection, filtro de abstenção ou temporizador de entrada/saída de uma estratégia com horizonte maior. Isso precisa ser medido; não é uma conclusão de rentabilidade. A proposta vigente define EV >1,2%, payoff ≥1, PF ≥1,25, 200 trades únicos e ao menos oito semanas ativas por variante e mercado, além de stress de custos; conferir [proposta após C12](Binance_MultiStrategy_PROPOSTA_APOS_CICLO12.md).

## Próximo experimento que evitaria repetir os anteriores

1. Antes de criar protocolo/código, provar a disponibilidade e integridade de L2 histórico para um único mercado e par. Não misturar Spot com Futures nem trocar símbolos retrospectivamente.
2. Se histórico suficiente não estiver disponível, iniciar captura paper somente em Spot BTCUSDT por WebSocket público, mantendo payload bruto, relógio de recepção, timestamp/evento, IDs e gaps/reconstruções. Não enviar ordens.
3. Congelar como hipótese principal a contribuição incremental de L2 sobre o baseline de candle/taker já conhecido. Treinar em ordem temporal e avaliar em janelas futuras purgadas, com ablação “baseline” versus “baseline + L2”; não selecionar horizonte, ativo ou limiar no bloco final.
4. Converter previsão em retorno executável usando próximo estado do livro após a decisão, spread, taxas, slippage e latência observada. Abster-se em livro desatualizado, gap de sequência, custo estimado superior à vantagem prevista ou baixa confiança. Relatar cobertura e drawdown junto a EV, payoff, PF e hit rate.
5. Manter o gate C12 sem exceções. Se o sinal de segundos não conseguir amostra e EV por trade exigidos, registrar falha; não renomear os trades de outro candidato como operações L2. Usar GPU somente depois de haver corpus cronológico suficiente para justificar um modelo de sequência; acelerar o treino não corrige ausência de histórico nem custos.

**Conclusão:** L2 é uma fonte nova, com base microestrutural plausível e feeds públicos ao vivo documentados. O estado atual não comprova histórico adequado, edge executável nem atendimento às metas C12. A próxima decisão técnica deve ser condicionada à prova de cobertura histórica; sem ela, apenas um estudo prospectivo paper pode produzir evidência válida.

