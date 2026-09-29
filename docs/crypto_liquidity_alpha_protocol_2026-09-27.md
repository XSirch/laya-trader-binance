# Protocolo: liquidez agregada de stablecoins como sinal para pares cripto

## Hipótese e relação com os testes anteriores

As pesquisas anteriores já avaliaram preço e indicadores técnicos cripto, fluxo agressor em resolução horária, funding, basis, posicionamento, sentimento Fear & Greed e variáveis macro tradicionais. A hipótese nova é que crescimento/contração da oferta agregada de stablecoins, um indicador de liquidez interna do ecossistema, acrescente informação semanal para operar pares Spot de cripto. A literatura disponível é mista e não valida esta regra.

O único universo negociado continua sendo BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT Spot. Stablecoins entram somente como variável informativa: nenhuma stablecoin, ETF, ação, índice ou outro produto será negociado. Não usar contratos futuros nesta rodada. A série agregada é um proxy de contexto, não representa capital pronto para comprar cripto nem comprova fluxos para uma corretora.

Todo o período de preço já foi consultado em outras pesquisas do projeto. Esta avaliação é walk-forward causal no código, mas continua retrospectiva e sujeita à seleção entre hipóteses; não é um holdout global intocado.

## Dados, relógio e congelamento

- Preços: reutilizar os arquivos Binance Spot 1h já verificados para BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT, de janeiro/2023 a agosto/2026, o manifesto e a agenda semanal UTC de `macro_external_alpha_research.py`.
- Liquidez: uma resposta bruta de `https://stablecoins.llama.fi/stablecoincharts/all`, endpoint público que a documentação do fornecedor descreve como histórico agregado. A série usada é especificamente `totalCirculatingUSD.peggedUSD` (oferta em USD de stablecoins atreladas ao dólar), sem somar stablecoins de outras moedas de referência. Salvar o payload exato apenas em `.cache/crypto_liquidity_alpha/` e registrar URL, hora UTC de aquisição, bytes e SHA-256. Não substituir silenciosamente uma resposta congelada em execução posterior.
- Auditar registros: timestamps únicos, ordenação cronológica, valores finitos e positivos, campos esperados, intervalo de datas e lacunas. Não interpolar. A API não oferece vintages históricas nesta rota; valores passados podem ser revisados. Por isso, a defasagem abaixo reduz antecipação de publicação, mas não prova disponibilidade histórica ponto a ponto.
- Decisão: domingo às 23:00 UTC; entrada/saída Spot na abertura da segunda-feira 00:00 UTC. Como a rota retorna observações diárias e não documenta a hora de divulgação, a feature usa somente a observação com timestamp no máximo até 96 horas antes da decisão. Exigir que ela e as referências de 7 e 30 dias estejam disponíveis e tenham no máximo 48 horas de distância dos respectivos cortes.
- Janela de treino, datas, primeiro horário comum, corte final e períodos walk-forward/holdout: idênticos ao protocolo de sinais semanais já registrado em `macro_external_alpha_protocol_2026-09-27.md`. Preservar a comparação principal de 06/01/2025 até 31/08/2026, além do desenvolvimento de 2024 e do walk-forward completo disponível.

## Features e regra de entrada/saída

Para cada decisão semanal, criar duas features cripto-nativas:

1. `stablecoin_supply_log_change_7d = log(S_t / S_{t-7d})`;
2. `stablecoin_supply_log_change_30d = log(S_t / S_{t-30d})`.

`S_t` é a oferta em USD de stablecoins atreladas ao dólar na observação mais recente permitida pelo corte de 96 horas. `S_{t-7d}` e `S_{t-30d}` são as observações mais recentes iguais ou anteriores aos respectivos cortes retroativos, sujeitas ao limite de idade de 48 horas. Se qualquer observação faltar, for stale ou inválida, a previsão do modelo ampliado para aquela semana não existe; não preencher com zero.

Comparar, por ativo, as mesmas regressões Ridge expansivas já especificadas para o benchmark semanal:

- `price_only`: retorno próprio do ativo nas últimas 1, 4 e 12 semanas;
- `price_plus_stablecoin_liquidity`: as mesmas três features mais as duas variações de oferta.

Usar `StandardScaler` fitado apenas no treino e `Ridge(alpha=1.0, fit_intercept=True)`, com mínimo de 52 rótulos completos. O alvo é o retorno Spot simples do ativo entre aberturas de segunda-feira consecutivas. Um rótulo só entra no treino se terminou antes do corte de decisão, conforme o atraso temporal do benchmark. Não testar outros modelos, hiperparâmetros, lags ou limiares.

Uma parcela de 25% do capital inicial é mantida por ativo. Cada segunda-feira, ficar 100% comprado na parcela quando a previsão for estritamente maior que `2*c/(1-c)`, onde `c` é o custo presumido por lado; nos demais casos, permanecer em caixa. Manter a posição sem ordem se a decisão continuar comprada. Os custos fixos são 0,15% e 0,30% por lado. Sem shorts, alavancagem, transferência de saldo, piramidagem ou trailing. Encerrar na próxima decisão ou na liquidação terminal prevista.

## Avaliação e decisão

Comparar os modelos nas mesmas semanas e pares disponíveis. Reportar MSE/MAE contra previsão zero e média de treino, habilidade incremental contra `price_only`, acurácia direcional, entradas, exposições, giros, taxas, retorno líquido, CAGR, drawdown nas aberturas e limite adverso pelas mínimas horárias, além de retornos mensais, anuais e por ativo. Incluir os comparadores caixa e buy-and-hold Spot com a mesma alocação.

Este replay só terá compatibilidade retrospectiva com a meta se a regra ampliada alcançar simultaneamente CAGR líquido de pelo menos 50% e drawdown adverso de no máximo 10% no walk-forward comum e no holdout, em ambos os custos, sem escolher ativo depois do resultado. Mesmo se isso ocorrer, a série revisável de stablecoins e os preços históricos já examinados impedem alegar validação confirmatória. A confirmação exigiria observação prospectiva em paper, com snapshots arquivados antes de cada decisão e custos de execução observados.

Não retunar a hipótese depois dos resultados. Não chamar JEV, não alterar o paper watcher e não enviar ordens.

```json
{"schema_version":1,"symbols":["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT"],"tradable_market":"Binance Spot only","tradable_products":["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT"],"stablecoins_are_features_only":true,"stablecoin_field":"totalCirculatingUSD.peggedUSD","stablecoin_endpoint":"https://stablecoins.llama.fi/stablecoincharts/all","publication_lag_hours":96,"max_observation_age_hours":48,"feature_lookbacks_days":[7,30],"price_lags_weeks":[1,4,12],"models":["price_only","price_plus_stablecoin_liquidity"],"estimator":"StandardScaler + Ridge(alpha=1.0)","minimum_training_weeks":52,"side_costs":[0.0015,0.003],"allocation_per_asset":0.25,"target_net_cagr_pct":50,"maximum_adverse_drawdown_pct":10,"historical_point_in_time_verified":false,"orders_authorized":false}
```
