# Resultado da previsão horária de BTC

Foram concluídos os 72 cenários fixados, sem cenário inválido. Nenhum atingiu CAGR líquido de 50% com drawdown de até 10%. A meta permanece não demonstrada; nenhum vencedor foi selecionado e nenhum candidato foi promovido para operação real.

O [protocolo](hourly_forecast_protocol_2026-09-26.md), as [fontes](hourly_forecast_sources_2026-09-26.md) e o [congelamento](hourly_forecast_freeze_2026-09-26.json) antecederam o cálculo de previsões e resultados. Foram usados 30.695 estados com 114 campos numéricos de spot e perp: médias, momentum, volatilidade, volume, participação, estrutura, Fibonacci, basis e funding. São todos os campos técnicos/econômicos previstos no esquema disponível, sem alegação de cobrir toda informação existente no mercado.

A conta opera BTC spot comprado ou caixa, sem alavancagem. O modelo HGB e o controle de média histórica usam os mesmos rótulos e pesos, ajustados mensalmente apenas com rótulos completos anteriores ao corte. Foram registrados 38 ajustes, 26.369 previsões por modelo e 26.366 retornos posteriores válidos para pontuação. O último ajuste gera previsões além da última abertura disponível, que não entram em operações ou pontuação sem os preços necessários.

## Retorno, risco e custos

Janela posterior: 01/01/2024 a 31/08/2026 às 23h UTC. A tabela principal usa 100% de alocação na entrada e custo presumido de 0,12% por lado. CAGR é retorno anualizado composto de todo o período; drawdown usa as avaliações horárias antes/depois das ordens. São resultados históricos simulados.

| Regra | CAGR líquido | Drawdown | Limite adverso intrahora | Entradas | Custos sobre capital inicial |
|---|---:|---:|---:|---:|---:|
| HGB: sinal positivo | -93,19% | 99,93% | 99,93% | 3082 | 126,61 p.p. |
| HGB: faixa de custo | 25,57% | 51,18% | 52,46% | 8 | 2,54 p.p. |
| HGB: faixa + trailing 4% | 0,82% | 22,02% | 22,76% | 40 | 10,88 p.p. |
| Média: sinal positivo | 26,24% | 38,30% | 40,00% | 1 | 0,34 p.p. |
| Comprar e manter | 26,06% | 53,74% | 54,20% | 1 | 0,34 p.p. |

A faixa exige previsão maior que duas vezes o custo para entrar, menor que o negativo desse limiar para sair e conserva a posição no intervalo. Ela reduziu as entradas do HGB de 3.082 para 8 e os custos acumulados de 126,61 para 2,54 pontos percentuais do capital inicial. Esses custos não são uma tarifa anual. As regras também alteram exposição, caixa e tamanho das compras; a comparação não é uma decomposição causal que mantenha as operações fixas.

A melhora perante o sinal simples não demonstrou vantagem preditiva. A faixa do HGB ficou abaixo do CAGR de comprar e manter e do controle de média, com queda ainda superior a 50%. Ficou exposta durante 22.257 das 23.375 horas, compatível com retenção prolongada do BTC. O retorno acumulado do HGB com faixa foi 83,51%, composto por 86,05 pontos de PnL de preço menos 2,54 de custos.

No período posterior, a única configuração que operou e respeitou drawdown observado de 10% foi HGB/faixa, alocação inicial de 50%, custo de 0,24% por lado e trailing de 4%: CAGR de 3,20%, drawdown de 9,18% e limite adverso de 9,90%, em cinco entradas. Essa descrição da grade não a torna uma seleção validada. As demais configurações abaixo de 10% ficaram em caixa, sem retorno. Os 16 cenários de média com faixa não operaram em nenhum dos dois períodos.

Dobrar custos também dobra a faixa de decisão, mudando a sequência de operações. A versão HGB/faixa com 100% e sem trailing passou a uma entrada, CAGR de 13,60% e drawdown de 53,74%. Isso não é simplesmente cobrar duas tarifas sobre os mesmos negócios.

## Trailing e consistência temporal

No HGB/faixa/base/100%, o trailing de 4% disparou 37 vezes. Reduziu o drawdown observado de 51,18% para 22,02%, enquanto o CAGR caiu de 25,57% para 0,82%. O pico do stop reinicia quando a posição fecha; o pico usado no drawdown total permanece. Perdas repetidas, custos e saltos entre observações podem ultrapassar o limite de carteira. O trailing testado observa aberturas horárias e não garante perda máxima de 4% ou 10%.

Retornos por ano dos mesmos cenários base/100%. Os períodos de desenvolvimento e posterior reiniciam o capital; 2026 contém apenas janeiro a agosto. O início elegível em 2023 ocorreu em 29/08 às 09h UTC, e o CAGR de desenvolvimento inclui o caixa anterior.

| Regra | 2023: desenvolvimento | 2024 | 2025 | 2026: parcial |
|---|---:|---:|---:|---:|
| HGB: faixa | 36,09% | 107,29% | -6,33% | -5,49% |
| HGB: faixa + trailing 4% | 18,45% | 13,05% | 9,06% | -17,10% |
| Média: sinal | 62,51% | 121,04% | -6,33% | -10,09% |
| Comprar e manter | 62,51% | 121,04% | -6,33% | -10,44% |

O HGB/faixa sem trailing teve forte ganho em 2024 e perdas em 2025 e no trecho de 2026. O histórico já foi utilizado em outras pesquisas: as janelas são comparações cronológicas retrospectivas, sem confirmação estatística intocada. Os resultados não provam que estratégias consistentes sejam impossíveis; rejeitam a demonstração da meta nesta família, nas condições testadas.

## Qualidade da previsão

O erro quadrático médio do HGB foi maior que o da média em desenvolvimento, no período posterior e em cada ano posterior. Não foi realizado teste de significância. A comparação descritiva não oferece evidência de melhora do previsor complexo.

| Janela | Rótulos | MSE HGB | MSE média | Acerto direcional HGB | Acerto direcional média |
|---|---:|---:|---:|---:|---:|
| development | 2991 | 1.81327168e-05 | 1.76986806e-05 | 47,91% | 52,09% |
| later | 23375 | 2.60888619e-05 | 2.58353719e-05 | 50,11% | 50,52% |
| year2024 | 8784 | 3.18196375e-05 | 3.15508305e-05 | 50,61% | 51,16% |
| year2025 | 8760 | 2.28633878e-05 | 2.25471412e-05 | 48,95% | 50,34% |
| year2026 | 5831 | 2.23015218e-05 | 2.21653859e-05 | 51,11% | 49,84% |

O campo `skill_vs_zero` do JSON compara a soma dos erros quadráticos com prever retorno zero; não é o R² convencional centrado na média observada. Acurácia direcional e previsão de retorno bruto de uma hora não são probabilidade calibrada de lucro nem lucro esperado da permanência inteira.

## Grade completa

Valores em porcentagem. Alocação vale na entrada; a quantidade permanece fixa até a venda. Os dois períodos começam com capital unitário. O JSON preserva limites intrahora, curvas, custos, stops e demais estatísticas.

| Modelo/regra | Alocação | Custo por lado | Trailing | CAGR 2023 | DD 2023 | CAGR posterior | DD posterior | Entradas posterior |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| rolling_mean/sign | 50% | 0,12% | ausente | 31,28 | 5,52 | 14,38 | 28,67 | 1 |
| rolling_mean/sign | 50% | 0,12% | 4% | 29,01 | 5,81 | 11,86 | 21,12 | 57 |
| rolling_mean/sign | 100% | 0,12% | ausente | 62,57 | 10,64 | 26,24 | 38,30 | 1 |
| rolling_mean/sign | 100% | 0,12% | 4% | 53,96 | 11,28 | 7,43 | 44,02 | 169 |
| rolling_mean/sign | 50% | 0,24% | ausente | 31,09 | 5,52 | 14,31 | 28,66 | 1 |
| rolling_mean/sign | 50% | 0,24% | 4% | 28,36 | 5,92 | 8,99 | 22,13 | 58 |
| rolling_mean/sign | 100% | 0,24% | ausente | 62,18 | 10,64 | 26,13 | 38,30 | 1 |
| rolling_mean/sign | 100% | 0,24% | 4% | 45,99 | 11,70 | -9,28 | 54,63 | 170 |
| rolling_mean/cost_band | 50% | 0,12% | ausente | 0,00 | 0,00 | 0,00 | 0,00 | 0 |
| rolling_mean/cost_band | 50% | 0,12% | 4% | 0,00 | 0,00 | 0,00 | 0,00 | 0 |
| rolling_mean/cost_band | 100% | 0,12% | ausente | 0,00 | 0,00 | 0,00 | 0,00 | 0 |
| rolling_mean/cost_band | 100% | 0,12% | 4% | 0,00 | 0,00 | 0,00 | 0,00 | 0 |
| rolling_mean/cost_band | 50% | 0,24% | ausente | 0,00 | 0,00 | 0,00 | 0,00 | 0 |
| rolling_mean/cost_band | 50% | 0,24% | 4% | 0,00 | 0,00 | 0,00 | 0,00 | 0 |
| rolling_mean/cost_band | 100% | 0,24% | ausente | 0,00 | 0,00 | 0,00 | 0,00 | 0 |
| rolling_mean/cost_band | 100% | 0,24% | 4% | 0,00 | 0,00 | 0,00 | 0,00 | 0 |
| hgb/sign | 50% | 0,12% | ausente | -33,89 | 34,61 | -73,48 | 97,15 | 3082 |
| hgb/sign | 50% | 0,12% | 4% | -33,89 | 34,61 | -73,62 | 97,19 | 3088 |
| hgb/sign | 100% | 0,12% | ausente | -56,53 | 57,47 | -93,19 | 99,93 | 3082 |
| hgb/sign | 100% | 0,12% | 4% | -56,95 | 57,88 | -93,71 | 99,94 | 3114 |
| hgb/sign | 50% | 0,24% | ausente | -56,23 | 56,44 | -93,36 | 99,93 | 3082 |
| hgb/sign | 50% | 0,24% | 4% | -56,23 | 56,44 | -93,41 | 99,93 | 3088 |
| hgb/sign | 100% | 0,24% | ausente | -80,97 | 81,16 | -99,58 | 100,00 | 3082 |
| hgb/sign | 100% | 0,24% | 4% | -81,25 | 81,43 | -99,62 | 100,00 | 3117 |
| hgb/cost_band | 50% | 0,12% | ausente | 17,22 | 5,28 | 13,04 | 35,12 | 8 |
| hgb/cost_band | 50% | 0,12% | 4% | 16,88 | 4,26 | 9,12 | 17,70 | 33 |
| hgb/cost_band | 100% | 0,12% | ausente | 36,12 | 10,55 | 25,57 | 51,18 | 8 |
| hgb/cost_band | 100% | 0,12% | 4% | 18,46 | 8,71 | 0,82 | 22,02 | 40 |
| hgb/cost_band | 50% | 0,24% | ausente | 20,53 | 5,14 | 7,16 | 37,25 | 1 |
| hgb/cost_band | 50% | 0,24% | 4% | 18,96 | 4,40 | 3,20 | 9,18 | 5 |
| hgb/cost_band | 100% | 0,24% | ausente | 41,06 | 8,59 | 13,60 | 53,74 | 1 |
| hgb/cost_band | 100% | 0,24% | 4% | 21,21 | 4,24 | 10,98 | 10,88 | 5 |
| benchmark/buy_hold | 50% | 0,12% | ausente | 31,28 | 5,52 | 14,27 | 40,23 | 1 |
| benchmark/buy_hold | 100% | 0,12% | ausente | 62,57 | 10,64 | 26,06 | 53,74 | 1 |
| benchmark/buy_hold | 50% | 0,24% | ausente | 31,09 | 5,52 | 14,20 | 40,21 | 1 |
| benchmark/buy_hold | 100% | 0,24% | ausente | 62,18 | 10,64 | 25,94 | 53,74 | 1 |

## Verificação e limites

A auditoria de previsões conferiu 25 âncoras, os 712 ZIPs e três manifestos, estados, rótulos, disponibilidade estrita, matrizes, máscaras de ausência, 38 ajustes e hashes das previsões. Recalculou média e métricas em 26.424 comparações, com diferença máxima zero e tolerância de 2e-12 vezes max(1, valor absoluto esperado). Reutilizou as fórmulas de indicadores congeladas; não reajustou nem executou inferência do HGB. Portanto, os vínculos dos valores salvos foram conferidos, mas sua inferência numérica não foi reproduzida por implementação independente.

A auditoria de operações reconstruiu as decisões completas, incluindo permanências, e verificou os 72 digests. Recalculou caixa, quantidades, taxas, PnL, curvas, anos, CAGR, drawdown e limite adverso sem chamar o executor original. As contagens somadas nos cenários são 28.124 episódios e 56.248 fills. Deduplicando apenas por relógios de entrada/saída há 3.837 episódios; por ativo/hora/ação há 7.289 fills. São simulações sobrepostas, não operações reais nem amostras estatisticamente independentes.

Foram verificadas 1.156.932 decisões e 1.818.723 comparações numéricas, com tolerância de 2e-10 vezes max(1, valor absoluto esperado). A diferença numérica máxima foi 8,53e-13; o erro máximo entre curva e ledger reconstruído foi zero. O hash dos inputs pré-replay foi exigido explicitamente, e os hashes dos arquivos permaneceram estáveis durante a auditoria.

A suíte completa passou com 554 testes e zero skips antes da inclusão do teste de composição anual. Depois, os quatro testes do runner passaram, incluindo o novo; são 555 testes distintos cobertos, sem alegar uma execução única de 555. A revisão independente executou os 47 testes novos dos quatro módulos. A codificação dos arquivos produzidos é verificada como UTF-8 válido, sem U+FFFD.

O limite intrahora incorpora picos favoráveis possíveis e vales adversos, cuja ordem real é desconhecida. Não é um caminho observado. Sua diferença em relação aos executores antigos está na [clarificação preservada](intrahour_bound_clarification_2026-09-26.md). Execuções em aberturas, custos e disponibilidade histórica das publicações continuam hipóteses; reconciliação contábil não comprova esses pontos nem rentabilidade futura.

Não houve nova chamada JEV, ordem ou download de mercado nesta rodada. O contrato do JEV permanece uma chamada agrupada por ativo/instante para pontuar aderência; a decisão pertence ao script. Os campos zero de execução nos artefatos não substituem uma auditoria independente de tráfego de rede. O candidato e a coleta paper anteriores foram preservados.

## Artefatos

Commit do primeiro replay: `dd95510f5b22352bf79c65915b16f09904ee1104`. Tempo registrado: 158,85 segundos.

- [Síntese e grade JSON](hourly_forecast_research_2026-09-26.json): 5290316 bytes, SHA-256 `e35c96682407dbbb8c6be9b98c36529e59bfee01523169f91d30a8835f18e0b4`.
- Relatório local completo `results/hourly_forecast_research.json`: 131751287 bytes, SHA-256 `469f8e2959343caacd0ada012880ac2d91d66e9d35fe6695022e2cf2bc698834`; permanece no armazenamento local de resultados.
- Inputs pré-replay: SHA-256 `4c97ffbd9d85c2b321209e56f7fd9479c75cca7619324f8a000c6bd0f805c9ec`.
- [Auditoria predictions](hourly_forecast_verification_predictions_2026-09-26.json): SHA-256 `d9e33a35fa8687c943fa3fdb3b7516b8f8e33da1002548bd7671e00975026ff9`; script local `verify_hourly_forecast_predictions.py`, SHA-256 `0a778f8d702d053094e8bbf87b84bc87f1fc5c92fd22b0abcfc80b29ff4ceea4`.
- [Auditoria ledgers](hourly_forecast_verification_ledgers_2026-09-26.json): SHA-256 `971590d23b18722341c3626b49bdff2804d8960a6ba487da303f8d92a07589fd`; script local `verify_hourly_forecast_ledgers.py`, SHA-256 `ec97501265cf1abe42affcca12aac9c8a50fccc1c9a56dac20cf6a19573f6b69`.

Os scripts de auditoria ficam em `.cache`, juntamente com o helper de CSV cujo hash consta em ambas as evidências. As limitações de cada auditoria estão registradas nos JSONs.
