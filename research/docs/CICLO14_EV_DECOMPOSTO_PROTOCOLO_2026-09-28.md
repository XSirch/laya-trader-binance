# C14 — Protocolo para estimativa de EV decomposto

Data: 28/09/2026  
Status: pré-registro antes de treinar os novos componentes. Resultado retrospectivo; não constitui validação independente nem autorização para operar.

## Pergunta e hipótese

O regressor direto do C06 ordena os candidatos de forma insuficiente. Esta rodada testa uma única forma alternativa de previsão para o mesmo rompimento/continuação em BTCUSDT e ETHUSDT USD-M: estimar separadamente a probabilidade de retorno líquido positivo, o tamanho condicional dos ganhos e o tamanho condicional das perdas, combinando-os em expectativa líquida por nocional:

```text
p = P(r > 0 | features)
G = E(r | r > 0, features)
L = E(-r | r <= 0, features)
EV = p * G - (1 - p) * L
```

Retorno zero pertence ao alvo não positivo e contribui zero para `L`. Todos os alvos usam o retorno líquido do mesmo simulador; taxas, slippage e funding não são subtraídos novamente.

## Escopo congelado

- Controle: scores, relatórios e simulador salvos do C06; nenhum regressor direto será retreinado.
- Universo: Binance USD-M, BTCUSDT e ETHUSDT, uma posição global por vez.
- Entradas: candidatos/labels já gerados pelo C06; scanner, rompimento de 300 minutos, cooldown de 15 minutos, features e stop ATR15m permanecem congelados.
- Saída: `trend_loss`, horizonte máximo de 1.440 minutos.
- Calendário: refit mensal, folds de janeiro a agosto de 2026; treinamento só com labels maduros antes do corte mensal e purge de 24 horas, usando `matured_training_labels` do C04.
- Decisão: selecionar se, e somente se, `EV previsto > 0,012`. Esse limite é fixo; nenhum limiar será ajustado com o período avaliado.
- Execução: mesmo simulador e limites de capital/risco do C06. Stress dobra taxa e slippage; funding observado é preservado.
- Período avaliado: 02/01/2026 00:00 UTC a 01/09/2026 00:00 UTC, exclusivo. Este período já foi inspecionado em C05, C06, C12 e C13; qualquer resultado é exploratório e sujeito a seleção retrospectiva.

## Ajuste e calibração prévia

Em cada refit mensal, o treino elegível mantém exatamente os filtros de maturidade e embargo do C04. Os 90 dias de sinal mais recentes dentro desse treino formam um bloco cronológico de calibração; um conjunto provisório de três modelos, ajustado somente nos dados elegíveis anteriores a esse bloco, gera as previsões de calibração.

- `p`: XGBoost binário com `binary:logistic`; aplicar calibração de Platt por regressão logística sobre o logit da probabilidade provisória e o rótulo `r > 0` do bloco anterior.
- `G`: XGBoost de regressão quadrática apenas nos retornos positivos. Calibrar a escala com mínimos quadrados pela origem entre a previsão truncada em zero e `r` observado nos positivos do bloco anterior.
- `L`: XGBoost de regressão quadrática sobre `max(-r, 0)` em todos os retornos não positivos. Calibrar a escala pela origem contra `max(-r, 0)` no bloco anterior.
- Após obter os três calibradores, reajustar os três modelos nos respectivos subconjuntos de todo o treino elegível. Aplicar os calibradores congelados às previsões finais do fold. Não usar labels do fold avaliado para ajuste ou calibração.
- Configuração fixa dos modelos: 320 árvores, profundidade 4, taxa 0,04, `subsample=0,8`, `colsample_bytree=0,8`, `min_child_weight=40`, `reg_lambda=10`, `max_bin=256`, `tree_method=hist`, `device=cuda:0`, semente 27. Sem fallback para CPU.
- Suporte mínimo por fold: treino final com pelo menos 1.000 labels, 50 positivos e 500 não positivos; bloco de calibração com pelo menos 200 labels, 25 positivos e 100 não positivos; treino provisório com pelo menos 1.000 labels, 50 positivos e 500 não positivos. Coeficientes não finitos, divisor nulo ou amostra abaixo do mínimo causam abstenção de todos os candidatos daquele fold, com motivo registrado.

## Controles e análises

1. Reproduzir os resultados do C06 a partir dos scores salvos e do mesmo simulador, verificando que trades e métricas fecham com o relatório dentro de tolerância numérica.
2. Comparar o previsor decomposto com o C06 direto congelado e com o baseline de regra já salvo. Reportar cobertura, candidatos selecionados, operações efetivamente executadas e resultados de base/stress.
3. Gerar 100 controles aleatórios determinísticos, sementes 1701–1800. Para cada conjunto escolhido pelo modelo, conservar a contagem por mês, símbolo, direção e quintil de risco ex-ante (`stop_fraction_signal`); os quintis do mês usam somente o treino elegível anterior ao corte. Sortear sem reposição dentro de cada grupo e aplicar o mesmo simulador, sem filtrar por desfecho futuro.
4. Reportar EV líquido, acerto, payoff, profit factor, drawdown, PnL, semanas ativas, concentração por ativo/direção, calibração e faixas de score. Se não houver seleção, os controles aleatórios pareados são inaplicáveis e isso será registrado.

## Critérios e limites

Critérios econômicos do usuário: EV-base estritamente acima de 1,2% por operação e payoff de pelo menos 1:1; profit factor-base de pelo menos 1,25; no mínimo 200 operações completas e distintas em oito semanas ativas; PnL agregado positivo no stress. Acerto perto de 70% é preferência, não piso. Não há teto de drawdown: medi-lo e minimizá-lo entre variantes aprovadas. Não consolidar amostras de mercados ou variantes para atingir gates.

Não atribuir validação independente a este replay. O C13 encontrou limite superior retrospectivo acima de 1,2% apenas no ranking-oráculo combinado dos dois contratos; resultados por ativo ficaram abaixo do limite. Isso justifica testar a forma do estimador, mas não prova que ela identifique oportunidades executáveis. Nenhum resultado histórico ou de paper autoriza ordens reais.

## Fontes congeladas

- Proposta: `research/docs/Binance_MultiStrategy_PROPOSTA_APOS_CICLO12.md`, seção 5.
- Controle/modelo: `research/scripts/cycle06_minute_breakout_stop15m.py` e `research/scripts/cycle03_direct_net_ev.py`.
- Labels/scores/relatório C06: `research/results/cycle06_minute_breakout_stop15m_2026-09-28/`.
- Features, custos, simulador e gates: `research/scripts/cycle02_multiframe_research.py`.
- Maturidade, embargo e folds: `research/scripts/cycle04_rolling_refit.py`.
- Dados USD-M e manifesto: `research/data/usdm_btc_eth_1m/`.
