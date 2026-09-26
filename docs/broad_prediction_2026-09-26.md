# Previsão conjunta dos fatores: resultado retrospectivo

As seis variantes de previsão conjunta não demonstraram uma estratégia lucrativa e consistente. Todas perderam no trecho de janeiro a julho de 2026. A configuração selecionada apenas pelo desenvolvimento, ridge 0,1 com pesos inversos à volatilidade e hedge de beta, também perdeu em 2024. A meta permanece não atingida.

## Experimento executado

Foram combinados dez fatores disponíveis antes da decisão: momentum de 7/30/90 dias, reversão de 1/7 dias, funding acumulado, volatilidade, participação agressora, beta e ensemble de médias móveis. Não se trata de RSI isolado. A família técnica mais ampla, com Fibonacci, MACD e demais indicadores já disponíveis, permanece um experimento separado para não mudar esta hipótese após observar seus resultados.

As entradas foram convertidas em percentis com tratamento igual para empates. Cada regressão usa no mínimo 52 semanas e uma janela de até 104 semanas anteriores; o alvo da semana terminada exatamente no momento do sinal ainda é excluído. O alvo é o retorno relativo semanal incluindo funding. Cada semana recebe o mesmo peso, independentemente do número de ativos. A referência nula permanece em caixa.

Foram adquiridos e verificados 960 arquivos horários adicionais de 2022–2023. O replay de seleção usa a mesma contabilidade global, custos e execução às 01:00 UTC dos períodos posteriores. Os sinais são calculados com dados encerrados às 00:00. O alvo de treino usa aberturas diárias e aproximações adversas de funding, diferença de frequência documentada no JSON.

## Retornos após custo de 0,15% por lado

| Regularização e dimensionamento | Desenvolvimento 2022–2023 | 2024 | Janeiro–julho/2026 |
| --- | ---: | ---: | ---: |
| 0,1; valores iguais | +8,16% | +7,87% | -2,51% |
| **0,1; inverso da volatilidade — selecionada** | **+8,93%** | **-1,79%** | **-2,41%** |
| 1; valores iguais | +6,02% | +6,35% | -3,42% |
| 1; inverso da volatilidade | +6,87% | -0,57% | -1,36% |
| 10; valores iguais | +5,29% | +4,83% | -4,95% |
| 10; inverso da volatilidade | +6,26% | -0,50% | -1,98% |
| Previsão nula / caixa | 0,00% | 0,00% | 0,00% |

Os cenários de custo 0,10% e 0,30% também estão registrados, inclusive para variantes negativas. O desenvolvimento inclui o aquecimento inicial em caixa até haver histórico suficiente de treino.

O replay de 2025 e o combinado interromperam em MKR em 8 de setembro de 2025 às 09:00 UTC, porque havia posição e não havia preço negociável verificado. Esses resultados são **inválidos/incompletos**, não zero e não uma perda estimada. Não se presumiu liquidação pelo último preço nem se removeu o contrato retroativamente. Os resultados completos de 2024 e 2026 são simulações independentes, iniciadas em caixa; não representam os trechos de uma curva contínua cuja execução falhou em 2025.

Como a família não teve execução completa, não foi publicado um teste estatístico de retorno agregado que descartasse silenciosamente as variantes com erro. A falha operacional de 2025 permanece registrada mesmo que os períodos completos já contradigam a consistência da configuração selecionada.

## Qualidade da previsão

Para ridge 0,1, a redução do erro quadrático em relação à previsão zero foi de aproximadamente 0,30% no conjunto de alvos disponíveis de 2024–julho/2026. Em 2026 o erro foi maior que o da referência, com R² fora da amostra de -0,00324. Um ganho pequeno no erro agregado não produziu rentabilidade estável após custos.

Semanas sem alvo completo para todos os integrantes elegíveis são excluídas integralmente do treino, depois que a indisponibilidade já é conhecida. Isso não remove o ativo da decisão corrente nem resolve sua eventual saída. As semanas excluídas, os coeficientes e o timestamp máximo dos alvos usados em cada treino estão preservados no JSON.

## Verificação e próximos passos

Os testes verificam que alterar alvos futuros não modifica previsões anteriores, que o treino exclui alvos ainda não encerrados, que empates não viram sinais pela ordem dos símbolos e que as carteiras respeitam exposição bruta e neutralidade de beta estimado.

A próxima comparação usará a família técnica completa disponível, mantendo registro separado e a mesma disciplina temporal. Também será necessário tratar anúncios de encerramento com evidência da disponibilidade histórica da informação, caso alguma hipótese dependa de operações nesses contratos. Nenhuma combinação será considerada aprovada enquanto a execução estiver incompleta.

Reprodução: `python -m jev_trader.broad_prediction`. Evidência: `broad_prediction_2026-09-26.json` e `broad_training_sources_2026-09-26.json`. Não houve chamada paga ao JEV nem ordem real nesta rodada.
