# Ciclo 05 — resultados do breakout USD-M avaliado a cada minuto

Executado em 28/09/2026 conforme o [protocolo registrado](CICLO05_MINUTE_BREAKOUT_PROTOCOLO.md). Resultado: `rejected_minute_entry_with_1m_atr`; nenhum gate Rev02 passou.

## Resultado

O scanner produziu 6.416 eventos completos entre BTCUSDT e ETHUSDT. No período de seleção, houve 1.977 candidatos e o XGBoost com atualização mensal selecionou apenas dois. Ambos eram ETHUSDT, ambos fecharam no stop, e o replay resultou em:

| Métrica | Resultado | Gate Rev02 |
|---|---:|---:|
| Trades-base / semanas ativas | 2 / 2 | ≥200 / ≥8 |
| EV líquido por trade | −0,382% | >+1,2% |
| Acerto | 0% | preferência próxima de 70% |
| Profit factor | 0 | ≥1,25 |
| PnL líquido sob custos dobrados | −US$ 41,88 | >0 |
| Trades de regra sem filtro | 1.476 | — |
| EV da regra sem filtro | −0,202% | — |

A regra sem filtro também teve lucro líquido de −US$ 9.250,77, PF 0,144 e drawdown 92,51%; no stress, perdeu US$ 9.665,08 com drawdown 96,65%. Isso rejeita o breakout de um minuto **com stop de 1 ATR de um minuto** nesta janela. O resultado não invalida o breakout de 15 minutos do Ciclo 04.

## Diagnóstico do componente que falhou

O Ciclo 05 alterou conjuntamente o momento da entrada, as features rápidas e a escala do stop; portanto, o replay não identifica sozinho qual desses efeitos causou a perda. O modelo selecionou apenas dois eventos, insuficientes para explicar toda a diferença. Na regra bruta, 1.476 trades tiveram só 2,17% de acerto, compatível com stops de 1 minuto muito sensíveis ao ruído intraminuto, mas ainda não prova que esse foi o único problema. No decil superior dos 1.977 scores, a previsão média foi +0,065%, enquanto o retorno observado médio foi −0,173%; a correlação foi 0,017 e o R² −0,069. O filtro não recuperou o comportamento observado no Ciclo 04.

O Ciclo 06 isolará uma hipótese: manter scanner e features de 1 minuto e alterar somente o stop inicial para ATR de 15 minutos, preservando a escala de risco do resultado promissor do Ciclo 04. O corte, modelo mensal, saída EMA21 de 15 minutos, custos, funding e sizing permanecem fixos. A nova hipótese será registrada antes do replay; o Ciclo 05 não será recalculado.

## Decisão e limites

Preservar o Ciclo 04 como melhor hipótese exploratória: scanner de 15 minutos, saída `trend_loss`, modelo mensal e retornos positivos em 7 trades, mas sem amostra suficiente e concentrado em dois movimentos. Rejeitar apenas a variação específica de 1 minuto com stop de 1 minuto. O Ciclo 06 isola a escala do stop para avaliar se o erro foi estreitar o risco além do adequado.

Todos os resultados são retrospectivos e usam período já observado. Nenhum autoriza paper nem ordens reais. Artefatos e modelos estão em [`cycle05_minute_breakout_2026-09-28`](../results/cycle05_minute_breakout_2026-09-28/).

## Proveniência

- SHA-256 do relatório: registrado em `research/EXPERIMENTS.jsonl` após a execução.
- SHA-256 do script: `9a445d8b2b6f8ebcd97167cbd26095f7bdb8e7c3c2245814cecc864cf96d7194`.
- SHA-256 do protocolo: `d7e149db6badc09797cb4fc49c4ccb59ff2d422b3aaa16970c215285ce1b06a3`.
- Oito XGBoost CUDA mensais confirmaram `device=cuda:0` e `tree_method=hist`.
- Nenhuma ordem real foi enviada.
