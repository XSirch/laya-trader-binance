# Previsão semanal com árvores e sessenta indicadores

O novo modelo não sustentou rentabilidade consistente. Os oito cenários de desenvolvimento foram positivos em 2023, mas os oito cenários posteriores perderam entre janeiro de 2024 e 26 de setembro de 2026. Nenhum dos dezesseis cenários cumpriu simultaneamente CAGR líquido de 50% e drawdown máximo de 10%. Um caso alcançou 56,23% em 2023, acompanhado de drawdown de 24,21%; a mesma configuração apresentou CAGR de -49,62% no período posterior. A família foi rejeitada para a meta solicitada, sem promover o melhor ano isolado a evidência de consistência.

O [protocolo](tree_prediction_protocol_2026-09-26.md), código, testes e dependências foram registrados no commit `1f5ab95` antes do replay. O processo terminou com código zero em 86,88 segundos, com os dezesseis cenários completos. [Resultados compactos](tree_prediction_research_2026-09-26.json); relatório completo com sinais, auditorias, curvas e atribuição em `results/tree_prediction_research.json`; entradas preservadas em `results/tree_prediction_inputs.json`.

Foi usado `HistGradientBoostingRegressor` com todos os sessenta campos econômicos e técnicos, incluindo médias, momentum, RSI, MACD, ADX, Bollinger, ATR, fluxo, volume, estrutura, Fibonacci, volatilidade e funding. As árvores têm parâmetros fixos e não receberam busca posterior para melhorar os números. O treino usa rótulos semanais de preços das 01h às 01h, somente depois de encerrados, com janela expansiva e ajuste mensal. A binagem é aprendida no treino, sem divisão aleatória para validação ou parada antecipada. Os detalhes e fontes primárias estão na [nota metodológica](tree_prediction_sources_2026-09-26.md); o protocolo define a configuração final.

Os valores de retorno abaixo são líquidos dos custos e funding simulados. A exposição bruta é a soma dos valores absolutos das posições dividida pelo patrimônio, após hedge de beta por BTC. O drawdown é medido nas marcações horárias. Os dois períodos começam separadamente em caixa.

| Exposição bruta | Trailing | Custo por lado | CAGR 2023 | DD 2023 | CAGR 2024–set/2026 | DD 2024–set/2026 |
|---|---|---:|---:|---:|---:|---:|
| 1,0 | Sem | 0,15% | 27,17% | 12,70% | -26,99% | 59,24% |
| 1,0 | Sem | 0,30% | 15,91% | 14,81% | -33,64% | 68,40% |
| 1,0 | 4% | 0,15% | 24,56% | 12,40% | -14,27% | 36,84% |
| 1,0 | 4% | 0,30% | 11,18% | 16,43% | -20,78% | 48,68% |
| 2,0 | Sem | 0,15% | 56,23% | 24,21% | -49,62% | 85,66% |
| 2,0 | Sem | 0,30% | 29,74% | 27,92% | -58,54% | 91,53% |
| 2,0 | 4% | 0,15% | 35,57% | 24,73% | -24,12% | 61,01% |
| 2,0 | 4% | 0,30% | 7,87% | 31,45% | -42,72% | 79,47% |

Na exposição 1,0 e custo de 0,15%, o trailing reduziu o drawdown posterior de 59,24% para 36,84%, mas a estratégia continuou perdendo. O trailing de carteira observa a abertura de cada hora, permite nova entrada no rebalanceamento semanal e reinicia a referência depois de ficar em caixa. Portanto 4% não é um teto para a perda acumulada da carteira: custos, saltos entre observações e perdas em episódios sucessivos continuam existindo. Mesmo a menor queda de desenvolvimento, 12,40%, excedeu o limite solicitado; o limite adverso intrahorário correspondente foi 13,58%.

O problema não se resume às taxas. Na configuração de exposição 1,0 sem trailing e custo de 0,15%, o período posterior teve perda de preço de 38,73 pontos do capital inicial, funding de -1,47 ponto e custos de 17,52 pontos, totalizando -57,73%. Com trailing, a perda de preço caiu para 7,77 pontos, mas os custos subiram para 25,03 pontos e o funding foi -1,58 ponto, resultando em -34,38%. O cenário de exposição 2,0 com trailing produziu atribuição de preço positiva, mas insuficiente para cobrir custos de 61,23 pontos do capital inicial; isso também não demonstra uma operação líquida viável.

A qualidade das previsões foi medida contra prever retorno relativo zero. R² negativo indica erro quadrático superior ao dessa referência. A acurácia de direção não mede, sozinha, rentabilidade ou significância estatística.

| Período | Observações ativo/semana | R² de previsão | Acerto de direção |
|---|---:|---:|---:|
| 2023 | 1.015 | -0,01869 | 52,12% |
| 2024 | 1.039 | -0,02454 | 48,51% |
| 2025 | 902 | -0,01562 | 53,22% |
| 2026 até setembro | 560 | -0,00939 | 47,68% |
| 2024–set/2026 | 2.501 | -0,02024 | 50,02% |

Foram realizados 45 ajustes mensais e 194 previsões semanais. O primeiro ajuste, em 9 de janeiro de 2023, usou 52 semanas e 1.040 linhas; o último, em 7 de setembro de 2026, usou 241 semanas e 4.529 linhas. A política propôs exposição em 51 das 52 decisões de desenvolvimento e em 140 das 143 decisões posteriores. A primeira decisão de 2023 ficou em caixa por aquecimento. Os stops podem reduzir a exposição efetivamente mantida depois dessas propostas.

Três semanas inteiras tiveram rótulos excluídos: 19 de maio de 2025, pela interrupção de EOS; 8 de setembro de 2025, pela interrupção de MKR; e 21 de setembro de 2026, por ainda não existir a semana seguinte completa no cache. A previsão corrente dessas semanas foi preservada; somente rótulos conhecidos e completos entraram no treino ou na métrica de erro. Nenhuma trajetória desta família precisou aplicar uma faixa de liquidação, e as restrições conhecidas bloquearam novos alvos em contratos encerrados. Ausência de falha no teste heurístico de margem não comprova as condições de uma conta real.

Os dados são os mesmos arquivos de mercado já preservados: 4.182 referências diárias/funding, 1.283 horárias posteriores, 1.045 horárias de treino e 54 snapshots REST. O hash dos estados coincide com o estudo de capacidade de funding, confirmando o mesmo pacote de entrada. A coleta de dados de mercado do experimento foi offline, com downloads bloqueados. Nenhum JEV, ordem real ou alteração da estratégia paper foi executado.

O escore usado no limiar de entrada é alpha relativo: depois do hedge BTC pode restar exposição monetária líquida, cujo retorno comum não é previsto pelo alvo centrado. Ele não deve ser interpretado como retorno total esperado ou probabilidade calibrada de lucro. O custo estimado de ida e volta permanece 0,003 nos dois cenários de execução; dobrar o custo realizado é um stress da mesma política. O histórico foi pesquisado repetidamente e não é uma amostra intocada. Não foi feita inferência de significância favorável a partir do ano positivo.

Validação: os 282 testes passaram no ambiente isolado, incluindo 36 testes novos do modelo e da política. Entre eles há ajuste real repetível do sklearn, alteração de dados futuros sem modificar previsões passadas, purga estrita de rótulos, cobertura horária, lifecycle, hedge, limites de exposição e sinal correto de funding adverso. A revisão independente anterior ao replay não encontrou bloqueios. Código e arquivos escritos foram verificados como UTF-8 válido.

A auditoria independente posterior confirmou os 23 hashes de módulos, protocolo, dependências, fontes metodológicas, lifecycle, settlement e quatro manifests. Reconstruiu os hashes dos 3.569 sinais salvos e das 194 previsões semanais, conferiu a purga e datas de treino dos 45 ajustes, e verificou as 1.560 decisões de política e execução. Limites de exposição e hedge de beta passaram, com resíduo máximo de beta de `1,94e-16`. Preço mais funding menos taxas reconciliam o resultado dos dezesseis cenários, com erro máximo de `2,05e-12` ponto percentual; taxas também correspondem a custo por lado vezes notional negociado. Essa auditoria não refaz o treinamento nem transforma o replay em evidência prospectiva.

Para reproduzir sem alterar o ambiente paper, criar `.venv-tree` com Python 3.13, instalar `requirements-tree.lock` com `--require-hashes`, instalar o projeto editável com `--no-deps` e executar `.venv-tree/Scripts/python.exe -m jev_trader.tree_research`. As versões foram fixadas em sklearn 1.9.1, numpy 2.5.3, scipy 1.18.1, joblib 1.6.0, narwhals 2.26.0, cloudpickle 3.1.2 e threadpoolctl 3.7.0. O lock identifica os pacotes e seus hashes de distribuição; a auditoria de execução compara versões, sem revalidar cada binário instalado.

Hashes de evidência:

- Relatório completo: `aac9e0d18eaad4e6a80d2f0669a39cbb20b453f27b4074add0f8afc419521e77`.
- Entradas: `d13b5e1b0f4d348c681b85ea788a1e0eadb675fc84472e85ec779fcde50f7483`.
- Estados diários: `6858c7cf9f86d184fc292095082f5d11c9dfd96b7128eae0d374e53f8ab326e8`.
- Sinais completos: `f937629200f298bafba1a9ec2ba99f8ddeb1aa6ef71c4c25bb2929dcb15f80d2`.
