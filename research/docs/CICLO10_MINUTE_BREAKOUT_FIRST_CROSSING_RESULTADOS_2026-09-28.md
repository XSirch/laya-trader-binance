# Ciclo 10 — resultados da transição causal do canal

Executado em 28/09/2026 conforme o [protocolo preregistrado](CICLO10_MINUTE_BREAKOUT_FIRST_CROSSING_PROTOCOLO.md). Resultado operacional: `no_trade_after_fixed_cutoff`; a regra reduziu sobreposição, mas o score não encontrou entrada acima de 1,2%.

## Comparação com C08

O C10 corrigiu a transição de estado após a tentativa não informativa do C09. Manteve o scanner de 1m, ponderação por unicidade, XGBoost mensal, stop ATR15, saída EMA21/15m, cutoff e execução.

| Métrica | C08: breakout em estado | C10: transição corrigida |
|---|---:|---:|
| Candidatos no histórico | 15.410 | 10.694 |
| Rótulos completos | 15.393 | 10.680 |
| Candidatos na seleção | 4.441 | 3.185 |
| Rótulos sobrepostos | 78,41% | 69,08% |
| Fração efetiva dos pesos no treino | 55,8–57,0% | 65,0–66,1% |
| Maior score previsto | +0,668% | +0,602% |
| Candidatos acima do cutoff | 0 | 0 |
| Trades filtrados | 0 | 0 |

O cruzamento anterior/atual reduziu a quantidade de eventos em 31% e a sobreposição em 9,3 pontos percentuais. Ainda assim, nenhum score mensal superou o cutoff congelado. Sem trades filtrados, não existe EV operacional estimável e nenhum gate Rev02 passa. Zero trades não significa lucro nem drawdown nulo de uma estratégia ativa.

## Qualidade do modelo e baseline

No C10, o score teve R² −0,019, correlação 0,058, MAE 0,457% e RMSE 1,140%. O MAE foi menor que o baseline constante de 0,514%, mas o RMSE foi pior que o baseline de 1,129%; o retorno realizado do decil de maior score foi −0,110%. O C08 teve correlação maior (0,145), apesar de igualmente não gerar entrada. A menor redundância melhorou a amostra de treino efetiva, sem produzir previsão forte de retorno acima de 1,2%.

O baseline de entrada sem filtro também permaneceu negativo: 737 trades, EV −0,179%, PF 0,489 e drawdown 52,89%; sob stress, 942 trades, EV −0,393%, PF 0,206 e drawdown 76,27%. A confirmação de rompimento não tornou a regra bruta negociável.

## Decisão

Preservar o C06 apenas como hipótese retrospectiva de cauda: EV +1,262%, stress positivo, mas 11 trades em seis semanas e ganhos concentrados. Preservar a ponderação como método para reduzir peso de rótulos redundantes, sem considerar C08/C10 estratégias aprovadas. Não reduzir o cutoff para produzir trades.

O C09 permanece invalidado por produzir exatamente os mesmos hashes de candidatos e rótulos do C08. O C10 corrige essa hipótese, mas seu filtro não encontra scores altos. Próximo passo: revisar os resultados anteriores das outras famílias de pares cripto documentadas em `docs/` e selecionar uma candidata com evidência mensurável para mudar apenas o componente que falhou. Evitar novos ajustes arbitrários na mesma combinação breakout/retorno. Nenhuma ordem real foi enviada.

## Proveniência

- Relatório JSON: [`cycle10_minute_breakout_first_crossing_2026-09-28/research.json`](../results/cycle10_minute_breakout_first_crossing_2026-09-28/research.json); hashes e ledger em `research/EXPERIMENTS.jsonl`.
- Oito folds XGBoost CUDA; todos registraram `device=cuda:0` e `tree_method=hist`.
- Três testes determinísticos passaram antes do replay.
