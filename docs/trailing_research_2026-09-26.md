# Avaliação de trailing stop

O trailing sobre o patrimônio total da carteira foi mais promissor que stops apertados por posição nesta simulação. **O trailing de 4% na carteira reduziu a queda máxima de 12,49% para 7,43% e elevou o retorno líquido de 29,16% para 37,57%.** Ele não evitou perdas em todos os períodos: na avaliação independente de agosto–setembro, o prejuízo aumentou.

## Comparação principal

Base: combinação já fixada de baixa volatilidade e carry com hedge de beta, sem mudar seus sinais. Período: 1º de janeiro de 2024 a 26 de setembro de 2026 às 00:00 UTC. Custos de 0,15% por lado, funding e saídas incluídos.

| Proteção | Retorno acumulado | Queda máxima horária | Meses positivos |
| --- | ---: | ---: | ---: |
| Sem trailing | +29,16% | 12,49% | 20/33 |
| Por posição: 2% | -9,29% | 12,92% | 11/33 |
| Por posição: 4% | -6,16% | 16,03% | 13/33 |
| Por posição: 8% | +5,70% | 14,11% | 17/33 |
| Carteira: 2% | +18,59% | 9,01% | 16/33 |
| **Carteira: 4%** | **+37,57%** | **7,43%** | **21/33** |
| Carteira: 8% | +29,45% | 11,75% | 20/33 |
| Por posição: 2 ATRs | +0,75% | 10,97% | 17/33 |
| Por posição: 3 ATRs | +15,82% | 8,52% | 19/33 |

O trailing percentual e o ATR por posição podem encerrar uma perna e deixar a outra exposta. O máximo de exposição líquida absoluta observado foi aproximadamente 9,86% do patrimônio sem trailing e 28,12% com trailing de 3 ATRs. Esse aumento é um dos motivos para avaliar proteção sobre a carteira inteira em uma estratégia com posições compradas e vendidas.

## Resultado por período e custo maior

| Janela, simulada separadamente | Sem trailing | Carteira 4% | Posição 3 ATRs |
| --- | ---: | ---: | ---: |
| 2024 | +4,99% | +15,05% | +6,49% |
| 2025 | +21,72% | +17,23% | +5,01% |
| Janeiro–julho/2026 | +8,13% | +8,13% | +6,70% |
| Agosto–26/setembro/2026 | -4,59% | **-6,05%** | -0,41% |

Com custo de 0,30% por lado, o agregado ficou em +23,20% sem trailing, +26,98% com trailing de 4% na carteira e +6,29% com 3 ATRs. O caso de 4% continuou pior no período recente: -6,50%, contra -4,94% sem trailing. Como o patrimônio influencia o acionamento do stop, alterar os custos também pode alterar o caminho das operações; não é apenas uma subtração fixa do retorno final.

Cada janela da tabela começa em caixa e reinicia o máximo do ciclo. Seus retornos não devem ser multiplicados como se fossem a mesma carteira contínua do agregado.

## Regras efetivamente simuladas

- O trailing por posição usa apenas extremos favoráveis de horas encerradas. Uma máxima da hora atual não pode apertar um stop retroativamente antes de uma mínima da mesma hora.
- Gaps saem pela abertura observada, mesmo quando pior que o nível do stop. Toques durante a hora usam o nível de acionamento e os custos definidos; essa execução continua sendo uma hipótese de liquidez, não uma ordem real comprovada.
- O ATR usa candles diários completos, com uma hora de defasagem para sua disponibilidade. O stop nunca afrouxa e uma mudança de quantidade no mesmo sentido não apaga o máximo/mínimo favorável.
- O trailing da carteira verifica o patrimônio nas aberturas horárias e fecha todas as pernas. Não usa extremos intrahorários de moedas diferentes como se tivessem ocorrido simultaneamente.
- Após uma parada, a reentrada aguarda um rebalanceamento semanal posterior. Um novo ciclo reinicia o máximo. Por isso perdas repetidas ou gaps podem produzir queda acumulada maior que os 4% de distância do stop.
- Créditos de funding de ordem temporal incerta na hora de um stop são retidos; obrigações são debitadas de forma conservadora.

## Evidência e limite da conclusão

O bootstrap em blocos de 30 dias, com 2.000 amostras e as nove configurações, produziu intervalo anualizado de 95% de aproximadamente +2,36% a +23,37% para o trailing de 4% na carteira. O p-valor da estatística máxima dessa família foi aproximadamente 0,037.

É uma evidência retrospectiva favorável **dentro desta comparação**, mas o ajuste não cobre todas as hipóteses anteriores da pesquisa. O parâmetro de 4% foi destacado depois de comparar o conjunto, e todos os períodos já haviam sido examinados. Portanto, não considero comprovada a consistência futura, especialmente diante da piora recente e dos 21/33 meses positivos. Não houve autorização ou envio de ordens reais.

A conclusão prática é continuar validando o trailing da carteira como candidato de controle de risco, mantendo o caso sem trailing como referência. Não adotar stops apertados por posição apenas por parecerem mais protetores. A próxima confirmação deve incluir atraso de execução, estabilidade de parâmetros e dados cronologicamente novos, sem reajustar o parâmetro ao próximo resultado.

Implementação: `src/jev_trader/trailing_stop.py`. Reprodução: `python -m jev_trader.trailing_research` e `python scripts/snapshot_trailing.py`. O JSON compacto contém métricas e hashes; eventos individuais e curvas completas ficam em `results/trailing_research.json`.
