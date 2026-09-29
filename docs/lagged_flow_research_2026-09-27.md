# Resultado do estudo de lags entre BTC/ETH e quatro ativos spot

**A hipótese de trading foi rejeitada para esta grade.** Lags de BTC/ETH reduziram ligeiramente o erro do HGB no período posterior em relação ao modelo próprio, mas ambos tiveram skill preditivo negativo contra retorno zero ou média móvel e perderam dinheiro após custos. Nenhum dos vinte cenários satisfez a meta de CAGR líquido de 50%, drawdown máximo de 10%, positividade em 2025 e no trecho de 2026 e aprovação sob dois custos. Nenhum vencedor foi selecionado.

O protocolo foi congelado em [lagged_flow_protocol_2026-09-27.md](lagged_flow_protocol_2026-09-27.md), antes do replay corrigido. Ele se baseia no achado acumulado de que árvores horárias próprias, previsões técnicas/fatores semanais, filtros de posicionamento, carry/funding, reversão residual, barreiras e alavancagem/trailing não demonstraram a meta posterior. Este experimento muda a pergunta: se retornos e fluxo taker recentes de BTC/ETH acrescentam informação para prever o retorno spot seguinte de oito horas em BTC, ETH, BNB e SOL. Estudos prévios usaram features transversais e indicadores de BTC, mas não este painel causal de lags líderes em cada decisão de oito horas.

## Método e dados

O painel contém 15.348 eventos em 142 campos, 3.837 eventos por ativo e 32 ajustes mensais HGB. Cada ativo contribui com os mesmos indicadores técnicos/econômicos congelados no estudo horário, lags próprios e indicadores fixos de ativo. O tratamento adiciona retornos e desequilíbrio de agressão de BTC/ETH nas janelas de 1, 2, 3 e 6 horas. O controle é o mesmo HGB com os campos próprios, sem lags dos líderes; uma média móvel por ativo serve de controle simples de previsão.

As decisões ocorrem às 00:00, 08:00 e 16:00 UTC, com uma hora de atraso. Os rótulos são retornos open-to-open de oito horas; treino só admite rótulos disponíveis antes do corte. A carteira mantém no máximo 25% do capital em cada ativo, sem alavancagem, e paga custos simulados em cada lado. Foram comparados 0,15% e 0,30% por lado em desenvolvimento (2024) e posterior (2025 até 31/08/2026). O conjunto tem 15.336 rótulos válidos, 11.340 previsões por modelo e 11.332 previsões pareadas pontuáveis. Doze rótulos ficaram indisponíveis por caminho ou liquidez não verificável; 4.008 eventos iniciais ainda não tinham histórico de treino suficiente.

Os dados vieram do cache local de 712 arquivos e três manifestos, sem downloads nem gravações de cache. Entradas usam preços de abertura e custos presumidos, não fills históricos observados; a disponibilidade pontual de cada variável histórica também não foi verificada. Os períodos posteriores já foram observados em estudos anteriores, portanto este replay é retrospectivo e não constitui validação independente.

## Precisão das previsões

`skill_vs_zero` compara o erro quadrático com previsão de retorno zero. Valores negativos indicam que o modelo perdeu para esse controle. Os ativos e horários são correlacionados; diferenças são descritivas e não vêm acompanhadas de um teste de significância.

| Período | Modelo | MSE | MAE | Acerto de direção | Skill vs. zero |
|---|---|---:|---:|---:|---:|
| Desenvolvimento | Média por ativo | 0,00037986 | 0,013491 | 52,40% | -0,0002% |
| Desenvolvimento | HGB próprio | 0,00038299 | 0,013571 | 50,45% | -0,8427% |
| Desenvolvimento | HGB + lags BTC/ETH | 0,00038552 | 0,013600 | 50,45% | -1,5090% |
| Posterior | Média por ativo | 0,00032469 | 0,012286 | 50,58% | -0,1750% |
| Posterior | HGB próprio | 0,00033128 | 0,012423 | 49,68% | -2,2079% |
| Posterior | HGB + lags BTC/ETH | 0,00032925 | 0,012416 | 49,84% | -1,5828% |

No período posterior, lags líderes reduziram o MSE do HGB próprio em 0,00000203, cerca de 0,61% em termos relativos; no desenvolvimento, aumentaram o MSE em cerca de 0,66%. A média simples teve o menor MSE em ambos os períodos. O acréscimo dos líderes é um indício pequeno e instável de informação incremental, não uma previsão lucrativa demonstrada.

## Retorno e risco

CAGR, drawdown máximo observado, bound adverso intrahorário e contagem de entradas:

| Regra | Custo/lado | Período | CAGR | DD observado | DD adverso | Entradas |
|---|---:|---|---:|---:|---:|---:|
| HGB próprio | 0,15% | Desenvolvimento | -12,06% | 32,17% | 33,18% | 513 |
| HGB + líderes | 0,15% | Desenvolvimento | -15,01% | 34,91% | 35,78% | 603 |
| HGB próprio | 0,15% | Posterior | -29,30% | 48,32% | 48,72% | 622 |
| HGB + líderes | 0,15% | Posterior | -10,14% | 31,26% | 36,49% | 614 |
| HGB próprio | 0,30% | Posterior | -15,98% | 33,77% | 38,90% | 218 |
| HGB + líderes | 0,30% | Posterior | -13,85% | 32,00% | 37,40% | 239 |
| Sempre entrar | 0,15% | Posterior | -96,72% | 99,71% | 99,71% | 7.292 |
| Comprar e manter quatro ativos | 0,15% | Posterior | -14,28% | 62,54% | 62,94% | 4 |

O melhor CAGR posterior da grade foi -10,14% do HGB com líderes ao custo primário, ainda com queda adversa de 36,49%. Retorno composto por ano desse cenário: **+9,10% em 2025 e -23,29% em janeiro–agosto de 2026**. Ao custo estressado, caiu -3,14% em 2025 e -19,43% em 2026. O controle de média não abriu posições, porque nenhuma previsão superou o custo de ida e volta, e ficou em caixa; isso reforça a dificuldade de superar custos nesse horizonte. O buy-and-hold ganhou 93,87% anualizado no desenvolvimento, mas com drawdown adverso de 39,59%, e perdeu no posterior.

### Grade completa

Todos os modelos, custos e períodos, em porcentagem. `DD` é o drawdown observado; `limite adverso` inclui extremos intrahorários em ordem desfavorável.

| Modelo | Custo/lado | Período | CAGR | DD | Limite adverso | Entradas |
|---|---:|---|---:|---:|---:|---:|
| Média por ativo | 0,15% | Desenvolvimento | 0,00 | 0,00 | 0,00 | 0 |
| Média por ativo | 0,15% | Posterior | 0,00 | 0,00 | 0,00 | 0 |
| Média por ativo | 0,30% | Desenvolvimento | 0,00 | 0,00 | 0,00 | 0 |
| Média por ativo | 0,30% | Posterior | 0,00 | 0,00 | 0,00 | 0 |
| HGB próprio | 0,15% | Desenvolvimento | -12,06 | 32,17 | 33,18 | 513 |
| HGB próprio | 0,15% | Posterior | -29,30 | 48,32 | 48,72 | 622 |
| HGB próprio | 0,30% | Desenvolvimento | -14,59 | 27,00 | 28,15 | 168 |
| HGB próprio | 0,30% | Posterior | -15,98 | 33,77 | 38,90 | 218 |
| HGB + lags BTC/ETH | 0,15% | Desenvolvimento | -15,01 | 34,91 | 35,78 | 603 |
| HGB + lags BTC/ETH | 0,15% | Posterior | -10,14 | 31,26 | 36,49 | 614 |
| HGB + lags BTC/ETH | 0,30% | Desenvolvimento | -18,56 | 32,46 | 33,52 | 203 |
| HGB + lags BTC/ETH | 0,30% | Posterior | -13,85 | 32,00 | 37,40 | 239 |
| Sempre entrar | 0,15% | Desenvolvimento | -92,46 | 92,93 | 93,00 | 4.392 |
| Sempre entrar | 0,15% | Posterior | -96,72 | 99,71 | 99,71 | 7.292 |
| Sempre entrar | 0,30% | Desenvolvimento | -99,72 | 99,73 | 99,74 | 4.392 |
| Sempre entrar | 0,30% | Posterior | -99,88 | 100,00 | 100,00 | 7.292 |
| Comprar e manter quatro ativos | 0,15% | Desenvolvimento | 93,87 | 37,88 | 39,59 | 4 |
| Comprar e manter quatro ativos | 0,15% | Posterior | -14,28 | 62,54 | 62,94 | 4 |
| Comprar e manter quatro ativos | 0,30% | Desenvolvimento | 93,29 | 37,88 | 39,59 | 4 |
| Comprar e manter quatro ativos | 0,30% | Posterior | -14,44 | 62,54 | 62,94 | 4 |

Diagnóstico pós-hoc das entradas a custo primário mostra a quebra temporal com mais detalhe. As entradas do HGB com líderes em 2025 tiveram retorno médio líquido positivo por ativo (de +0,01% a +0,18% por episódio equivalente), mas no trecho de 2026 o retorno médio líquido foi negativo nos quatro ativos (de -0,21% a -0,83%). Os quatro ativos também são correlacionados; este recorte não autoriza escolher um símbolo depois do resultado. Ele sugere uma hipótese de regime, ainda sem regra validada para reconhecê-lo antes da perda.

## Decisão e próximo passo

Esta família de previsões não é candidata a trading nem a ordens reais. O sinal dos líderes melhorou ligeiramente o erro posterior do HGB e as entradas de 2025, mas não sobreviveu ao período parcial de 2026. Histórico já pesquisado impede chamar esse diagnóstico de holdout. A próxima ablação congelada compara HGB com lags próprios, apenas líderes e ambos, para verificar se os lags carregam sinal sem os outros 114 campos; o [protocolo](lagged_flow_ablation_protocol_2026-09-27.md) já fixa modelos, cortes, custos e métricas. Esta ablação ainda será retrospectiva. Qualquer candidato futuro também precisará de confirmação prospectiva, custos reais da conta, spreads e fills executáveis.

**Estado do objetivo:** nenhuma estratégia lucrativa e consistente encontrada até este estudo; a busca continua. O resultado rejeita as regras congeladas, não prova que seja impossível obter uma estratégia lucrativa.

## Artefatos e reprodução

- Resultado com grade, scores e âncoras: [lagged_flow_research_2026-09-27.json](lagged_flow_research_2026-09-27.json).
- Relatório completo local com previsões, rótulos e curvas: `results/lagged_flow_research.json`, 35.503.986 bytes, SHA-256 `d41ed243b720185314aaffa819fb72dfd353cf886be5c672430a6f25acf0a9c1`.
- Snapshot dos insumos congelados: `results/lagged_flow_inputs.json`, SHA-256 `293ed8567f5901b83a74f3f447c6a46825d8c41d55a5d267a8257918a46ed1f3`.
- Hash do relatório completo repetido no resumo: `d41ed243b720185314aaffa819fb72dfd353cf886be5c672430a6f25acf0a9c1`.
- Replay corrigido: 443 segundos; 20 cenários; `goal_achieved=false`, `deployable=false`, zero ordens, downloads, gravações de cache e chamadas JEV.
- Os registros de duas tentativas de replay sem relatório final estão em [lagged_flow_run_log_2026-09-27.md](lagged_flow_run_log_2026-09-27.md); os snapshots usados foram preservados no diretório local de resultados.
