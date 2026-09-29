# Auditoria exploratória de regime BTC para o candidato short-only

## Resultado

A hipótese era que uma condição ampla de tendência do BTC explicaria as perdas do short-only nas janelas anteriores. Os cortes binários testados não atendem juntos a acerto de 70%, payoff mínimo 1:1 e EV acima de 1,2% do notional. O drawdown não foi refeito por subconjunto, portanto nenhum corte pode passar o gate completo.

| Condição na entrada | Episódios | Acerto | Payoff | EV líquido/operação |
|---|---:|---:|---:|---:|
| Todas as janelas em separado | 96 | 61.46% | 1.043 | 4.66% |
| BTC: retorno 30d negativo | 45 | 62.22% | 0.772 | 2.12% |
| BTC: retorno 30d não negativo | 51 | 60.78% | 1.346 | 6.90% |
| BTC: retorno 90d negativo | 42 | 66.67% | 0.721 | 2.82% |
| BTC: retorno 90d não negativo | 54 | 57.41% | 1.341 | 6.09% |
| BTC: conjunto de EMAs negativo | 38 | 68.42% | 0.883 | 5.46% |
| BTC: conjunto de EMAs não negativo | 58 | 56.90% | 1.163 | 4.13% |

## Leitura por janela

| Janela | Episódios | Acerto | Payoff | EV líquido/operação |
|---|---:|---:|---:|---:|
| calibration_2025h1 | 18 | 50.00% | 0.949 | -0.71% |
| confirmation_2026 | 22 | 72.73% | 2.250 | 9.42% |
| validation_2024 | 39 | 51.28% | 1.044 | 0.85% |
| validation_2025h2 | 17 | 82.35% | 1.212 | 12.93% |

## Método e limites

A amostra tem 96 episódios das quatro janelas em separado, somente no custo stress de 0,15% por lado. Cada retorno foi associado ao estado BTC disponível na entrada: momentum de 30 dias, momentum de 90 dias e sinal do ensemble EMA. Acerto considera PnL líquido positivo; payoff é ganho médio dividido pela perda média absoluta; EV é retorno líquido médio como percentual do notional de entrada.

A soma das janelas separadas difere do replay combinado porque operações que cruzam fronteiras de período são fechadas e reiniciadas nos recortes separados. Os 96 episódios desta análise não devem ser confundidos com os 88 episódios do replay combinado.

Este é um diagnóstico posterior sobre filtros simples, não confirmação independente. As janelas e a direção short já tinham sido examinadas. Os subconjuntos não tiveram replay de carteira, logo não há evidência de drawdown abaixo de 10%. Nenhuma regra foi ajustada e nenhuma ordem foi enviada.

Os dados locais de futuros usados no candidato estão desatualizados para novas decisões: 18 de 20 contratos chegam somente ao candle de 31/08/2026; EOSUSDT termina em 21/05/2025 e MKRUSDT em 08/09/2025. A próxima etapa operacional exige atualizar candles e mark price diários e funding antes de gerar qualquer sinal. A Binance documenta os endpoints USDⓈ-M de klines, mark-price klines, funding e exchange info [na referência oficial da API](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data). Os arquivos públicos diários ficam disponíveis no dia seguinte e trazem o formato de klines USD-M [na documentação oficial do arquivo](https://github.com/binance/binance-public-data/blob/master/README.md).

## Artefatos de entrada

- Protocolo short-only: `docs/low_volatility_short_only_protocol_2026-09-28.md` (SHA-256 `90bbf2f60d6494e83915463ad9687b7ebe193f298dc93d06c4a30d6635176399`).
- Resultado e ledger: `results/low_volatility_short_only_20260928.json` e `results/low_volatility_short_only_ledger_20260928.csv`.
- Manifesto histórico: SHA-256 `11f72aa37a646cf46e7904337aced83e2aa06c052377f07c7596e0287465a05a`.
- Qualidade/frescor diário: `data/binance/broad/data_quality.json` (SHA-256 `89af7a1e9b63f6a6df4ded2f1d2b2dd4b71a15f1d0d6811b04fb4dc6cc2c7edc`).
- Código deste diagnóstico: SHA-256 `1d9bb8124e3dd048e8e1dd49f5f2ba7e72fe549b81fc2e8480b7a4756960349f`.
