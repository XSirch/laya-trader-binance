# Protocolo: holdout temporal de setembro para modelos de lags

Congelado em 27/09/2026, depois de a pesquisa até 31/08/2026 rejeitar o painel HGB amplo e a ablação de lags. O teste responde se os três grupos de lags previamente definidos preservam sinal em candles mais recentes que não estavam no cache nem nos relatórios anteriores. Esta janela mede generalização recente por 25 dias, não consistência anual.

## Período e dados

Baixar somente os arquivos diários Spot 1h de `BTCUSDT`, `ETHUSDT`, `BNBUSDT` e `SOLUSDT` para 01–26/09/2026. A estrutura oficial de arquivo diário é `https://data.binance.vision/data/spot/daily/klines/{SYMBOL}/1h/{SYMBOL}-1h-2026-09-{DD}.zip`. Obter o arquivo `.CHECKSUM` correspondente para cada ZIP, conferir SHA-256 e CRC, registrar URL, horário de aquisição, bytes e hash e manter os artefatos em `results/lagged_flow_forward_data/`, sem alterar o manifesto histórico em `data/binance/spot/1h/`. O repositório oficial descreve arquivos diários para candles Spot, disponibilidade no dia seguinte, checksums e timestamps Spot em microssegundos desde 01/01/2025; o parser local deve normalizar microssegundos para milissegundos. [Binance Public Data README](https://github.com/binance/binance-public-data/blob/master/README.md).

Validar 24 candles contínuos para cada ativo/dia, sem duplicatas, lacunas nem sobreposição com a última barra anterior. Fundir os dados novos somente em memória com o inventário histórico até agosto, para formar features. O estudo anterior treinou os três HGBs de lags curtos somente com próprios/ líderes e indicadores fixos de ativo; nenhum feature perpétuo, funding, positioning ou candle futuro entra nestes modelos. No corte de setembro, o treino termina em rótulos estritamente disponíveis antes de cada previsão; não refitar durante o mês.

## Decisões, horizonte e carteira

A janela executável começa em 01/09/2026 00:00 UTC e termina em 26/09/2026 16:00 UTC. A última previsão pontuável ocorre em 26/09 às 08:00 e encerra às 16:00; são 77 eventos no relógio por ativo antes de barras ou labels inválidos. O label desse último episódio fecha contabilmente no open de 16:00 e passa a estar completo uma hora depois; seu erro de previsão é pontuado até 17:00 UTC, embora a carteira termine às 16:00. A previsão das 16:00 de 26/09 não entra na carteira porque não há o open de 27/09 para completar o horizonte.

Usar retorno open-to-open de oito horas, atraso de uma hora, decisões em 00:00/08:00/16:00, HGB mensal já congelado e os grupos `own_lag_hgb`, `leader_lag_hgb` e `combined_lag_hgb`. O último evento derivável do cache anterior pode coincidir com 01/09 00:00; mantê-lo uma única vez somente se os lags próprios e líderes forem idênticos aos reconstruídos com os ZIPs de setembro. Contextos Spot novos populam apenas os lags próprios, dos líderes e as IDs fixas; os campos técnicos não usados ficam ausentes. Não treinar, filtrar, reordenar ou ajustar modelos com os resultados de setembro.

Executar a regra spot long/cash já congelada, no máximo 25% de equity por ativo, sem alavancagem, a 0,15% e 0,30% presumidos por lado. Manter como controles `always` e `buy_hold`, reiniciando cada carteira com 1,0 no início. Reportar quantidade de previsões/labels, MSE, MAE, direção, operações, retorno acumulado, CAGR meramente descritivo, DD observado e limite adverso intrahorário. Os custos, spreads e fills não foram observados na conta; positivos por 25 dias não provam consistência nem satisfazem o gate anual 50%/10%.

## Limites e integridade

Este é um holdout temporal recente para os modelos definidos, não uma garantia de que o usuário não tenha visto os preços em outra fonte. A janela é curta, as quatro séries são correlacionadas e as aberturas OHLC não provam preenchimentos. Não escolher ativo nem modificar regras por resultado. Um resultado positivo só autoriza considerar uma observação paper prospectiva mais longa; não autoriza ordens reais. Não enviar ordens nem chamadas JEV.

```json
{
  "schema_version": 1,
  "base_summary": "docs/lagged_flow_ablation_research_2026-09-27.json",
  "symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"],
  "daily_archives": ["2026-09-01", "2026-09-26"],
  "execution_period_utc": ["2026-09-01T00:00:00+00:00", "2026-09-26T16:00:00+00:00"],
  "decision_interval_hours": 8,
  "target_horizon_hours": 8,
  "execution_delay_hours": 1,
  "models": ["own_lag_hgb", "leader_lag_hgb", "combined_lag_hgb"],
  "side_costs": [0.0015, 0.003],
  "allocation_per_asset": 0.25,
  "target_net_cagr_pct": 50,
  "maximum_drawdown_pct": 10,
  "acceptance_gate_for_25_day_window": false,
  "orders_authorized": false
}
```
