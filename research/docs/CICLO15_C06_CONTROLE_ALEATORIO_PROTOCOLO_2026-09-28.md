# C15 — Controle aleatório pareado do seletor C06

Data: 28/09/2026  
Status: pré-registro antes de executar os sorteios. Estudo retrospectivo; não é validação independente.

## Pergunta

As 19 decisões do score direto C06 que excederam `EV previsto > 1,2%` produziram resultado melhor que grupos de candidatos sem conhecimento do desfecho, comparáveis por ativo, direção, mês e risco ex-ante?

## Escopo congelado

- Controle fixo: scores e seleção salvos do C06; nenhum modelo será retreinado e nenhum cutoff será escolhido.
- Universo e período: BTCUSDT e ETHUSDT USD-M, 02/01/2026 00:00 UTC a 01/09/2026 00:00 UTC, fim exclusivo.
- Grupo pareado: conservar, em cada sorteio, exatamente a contagem de decisões do C06 por mês UTC, símbolo, direção e quartil de risco ex-ante.
- O quartil de risco usa `stop_fraction_signal` e cortes mensais calculados somente com labels maduros anteriores ao fold, já preservados em `C14 fold_calibration.json`.
- Sorteios: 100 sementes fixas, 1701 a 1800, amostragem sem reposição em cada grupo. Não escolher sementes depois de ver resultados.
- Reexecução: mesmo simulador, uma posição global por vez, capital/alocação C06, saída `trend_loss`, horizonte de 1.440 minutos, custos-base e stress com taxas/slippage dobrados e funding observado.
- Métricas: quantidade selecionada e executada, EV líquido por operação, acerto, payoff, profit factor, PnL, drawdown e semanas ativas, em base e stress; percentis dos controles e posição empírica do C06 na distribuição aleatória.
- Reconciliar o replay do controle com o relatório C06 antes de calcular comparações. Interromper em caso de divergência.
- Sem ML, nova hipótese de entrada/saída, ajuste de score ou ordens reais.

## Limitações

O período já foi inspecionado em estudos anteriores. Este teste mede quanto as 19 escolhas C06 se distinguem de amostras pareadas sob a mesma janela histórica; não corrige seleção retrospectiva do cutoff nem valida estabilidade futura. Os sorteios aleatórios não são observações independentes entre si, e os candidatos podem compartilhar episódios de mercado.

## Fontes

- Requisito de controles estratificados e simulador: seção 4 de `research/docs/Binance_MultiStrategy_PROPOSTA_APOS_CICLO12.md`.
- Candidatos, labels, score direto, relatório e modelos congelados: `research/results/cycle06_minute_breakout_stop15m_2026-09-28/`.
- Cortes de risco calculados com treino anterior: `research/results/cycle14_ev_decomposed_2026-09-28/fold_calibration.json`.
- Dados, custos e simulador: `research/data/usdm_btc_eth_1m/` e `research/scripts/cycle02_multiframe_research.py`.
