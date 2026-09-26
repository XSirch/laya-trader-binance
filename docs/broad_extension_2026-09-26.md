# Extensão cronológica e atribuição da candidata

A combinação fixada de baixa volatilidade e carry com hedge de beta **não confirmou consistência**. Sem mudar sinais, pesos, horário ou custos, a extensão de 1º de agosto a 26 de setembro de 2026 às 00:00 UTC perdeu 4,59%, com queda máxima horária de 6,62%, no cenário principal de 0,15% por lado. A pesquisa permanece aberta e a candidata não está liberada para operação real.

| Custo por lado | Retorno da extensão | Queda máxima horária |
| --- | ---: | ---: |
| 0,10% | -4,47% | 6,56% |
| 0,15% | -4,59% | 6,62% |
| 0,30% | -4,94% | 6,83% |

Agosto contribuiu com -2,38% e setembro parcial com -2,26% na curva contínua iniciada em agosto. O resultado de agosto difere do teste isolado anterior porque a curva contínua mantém as posições ao virar o mês e inclui a abertura de setembro, enquanto o teste isolado encerrou as posições em 31 de agosto às 23:00.

## Fontes e conferências

Foram preservados 54 snapshots públicos HTTPS de candles, preços de marcação e funding dos 18 contratos ainda ativos na data inicial da extensão. EOS e MKR continuam no universo histórico e na contabilidade; seus encerramentos anteriores não são usados para apagar operações passadas. Nenhuma chave privada ou endpoint de ordens foi utilizado.

Cada snapshot registra URL, horário da aquisição, tamanho e hash local do conteúdo. Esse hash identifica os bytes adquiridos, mas não equivale ao checksum publicado dos arquivos mensais. A sobreposição confirmou 864 candles e 54 registros de funding entre API e arquivos históricos. Os candles horários foram agregados apenas em dias completos; o candle terminal serve para avaliação/encerramento e não entra nos sinais.

O formato dos endpoints e o campo `markPrice` do histórico de funding foram conferidos na [documentação oficial de dados de mercado da Binance](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data). Os snapshots locais ficam em `data/binance/broad/extension_rest/`; a lista de fontes e seus hashes acompanha o JSON desta extensão.

No cenário principal, o funding continua usando aproximações adversas dos candles horários. Um diagnóstico adicional usa as marcas exatas retornadas pela API onde disponíveis e mantém a aproximação para o restante. O retorno passa de -4,5893% para -4,5879%, diferença insuficiente para alterar a conclusão. Dois pagamentos com exposição tiveram marca exata ligeiramente fora do candle da nova hora, mas dentro do anterior, na fronteira de liquidação. Esses casos são contados explicitamente; valores fora de ambos os candles são rejeitados. Os extremos da hora isolada são uma aproximação adversa, não uma garantia matemática de conter todo preço de liquidação na fronteira.

## De onde veio o resultado

A atribuição em pontos percentuais do capital inicial reconcilia preço, funding e custos com o retorno total. No histórico de janeiro/2024 a julho/2026, TRX contribuiu +12,30 pontos e BNB +9,74 pontos: aproximadamente 62% do lucro líquido total. O funding contribuiu +3,76 pontos, enquanto os custos consumiram 5,02 pontos. Portanto, o ganho histórico veio principalmente das mudanças de preços relativas entre posições compradas e vendidas, não de pagamentos de funding previsíveis.

Na extensão, as maiores contribuições negativas foram CRV (-3,31 pontos), UNI (-3,02) e AAVE (-2,31); BCH (+2,02) e BNB (+1,45) compensaram parcialmente. Não foram removidos ativos nem recalculada uma carteira vencedora a partir dessas perdas. A atribuição é uma decomposição contábil, não o retorno que teria ocorrido ao excluir um ativo e redistribuir seu capital.

## Consequência para a pesquisa

A candidata fica mantida como referência exploratória, com resultado posterior adverso. A próxima hipótese deve modelar conjuntamente os fatores e o risco relativo das posições, com alvos de previsão já encerrados antes de cada treino. A avaliação precisará registrar todas as variantes e reconhecer que os períodos até setembro agora foram examinados. Melhorar o ajuste nesses períodos não os transforma em nova confirmação independente.

Reprodução: `python -m jev_trader.broad_extension`. O programa reutiliza snapshots com hashes conferidos e rejeita alterações no código da estratégia fixada. Não houve gasto adicional com JEV.
