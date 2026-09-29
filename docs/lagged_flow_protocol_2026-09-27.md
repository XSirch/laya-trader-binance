# Protocolo: fluxo e retornos defasados entre criptoativos

Registro antes do novo replay, em 27/09/2026. A hipótese é que retornos e desequilíbrio de agressão de BTC/ETH, observados antes da decisão, melhorem o sinal de retorno spot de oito horas para BTC, ETH, BNB e SOL. Os estudos anteriores usaram indicadores próprios do ativo em previsões horárias e fatores transversais semanais; o teste local de liderança entre ativos ainda não foi executado. Ver [inventário de fontes](cross_asset_sources_2026-09-26.md) e [revisão metodológica](strategy_research_sources_2026-09-27.md).

Todos os períodos históricos do projeto já foram examinados. O posterior abaixo é walk-forward causal dentro deste protocolo, mas não é um holdout de pesquisa intocado. Um resultado positivo continuará retrospectivo e precisará de validação prospectiva.

## Dados e relógio

Usar somente os 712 ZIPs locais e os três manifestos já verificados de spot, perpétuos, mark price e funding, sem downloads. Ativos: BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT. Reutilizar os 114 campos próprios por ativo e acrescentar retornos fechados e desequilíbrio de volume taker em janelas de 1, 2, 3 e 6 horas. O tratamento acrescenta somente campos de BTC/ETH que não dupliquem o ativo previsto. O controle usa os mesmos campos próprios, lags do ativo e identificadores fixos dos quatro ativos.

Decidir às 00:00, 08:00 e 16:00 UTC. Para a execução em `t`, a última informação própria é o candle `[t-2h, t-1h)`; a hora até a execução fica fora do vetor. Retorno e fluxo encerram até esse mesmo candle. O rótulo é `open[t+8h] / open[t] - 1`; sua disponibilidade para treino é o fechamento do candle aberto em `t+8h`, portanto `t+9h`. O treino admite somente rótulos com `available_ms < cutoff_ms`. A ordem e os gaps de cada série permanecem explícitos; não interpolar.

Para cada janela `n` horas, retorno usa os fechamentos das duas extremidades separadas por `n` horas. Desequilíbrio agressor é `2*sum(taker_buy_base)/sum(volume)-1` nos últimos `n` candles. Campos incompletos viram ausência, nunca zero imputado fora do ajuste. As features próprias são comuns aos dois modelos; o tratamento adiciona lags de BTC/ETH, com os campos do próprio líder mascarados quando o ativo previsto já é BTC ou ETH.

## Modelos e política

Pooled HGBRegressor próprio versus pooled HGBRegressor com lags líderes; mesmas observações, alvo, calendário e parâmetros fixos já usados no estudo horário (`squared_error`, taxa 0,05, 100 iterações, sete folhas, profundidade 3, mínimo 40 por folha, regularização L2 10, semente 548, um thread). Ambos incluem um indicador fixo de cada ativo. Uma média histórica por ativo é o controle de previsão. Ajustar no primeiro evento elegível de cada mês UTC, com janela móvel de 365 dias, rótulos completos e no mínimo 4.000 episódios. Não ajustar hiperparâmetros nem filtrar ativos por resultado.

Manter uma parcela máxima de 25% do patrimônio em cada ativo e nunca alavancar. A carteira realiza os episódios a cada oito horas: fecha no open de `t`, depois considera a nova previsão, pagando taxa em cada lado. A regra de previsão compra somente se o retorno previsto superar o limiar bruto exato `2*c/(1-c)`, para custo por lado `c`; o limite de custo não é margem de segurança contra erro de previsão. `always` entra em todos os episódios elegíveis; `buy_hold` mantém quatro parcelas iguais do início ao fim; caixa rende zero.

Usar custos de 0,15% e 0,30% por lado. São hipóteses, não taxas confirmadas da conta. Fills usam aberturas e custos proporcionais, sem spread observado, livro, latência, fila, impacto ou funding de Spot. Candle com liquidez zero pode invalidar a simulação, mas qualidade futura nunca é filtro da previsão corrente. Enquanto exposto, qualquer barra ausente ou OHLC inválido invalida o cenário. O drawdown de referência usa patrimônio em cada abertura de oito horas; o limite adverso também considera máximas e mínimas de cada candle enquanto exposto, em ordem desfavorável.

## Datas e critérios congelados

Desenvolvimento: 01/01/2024 00:00 a 01/01/2025 00:00 UTC. Posterior: 01/01/2025 00:00 a 31/08/2026 16:00 UTC, incluindo a marcação terminal. A última abertura terminal existe no cache; não presumir o candle de setembro. Cada período começa com capital unitário. Reportar também 2025 e janeiro–agosto/2026 separadamente. MSE/MAE dos mesmos eventos disponíveis comparam a contribuição incremental das features líderes, mas não são métricas financeiras.

A meta local exige CAGR líquido posterior de pelo menos 50%, drawdown máximo de no máximo 10%, retorno líquido positivo em 2025 e em janeiro–agosto/2026, e conclusão positiva tanto ao custo primário quanto ao estressado. Reportar todos os modelos, custos, ativos e anos, mesmo sem operações. Nenhuma escolha posterior de ativo, regra, janela, custo ou estatística pode alterar esta grade. Nenhum resultado habilita ordens reais.

```json
{
  "schema_version": 1,
  "symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"],
  "leader_symbols": ["BTCUSDT", "ETHUSDT"],
  "feature_lags_hours": [1, 2, 3, 6],
  "models": ["rolling_mean", "own_hgb", "leader_hgb", "always", "buy_hold"],
  "side_costs": [0.0015, 0.003],
  "allocation_per_asset": 0.25,
  "decision_interval_hours": 8,
  "target_horizon_hours": 8,
  "execution_delay_hours": 1,
  "training_window_days": 365,
  "minimum_training_rows": 4000,
  "refit": "first_eligible_event_monthly_cutoff",
  "development": ["2024-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"],
  "later": ["2025-01-01T00:00:00+00:00", "2026-08-31T16:00:00+00:00"],
  "target_net_cagr_pct": 50,
  "maximum_drawdown_pct": 10,
  "historical_point_in_time_verified": false
}
```
