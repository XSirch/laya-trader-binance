# Binance USDⓈ-M `BTCUSDT@bookTicker`: validação da fonte WebSocket

- **Consulta:** 29/09/2026
- **Escopo:** documentação e anúncio oficiais Binance; endpoint público somente leitura
- **Tipo:** validação de fonte; não é coleta, experimento de trading ou evidência de rentabilidade

## Veredito

A documentação oficial atual sustenta o uso do stream individual USDⓈ-M `btcusdt@bookTicker` na rota pública:

```text
wss://fstream.binance.com/public/ws/btcusdt@bookTicker
```

A página de conexão define `/public` como a rota de dados públicos de alta frequência e documenta o formato `/public/ws/<streamName>`. A página do stream individual documenta `btcusdt` como exemplo de símbolo e fornece esse formato de URL; o aviso de migração classifica `<symbol>@bookTicker` em **Public**. O anúncio Binance de 06/03/2026 apresentou `wss://fstream.binance.com/public` e informou a retirada das URLs legadas em 23/04/2026. Assim, a URL acima é a forma explicitamente documentada e roteada para esta assinatura. A página de conexão também diz que conexões sem caminho roteado recebem somente dados **Public**; esta validação não afirma que o fallback sem `/public` seja rejeitado para este stream.

Fontes: [WebSocket Market Streams — Connect](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/Connect), [Individual Symbol Book Ticker Streams](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/public#individual-symbol-book-ticker-streams), [aviso oficial de migração](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/Important-WebSocket-Change-Notice), [anúncio Binance de 06/03/2026](https://www.binance.com/en/support/announcement/detail/ebf9b0aa9eca4ff3804eef6fb09ba32a).

## Semântica e schema do stream individual

A Binance descreve o stream individual como envio em tempo real quando muda o preço ou a quantidade do melhor bid ou ask. A velocidade publicada é **Real-time**; a documentação não fixa uma cadência numérica, intervalo máximo entre mensagens nem frequência garantida. Isso descreve a semântica anunciada do feed, não latência de entrega ou garantia de execução.

O schema USDⓈ-M publicado lista:

| Campo | Significado documentado |
| --- | --- |
| `e` | tipo do evento (`bookTicker`) |
| `u` | identificador de atualização do livro (`updateId`) |
| `E` | horário do evento |
| `T` | horário da transação |
| `s` | símbolo |
| `ps` | par; campo documentado após a migração CM |
| `b`, `B` | preço e quantidade do melhor bid |
| `a`, `A` | preço e quantidade do melhor ask |
| `st` | tipo do símbolo após a migração CM: `1` = UM; `2` = CM |

O exemplo atual contém `e`, `u`, `E`, `T`, `s`, `ps`, `b`, `B`, `a`, `A` e `st`. No schema pós-migração CM, deve-se preservar `st` para distinguir UM de CM. A Binance também informa que ordens Retail Price Improvement (RPI) não são visíveis e ficam excluídas dessa mensagem; o stream não representa toda a liquidez executável quando RPI se aplica.

Fonte: [Individual Symbol Book Ticker Streams — Binance USDⓈ-M](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/public#individual-symbol-book-ticker-streams).

### Não confundir com `!bookTicker`

O stream agregado `!bookTicker` não é equivalente ao stream individual: a documentação da Binance lista atualização de **5 s** para o agregado, enquanto lista **Real-time** para `<symbol>@bookTicker`. Este registro trata apenas do stream individual BTCUSDT.

Fonte: [All Book Tickers Stream e Individual Symbol Book Ticker Streams](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/public).

## Conexão, limites e ciclo de vida

As regras publicadas pela página oficial USDⓈ-M de conexão são:

- Uma conexão vale por no máximo **24 horas**; a Binance diz para esperar a desconexão ao atingir esse limite.
- O servidor envia um frame **PING a cada 3 minutos**. Se não receber um frame PONG em até **10 minutos**, desconecta a conexão. PONGs não solicitados são permitidos.
- O limite é **10 mensagens recebidas por segundo** em cada conexão. A página informa que excedê-lo desconecta a conexão e que IPs desconectados repetidamente podem ser banidos; ela não enumera, nessa regra, quais tipos de frame compõem a contagem.
- Cada conexão pode escutar no máximo **1.024 streams**.

A página consultada não especifica política de backoff, tempo de espera para reconectar, replay automático de assinaturas ou uma exigência adicional de reconexão. Para uma captura que precise continuar após 24 horas, a implementação terá de tratar a desconexão e restabelecer a assinatura; essa é uma necessidade operacional derivada do limite de duração, não uma receita de reconexão prescrita pela Binance.

Não localizei nessas páginas USDⓈ-M um limite de novas conexões por IP em uma janela de tempo. Não transferi para USDⓈ-M números publicados em páginas de outros produtos Binance.

Fonte: [WebSocket Market Streams — Connect](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/Connect).

## Conclusão para C20

A afirmação do protocolo C20 sobre a URL pública USDⓈ-M `wss://fstream.binance.com/public/ws/btcusdt@bookTicker` está sustentada por fontes oficiais atuais. Para especificar o coletor, registrar o schema acima, tratar o feed como evento de melhor cotação em tempo real sem cadência numérica fixa, observar o limite de 24 horas e responder aos PINGs. As fontes verificadas não definem uma estratégia de reconexão/backoff nem fornecem cadência ou latência garantida. Esta validação não confirma que a coleta C20 foi iniciada, não comprova integridade de uma série e não demonstra edge, EV, acerto, payoff, drawdown ou rentabilidade.
