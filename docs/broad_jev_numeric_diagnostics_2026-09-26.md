# Por que o filtro numérico ficou quase sempre em caixa

O filtro numérico fixado no protocolo aprovou a carteira em apenas **4 das 143 semanas** de janeiro/2024 a 26/setembro/2026. A restrição resulta da combinação dos critérios por ativo com a exigência de aprovação de pelo menos 60% do peso bruto da carteira. Não houve alteração de limiar, escolha de vencedor ou teste de novos parâmetros neste diagnóstico. As respostas do JEV e os resultados do replay pago não foram utilizados.

Foram lidos os dois artefatos já preparados, sem chamadas de rede nem novas simulações:

| Artefato | SHA-256 dos bytes lidos |
|---|---|
| `results/broad_jev_events.jsonl` | `d8986609ff675bf6e211b74c47974c728a5804886af653ba31b696d97397cb1d` |
| `results/broad_jev_prepare.json` | `610d89468dbafd63f0d37b2cf5f2a1ec0e18159738d4e1155838eaa5f8c01171` |

O arquivo de eventos contém 2.785 observações de ativo/semana com peso não nulo: 1.309 em 104 semanas de desenvolvimento, de 2022 a 2023, e 1.476 em 143 semanas no período posterior conhecido. Cada observação conserva os sessenta campos arredondados enviados à avaliação, direção, liquidez, peso original e resultado numérico dos cinco critérios. As datas são os fechamentos dos sinais de segunda-feira às 00h UTC, após o término do candle diário de domingo; a execução simulada ocorre uma hora depois.

## Método descritivo

As taxas abaixo contam o resultado binário existente em `numeric_adherence`; cada observação tem o mesmo peso nessas taxas por critério. Para a aprovação do ativo, o script exige risco maior ou igual a 0,75 e pelo menos dois dos outros quatro critérios maiores ou iguais a 0,65. Como o comparador numérico retorna somente zero ou um, isso equivale a risco aprovado e pelo menos dois apoios aprovados.

Para cada semana, a fração aprovada é:

`soma(abs(peso_original) dos ativos aprovados) / soma(abs(peso_original) de todas as posições não nulas)`.

BTC entra no numerador e no denominador pelas mesmas regras, inclusive quando seu peso decorre de hedge. O gatilho de carteira é fração maior ou igual a 0,60. Quando ele passa, todas as posições originais recebem uniformemente a escala 1 ou 4, preservando as proporções; o cálculo não elimina posições individuais reprovadas. Os dois tamanhos de exposição têm, portanto, as mesmas semanas aprovadas pelo filtro numérico.

Os percentis das frações semanais usam a posição `q * (n - 1)` da lista ordenada, com interpolação linear entre vizinhos. As observações por ativo e por semana não são independentes; as contagens não constituem testes de significância, probabilidades futuras ou validação econômica de uma estratégia.

## Aprovação dos critérios

Valores em porcentagem de observações, sem ponderação pelo peso financeiro.

| Amostra | Observações | Tendência | Timing | Participação | Estrutura | Risco | Aprovação completa, contagem |
|---|---:|---:|---:|---:|---:|---:|---:|
| Todo o histórico | 2.785 | 51,17% | 67,50% | 16,37% | 13,43% | 34,83% | 482 |
| Todo o histórico, comprado | 1.324 | 45,32% | 65,18% | 14,50% | 13,75% | 49,70% | 322 |
| Todo o histórico, vendido | 1.461 | 56,47% | 69,61% | 18,07% | 13,14% | 21,36% | 160 |
| Jan/2024–set/2026 | 1.476 | 53,86% | 70,12% | 17,41% | 14,43% | 36,18% | 278 |
| Jan/2024–set/2026, comprado | 713 | 53,30% | 68,86% | 14,87% | 13,74% | 54,00% | 202 |
| Jan/2024–set/2026, vendido | 763 | 54,39% | 71,30% | 19,79% | 15,07% | 19,53% | 76 |
| Desenvolvimento 2022–2023 | 1.309 | 48,13% | 64,55% | 15,20% | 12,30% | 33,31% | 204 |

No período posterior, apenas 278/1.476 observações, ou 18,83%, passam pelo conjunto. São 202/713 entre posições compradas, 28,33%, e 76/763 entre vendidas, 9,96%.

## Reprovação por risco e por apoios

As categorias desta tabela são mutuamente exclusivas. “Apoios insuficientes” significa menos de dois critérios aprovados entre tendência, timing, participação e estrutura.

| Amostra | Só risco reprova | Só apoios reprovam | Ambos reprovam | Ambos aprovam |
|---|---:|---:|---:|---:|
| Todo o histórico | 943 | 488 | 872 | 482 |
| Desenvolvimento 2022–2023 | 432 | 232 | 441 | 204 |
| Jan/2024–set/2026 | 511 | 256 | 431 | 278 |
| Jan/2024–set/2026, comprado | 161 | 183 | 167 | 202 |
| Jan/2024–set/2026, vendido | 350 | 73 | 264 | 76 |

No período posterior, os componentes do critério de risco apresentam estas falhas. Diferentemente da tabela anterior, **as contagens se sobrepõem**, porque um ativo pode violar vários limites ao mesmo tempo:

| Condição que reprova risco | Todas as 1.476 observações | 713 compradas | 763 vendidas |
|---|---:|---:|---:|
| Volatilidade econômica diária acima de 0,05 | 408 | 36 | 372 |
| ATR diário acima de 6% | 746 | 145 | 601 |
| Retorno diário técnico absoluto acima de 8% | 82 | 17 | 65 |
| Liquidez histórica abaixo de 10 milhões | 0 | 0 | 0 |
| Direção × carry anualizado histórico abaixo de −0,05 | 250 | 230 | 20 |

O limite de ATR reprova 601/763 posições vendidas, 78,77%, e o de volatilidade reprova 372/763, 48,75%. Nas posições compradas, o carry desfavorável reprova 230/713, 32,26%, seguido por ATR em 145/713, 20,34%. O carry representa funding passado anualizado, sem previsão de recebimento futuro.

A participação também é pouco frequente: 977/1.476 observações, 66,19%, têm volume relativo abaixo de 0,8. Os votos direcionais de participação, considerados separadamente, passam em 803/1.476, 54,40%, mas 546/1.476, 36,99%, passam nesses votos e falham no volume mínimo. Além disso, 1.261/1.476, 85,43%, apresentam volume relativo abaixo de 1,2, valor exigido pelo ramo de rompimento do critério de estrutura. Esses números descrevem os candles dominicais presentes no calendário fixado; não demonstram por si só uma causa sazonal nem justificam trocar o calendário após observar o resultado.

## Fração do peso bruto aprovado por semana

| Estatística | Desenvolvimento, 104 semanas | Jan/2024–set/2026, 143 semanas |
|---|---:|---:|
| Fração zero, contagem | 37 | 34 |
| Mediana | 14,29% | 17,33% |
| Percentil 75 | 29,30% | 36,44% |
| Percentil 90 | 42,88% | 49,15% |
| Percentil 95 | 46,73% | 54,19% |
| Máximo | 54,69% | 87,51% |

| Intervalo da fração aprovada | Desenvolvimento | Jan/2024–set/2026 | Total |
|---|---:|---:|---:|
| De 0% inclusive a 20% exclusive | 61 | 76 | 137 |
| De 20% inclusive a 40% exclusive | 29 | 39 | 68 |
| De 40% inclusive a 60% exclusive | 14 | 24 | 38 |
| De 60% a 100%, inclusive | 0 | 4 | 4 |

Em 2022–2023, nenhuma semana alcança os 60% exigidos. No período posterior, a aprovação de risco isoladamente abrange pelo menos 60% do peso em 35 semanas; os apoios suficientes isoladamente abrangem esse peso em 53 semanas. Ao exigir que os mesmos ativos satisfaçam os dois grupos, restam quatro semanas. Essas contagens isoladas são decomposições descritivas do filtro; não são resultados de replays com regras alternativas.

| Fechamento do sinal, UTC | Fração do peso aprovada | Ativos aprovados / posições não nulas |
|---|---:|---:|
| 2024-09-30 | 60,848245% | 6 / 9 |
| 2025-04-28 | 62,287914% | 5 / 10 |
| 2026-01-12 | 87,505085% | 9 / 10 |
| 2026-05-04 | 80,464903% | 6 / 9 |

Essas quatro datas coincidem com `active_rebalance_count=4` do cenário `numeric1_none`, período `combined`, custo `stress`. O replay já existente informa 97,20% das horas em caixa, retorno acumulado de 0,621890%, CAGR de 0,226770% e drawdown horário máximo de 1,970067%. Não atingir a meta de 50% ao ano com drawdown máximo de 10% nesse cenário não decorre apenas de o trailing retirar posições: esta comparação específica não tem trailing, e a carteira quase nunca recebe aprovação para entrar.

A evidência identifica uma combinação de requisitos muito restritiva para os pesos e o calendário desta hipótese. O protocolo, os parâmetros, os estados e a série prospectiva permanecem os já fixados. O diagnóstico não promove nenhuma variante, não avalia a qualidade das respostas pagas e não converte menor exposição em prova de uma estratégia lucrativa e consistente.
