# Interações não lineares dos 60 indicadores

A família não linear apresentou algumas curvas positivas, mas ainda não comprovou lucratividade consistente. A configuração selecionada no desenvolvimento, escala 1 com posições inversas à volatilidade, teve retorno acumulado de 13,03% de janeiro/2024 a julho/2026 no cenário condicionado às faixas de liquidação. Foram apenas 14 meses positivos em 31, com perda em 2025 e intervalo estatístico que inclui zero.

## Experimento

Os mesmos 60 indicadores foram convertidos em percentis causais. A transformação usa 64 características de Fourier, semente 548 e escalas 1/2/4, exatamente como registrado antes da execução. Os pesos aleatórios são fixos e não usam resultados futuros. A regressão mantém regularização 0,1, treino móvel de até 104 semanas e mínimo de 52 semanas já encerradas.

Cada escala teve 214 ajustes semanais. As duas formas de dimensionamento resultam em seis variantes, mais caixa. O replay usa candles horários, funding, exposição bruta alvo limitada a 50% e custos de 0,10%, 0,15% e 0,30% por lado. Não houve chamada paga ao JEV.

## Retorno líquido no cenário de custo de 0,15%

| Escala e dimensionamento | Desenvolvimento 2022–2023 | 2024 | 2025 | Janeiro–julho/2026 | Combinado posterior |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1; valores iguais | +1,97% | +8,95% | +2,00% | +0,84% | +11,50% |
| **1; inverso da volatilidade — selecionada** | **+2,76%** | **+11,70%** | **-0,65%** | **+1,19%** | **+13,03%** |
| 2; valores iguais | -24,39% | -10,55% | +3,11% | -7,75% | -17,98% |
| 2; inverso da volatilidade | -26,78% | -8,97% | +2,84% | -5,85% | -15,11% |
| 4; valores iguais | -12,26% | -6,85% | +6,90% | -2,55% | -6,06% |
| 4; inverso da volatilidade | -11,72% | -12,61% | +6,83% | -0,61% | -10,58% |

Os resultados de 2025 e do combinado das escalas 1 e 4 dependem do cenário documentado de liquidação por faixas de preço do índice. Seus replays estritos interrompem por ausência do preço exato. A escala 2 não precisou dessa aproximação e perdeu nas duas formas de dimensionamento. O cenário não transforma uma faixa documentada em comprovação do settlement real.

Embora a escala 1 com valores iguais tenha ficado positiva em todas as janelas anuais listadas, sua curva combinada teve apenas 13/31 meses positivos. Ela não era a seleção de maior retorno no desenvolvimento. Não foi promovida após observar os anos posteriores.

## Erro de previsão e múltiplas tentativas

Na escala 1, o R² fora da amostra foi aproximadamente 0,000715 no agregado posterior; em 2025 e 2026 ele foi negativo. Essa pequena redução do erro agregado não estabelece uma vantagem econômica estável.

Para a variante não linear selecionada, o intervalo de 95% do retorno anualizado ficou entre -8,30% e +23,52%. O p-valor do teste da família foi aproximadamente 0,53. A queda máxima horária foi 10,49%, mas controlar a queda, isoladamente, não comprova vantagem de previsão.

Também foi executado um diagnóstico conjunto com as 18 variantes das famílias econômica, técnica e não linear, mais caixa. A escolha pelo desenvolvimento continuou sendo o modelo econômico 0,1 com pesos inversos à volatilidade. O p-valor da estatística máxima conjunta ficou em aproximadamente 0,57, e o intervalo da escolha continuou incluindo zero. Esse ajuste cobre estas 18 variantes, não todas as experiências anteriores, e depende das hipóteses de liquidação já documentadas. A criação sequencial das famílias após observar resultados também limita qualquer interpretação confirmatória.

## Próximo problema a investigar

Na variante selecionada, os custos consumiram 15,77 pontos percentuais do capital inicial e o funding contribuiu -0,58 ponto. A atribuição líquida de XLM (+9,58 pontos) e SUSHI (+8,29 pontos), somada, supera o lucro total, pois outros ativos tiveram perdas que compensaram parte desses ganhos. Essa decomposição evidencia concentração; ela não equivale ao retorno de uma carteira recalculada sem esses ativos.

As carteiras atuais ordenam as previsões e negociam os extremos, mesmo quando a vantagem prevista é pequena diante do custo de alterar as posições. A próxima hipótese será uma política explícita de decisão sensível a custos, comparando manter, ajustar e encerrar posições. Será registrada separadamente; seus resultados não poderão ser usados para reclassificar estas curvas como aprovadas.

Reprodução: `python -m jev_trader.broad_nonlinear` para execução estrita, acrescentando `--settlement-bounds` para o cenário condicionado. A comparação conjunta é executada por `python scripts/compare_prediction_families.py`. Os arquivos de resultados preservam os sinais, coeficientes, horários de treino, perdas e limitações.
