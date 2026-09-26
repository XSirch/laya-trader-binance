# Inventário de métricas históricas de derivativos

Consulta em 26/09/2026. Open interest e posicionamento oferecem dados distintos dos indicadores de preço já presentes no repositório. Há arquivos públicos históricos, mas a disponibilidade original de cada observação não está comprovada. Este inventário não executa estratégia, não identifica vantagem preditiva e não valida a meta de retorno ou drawdown.

## Arquivo público e esquema observado

Padrão confirmado com downloads públicos:

```text
https://data.binance.vision/data/futures/um/daily/metrics/{SYMBOL}/{SYMBOL}-metrics-{YYYY-MM-DD}.zip
https://data.binance.vision/data/futures/um/daily/metrics/{SYMBOL}/{SYMBOL}-metrics-{YYYY-MM-DD}.zip.CHECKSUM
```

O CSV interno chama-se `{SYMBOL}-metrics-{YYYY-MM-DD}.csv`. As duas amostras possuem oito colunas, nesta ordem:

```text
create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio
```

Evidência direta: [BTCUSDT, 01/09/2020](https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2020-09-01.zip), [ETHUSDT, 01/12/2021](https://data.binance.vision/data/futures/um/daily/metrics/ETHUSDT/ETHUSDT-metrics-2021-12-01.zip). Os nomes sugerem a correspondência abaixo; o README do arquivo não fornece um contrato específico que prove equivalência exata entre cada coluna e a resposta REST atual.

| Campo do CSV | Endpoint REST correspondente por significado | Conteúdo |
| --- | --- | --- |
| `sum_open_interest`, `sum_open_interest_value` | `/futures/data/openInterestHist` | Interesse aberto e seu valor |
| `count_toptrader_long_short_ratio` | `/futures/data/topLongShortAccountRatio` | Razão de contas líquidas long/short entre os maiores saldos de margem |
| `sum_toptrader_long_short_ratio` | `/futures/data/topLongShortPositionRatio` | Razão das posições long/short desse grupo |
| `count_long_short_ratio` | `/futures/data/globalLongShortAccountRatio` | Razão de contas long/short globais |
| `sum_taker_long_short_vol_ratio` | `/futures/data/takerlongshortRatio` | Razão do volume comprador/vendedor agressor |

A documentação define o grupo “top” pelos 20% de usuários com maior saldo de margem, não por rentabilidade. O histórico REST limita OI ao último mês e as razões aos últimos 30 dias; `limit` máximo 500. OI e razões de contas/posições usam timestamp de fim do período; taker usa início. Todos são milissegundos no REST. Os dois endpoints “top” estão documentados com `X-MBX-APIKEY` obrigatório. Não foram chamados. [Referência oficial de mercado USD-M](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data).

## Cobertura observada, sem extrapolar continuidade

O frontend oficial informa o bucket público `https://s3-ap-northeast-1.amazonaws.com/data.binance.vision`. Consultas de listagem com `prefix=data/futures/um/daily/metrics/{SYMBOL}/&max-keys=1` verificaram o primeiro objeto dos 20 ativos do cohort congelado. Não foi feito download desse histórico completo.

| Grupo | Primeira data encontrada no nome do objeto | `LastModified` do objeto atual |
| --- | --- | --- |
| BTCUSDT | 2020-09-01 | 2026-03-18 12:30:27 UTC |
| Outros 19 ativos | 2021-12-01 | 2023-06-16, entre 11:35:53 e 11:35:56 UTC |

Os outros 19 são ETHUSDT, XRPUSDT, LINKUSDT, LTCUSDT, DOGEUSDT, DOTUSDT, BCHUSDT, XLMUSDT, ADAUSDT, EOSUSDT, UNIUSDT, SUSHIUSDT, YFIUSDT, BNBUSDT, TRXUSDT, CRVUSDT, MKRUSDT, AAVEUSDT e GRTUSDT. Exemplos reproduzíveis: [listagem inicial de BTC](https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?prefix=data%2Ffutures%2Fum%2Fdaily%2Fmetrics%2FBTCUSDT%2F&max-keys=1), [listagem inicial de ETH](https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?prefix=data%2Ffutures%2Fum%2Fdaily%2Fmetrics%2FETHUSDT%2F&max-keys=1).

Também foram encontrados ZIP e checksum de 25/09/2026 para BTC e ETH por prefixo exato, sem baixá-los. A consulta `data/futures/um/monthly/metrics/BTCUSDT/` retornou zero objetos. Isso confirma o caminho diário para estas amostras; não prova a inexistência universal de arquivos mensais. [Listagem recente de BTC](https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?prefix=data%2Ffutures%2Fum%2Fdaily%2Fmetrics%2FBTCUSDT%2FBTCUSDT-metrics-2026-09-25&max-keys=2), [prefixo mensal consultado](https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?prefix=data%2Ffutures%2Fum%2Fmonthly%2Fmetrics%2FBTCUSDT%2F&max-keys=6).

Primeiro objeto e arquivo recente não comprovam ausência de lacunas, validade dos valores intermediários ou disponibilidade contínua dos ativos deslistados.

## Duas amostras verificadas

Foram baixados somente dois ZIPs e seus checksums, salvos em `.cache/research-metrics/`. Ambos passaram na comparação SHA-256 com o checksum público e na leitura UTF-8 estrita do CSV.

| Amostra | Bytes ZIP | Linhas de dados | Instantes distintos | Qualidade observada |
| --- | --- | --- | --- | --- |
| BTCUSDT 2020-09-01 | 12.191 | 576 | 288 | Cada instante aparece duas vezes; linhas duplicadas idênticas |
| ETHUSDT 2021-12-01 | 14.930 | 288 | 288 | Nenhum instante duplicado |

Nos dois arquivos, os instantes distintos avançam de cinco em cinco minutos, de `00:00:00` a `23:55:00`. Nenhuma das oito colunas contém vazio, `NaN` ou `null` nessas duas amostras. Nenhuma dessas verificações representa auditoria do restante do arquivo histórico. O CSV usa texto de data/hora sem offset de fuso explícito; interpretar `create_time` como UTC exige hipótese documentada ou confirmação adicional.

SHA-256 dos ZIPs:

```text
BTCUSDT-metrics-2020-09-01.zip
9a9c0518bfb939032afe97a6b1708668ec833457743b1ba6ef448fb157722ae3

ETHUSDT-metrics-2021-12-01.zip
0372e6c6efc132bc96983b06fdc7ca5e788a1c98e2bbd448c2030bfe925d1807
```

O caso BTC já justifica uma regra explícita de ingestão: aceitar duplicatas somente quando todos os campos forem idênticos, contabilizá-las e rejeitar versões conflitantes. Não escolher arbitrariamente “a última” linha em caso de conflito.

## Três relógios diferentes

O README oficial informa publicação diária no dia seguinte e permite revisões posteriores dos arquivos. O SHA-256 protege integridade do arquivo baixado, não demonstra que os mesmos bytes estavam disponíveis no passado. [Binance Public Data](https://github.com/binance/binance-public-data#readme).

É necessário separar:

1. **Tempo econômico:** instante/período ao qual o número se refere. A definição REST varia entre OI/posições e fluxo taker; o CSV reúne esses campos em um único `create_time`, sem documentar como alinha as janelas.
2. **Tempo de publicação:** primeira vez em que o número poderia ser conhecido. Não há essa coluna nas amostras. A regra genérica “dia seguinte” não informa hora exata, atraso de cálculo, backfill nem primeira publicação histórica.
3. **Tempo de observação da versão:** momento do download atual e `LastModified` do objeto atual. O BTC de 2020 foi gravado/modificado no bucket em 2026; ETH de 2021, em 2023. Isso comprova uma versão atual posterior ao período econômico, sem distinguir carga inicial, migração ou revisão. Não prova que versões anteriores não existiram.

Portanto, adicionar um atraso arbitrário de cinco minutos, uma hora ou dois dias não resolve por si só a falta de histórico de revisões. Uma análise com os arquivos atuais pode ser apresentada como estudo retrospectivo de dados revisáveis, sem chamar o conjunto de point-in-time. Para evidência prospectiva, registrar primeira observação local e guardar versões imutáveis a partir da coleta. Esta tarefa não iniciou coletor nem modificou o watcher existente.

## Informação adicional frente aos 60 campos atuais

Inspeção de `broad_technical.feature_bundle`, `broad_prediction.FIELDS`, `broad_research.features` e `market_state.states` mostra combinação de OHLCV, taker, funding e transformações técnicas. Não há OI nem razão de contas ou posições nesses campos. A conclusão é sobre a origem dos dados, não independência estatística ou capacidade de prever retornos.

- **OI:** acrescenta estoque de posições abertas. Examinar quantidade e valor separadamente evita tratar valorização do ativo como aumento automático de quantidade; padronizações devem usar somente o passado.
- **Contas e posições top/globais:** acrescentam composição de posicionamento. Não inferir qualidade do investidor por saldo de margem, direção do próximo movimento ou exposição líquida de toda a instituição: hedge spot e posições em outras bolsas não aparecem.
- **Taker:** já aparece como `taker_flow20` e `technical.participation.taker_buy_fraction20`. Com a mesma janela, volume e convenção, `B/S = f/(1-f)` quando `f=B/(B+S)`. Uma nova razão taker pode acrescentar resolução temporal, mas não deve ser contada automaticamente como fonte independente. A média de razões de cinco minutos também difere da razão entre volumes agregados; o CSV de métricas não oferece os dois volumes para ponderação.

Uma hipótese distinta e testável seria estudar se crescimento de OI combinado com funding e divergência entre posicionamento de contas e posições identifica concentração de risco. Isso ainda é uma hipótese: não fixa direção lucrativa nem autoriza seleção de thresholds depois dos resultados. O próximo passo justificável é um inventário de cobertura e qualidade por ativo/data, seguido de protocolo causal com tratamento explícito da disponibilidade e comparação incremental contra os 60 campos atuais. A coleta deve preservar o cohort histórico e seus eventos de deslistagem. Nenhum backtest foi executado neste inventário.
