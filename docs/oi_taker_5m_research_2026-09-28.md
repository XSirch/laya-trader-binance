# Resultado: OI e fluxo taker em 5 minutos

A hipótese congelada combina expansão de open interest, direção do preço e fluxo taker em BTCUSDT perpétuo. Os primeiros 20 dias formaram a janela de treino e os últimos 10 dias, a validação temporal; o HGB só é ajustado quando a amostra atinge o mínimo congelado. Custos em percentual por lado; o drawdown marca uma posição por vez com notional igual ao patrimônio e sem alavancagem.

Treino: 380 rótulos (14 vitórias, 366 perdas), 18 dias; HGB indisponível por amostra/classe insuficiente. Dados alinhados: 8639 candles; primeiro candle comum 2026-08-29T00:55:00+00:00; último 2026-09-28T00:45:00+00:00.

| Estratégia | Custo/lado | Trades | Acerto | Payoff | EV/trade | DD | Retorno da carteira |
|---|---:|---:|---:|---:|---:|---:|---:|
| Regra-base | 0,10% | 60 | 16,67% | 0,19 | -0,23% | 12,78% | -12,78% |
| Regra-base | 0,15% | 60 | 1,67% | 0,62 | -0,33% | 17,87% | -17,87% |
| Regra + HGB | 0,10% | 0 | — | — | — | 0,00% | 0,00% |
| Regra + HGB | 0,15% | 0 | — | — | — | 0,00% | 0,00% |

## Decisão

A regra não passou todos os gates congelados; esta janela curta não demonstra a meta nem permite ajustes sem novo período independente.
A amostra de validação é curta, a faixa inteira foi vista em pesquisas anteriores e os rótulos de treino sobrepõem-se. Nenhum resultado autoriza ordens reais.

## Integridade

- Protocolo SHA-256 `92305fa0b9fc1f984360840f74cde9f858b08000ff4a472f173cf726eb68e08c`; código `be14c3ddd6507b100942ce04b7c3ad2ed2922dfbd59bc8f6d06e34f1d45c6827`.
- Manifesto de aquisição SHA-256 `3633a1fd4ec16ba38f316f778d8659523a85fc4703f17136336298120fcbdebf`.
- Trades completos: [CSV](../results/oi_taker_5m_trades_20260928.csv); métricas e proveniência: `results/oi_taker_5m_research_20260928.json`.
- Arquivos brutos e paginação: `results/oi_taker_5m_20260928_attempt5/raw/` e `input_manifest.json`.
- Nenhuma chamada paga ao JEV ou ordem real foi feita.
