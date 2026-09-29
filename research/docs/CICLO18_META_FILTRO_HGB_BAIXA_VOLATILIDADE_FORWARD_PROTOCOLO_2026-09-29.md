# Ciclo 18 — filtro HGB de baixa volatilidade: protocolo prospectivo

**Registrado em 29/09/2026, antes do ajuste do modelo C18, da geração de scores prospectivos e da coleta específica deste paper.** Esta é uma avaliação paper prospectiva de uma candidata histórica selecionada; não é um holdout global intocado, aprovação de estratégia nem autorização para ordens reais.

## Pergunta e limite da evidência anterior

O filtro `HistGradientBoostingClassifier` sobre `low_volatility30_betahedged` produziu, no replay exploratório jan/2024–jul/2026, 89 episódios, EV líquido médio de +8,67% do notional inicial, payoff 1,50, acerto de 62,9% e drawdown de carteira de 9,65%. Na janela de confirmação jan–jul/2026 foram apenas 16 episódios: EV +6,15%, payoff 3,15, acerto 62,5% e drawdown 3,91%. Em H2/2025 houve 23 episódios, EV +8,29%, payoff 1,53 e acerto 65,2%.

Esses períodos já foram examinados e a regra-base foi escolhida após inspeção dos resultados. Os valores são triagem retrospectiva, não validação; não satisfazem o requisito de 200 operações prospectivas. O acerto ficou abaixo da preferência de aproximadamente 70%. A cadência retrospectiva foi cerca de 34 episódios selecionados por ano; 200 operações poderiam exigir perto de seis anos nessa cadência, sem garantia de que ela continue. Não encurtar a amostra nem promover checkpoints anuais a aprovação.

## Variante congelada

- **Mercado:** futuros perpétuos Binance USD-M, isolado de Spot e de outros mercados.
- **Coorte fixa, formada pelo volume de cotação de janeiro/2021 sem filtro de sobrevivência atual:** BTCUSDT, ETHUSDT, XRPUSDT, LINKUSDT, LTCUSDT, DOGEUSDT, DOTUSDT, BCHUSDT, XLMUSDT, ADAUSDT, EOSUSDT, UNIUSDT, SUSHIUSDT, YFIUSDT, BNBUSDT, TRXUSDT, CRVUSDT, MKRUSDT, AAVEUSDT e GRTUSDT. Não substituir contratos que deixarem de negociar. Ausência de dados, cotação ou liquidação identificável suspende a decisão e fica registrada; não vira retorno zero.
- **Regra-base:** `low_volatility30_betahedged`, semanal, com features calculadas somente a partir de candles diários completos e funding conhecido até o corte. Elegibilidade e seleção transversal permanecem conforme `broad_research.target_weights`: volume médio de cotação de 20 dias ≥ US$ 10 milhões, volatilidade entre 0,5% e 15%, pelo menos oito ativos elegíveis, quintis extremos com exposição bruta de 25% por lado e hedge de beta pelo BTC, limitado a 50% de exposição bruta total.
- **Vetor do classificador:** `momentum7`, `momentum30`, `momentum90`, `reversal1`, `reversal7`, `carry30`, `volatility`, `taker_flow20`, `beta60`, `time_series_ensemble` e direção. Símbolo, timestamp, retorno futuro e qualquer outro campo ficam fora do vetor.
- **Modelo e corte:** `HistGradientBoostingClassifier(max_iter=100, learning_rate=0.05, max_leaf_nodes=7, min_samples_leaf=15, l2_regularization=2.0, early_stopping=False, random_state=2026)`; aceitar entrada nova somente se `P(vitória) >= 0,70`. O score não é tratado como probabilidade calibrada.
- **Ajuste único:** treinar uma vez após este registro, antes do primeiro sinal prospectivo, com episódios completos da regra-base cujo fechamento seja estritamente anterior a `2026-08-01T00:00:00Z` e cuja entrada pertença às 104 semanas anteriores a esse corte. Deduplicar por ativo, entrada, saída e direção; excluir episódios combinados duplicados, saídas proxy, episódios terminais/truncados, features incompletas e retorno líquido exatamente zero, conforme a construção do estudo-fonte. O rótulo é `1` se o retorno líquido do episódio for positivo após funding e custo de stress histórico de 0,15% por lado; caso contrário é `0`. Exigir ao menos 100 rótulos e ambas as classes. Se falhar, registrar insuficiência e não ampliar a janela nem mudar o corte. Arquivar o modelo treinado e seu hash antes de qualquer inferência C18. **Não refitar com os resultados prospectivos.** Esta versão estática é uma nova variante, diferente do classificador walk-forward histórico.
- **Decisão semanal:** primeira coleta elegível em `2026-10-05T01:00:00Z`; depois, segunda-feira UTC entre 01:00 e 01:05, com dados fechados até 00:00 UTC e cotação fresca. Decisão fora da janela, relógio divergente, candle em formação, mercado incompleto ou risco de disponibilidade resulta em abstenção documentada. Nenhuma decisão atrasada será reconstruída com preço histórico.
- **Posições:** a regra HGB decide entradas novas. Uma posição existente pode continuar somente enquanto o sinal-base mantiver a mesma direção; mudança ou perda de elegibilidade encerra/reverte na próxima decisão semanal válida. Exposição aceita é redistribuída igualmente em até 25% comprados e 25% vendidos. Se não houver posições aceitas nos dois lados, a carteira fica em caixa. Como a reequalização pode desfazer o hedge do fator-base, o paper deve informar beta residual, exposição líquida e exposição bruta em cada rebalanceamento; não alegar neutralidade beta garantida.

## Custos, execução simulada e métricas

Não transmitir ordens, usar endpoints autenticados ou acessar chaves. Simular entradas, saídas e rebalanceamentos no próximo preço público observável após a decisão, com taxa de 5 bp e slippage adverso de 5 bp por lado na base. No stress, dobrar separadamente taxa e slippage (10 bp de cada por lado). Aplicar funding realizado de USD-M observado nos horários de liquidação; qualquer intervalo ausente ou não conciliado bloqueia o cálculo afetado. Não presumir fills maker, rebates, fila ou execução no preço médio sem custo.

Reportar para cada checkpoint e para a amostra prospectiva acumulada: número de episódios completos e abertos, semanas ativas, acerto líquido, payoff líquido, EV médio líquido por episódio sobre o notional inicial, profit factor, PnL total sob custo-base e stress, drawdown de patrimônio marcado a mercado, turnover, custos, funding, concentração por símbolo/direção, beta residual e intervalos de incerteza com dependência agrupada por ativo e semana. Rebalanceamentos na mesma direção continuam no episódio; reversão abre episódio distinto. Não contar sinais, predições, rótulos de treino ou cenários de custo como trades.

Gates para considerar a variante aprovada: pelo menos 200 episódios completos, únicos e prospectivos em pelo menos oito semanas ativas; EV-base estritamente acima de 1,2%; payoff-base ≥1:1; profit factor-base ≥1,25; PnL agregado positivo sob stress. Medir o acerto e preferir resultado próximo de 70%, sem torná-lo piso obrigatório. Drawdown não tem teto fixo: reportar e minimizar ao comparar variantes que passem os demais gates, sem ajustar C18 usando a própria janela prospectiva. Não somar mercados ou variantes para atingir a amostra. Um checkpoint anual é apenas descritivo e nunca aprova antes dos gates.

## Reprodutibilidade, limites e segurança

Implementar coletor, ledger e avaliador em série própria C18; não alterar os módulos, hashes, configuração ou processo `forward_paper_v2`/JEV existentes. Guardar payloads públicos, timestamps de início/fim de requisição, status de disponibilidade, features, probabilidades, alvos, fills simulados, funding, posições, patrimônio, eventos abertos/fechados e hashes. Separar o custo usado para treinar os rótulos históricos do custo aplicado à avaliação prospectiva.

O classificador HGB desta variante roda em CPU; não será descrito como CUDA/GPU. Os experimentos CUDA anteriores permanecem resultados separados. A seleção retrospectiva da família, a inspeção ampla do mercado em 2026 e a dependência entre ativos/episódios limitam a inferência. Resultado favorável ainda exige o gate prospectivo completo e revisão separada; não libera ordens reais.

## Integridade das entradas conhecidas no registro

| Entrada | SHA-256 |
|---|---|
| Proposta pós-Ciclo 12 | `6a4597ca61f2ab217ea1b93c49c966698c7bd61421278f8936e853e67a27390b` |
| Protocolo retrospectivo do filtro HGB | `56c17ec4530f6182594d37c2a5134e5eb959f84c06bbb68b1f11b8618ad8712a` |
| Relatório retrospectivo do filtro HGB | `56125e2a310d62746d24ff159aba9879daf6abcfddaede0f3a930349a79b3e56` |
| Resultado JSON retrospectivo | `2139c5441375e335cba442621188ec531219cacfb6d9fba7ef4b49b839b100af` |
| Ledger de episódios retrospectivos do filtro | `16e1f6c72830d9008ae2dc7217ec53d045cb53903be00ef5260f1ce1d235362a` |
| Ledger-base de episódios | `b4eb4024531520aac41be58f9d229241b1a3392ea6d53a685531e96765f974f3` |
| Reanálise-base | `ece50f987518caec9d7adefdf68a9d929716425f7f38a673316fc9a9aaf93e9b` |
| Relatório amplo de fatores | `9fa70e1fd1b486072392333decde61f110019c1d39276c517ab749d97582d3a0` |
| Coorte formada em janeiro/2021 | `f7716d2b673f37cecfd9779b9090b4c63681a8e4b667340e5586972a8661ed57` |
| Código do estudo HGB | `f8e71887e12ae9561486343ed583d79ff87395eb87a2045ba0b7aecc14cfd690` |
| Preditores e campos econômicos | `1348cf6c2b8a2ce011a19eff38546cf8c7204df9620781ed6af886af3ff7e358` |
| Regra e features fatoriais | `9144a4b085a71b2a6ee0a701b748fb8694e1409ee5f6a5cfd3b73c50179a154b` |
| Motor de episódios e carteira | `583575e3c129c8a109e6487ac19f29056f0ffb884fd61e2d4dd4e72766d01181` |
| Carga de dados e coorte | `d905e107025dcdc0bac6f0c7443ac86a9f00ed5ef5b8e99807c550fb14103a27` |

O snapshot público já existente não é entrada de resultado nem valida a regra C18; qualquer código reutilizado deve ter hash registrado e respeitar este protocolo. Antes da primeira inferência, registrar no ledger C18 os hashes do coletor, runner, modelo serializado, configuração e entradas de treino. Resultado previsto: `research/results/cycle18_lowvol_hgb_forward/`; não havia artefato prospectivo C18 no momento do registro.
