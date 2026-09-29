# Protocolo: filtro ML por operação da regra de baixa volatilidade

## Hipótese e viés de seleção

A reanálise de 24 regras antigas de futuros Binance USDT mostrou que `low_volatility30_betahedged` teve 70% de acerto em 30 episódios na validação H2/2025, payoff líquido de 1,25 e EV de +7,44% sobre o notional inicial por episódio. Na confirmação jan–jul/2026, o acerto caiu para 60,5%, embora payoff (1,63), EV (+4,45%) e drawdown (3,19%) tenham permanecido favoráveis. O teste avalia se um classificador pode rejeitar novas entradas de baixa probabilidade e preservar uma amostra útil.

A própria regra foi escolhida depois de inspecionar os resultados históricos; este experimento é exploratório e sujeito a viés de seleção. H2/2025, 2026 e o combinado já foram vistos em estudos anteriores e não constituem holdout futuro independente. O resultado não autoriza negociação real.

## Dados, rótulo e features

- Universo histórico congelado dos mesmos contratos perpétuos Binance USDT e dos mesmos estados causais da pesquisa ampla; nenhum ETF ou ativo fora de cripto.
- Cada rótulo é um episódio completo do `low_volatility30_betahedged`, do primeiro sinal na direção atual até a saída ou inversão. Rebalanceamentos que mantêm a direção pertencem ao mesmo episódio.
- O rótulo é vitória se o PnL líquido do episódio for positivo, após funding e custo de estresse de 0,15% por lado. Perdas são rótulo negativo; saídas proxy e episódios truncados no limite do recorte não entram no treino.
- Features são os dez campos econômicos existentes em `broad_prediction.FIELDS` e a direção do episódio. Símbolo, timestamp e dados posteriores ao sinal ficam fora do vetor.
- Em cada decisão semanal, só entram episódios encerrados estritamente antes do sinal, numa janela móvel de 104 semanas. São necessários pelo menos 100 exemplos e as duas classes; caso contrário, a carteira fica em caixa.

## Modelo e regra congelados

`HistGradientBoostingClassifier(max_iter=100, learning_rate=0.05, max_leaf_nodes=7, min_samples_leaf=15, l2_regularization=2.0, early_stopping=False, random_state=2026)`, com limiar fixo `P(vitória)>=0.70`. Os parâmetros e o limiar repetem exatamente o filtro já aplicado à regra `rank_blend`; não haverá grade adicional de limiares, features ou hiperparâmetros.

O filtro afeta entradas novas. Posições abertas que continuam alinhadas ao sinal-base mantêm-se até a saída original. As pernas aceitas são redistribuídas igualmente, com gross de 25% comprados e 25% vendidos no máximo; se faltar um dos lados, a carteira fica em caixa. As regras de seleção, rebalanceamento, saída e exposição da estratégia-base permanecem fixas.

## Avaliação

Apresentar taxa de acerto líquida, payoff, EV líquido por episódio sobre notional inicial e drawdown da carteira, sob 0,15% de custo por lado, em H2/2025, jan–jul/2026 e combinado jan/2024–jul/2026. Os gates são acerto >=70%, payoff >=1:1, EV >1,2%, drawdown <=10%, pelo menos 30 episódios em cada janela e nenhuma saída proxy não resolvida. Todas as metas devem passar nas duas janelas, e o drawdown combinado também deve ser <=10%.

O EV medido sobre notional não é retorno sobre margem ou patrimônio da conta. A execução continua sendo replay diário ao próximo open, com funding e custos modelados; não inclui livro de ofertas, latência nem prova de execução real.

## Reprodutibilidade

O executor lê a reanálise e o ledger de operações existentes, não baixa novos dados, não modifica o paper JEV, não faz chamadas pagas e não envia ordens. Registra hashes das entradas, protocolo, código e arquivos de saída; verifica que a soma do PnL líquido por episódio reconcilia com o retorno da carteira.
