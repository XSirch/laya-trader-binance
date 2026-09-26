# Resultado da comparação entre sessenta e sessenta e oito campos

**A hipótese não atingiu a meta de 50% ao ano com drawdown máximo de 10%.** Os dezesseis cenários de 2024 a 26/09/2026 terminaram com perda líquida. Os dezesseis cenários de 2023 ficaram em caixa, sem operações, pois ainda não havia 52 semanas completas de treino. Acrescentar os oito campos de posicionamento não melhorou o erro preditivo agregado nesta configuração. Isso rejeita a família testada para a meta; não demonstra que qualquer uso possível desses dados seja inútil.

O experimento foi congelado em `aa9046e`, antes dos resultados, conforme o [protocolo](positioning_prediction_protocol_2026-09-26.md). A [aquisição auditada](positioning_acquisition_2026-09-26.md) preservou 4.896 arquivos e produziu 3.899 snapshots utilizáveis. Após exigir os lags definidos, restaram 3.565 observações ativo/segunda-feira. O controle de sessenta campos e o modelo de sessenta e oito usaram os mesmos ativos, datas, rótulos, pesos, períodos, custos, hedge e stops. Esse controle difere do modelo anterior com universo completo; não comparar diretamente os resultados como se apenas as features tivessem mudado.

Cada modelo teve **33 ajustes mensais, 134 semanas de previsão e 2.339 previsões individuais somadas entre os ativos**. A avaliação preditiva pareada conta 2.286 resultados completos. O primeiro ajuste ocorreu em **22/01/2024**, com 52 semanas e 1.029 amostras; o último, em 07/09/2026, com 181 semanas e 3.288 amostras. Os rótulos de treino terminam estritamente antes do corte de previsão. Os dois modelos compartilham 184 semanas de rótulos completos, totalizando 3.335 amostras; três semanas com rótulo incompleto foram registradas, incluindo os encerramentos de EOS/MKR e a última semana ainda incompleta.

Os números financeiros abaixo são anualizados sobre todo o período fixo de janeiro de 2024 a 26/09/2026, incluindo o caixa inicial. Incluem funding e descontam os custos simulados de negociação, antes de tributos. DD é o drawdown máximo marcado por hora, não uma perda máxima garantida.

| Bruto | Trailing | Custo/lado | CAGR 60 | DD 60 | CAGR 68 | DD 68 |
|---:|---|---:|---:|---:|---:|---:|
| 1x | sem | 0,15% | -13,31% | 36,77% | -12,42% | 38,85% |
| 1x | sem | 0,30% | -21,07% | 50,15% | -19,91% | 48,43% |
| 1x | 4% | 0,15% | -6,85% | 29,46% | -8,10% | 29,18% |
| 1x | 4% | 0,30% | -12,94% | 37,09% | -15,80% | 39,49% |
| 2x | sem | 0,15% | -29,29% | 65,54% | -26,45% | 65,62% |
| 2x | sem | 0,30% | -41,53% | 79,01% | -38,63% | 75,67% |
| 2x | 4% | 0,15% | -1,26% | 31,33% | -23,44% | 57,43% |
| 2x | 4% | 0,30% | -28,27% | 66,70% | -38,99% | 75,53% |

No modelo ampliado com exposição bruta de 1x e custo de 0,15% por lado, o trailing de 4% reduziu o drawdown de **38,85% para 29,18%** e mudou o CAGR de **-12,42% para -8,10%**. A trajetória continuou perdedora e excedeu o teto de 10%. Esse stop usa o pico observado enquanto há posições; depois de sair e entrar novamente, uma nova sequência de perdas pode aumentar a queda acumulada da carteira. Marcações horárias, custos e saltos de preço também impedem interpretar 4% como limite garantido.

Nesse cenário, houve 36 horários distintos de fechamento por stop, envolvendo 255 fechamentos de pernas. A atribuição acumulada, em pontos percentuais do patrimônio inicial, foi preço **6,78**, funding **-0,27** e custos **27,14**, resultando em **-20,63%**. Essa atribuição não equivale a um novo backtest sem custos, pois os custos também afetam o patrimônio usado para dimensionar posições futuras.

| Período | Amostras comuns | R² 60 | R² 68 | Acerto direção 60 | Acerto direção 68 |
|---|---:|---:|---:|---:|---:|
| 2024–26/09/2026 | 2286 | -0,018664 | -0,019486 | 50,70% | 50,00% |
| 2024 | 857 | -0,024000 | -0,025996 | 50,18% | 51,34% |
| 2025 | 869 | -0,014787 | -0,012240 | 52,24% | 51,67% |
| 2026 parcial | 560 | -0,005038 | -0,007511 | 49,11% | 45,36% |

R² é relativo à previsão zero do retorno semanal já centrado na seção transversal. Todos os valores anuais e agregados foram negativos para ambos os modelos. O acerto direcional sozinho não demonstra rentabilidade: ele não considera a magnitude dos erros, o tamanho das posições ou o custo de negociar. Não houve seleção de parâmetros, inversão de previsões ou remoção de indicadores depois desses resultados.

Os dezesseis replays posteriores foram concluídos e não registraram falha do teste heurístico de margem. Todos, porém, envolveram liquidação de EOS por um intervalo adverso documentado; o modelo ampliado também envolveu MKR. Os valores finais efetivos dessas liquidações não são comprovados por esta simulação. O limite adverso intrahorário do cenário ampliado de 1x com trailing e custo de 0,15% foi **29,79%**, igualmente acima da meta. A ausência de falha heurística não valida margem real, execução ou liquidez para uma conta.

A [auditoria de artefatos](positioning_prediction_verification_2026-09-26.json) passou: revalidou os hashes de 14.688 arquivos de posicionamento e oitenta páginas XML, âncoras de código/fontes, vetores e valores de previsão, correspondência dos modelos, datas expostas de treino, grade de cenários e identidades de contabilidade. Ela não reconstrói todas as linhas históricas de treino, o caminho intrahorário ou preenchimentos reais; esses limites estão preservados no relatório. Os **394 testes passaram sem skips**, e os arquivos produzidos foram verificados como UTF-8 válido.

Os arquivos de posicionamento são versões observadas agora. A interpretação UTC e a disponibilidade antes da decisão permanecem hipóteses; atrasar o sinal não elimina revisões posteriores. O histórico já foi usado em pesquisas anteriores, de modo que não há confirmação independente intocada. As previsões são relativas, e o hedge de beta pode deixar exposição líquida em dinheiro; o limiar de entrada não é uma estimativa calibrada do retorno total da carteira. Essas limitações continuam visíveis; nenhuma estratégia foi aprovada para operação.

O relatório completo está em `results/positioning_prediction_research.json`, com SHA-256 `2aac3d9149e2b2f926a278cc2f5369be6583c546eaa047d5b2566787e01a0983`. Os inputs têm SHA-256 `8ca65defeb21184f47058044dd39fd348bfd248c907e0fa5c1b06bdb3d442191`; o estado pareado tem `35c38f44b8e403afdd5272860e85474b1aa7d1d0080d489754a783cf3bdce1df`. A [evidência compacta](positioning_prediction_research_2026-09-26.json) guarda parâmetros, métricas, scores e digests. Reproduzir com `.venv-tree/Scripts/python.exe -m jev_trader.positioning_research`; os inputs existentes devem coincidir integralmente ou a execução aborta.

Esta rodada usou zero chamadas JEV e enviou zero ordens reais. O gasto JEV acumulado permanece em US$ 0,448006314 do teto autorizado de US$ 2. O watcher paper não foi alterado. A meta permanece não atingida; os resultados desta família não justificam executá-la com dinheiro real.
