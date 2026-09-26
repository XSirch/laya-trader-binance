# Resultado: reação após o funding realizado

O experimento fixo concluiu 32 dos 32 cenários com execução válida e encontrou 0 casos que alcançaram simultaneamente CAGR líquido de 50%, drawdown horário de até 10% e nenhuma falha na heurística de margem. Isso não constitui validação de operação real. A meta permanece aberta.

Dos dezesseis cenários de 2024–2026, somente dois foram positivos: o modelo ampliado, sem trailing, com custo de 0,30% por lado. Exposição máxima 1 produziu CAGR de 5,67% e drawdown de 21,30%; exposição 2 produziu 6,60% e 37,47%. Essas mesmas configurações perderam 5,93% e 17,22% em 2023. Portanto, além de não alcançar a meta, esta família não mostrou resultado líquido positivo nos dois períodos.

O custo maior também torna o filtro mais seletivo: com exposição 1 e sem trailing, foram 200 entradas de pernas no cenário de 0,30%, contra 599 no de 0,15%. Isso não significa que aumentar taxas melhora a mesma sequência de operações. Nesses dois cenários positivos, acrescentar trailing de 4% tornou o CAGR negativo e aumentou o drawdown. O trailing ajudou em outras comparações, mas não produziu uma melhoria uniforme nem protegeu a carteira no limite solicitado.

Os cinco novos campos reduziram ligeiramente o erro agregado de previsão no período posterior, mas ambos os modelos tiveram R² negativo contra previsão zero em cada ano. Não há evidência nesta rodada para promover o modelo de 80 parâmetros a uma estratégia consistente. A conclusão se restringe a esta comparação e não exclui outros mecanismos econômicos.

O [protocolo](funding_event_protocol_2026-09-26.md), o código, os testes e o [freeze dos inputs](funding_event_freeze_v2_2026-09-26.json) foram registrados no commit `845963017dd1615ed069fedac475bba58e2ac13f` antes dos resultados financeiros. A suíte completa passou 438 testes, sem skips. Não houve ajuste de parâmetros após os resultados.

A primeira tentativa parou no primeiro ajuste por uma falha da biblioteca com colunas totalmente ausentes, antes de produzir previsões. A [correção técnica](funding_event_runtime_revision_2026-09-26.md) foi testada e congelada em uma revisão separada; os inputs brutos e todas as escolhas financeiras foram preservados. Colunas vazias no treino ficam desativadas até o próximo ajuste, sem antecipar disponibilidade futura.

Foram comparadas árvores com 75 campos de contexto e as mesmas árvores acrescidas de cinco métricas do pagamento recém-realizado, totalizando 80 campos. O controle já inclui médias, Fibonacci, momentum, volatilidade, volume, fluxo, funding histórico e posicionamento quando disponível. A taxa atual também entra no filtro de custo de ambos; a comparação isola sua contribuição adicional à previsão.

As observações são do funding de meia-noite UTC, com decisão às 01h e execução às 02h, horizonte de 24 horas e pares com hedge em BTC. O pagamento anterior à entrada não é recebido pela posição. O script escolhe até três pares que superem custos e funding adverso estimado, e a carteira contabiliza preços, pagamentos efetivos, negociações e stops. JEV e ordens reais: zero nesta rodada.

## Cobertura e comparação

Foram verificados 123.065 eventos e construídas 33.704 observações por ativo/dia; 24.927 tinham posicionamento disponível. As demais preservaram os oito campos ausentes, com flag de disponibilidade, sem substituir a semana. Vinte e uma observações foram excluídas por janela horária incompleta e uma por ausência do evento de meia-noite.

| Modelo | Ajustes mensais | Datas com previsão | Previsões individuais, sem BTC sintético |
|---|---:|---:|---:|
| control75 | 45 | 1363 | 23703 |
| augmented80 | 45 | 1363 | 23703 |

Os modelos compartilham universo, rótulos, pesos e calendário de ajustes. O treino usa somente datas completas cujo horizonte já terminou antes da decisão, com ao menos 365 datas. Rótulos futuros ausentes descartam a data inteira do treino, sem eliminar a previsão daquele dia.

## Carteiras

CAGR e drawdown em %. Custo por lado sobre o valor negociado. O cenário de custo maior também exige um limiar de entrada maior; portanto pode mudar as operações. Valores abaixo são simulações, sem garantia de execução ou rentabilidade futura.

| Período | Bruta máxima | Trailing | Custo/lado | Controle CAGR | Controle DD | Ampliado CAGR | Ampliado DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2023 | 1 | ausente | 0,15% | 10,65 | 24,31 | -19,06 | 35,88 |
| 2023 | 1 | ausente | 0,30% | -14,18 | 21,61 | -5,93 | 22,95 |
| 2023 | 1 | 4% | 0,15% | -9,93 | 31,33 | -24,70 | 36,93 |
| 2023 | 1 | 4% | 0,30% | -27,97 | 32,72 | -23,54 | 30,88 |
| 2023 | 2 | ausente | 0,15% | 6,08 | 44,72 | -40,36 | 62,20 |
| 2023 | 2 | ausente | 0,30% | -31,14 | 42,41 | -17,22 | 41,60 |
| 2023 | 2 | 4% | 0,15% | -44,50 | 52,67 | -60,21 | 71,38 |
| 2023 | 2 | 4% | 0,30% | -47,23 | 53,69 | -20,39 | 34,71 |
| 2024–26/09/2026 | 1 | ausente | 0,15% | -17,13 | 52,46 | -20,50 | 55,32 |
| 2024–26/09/2026 | 1 | ausente | 0,30% | -17,98 | 48,32 | 5,67 | 21,30 |
| 2024–26/09/2026 | 1 | 4% | 0,15% | -21,10 | 58,15 | -17,31 | 49,47 |
| 2024–26/09/2026 | 1 | 4% | 0,30% | -13,65 | 40,50 | -1,53 | 24,43 |
| 2024–26/09/2026 | 2 | ausente | 0,15% | -37,22 | 81,73 | -41,86 | 83,47 |
| 2024–26/09/2026 | 2 | ausente | 0,30% | -37,24 | 77,71 | 6,60 | 37,47 |
| 2024–26/09/2026 | 2 | 4% | 0,15% | -35,66 | 76,99 | -35,86 | 79,84 |
| 2024–26/09/2026 | 2 | 4% | 0,30% | -34,12 | 71,75 | -12,58 | 49,21 |

## Atribuição do cenário predefinido de exposição 1, trailing 4% e custo 0,15%

Este recorte ilustra a composição do resultado; não é seleção do melhor cenário. Os valores de preço, funding e custos são pontos percentuais do capital inicial, e sua soma resulta no retorno total, não no CAGR.

| Modelo, 2024–26/09/2026 | Preço | Funding | Custos | Retorno total | Stops da carteira | Limite adverso de DD |
|---|---:|---:|---:|---:|---:|---:|
| control75 | 8,29 | 0,37 | 56,39 | -47,73 | 57 | 58,73 |
| augmented80 | 14,91 | 1,18 | 56,65 | -40,55 | 46 | 51,38 |

Cada stop pode fechar várias pernas; a tabela conta instantes distintos. Trailing de 4% não é limite garantido para o drawdown total. O limite adverso intrahorário combina extremos simultâneos de marcação e não reconstrói a trajetória de preços dentro da hora.

## Previsão e limites

R² é calculado contra previsão zero de retorno do par. Os erros abaixo são diagnósticos descritivos sobre história reutilizada, sem teste confirmatório independente.

| Período | R² controle | R² ampliado | Amostras por modelo |
|---|---:|---:|---:|
| development | -0,009634 | -0,012551 | 6857 |
| combined | -0,005702 | -0,004458 | 16816 |
| year_2024 | -0,006267 | -0,003766 | 6806 |
| year_2025 | -0,006675 | -0,006522 | 6236 |
| year_2026 | -0,001079 | -0,003843 | 3774 |

A disponibilidade histórica do funding até 01h e dos snapshots de posicionamento não está comprovada. Arquivos atuais podem conter revisões. A presença/ausência de posicionamento pode representar mudanças de cobertura histórica. Os rótulos preveem preço bruto de pares; o custo e o funding adverso são filtros estimados, não uma previsão calibrada de lucro líquido. O hedge usa beta histórico e pode deixar exposição líquida em dinheiro.

Os preços horários, negócios observados depois do fato e a heurística de margem não comprovam fills, spreads, latência ou regras completas de liquidação. Nenhum eventual resultado nominal dispensa confirmação prospectiva. As conclusões se restringem ao horário, horizonte, modelos e custos testados; não demonstram impossibilidade de outras estratégias.

## Verificação e reprodução

A [auditoria independente](funding_event_verification_2026-09-26.json) passou: hashes de fontes/inputs/freeze, pareamento e purga, vetores e previsões persistidas, decisões de carteira, hedge, custos estimados, identidades contábeis e critérios de meta. O auditor não refez os modelos nem reconstruiu todos os rótulos brutos, todas as linhas de treino ou o caminho horário de cada fill; esses limites estão registrados no JSON.

- Relatório completo local: `results/funding_event_research.json`; SHA-256 `af5a925a63d5e1bb027696559a5808a8ad9dd3d752a12f0903b5202431d39f30`.
- Inputs locais: `results/funding_event_inputs_v2.json`; SHA-256 `bcb03120fc003e56a77d46ab4c134adb1a60aca81da3c7d0b09c390973bd9caf`.
- Resumo versionado: [funding_event_research_2026-09-26.json](funding_event_research_2026-09-26.json).
- Replay: `.venv-tree/Scripts/python.exe -m jev_trader.funding_event_research`.
- Auditor: `.venv-tree/Scripts/python.exe .cache/verify_funding_event_result.py`.
- Auditor SHA-256: `b253a26c99bf537faaa73a668623ef1f9fc4394c13035e3352abd91517d8ff32`.

Os módulos anteriores e o watcher paper foram preservados. Nenhuma chamada paga ou ordem foi enviada por esta pesquisa. O resultado e seu commit permanecem locais.
