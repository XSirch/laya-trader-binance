# Parâmetros vigentes da pesquisa

Atualizado em 28/09/2026, com base na confirmação do usuário e na revisão 2 do CÍCLO 02. Este documento substitui os gates incompatíveis dos handoffs anteriores.

## Escopo e critérios obrigatórios

A pesquisa inclui somente pares cripto Binance Spot e futuros perpétuos USD-M. Nenhum resultado de treinamento, replay ou paper autoriza ordens reais.

| Critério | Definição e gate |
|---|---|
| EV líquido por operação | Média aritmética de `net_pnl / nocional_inicial`, estritamente maior que 1,2% (`> 0,012`). |
| Payoff | Média dos retornos líquidos positivos dividida pelo valor absoluto da média dos retornos líquidos negativos; mínimo 1,0. |
| Amostra | Mínimo de 200 operações completas e não duplicadas. Trades de modelos, folds e custos distintos não são somados para alcançar o mínimo. |
| Cobertura | Pelo menos 8 semanas ativas. |
| Profit factor | Soma dos PnLs positivos dividida pelo módulo da soma dos PnLs negativos; mínimo 1,25. |
| Custos estressados | Replay completo positivo com taxas e slippage multiplicados por 2; funding observado permanece incluído em USD-M. |
| Taxa de acerto | Preferência próxima de 70%, sem piso obrigatório se os demais gates forem cumpridos. Reportar taxa e incerteza. |
| Drawdown | Sem teto de aprovação. Medir e comparar; entre candidatos que cumpram todos os gates, preferir o menor drawdown. |

## Escopo de aplicação no pacote atual

`promotion_gate` é executado por mercado/modelo e por fold de avaliação; também é usado para selecionar thresholds nos dados de seleção. Não agregar folds nem backends para reclassificar uma reprovação.

No cenário-base, o código exige amostra, semanas ativas, profit factor disponível e ≥1,25, EV >1,2% por operação e payoff disponível e ≥1. No stress, o gate é somente PnL líquido agregado positivo com taxas e slippage dobrados; EV, payoff, profit factor, quantidade de operações e drawdown no stress são diagnósticos, não gates adicionais. O win rate e o limite inferior do bootstrap também são diagnósticos, mesmo se o campo legado `confidence_lower_bound_required` estiver configurado. `max_drawdown` permanece como campo legado de configuração, mas não é aplicado como gate.

`min_expected_r = 0.05` é um filtro de score em unidades de R. Não substitui o EV observado por nocional. `minimum_probability = 0.35` é o piso de busca de threshold, não um critério de rentabilidade.

## Hipóteses de risco e custos configuradas

- Spot: taxa de 10 bps por lado e slippage adverso de 5 bps por lado.
- USD-M: taxa de 5 bps por lado e slippage adverso de 5 bps por lado.
- Estresse: multiplica taxa e slippage por 2.
- Sizing simulado: risco configurado de 0,25% do patrimônio por trade, considerando distância do stop e fricção estimada; notional máximo de 1x o patrimônio.
- Esses custos não foram verificados na conta do usuário. O motor não modela liquidação de futuros nem execução real.

O código incorpora slippage nos preços de entrada e saída. A fricção também entra no cálculo do tamanho da posição para limitar o risco estimado; não é debitada uma segunda vez do PnL.

## Estado em 28/09/2026

`target_not_demonstrated` continua vigente. A primeira execução multi-timeframe do Ciclo 02 foi invalidada por um erro de roteamento dos modos de saída: `fixed`, `trailing` e `trend_loss` receberam o mesmo comportamento efetivo. Os resultados e derivados daquela execução não servem para aprovar ou rejeitar estratégias. Na reexecução corrigida, nenhum dos 72 comparadores nem das 480 combinações ML/threshold passou todos os gates; nenhuma combinação ML chegou a 200 trades (máximo 99). A sensibilidade corrigida de 288 thresholds adicionais encontrou 16 combinações com pelo menos 200 trades e oito semanas, mas EV base negativo em todas e nenhuma positiva no stress; zero passaram os gates. O melhor EV foi +0,590% em apenas uma operação, abaixo do piso de +1,2%. Todos os resultados seguem retrospectivos. Consulte [resultados e invalidação do Ciclo 02](CICLO02_RESULTADOS_2026-09-28.md), o [protocolo de correção](CICLO02_CORRECAO_SAIDAS_PROTOCOLO.md) e a [sensibilidade corrigida](CICLO02_SENSIBILIDADE_CORRIGIDA_PROTOCOLO.md).

O gate de promoção foi alinhado à Rev02 depois desses replays. Os protocolos congelados da reexecução e do filtro custo/stop incluíam condições adicionais no stress (EV por trade e payoff ≥1); esses campos permanecem nos resultados como diagnósticos históricos. A conclusão de zero candidatos não muda: nenhuma combinação chegou aos gates-base de amostra e EV. A decisão de alinhamento está em [CICLO02_ALINHAMENTO_GATES_REV02.md](CICLO02_ALINHAMENTO_GATES_REV02.md).

O filtro custo/stop reteve apenas 1/5.871 sinais Spot e 598/11.384 USD-M; nenhuma variante chegou a 200 trades. O diagnóstico de trajetória corrigido confirma EV negativo em todas as 24 regras e fricção mediana de 0,65–1,18R no cenário-base. O primeiro diagnóstico foi invalidado por classificar gaps como candles completos; a extração corrigida e seus hashes estão no [relatório](CICLO02_RESULTADOS_2026-09-28.md). Nenhuma estratégia está aprovada.

## Atualização P0 — 28/09/2026

O funil detalhado, o stress pareado, os retornos mensais, a exposição/capital ocioso e os limites de MFE/MAE estão registrados em [ACCOUNTING_AUDIT.md](ACCOUNTING_AUDIT.md) e nos artefatos de [p0_completion_2026-09-28](../results/p0_completion_2026-09-28/). Nenhum limiar estudado está aprovado para paper ou operação.

## Invalidação técnica do P1 — 28/09/2026

A auditoria confirmou que as chamadas enviavam os nomes descritivos dos planos ao simulador, que exige os identificadores canônicos. Assim, as 8 combinações de mercado/família/horizonte produziram os mesmos rótulos e os três planos não foram comparados. O treino inicial, a sensibilidade pós-hoc e o ganho de features foram invalidados; números anteriores permanecem apenas como trilha de auditoria e não devem orientar seleção. A reexecução corrigida foi concluída em `research/results/cycle02_multiframe_corrected_2026-09-28/`; nenhum resultado histórico habilita paper ou ordens reais.
