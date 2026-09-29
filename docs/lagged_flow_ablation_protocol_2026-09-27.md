# Protocolo: ablação de campos de fluxo e retornos curtos

Registrado em 27/09/2026 após o HGB amplo mostrar pequena melhora posterior, mas perda líquida e falha em 2026. A próxima pergunta é restrita: lags curtos de retorno e fluxo carregam o incremento ou esse efeito aparece apenas quando misturado aos outros 114 campos técnicos/econômicos?

## Hipótese e modelos

Treinar três HGBRegressor agrupados e pareados, com os mesmos parâmetros congelados no estudo horário, os mesmos eventos, alvos, pesos e cortes mensais:

1. `own_lag_hgb`: retornos e desequilíbrio taker próprios em 1, 2, 3 e 6 horas, mais quatro indicadores fixos de ativo.
2. `leader_lag_hgb`: os mesmos oito lags de BTC e ETH, mascarando o próprio ativo para BTC/ETH, mais os quatro indicadores fixos.
3. `combined_lag_hgb`: lags próprios e dos líderes, mais os indicadores fixos.

Os lags vêm de candles spot fechados até uma hora antes da execução. Retorno usa os fechamentos das extremidades; desequilíbrio é `2*sum(taker_buy_base)/sum(volume)-1`. Campos incompletos continuam ausentes. Não haverá seleção de lags, ativos ou hiperparâmetros após o resultado. A comparação base é o HGB amplo próprio e o HGB amplo com líderes já executados; eles são consumidos como referências congeladas, sem recalcular a grade.

## Walk-forward e avaliação

Manter treino móvel de 365 dias, mínimo de 4.000 rótulos concluídos, rótulos disponíveis estritamente antes do corte e ajuste no primeiro evento elegível de cada mês UTC. Períodos e executor permanecem idênticos ao estudo base: 2024 como desenvolvimento e 01/01/2025–31/08/2026 como posterior; decisões de oito em oito horas, retorno de oito horas, spot long/cash e máximo de 25% por ativo. Cruzar 0,15% e 0,30% por lado com controles `always` e `buy_hold`, gerando 20 cenários para os três novos modelos e controles. Resultados-base dos dois HGB amplos ficam no relatório vinculado.

Reportar MSE, MAE, habilidade contra retorno zero, acerto direcional, CAGR líquido, drawdown horário, bound adverso intrahorário, entradas e retornos anuais 2025 e janeiro–agosto/2026. A referência de meta continua CAGR posterior de 50%, DD até 10%, retorno anual positivo nos dois anos e aprovação pelos dois custos. O período já foi investigado em outros estudos, logo esta ablação é exploratória, não confirmação independente. Mesmo um vencedor desta grade precisa de evidência prospectiva e fills observáveis.

Nenhuma compra/venda, chamada JEV, ajuste de estratégia ativa ou download adicional está autorizado por este protocolo. A preparação usa somente o cache local já verificado.

```json
{
  "schema_version": 1,
  "base_report": "docs/lagged_flow_research_2026-09-27.json",
  "feature_groups": ["own_lags_plus_asset_ids", "leader_lags_plus_asset_ids", "own_and_leader_lags_plus_asset_ids"],
  "symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"],
  "feature_lags_hours": [1, 2, 3, 6],
  "decision_interval_hours": 8,
  "target_horizon_hours": 8,
  "execution_delay_hours": 1,
  "training_window_days": 365,
  "minimum_training_rows": 4000,
  "refit": "first_eligible_event_monthly_cutoff",
  "development": ["2024-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"],
  "later": ["2025-01-01T00:00:00+00:00", "2026-08-31T16:00:00+00:00"],
  "side_costs": [0.0015, 0.003],
  "allocation_per_asset": 0.25,
  "target_net_cagr_pct": 50,
  "maximum_drawdown_pct": 10,
  "historical_point_in_time_verified": false,
  "confirmatory_holdout": false
}
```
