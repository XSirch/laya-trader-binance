# Protocolo: filtro ML pela chance de fechar uma operação positiva

## Hipótese

A regra preexistente `rank_blend` escolhe long/short semanalmente pela combinação de momentum de 30 dias, funding, baixa volatilidade e fluxo taker. Sua reanálise por operação ficou perto das metas de payoff e EV, mas o acerto foi 63,6% na validação de 2025 H2 e 60,3% na confirmação de 2026. A hipótese é que um classificador treinado para prever o resultado líquido do episódio completo possa rejeitar entradas com baixa probabilidade de vitória.

Esta é uma hipótese exploratória escolhida depois da leitura dos resultados históricos; não constitui holdout independente. Os estudos `broad_prediction` e `broad_nonlinear_prediction` já previram retornos de sete dias e foram avaliados como carteiras. Este experimento muda o rótulo para vitória/derrota da operação completa e só abre entradas; não altera o modelo de ranking nem otimiza seus parâmetros.

## Dados e rótulo

- Universo: contratos perpétuos Binance USDT do universo histórico de 20 pares já usado na pesquisa ampla.
- Uma linha de treino é um episódio completo da regra `rank_blend`, do início de uma posição long/short até ficar flat ou inverter a direção. Rebalanceamentos semanais na mesma direção permanecem no episódio.
- O rótulo é `1` se o retorno líquido do episódio for positivo e `0` se for negativo. O retorno inclui preços, funding e custo de estresse já aplicados ao ledger. Episódios truncados pela borda de um período e saídas proxy de listagem são excluídos do treino.
- Features: os dez campos econômicos existentes de `broad_prediction.FIELDS`, mais a direção do episódio. Não entram símbolo, data nem informação posterior à decisão.
- Um rótulo só é elegível depois que a saída ocorreu estritamente antes da decisão atual. A janela de treino é móvel de 104 semanas.

## Modelo e regra de entrada congelados

- `HistGradientBoostingClassifier(max_iter=100, learning_rate=0.05, max_leaf_nodes=7, min_samples_leaf=15, l2_regularization=2.0, early_stopping=False, random_state=2026)`.
- Requer ao menos 100 episódios encerrados e exemplos das duas classes. Caso contrário, o estado fica em caixa.
- Uma nova perna do `rank_blend` só é aceita quando a probabilidade prevista de vitória líquida for `>= 0.70`. Pernas já abertas e ainda alinhadas ao sinal base seguem até a saída original do `rank_blend`; a probabilidade não é recalculada para fechar posições abertas.
- Após o filtro, as pernas aceitas são redistribuídas igualmente entre comprados e vendidos, com gross de 25% por lado (máximo 50%). Se um dos lados não tiver pernas aceitas, a carteira fica em caixa.
- Não será pesquisada uma grade de thresholds, features ou hiperparâmetros depois da leitura dos resultados.

## Execução e gates

Rebalanceamento semanal nos mesmos horários do sinal original; PnL diário por aberturas Binance, funding e turnover. Custo por lado de 0,10% no cenário base e 0,15% no cenário de estresse. Exits, fills e custos continuam sendo hipóteses do replay.

Relatar acerto, payoff líquido, EV por episódio sobre notional inicial e drawdown de carteira em H2/2025, jan–jul/2026 e no combinado jan/2024–jul/2026. A triagem requer ao menos 30 episódios em cada janela, acerto `>=70%`, payoff `>=1:1`, EV `>1,2%`, drawdown `<=10%` e nenhuma saída proxy não resolvida. Uma aprovação em replay histórico ainda exige confirmação prospectiva com regras congeladas.

## Verificações de integridade

Antes de interpretar o filtro, o executor reproduzirá o replay original sem ML para retorno, drawdown, taxas e funding. O ledger ML deverá reconciliar PnL por episódio ao resultado da carteira. O experimento é offline e não envia ordens nem faz chamadas pagas ao JEV.
