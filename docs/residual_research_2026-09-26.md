# Resultado da hipótese de reversão residual

**A hipótese foi rejeitada nesta configuração: os dezesseis cenários completos tiveram retorno líquido negativo e nenhum atingiu 50% ao ano com drawdown de até 10%.** O teste foi inteiramente local, sem chamadas JEV ou ordens reais. Ele acrescenta um mecanismo distinto aos anteriores: reversão do movimento próprio do ativo após descontar sua relação estimada com BTC e ETH, com hedge dos dois fatores.

O [protocolo original](residual_protocol_2026-09-26.md) foi registrado no commit `a634668` antes dos resultados. A regressão usa sessenta retornos antigos; a reversão é estimada nos sessenta retornos seguintes, sem sobreposição entre essas duas janelas. O pacote diário completo de sessenta campos foi calculado e preservado no hash dos estados. Entradas consideram desvio residual, velocidade de reversão, liquidez, volatilidade, deriva, funding e custos. O modelo não usa respostas do JEV para calcular equações determinísticas.

## Duas rodadas preservadas

A primeira rodada, R1, reproduziu exatamente as quatro referências semanais: retorno, drawdown, taxas, curva diária, pesos de rebalanceamento e eventos de stop. Seus oito cenários de 2022–2023 terminaram com perdas. Os oito posteriores foram corretamente marcados como inválidos ao tentar reabrir EOS em **22/maio/2025 às 01h UTC**, depois do encerramento contratual. A contabilidade havia retirado a posição anterior; o episódio de sinal ainda ativo gerou um novo alvo. O simulador recusou preencher essa ordem sem liquidez.

A [correção R2](residual_lifecycle_protocol_2026-09-26.md), registrada no commit `4c168e0`, exclui de decisões futuras somente os contratos cujo comunicado já esteja publicado e cujo horário documentado de proibição de novas posições tenha chegado. Preserva o histórico anterior e os resultados R1. Nenhuma janela, limiar, custo, regra de sinal, exposição ou stop foi ajustado. Os oito cenários de desenvolvimento reproduziram **integralmente** seus resultados R1, inclusive curvas, ordens, funding e auditorias dos sinais.

R1 terminou em 25,22 segundos; R2, em 25,46 segundos nesta máquina. Os estados calculados e as fontes de mercado de R2 reproduziram exatamente os hashes de R1. As duas rodadas são retrospectivas e não constituem observações independentes.

## Resultado após custos e funding

Cada célula contém **CAGR / drawdown máximo horário**, em porcentagem. Os períodos começam separadamente em caixa; não formam uma única trajetória contábil. O trecho posterior vai de 1/janeiro/2024 a 26/setembro/2026, com 999 dias.

| Escala de risco | Trailing de carteira | Custo por lado | 2022–2023 | Jan/2024–set/2026 |
|---|---|---:|---:|---:|
| 1 | Sem | 0,15% | −12,85% / 27,02% | −10,13% / 30,90% |
| 1 | 4% | 0,15% | −12,91% / 27,11% | −9,31% / 29,17% |
| 2 | Sem | 0,15% | −24,48% / 47,27% | −19,81% / 53,11% |
| 2 | 4% | 0,15% | −26,30% / 49,69% | −16,57% / 46,71% |
| 1 | Sem | 0,30% | −20,67% / 38,44% | −16,55% / 42,42% |
| 1 | 4% | 0,30% | −20,89% / 38,07% | −15,89% / 41,16% |
| 2 | Sem | 0,30% | −37,45% / 62,50% | −30,88% / 67,49% |
| 2 | 4% | 0,30% | −42,56% / 68,50% | −28,53% / 63,85% |

A escala 1 busca volatilidade anual estimada de 10%, com alvo bruto de até 100%; a escala 2 dobra os limites. Isso não corresponde a prometer drawdown de 10%. Foram 685 dias com alvo não nulo no desenvolvimento e 882 no trecho posterior. A heurística de margem não sinalizou falha, mas essa ausência não prova ausência de liquidação em uma conta real.

O trailing reduziu algumas perdas posteriores, sem criar rentabilidade. Na escala 1 e custo de 0,15%, o trecho posterior teve onze acionamentos de stop e drawdown de 29,17%, apesar do trailing configurado em 4%. O stop encerra um episódio de exposição; sucessivas reentradas e perdas podem produzir uma queda acumulada muito maior. Em 2022–2023, o mesmo trailing teve cinco acionamentos e piorou ligeiramente o retorno.

## De onde vieram as perdas

Na configuração principal, escala 1 sem trailing e custo de 0,15%, a decomposição é dada em **pontos percentuais do patrimônio inicial**, e não em retornos anuais:

| Componente | 2022–2023 | Jan/2024–set/2026 |
|---|---:|---:|
| Resultado da variação de preços | −8,3235 | −7,3650 |
| Funding | +0,3158 | +0,1766 |
| Custos de negociação | −16,0393 | −18,1559 |
| Retorno líquido acumulado | **−24,0470%** | **−25,3443%** |

Portanto, a configuração principal já perde antes das taxas; reduzir custos isoladamente não demonstraria a vantagem pretendida. Os custos agravam essa perda, com giro de 106,93 e 121,04 vezes o patrimônio inicial nos dois períodos. A aprovação de uma entrada pelo ganho de reversão estimado não cobre todos os reajustes diários posteriores de pesos e hedges.

Todos os oito cenários de desenvolvimento tiveram resultado de preços negativo antes das taxas. No trecho posterior, as duas variantes de escala 2 com trailing tiveram resultado de preços positivo, mas insuficiente para os custos. Na versão a 0,15%, foram +1,4507 pontos de preços e +0,2339 de funding contra 40,7740 de custos, resultando em −39,0894% acumulados. As trajetórias de preço atribuídas mudam entre cenários porque os custos e stops alteram o patrimônio disponível e as quantidades futuras; não são subtrações de uma curva bruta invariável.

## Limites de execução e evidência

Sete dos oito cenários posteriores usaram um encerramento EOS por limite adverso de liquidação; na escala 2 com trailing e custo de 0,30%, a posição já havia sido encerrada antes. Esses limites foram recalculados a partir dos trinta candles de índice de um minuto verificados por hash. Não representam o preço efetivo de uma liquidação em conta real. Nenhum cenário de desenvolvimento depende desse recurso. Os comunicados atuais também não provam que cada detalhe de seu conteúdo existia na publicação original.

O novo simulador exige negócios no candle para todas as ordens, inclusive saídas, terminal e stops. Conserva a cobrança adversa nas colisões de funding, o custo de cada mudança de quantidade e a ausência de funding após a liquidação terminal. Os preços de marcação extremos fornecem um limite adverso intrahorário, sem reconstruir a trajetória exata entre observações. O hedge e o limite de volatilidade são estimados; não garantem neutralidade futura ou teto de perda.

| Artefato | SHA-256 |
|---|---|
| R1 completo, `results/residual_research.json` | `0b52e68ff889e0d74f9120e049847d6b2d7a1a2709c68c52d3b81ba58dfd5a97` |
| Estados calculados, reproduzidos por R2 | `9e99ed3a11e043bb66a8fc5f00686eacaa8a20cecc2536a33fb5a893a4134a94` |
| Entradas R2, `results/residual_lifecycle_inputs.json` | `753a9c159968ac3135692835fa7acc05ad79428ccb5b53abe55fa75b4ac0e6d2` |
| R2 completo, `results/residual_lifecycle_research.json` | `9a034467f3df7f649d68bff4c3386aa31de7c4685482c7aa9cf3f2a40b2e21f3` |

Os resumos versionados preservam a [primeira rodada, inclusive os cenários inválidos](residual_research_2026-09-26.json) e os [dezesseis cenários completos da correção](residual_lifecycle_research_2026-09-26.json). As saídas completas locais conservam curvas, ordens e auditorias diárias. A suíte passou com 220 testes, incluindo causalidade, janelas disjuntas, custos, hedge, agenda, liquidez e restrições contratuais. Esses testes validam comportamento do código; a evidência econômica negativa vem dos replays.

Para reproduzir R2 com as entradas R1 preservadas, sem API:

```powershell
.venv\Scripts\python.exe -m jev_trader.residual_lifecycle_research
```

O comando regrava o relatório R2 e seu horário, alterando seu hash de saída. Reexecutar R1 também regrava seu relatório e rompe o vínculo com a evidência R1 preservada nos inputs R2; isso exige uma nova revisão explícita. Não reutilizar hashes antigos para arquivos regenerados.

Não houve despesa adicional de API: o ledger JEV anterior permaneceu inalterado, com gasto cumulativo de US$ 0,448006314. Nenhuma configuração residual foi promovida à carteira paper. A conclusão é restrita a esta hipótese e protocolo: não apareceu vantagem líquida que sustente a meta de 50%/10%, e não se afirma a impossibilidade universal de uma estratégia lucrativa.
