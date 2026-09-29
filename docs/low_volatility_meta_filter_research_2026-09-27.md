# Resultado: filtro ML para low_volatility30_betahedged

Este teste exploratório aplicou um classificador HGB às novas entradas da regra `low_volatility30_betahedged`. O modelo treinou somente com episódios completos dessa mesma regra encerrados antes da decisão, usando janela móvel de 104 semanas; a entrada nova exigiu probabilidade prevista de vitória líquida >=70%. O candidato-base foi escolhido após inspeção dos resultados históricos, então estas janelas não são holdouts independentes.

O custo de estresse é 0,15% por lado. EV representa o PnL líquido médio como percentual do notional inicial por episódio; drawdown é da carteira.

| Regra | Validação H2/2025 | Confirmação jan–jul/2026 | Combinado jan/2024–jul/2026 |
|---|---|---|---|
| low_volatility30_betahedged base | n=30; 70,0%; payoff 1,25; EV +7,44%; DD 5,03% | n=38; 60,5%; payoff 1,63; EV +4,45%; DD 3,19% | n=166; 57,2%; payoff 1,03; EV +2,75%; DD 16,74% |
| low_volatility30_betahedged + filtro HGB | n=23; 65,2%; payoff 1,53; EV +8,29%; DD 6,14% | n=16; 62,5%; payoff 3,15; EV +6,15%; DD 3,91% | n=89; 62,9%; payoff 1,50; EV +8,67%; DD 9,65% |

## Decisão

O filtro não passou todos os gates de acerto, payoff, EV, amostra e drawdown; confira quais critérios falharam por janela no JSON.
O estudo é retrospectivo e exploratório. A regra-base foi selecionada após olhar métricas históricas, probabilidades HGB não têm calibração comprovada, e nenhum threshold ou hiperparâmetro foi ajustado após este replay.

## Integridade e proveniência

- Cada previsão usou apenas episódios cuja saída ocorreu estritamente antes do sinal; saídas proxy e posições truncadas no fim da janela não entraram no treino.
- O PnL líquido dos episódios fecha com o retorno da carteira em cada janela e cenário de custo.
- Protocolo: SHA-256 `56c17ec4530f6182594d37c2a5134e5eb959f84c06bbb68b1f11b8618ad8712a`.
- Ledger-fonte: SHA-256 `b4eb4024531520aac41be58f9d229241b1a3392ea6d53a685531e96765f974f3`; reanálise-fonte `ece50f987518caec9d7adefdf68a9d929716425f7f38a673316fc9a9aaf93e9b`.
- Código do estudo: SHA-256 `f8e71887e12ae9561486343ed583d79ff87395eb87a2045ba0b7aecc14cfd690`.
- Ledger filtrado: [CSV](../results/low_volatility_meta_filter_ledger_20260927.csv); previsões e métricas: [JSON](../results/low_volatility_meta_filter_research_20260927.json).

Nenhuma ordem real, chamada paga ao JEV ou alteração no paper JEV foi feita.
