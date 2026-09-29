# Resultado: regressão de EV para a regra de baixa volatilidade

O HGB regressor previu retorno líquido por operação e aceitou apenas previsões >= 1.2% do notional. O treino foi walk-forward: só operações encerradas antes de cada segunda-feira UTC entraram no ajuste. Este teste reaproveita uma regra escolhida após inspeção histórica, portanto é exploratório.

| Regra | Validação H2/2025 | Confirmação jan-jul/2026 | Combinado jan/2024-jul/2026 |
|---|---|---|---|
| Regra-base | n=30; acerto 70.0%; payoff 1.2518737435419236; EV 7.4370464394426214; DD 5.03% | n=38; acerto 60.5%; payoff 1.6318268365690802; EV 4.448345876392163; DD 3.19% | n=166; acerto 57.2%; payoff 1.033221932683593; EV 2.7470832286750366; DD 16.74% |
| HGB com gate de EV previsto | n=23; acerto 69.6%; payoff 1.2586145119388583; EV 8.60622379149429; DD 6.17% | n=33; acerto 60.6%; payoff 1.234223229684929; EV 4.035126594035645; DD 3.61% | n=131; acerto 59.5%; payoff 1.276824241242944; EV 6.120756998850826; DD 14.64% |

## Decisão

A regressão não passou todos os gates congelados. Mesmo se alguma janela isolada passar, não é evidência prospectiva porque estes períodos e a regra-base já foram vistos.
Nenhuma ordem real ou chamada JEV foi feita.

Protocolo SHA-256 `e9740e477ab4d7c0753801fc000777b14c85f1b2e0b3a80faefb5c0abc77cb29`; código `4f8bb88eb1141683fe7bf0a7e59e633f7b8969e619b605f588b97915e1fceecc`; ledger-fonte `b4eb4024531520aac41be58f9d229241b1a3392ea6d53a685531e96765f974f3`.
Ledger gerado: `results/low_volatility_ev_forecast_ledger_20260928.csv`.
