# Resultado: filtro ML por vitória do episódio

O modelo HGB treinou em operações completas da regra `rank_blend` encerradas antes de cada decisão, com janela móvel de 104 semanas. A entrada nova foi aceita somente quando a probabilidade prevista de PnL líquido positivo atingiu 70%. O mesmo filtro e as mesmas previsões foram avaliados com 0,10% e 0,15% de custo por lado; a tabela usa o estresse.

| Regra | Validação H2/2025 | Confirmação jan–jul/2026 | Combinado jan/2024–jul/2026 |
|---|---|---|---|
| rank_blend base | n=44; 63,6%; payoff 1,22; EV +5,34%; DD 4,44% | n=58; 60,3%; payoff 1,02; EV +1,99%; DD 4,52% | n=252; 58,3%; payoff 1,03; EV +2,85%; DD 10,79% |
| rank_blend + filtro HGB | n=17; 58,8%; payoff 1,72; EV +10,15%; DD 5,79% | n=20; 70,0%; payoff 0,74; EV +2,31%; DD 5,91% | n=57; 63,2%; payoff 1,25; EV +5,57%; DD 17,29% |

## Decisão

O filtro não passou todos os gates de acerto, payoff, EV, amostra e drawdown nas duas janelas; os valores acima mostram quais critérios falharam.
A probabilidade estimada não foi tratada como calibração comprovada. O teste é retrospectivo e exploratório, porque a regra-base foi escolhida após ver métricas históricas. Nenhum threshold adicional foi tentado.

## Integridade e proveniência

- O ledger de episódios líquidos da regra-base foi reconciliado com o replay original antes do treino; o replay ML também fecha PnL dos episódios com retorno da carteira.
- Os rótulos de treino excluem saídas proxy e posições fechadas artificialmente no fim de uma janela. Cada previsão usa apenas episódios cuja saída ocorreu estritamente antes do sinal.
- Protocolo: SHA-256 `f696fa67040e7d894a9a19703eb2fbc5dedb24faa7eb41c3024cd2cf0afa44bf`.
- Ledger-base: SHA-256 `b4eb4024531520aac41be58f9d229241b1a3392ea6d53a685531e96765f974f3`; reanálise-base `ece50f987518caec9d7adefdf68a9d929716425f7f38a673316fc9a9aaf93e9b`.
- Código do estudo: SHA-256 `f1496f785b60947824a8bfa009276251e05566ceac2189d73ce7be936a65baab`.
- Saídas por episódio: [CSV](../results/episode_ml_meta_filter_ledger_20260927.csv); métricas, previsões e decisões semanais: [JSON](../results/episode_ml_meta_filter_research_20260927.json).

Nenhuma ordem real, chamada paga ao JEV ou alteração no paper JEV foi feita.
