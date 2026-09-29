# C15 — Resultado do controle aleatório pareado do C06

Data: 28/09/2026  
Status: ordenamento retrospectivo favorável ao seletor C06; evidência insuficiente para validar estratégia.

## Resultado principal

Foram comparados os 19 eventos que o score direto C06 selecionou (`score > 1,2%`) com 100 grupos aleatórios de 19 candidatos, pareados por mês, símbolo, lado e quartil de risco ex-ante. Cada grupo passou pelo mesmo simulador, com uma posição global, custos-base e stress.

| Métrica | C06 selecionado | Controles aleatórios: mediana | Controles aleatórios: p95 |
|---|---:|---:|---:|
| Média líquida dos 19 eventos selecionados | +1,4571% | −0,2093% | +0,4085% |
| Acerto dos 19 eventos | 36,84% | 15,79% | 26,32% |
| Operações executadas pelo replay | 11 | 16 | 18 |
| PnL-base do replay | +US$ 575,01 | −US$ 99,23 | +US$ 307,89 |
| Profit factor-base do replay | 4,35 | 0,68 | 2,05 |
| Drawdown-base | 2,39% | 2,92% | 3,65% |
| PnL no stress | +US$ 380,50 | −US$ 155,25 | +US$ 160,92 |
| Semanas ativas | 6 | 8 | 9 |

Nenhum dos 100 controles igualou a média dos eventos escolhidos pelo C06 ou seu PnL-base; o maior PnL-base aleatório foi +US$ 433,21. O tail rank empírico foi 1/101 = 0,0099 para ambas as métricas. Esse número descreve apenas estes sorteios pareados: não é um p-valor confirmatório, pois os scores, cutoff e janela já haviam sido examinados.

## Limites do resultado

O replay direto executou somente 11 operações em seis semanas ativas. O EV-base observado foi 1,2617%, payoff 10,17 e profit factor 4,35; o stress ficou positivo em +US$ 380,50. Apesar do ordenamento favorável contra os sorteios, não alcança 200 operações nem oito semanas. O acerto foi 27,27%, longe da preferência de aproximadamente 70%.

A cauda importa: o relatório/proposta anterior registra que retirar os dois maiores ganhos do C06 leva o EV-base a −0,136%. O controle aleatório reforça que os 19 eventos parecem melhores que amostras pareadas dentro desta janela, mas não mostra repetição suficiente dos ganhos em períodos independentes. O modelo de EV decomposto do C14, por sua vez, não aprovou nenhum evento; não deve substituir o seletor C06 com a evidência atual.

Os controles executaram entre 14 e 18 operações porque horários e conflitos de posição diferem entre sorteios. O simulador aplicou as mesmas regras a todos. O drawdown aleatório mediano foi maior que o C06, mas esse comparativo não aprova risco nem constitui teto de drawdown.

## Método e integridade

- Foram usados exatamente 100 sementes pré-registradas, 1701–1800, sem reposição dentro de cada estrato.
- Os cortes de quartil de `stop_fraction_signal` vieram do treino histórico anterior de cada mês; nenhum desfecho futuro participou da formação dos grupos.
- O replay C06 foi reproduzido antes da comparação e reconciliou em todas as métricas salvas.
- Não houve retreino, mudança de cutoff, escolha de semente, ajuste de posição ou ordem real.
- O período de janeiro a agosto de 2026 já havia sido usado em C05/C06/C12/C13/C14; portanto, o resultado é retrospectivo e não independente.

## Decisão

Manter o score direto C06 como hipótese exploratória com ordenamento promissor, não como estratégia pronta. Preservar o cutoff e procurar validação em observações futuras congeladas, sem retreino/ajuste com o resultado do período. O C14 fica rejeitado no corte atual. Não usar o resultado aleatório para liberar ordens reais.

## Artefatos

- Pré-registro: [`CICLO15_C06_CONTROLE_ALEATORIO_PROTOCOLO_2026-09-28.md`](CICLO15_C06_CONTROLE_ALEATORIO_PROTOCOLO_2026-09-28.md)
- Dados e resumos: `research/results/cycle15_c06_random_control_2026-09-28/research.json`
- 100 replays: `research/results/cycle15_c06_random_control_2026-09-28/random_control_replays.csv`
- Estratos pareados: `research/results/cycle15_c06_random_control_2026-09-28/matched_strata.csv`
- Trades do C06 reconciliados: `research/results/cycle15_c06_random_control_2026-09-28/c06_trades_base.csv` e `c06_trades_stress.csv`

