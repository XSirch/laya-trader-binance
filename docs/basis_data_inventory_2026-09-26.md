# Inventário local para pesquisa de convergência spot/perp

Inspeção em 26/09/2026, somente dos dados e do código locais. Esta nota prepara uma hipótese de entrada pelo diferencial observado entre spot e perpétuo de BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT. Não executa backtest, não calcula retornos, não seleciona limiares e não demonstra rentabilidade. O estudo de reação ao funding congelado no commit `8459630` permanece separado e inalterado.

## Fontes e verificação realizada

Foram lidos e comparados aos hashes dos manifestos **712 arquivos ZIP locais**: 176 de spot, 528 de derivativos e oito suplementos de mark price. Os registros foram interpretados pelos parsers existentes; não houve download. Cada manifesto identifica caminho local, URL original, símbolo, período e SHA-256 do respectivo arquivo. A verificação demonstra correspondência dos bytes atuais com esses registros, sem comprovar disponibilidade histórica de cada versão.

| Manifesto, relativo à raiz do repositório | Arquivos | SHA-256 do manifesto |
|---|---:|---|
| `data/binance/spot/1h/manifest.json` | 176 | `786bfeeb9ccfa3486033ca36cf98aad5a6b3a6ac59ec3c7ec4e1713634a0efe6` |
| `data/binance/futures/um/manifest.json` | 528 | `c2e6ec8281437f6771a236bb0311264e17ebf0e4d2dc19ee11bcd68cee2215bd` |
| `data/binance/futures/um/supplemental_manifest.json` | 8 | `1f1c645c313563f20201a8a5665f068f4c464af045ea8c76de1d2612509a3f75` |

Os 528 arquivos mensais de derivativos são 176 de preços negociados, 176 de mark price e 176 de funding. Os oito suplementos recompõem mark price de 24/02/2023 e 29/06/2026 nos quatro ativos.

Os arquivos de dados seguem estes caminhos locais:

```text
data/binance/spot/1h/{SYMBOL}/{SYMBOL}-1h-{YYYY-MM}.zip
data/binance/futures/um/klines/{SYMBOL}/1h/{SYMBOL}-1h-{YYYY-MM}.zip
data/binance/futures/um/markPriceKlines/{SYMBOL}/1h/{SYMBOL}-1h-{YYYY-MM}.zip
data/binance/futures/um/fundingRate/{SYMBOL}/{SYMBOL}-fundingRate-{YYYY-MM}.zip
data/binance/futures/um/daily/markPriceKlines/{SYMBOL}/1h/{SYMBOL}-1h-{YYYY-MM-DD}.zip
```

A origem pública registrada é `https://data.binance.vision/data/spot/monthly/klines/` para spot e `https://data.binance.vision/data/futures/um/` para derivativos, com os subdiretórios mensais ou diários indicados nos manifestos. Essas URLs não foram consultadas nesta inspeção.

## Cobertura encontrada

As contagens abaixo valem separadamente para cada um dos quatro símbolos. Datas e horas são UTC; o timestamp do candle indica sua abertura.

| Série | Primeiro registro | Último registro | Registros por ativo |
|---|---|---|---:|
| Spot horário | 01/01/2023 00h | 31/08/2026 23h | 32.135 |
| Perp negociado horário | 01/01/2023 00h | 31/08/2026 23h | 32.136 |
| Mark price horário, com suplementos | 01/01/2023 00h | 31/08/2026 23h | 32.136 |
| Funding realizado | 01/01/2023 00h | 31/08/2026 16h00m00,001s | 4.017 |

A interseção de spot, perp negociado e mark price contém **29.976 timestamps consecutivos por ativo**, de **01/04/2023 00h a 31/08/2026 23h**. Continuidade de timestamps não equivale a liquidez ou execução demonstrada. Os diretórios spot inspecionados contêm os 176 ZIPs do manifesto e nenhum arquivo de setembro de 2026. Assim, a cobertura de futuros mais recente usada por outros estudos não permite estender automaticamente uma carteira pareada spot/perp até setembro. O limite final de um futuro protocolo deve exigir um preço terminal realmente presente; não presumir a abertura de 01/09/2026.

Ocorrências preservadas nos quatro ativos:

| Mercado | Horário UTC | Observação |
|---|---|---|
| Spot | 24/03/2023 12h | Candle presente, volume zero e zero negócios |
| Spot | 24/03/2023 13h | Candle ausente |
| Perp negociado | 28/10/2024 20h | Candle presente, volume zero e zero negócios |

Os dois eventos spot ficam fora do intervalo contínuo iniciado em abril de 2023. A hora perp sem negócios permanece dentro desse intervalo e deve ser tratada explicitamente pelo executor; não autoriza fill apenas porque há um OHLC. Esta nota não escolhe entre rejeitar um cenário ou adiar a ordem conforme uma regra previamente fixada. Não remover a observação depois de conhecer seu efeito financeiro.

## Estruturas e funções existentes

| Código | Interface e comportamento relevante |
|---|---|
| `src/jev_trader/binance_data.py:22` | `Bar`: `open_ms`, OHLC, volume, volume financeiro, número de negócios e volume comprador agressor |
| `src/jev_trader/binance_data.py:124` | `parse_archive(path, max_gap_hours=...)`: interpreta ZIP local; normaliza timestamps spot em microssegundos quando necessário |
| `src/jev_trader/binance_data.py:183` | `load_cached_range(symbols, first, last, root)`: leitura spot somente do cache, com manifesto e SHA-256 |
| `src/jev_trader/derivatives_data.py:25` | `Funding`: `timestamp_ms`, `interval_hours`, `rate` |
| `src/jev_trader/derivatives_data.py:74` | `parse_funding(path)`: interpreta pagamentos do ZIP local e preserva o timestamp real |
| `src/jev_trader/derivatives_data.py:89` | `load(...)`: pode chamar `fetch()` ao reparar lacunas e gravar suplementos; não é uma interface estritamente somente leitura/offline |
| `src/jev_trader/carry.py:52` | `prepare(spot, derivatives)`: pareia os três preços, exclui o trecho anterior a abril de 2023 e produz pagamentos e médias históricas semanais |
| `src/jev_trader/carry.py:78` | `evaluate(...)`: simula compra spot e venda perp em quantidades iguais, com funding e taxas |

Por ativo, `carry.prepare()` devolve `spot` como lista de `Bar`; `futures` e `mark` como mapas de timestamp para `Bar`; `funding` como mapa da hora para o evento que preserva seu timestamp exato; e `past_annualized` como mapa das decisões semanais para funding passado anualizado. O novo carregamento poderá reutilizar os parsers puros, lendo explicitamente os três manifestos e recusando fontes ausentes, sem acionar reparos em rede.

## O que o carry existente cobre e o que precisaria mudar

`carry.target_for()`, na linha 38, usa somente a média de funding de trinta dias. O agendamento depende de `past_annualized`, às segundas 00h UTC. A diferença spot/perp já influencia a contabilidade e aparece em `basis_pnl_pct_initial`, mas não determina entradas. Usar o diferencial observado como sinal é uma hipótese distinta; aumentar o retorno de funding não é seu objetivo contábil.

O executor mantém uma quantidade positiva `q` de spot e um short perp de mesma quantidade. Debita a compra spot e as taxas das duas pernas, contabiliza PnL do short, funding e fechamento terminal. Entretanto, `cash[s]` agrega caixa e PnL da perna futura: não identifica carteiras spot/margem separadas nem transferências reais. A marcação de PnL não pode ser tomada como prova de disponibilidade de dinheiro para outra compra spot.

`desired = allocation * equity / spot_price` limita o notional spot. O notional perp é `q * future_price` e será diferente quando houver basis. Um limite por perna precisa verificar ambos os valores. O executor também não exige negócios positivos antes de fills. A margem de manutenção de 10% é apenas uma aproximação de stress: violações são contadas, sem reproduzir tiers, liquidação, ADL ou condições de uma conta.

O funding usa mark da abertura da hora. Em colisões de rebalanceamento e pagamento, créditos usam a menor quantidade anterior/posterior e débitos a maior. A aproximação do preço de marcação merece tratamento explícito porque o evento pode ocorrer milissegundos após a abertura, e o ganho procurado no diferencial pode ser pequeno. O funding terminal é excluído pela lógica existente.

Uma contabilidade isolada deve distinguir caixa spot, inventário spot, caixa de margem perp, preço médio e quantidade do short, PnL realizado e PnL não realizado. Abrir perp não credita o dinheiro de uma venda spot fictícia. Taxas e funding pertencem à carteira correspondente; alterações de quantidade realizam PnL, e transferências entre carteiras precisam de regra explícita. O patrimônio consolidado deve reconciliar caixa, inventário e PnL sem contar o colateral novamente como capital adicional. Orçamento de compra, reserva de margem e política de transferências ainda precisam ser definidos antes de qualquer resultado; esta nota não escolhe suas frações.

## Limites de executabilidade e escopo mínimo isolado

Um diferencial calculado de `perp_close` e `spot_close` usa últimas negociações de mercados diferentes, que podem ter ocorrido em instantes diferentes. Comprar spot e vender perp depende de ask spot e bid perp; encerrar depende de bid spot e ask perp. O cache não contém essas quatro cotações simultâneas, profundidade, fila ou latência entre pernas. Mark price serve à margem/funding e não é preço de execução. Um perp não possui vencimento que assegure convergência.

Uma triagem horária deverá declarar quando ambos os candles se tornam conhecidos e o atraso até a execução simulada, cobrar entrada e saída das duas pernas e incorporar funding adverso. Uma leitura favorável de OHLC não comprovará arbitragem executável. Empregar somente spot comprado/perp vendido evita supor empréstimo de spot não documentado, mas direção e regras finais ainda pertencem ao futuro protocolo.

O mínimo de implementação pode ficar inteiramente separado dos módulos congelados: carregador de basis somente local, política causal do diferencial com estado de entrada/manutenção/saída, executor das duas carteiras e runner com protocolo, fontes, hashes e atribuição. Testes sintéticos devem cobrir conservação de patrimônio, custos das duas pernas na entrada e saída, quantidades iguais, funding negativo/colisões, liquidez zero, exclusão de dados futuros e fechamento terminal. Não foram criados módulos ou testes nesta inspeção, nem fixados limiares, horizonte ou janelas de seleção por desempenho.

Esta nota documenta disponibilidade de dados e lacunas do simulador. Não altera `carry.py`, o paper ou o estudo de reação ao funding, não inicia uma nova pesquisa de retornos e não constitui evidência a favor da meta de rentabilidade/drawdown.
