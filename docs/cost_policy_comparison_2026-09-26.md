# Política de decisão com custo de transação

A política que compara manter, rebalancear e sair não comprovou consistência. As previsões, coeficientes e amostras de treino foram comparados com os relatórios anteriores e permaneceram idênticos. A mudança foi apenas na decisão do script.

Cada alternativa recebe a soma dos pesos multiplicados pelas previsões semanais menos o custo da mudança de posição. Manter não gera ordens fictícias por arredondamento; ausência de previsão para uma posição ou exposição bruta acima do limite impede essa alternativa. Os custos previstos e contabilizados reconciliaram com erro máximo inferior a 1e-10 do patrimônio.

No cenário condicionado às faixas de liquidação, a seleção conjunta pelo desenvolvimento foi o modelo não linear de escala 4 e pesos inversos à volatilidade: +22,88% no desenvolvimento, mas **-27,87%** de janeiro/2024 a julho/2026. A melhor aparência retrospectiva de outra variante não autoriza trocar a seleção depois de observar a validação.

| Variante com política de custos | Desenvolvimento | 2024–julho/2026 |
| --- | ---: | ---: |
| Econômica 0,1; inverso da volatilidade | +13,39% | +4,13% |
| Técnica 1; inverso da volatilidade | +3,70% | -9,46% |
| Não linear escala 4; inverso da volatilidade — seleção conjunta | +22,88% | -27,87% |
| Não linear escala 1; inverso da volatilidade | +5,53% | +22,21% |

As variantes lineares com regularização 10 permaneceram integralmente em caixa, com retorno zero. Isso não foi classificado como estratégia lucrativa. Algumas variantes reduziram custos e melhoraram o retorno; outras mantiveram posições desfavoráveis por mais tempo e pioraram.

A comparação conjunta incluiu 36 combinações de modelos e políticas mais caixa. O p-valor da estatística máxima foi aproximadamente 0,54. O intervalo anualizado de 95% da seleção ficou entre -22,61% e +0,34%. Essa análise cobre apenas as famílias incluídas e é condicionada às faixas de liquidação documentadas, não à comprovação dos settlements reais.

Os replays estritos e os cenários condicionados foram preservados separadamente. O relatório JSON contém comparação por variante, períodos, tempo em caixa, decisões, contribuições por ativo, custos e hashes. A meta permanece não atingida por essa rodada. O pedido posterior do usuário sobre trailing stop é avaliado em relatório separado, sem substituir ou ocultar estes resultados.

Reprodução: `python -m jev_trader.broad_cost_policy economic`, substituindo a família por `technical` ou `nonlinear`; `--settlement-bounds` ativa o diagnóstico condicionado. `python scripts/compare_cost_policy.py` confere as previsões e compara as políticas.
