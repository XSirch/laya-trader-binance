# Consistência não exige lucro em toda janela

A combinação de baixa volatilidade e carry protegido continua sendo um candidato com evidência histórica favorável. O critério anterior que exigia resultado positivo em toda janela e dois terços dos meses positivos era uma convenção do screening, não uma condição necessária para expectativa positiva. Uma perda recente precisa ser avaliada em relação à distribuição de perdas e à exposição, sem aprovação automática nem rejeição automática.

Esta análise mantém as regras e compara a referência com o trailing de carteira de 4%. Não modifica sinais, escolhe outra distância nem promove um vencedor após os resultados. A referência sem trailing permanece a escolha mecânica de desenvolvimento do experimento de contexto.

## Retorno e risco na trajetória contínua

Janeiro/2024 a 26/setembro/2026, 999 retornos diários, custo de 0,15% por lado:

| Métrica | Sem trailing | Trailing de carteira 4% |
| --- | ---: | ---: |
| Retorno acumulado líquido simulado | +29,16% | +37,57% |
| Crescimento anualizado | +9,80% | +12,36% |
| Queda máxima observada a cada hora | 12,49% | 7,43% |
| Maior sequência diária sem recuperar o pico | 319 dias | 117 dias |
| Janelas móveis positivas de 365 dias | 635/635 | 635/635 |
| Pior janela móvel de 365 dias | +1,03% | +7,39% |
| Janelas móveis positivas de 90 dias | 685/910 | 768/910 |
| Pior janela móvel de 90 dias | -9,30% | -6,06% |

As 635 janelas anuais se sobrepõem fortemente: não são 635 experimentos independentes. A duração sem recuperar o pico também não é um limite futuro. Ambas as carteiras terminam o histórico 117 dias abaixo do pico, portanto essa sequência ainda não tem recuperação observada. A custo de 0,30%, os retornos agregados continuam positivos (+23,20% e +26,98%); a referência sem trailing passa a ter sete janelas anuais negativas, com pior resultado de -0,66%.

## Correção da comparação recente

O relatório anterior usou replays que começavam agosto em caixa. Isso mede uma entrada nova, não o resultado de manter a carteira já em andamento:

| Agosto–26/setembro, 56 dias | Sem trailing | Trailing 4% |
| --- | ---: | ---: |
| Começando em caixa em agosto | -4,59% | -6,05% |
| Continuação da carteira desde janeiro/2024 | -4,71% | -3,84% |

Na carteira contínua, o stop de agosto foi acionado em 21/agosto às 03:00 UTC. Na carteira reiniciada, ocorreu em 23/agosto às 14:00 UTC. O patrimônio, as posições herdadas e o pico anterior mudaram o momento da saída. Portanto, a afirmação genérica de que o trailing piorou o período recente era ampla demais: isso aconteceu no replay iniciado em caixa, mas não na trajetória contínua com custo de 0,15%.

Essa correção não cria superioridade universal. A custo de 0,30%, a trajetória contínua recente perdeu 5,05% sem trailing e 6,50% com trailing. Custos podem mudar a ativação e o estado do controle de risco.

## Como a perda recente se compara ao histórico anterior

Os cenários foram calibrados somente com retornos terminados até a amostra de 1/agosto e geraram trajetórias de 56 dias. Com blocos de 30 dias e 5.000 amostras:

| Diagnóstico condicionado ao histórico anterior | Sem trailing | Trailing 4% |
| --- | ---: | ---: |
| Cenários com qualquer perda | 25,56% | 23,82% |
| Cenários tão ruins quanto o trecho recente observado | 4,18% | 1,74% |
| Percentil 5 do retorno de 56 dias | -4,06% | -2,71% |
| Mediana do retorno de 56 dias | +2,03% | +2,09% |
| Percentil 95 do retorno de 56 dias | +7,14% | +7,14% |

Perdas de dois meses aparecem com frequência mesmo neste histórico de crescimento positivo. Entretanto, a magnitude da perda recente ficou na cauda inferior dos cenários, especialmente com trailing. Nos blocos de 14/30/60 dias, a frequência de resultado tão ruim quanto o observado variou de 3,88% a 4,86% para a referência e de 0,14% a 3,00% para o trailing. Isso é um sinal para investigar deterioração; não é uma prova de que a estratégia deixou de funcionar, nem um motivo para desprezar a perda.

Essas frequências não são probabilidades futuras calibradas ou p-valores de validação. Supõem que os regimes e a dependência temporal do passado continuem representativos. Blocos concatenados também não reproduzem exatamente a dinâmica de posições e do trailing; são cenários da série de retornos já produzida, não novos replays de mercado.

O intervalo individual de crescimento anualizado do trecho anterior a agosto foi aproximadamente +0,04% a +25,36% na referência e +4,73% a +26,00% no trailing, com custo de 0,15%. O limite da referência está muito próximo de zero e é sensível à amostragem. Com custo de 0,30%, o intervalo da referência inclui zero (-1,68% a +23,29%). Esses intervalos não corrigem o histórico de seleção de estratégias; o limite positivo do trailing não deve ser interpretado como prova independente.

## Decisão de pesquisa

Há fundamento para continuar acompanhando o candidato com regras fixas. A conclusão correta é **evidência histórica favorável, com perda recente relevante e consistência futura ainda não demonstrada**. Uma janela negativa, por si só, não encerra a investigação. Tampouco a presença de muitas janelas anuais positivas resolve o viés de seleção, execução real ou mudanças de regime.

Os timestamps diários representam o estado após eventos atribuídos à hora 00:00; a amostra terminal inclui custos de encerramento. Não são marcações puras anteriores a todos os eventos da meia-noite. A divisão cronológica foi preservada, mas todos esses dados já tinham sido examinados pelo pesquisador. As quedas diárias dos cenários podem subestimar as quedas horárias; a tabela principal mantém a medida horária original.

Reprodução: `python -m jev_trader.consistency`. Evidência: `consistency_2026-09-26.json`, com hashes do resultado original, código e protocolo. Não houve gasto adicional com JEV ou envio de ordens.
