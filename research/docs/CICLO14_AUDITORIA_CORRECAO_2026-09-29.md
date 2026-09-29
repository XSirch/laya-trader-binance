# Correção de leitura do resultado C14

**Data:** 29/09/2026. Esta nota preserva o relatório original e corrige uma contradição textual para que a busca de hipóteses não repita um experimento já executado.

## Evidência conferida

O Ciclo 14 já treinou o seletor decompondo retorno esperado como `p × G − (1 − p) × L`: classificação calibrada para `p`, regressões calibradas para o tamanho de ganho `G` e perda `L`. O pré-registro fixa essa fórmula; a linha de resultado no ledger registra 48 modelos XGBoost/CUDA. O CSV fora do treino tem 1.977 candidatos e colunas `probability_calibrated`, `gain_calibrated`, `loss_calibrated` e `predicted_ev`.

Recalculei a fórmula em cada linha: a maior diferença absoluta entre `predicted_ev` e `p × G − (1 − p) × L` foi `0.0`. Nenhuma previsão excedeu o cutoff fixo de 1,2%. O maior EV previsto foi 0,7135%; o replay resultou em zero trades. A decomposição foi executada e reprovada como seletor nesta configuração.

## Errata

A seção “Verificação da proposta C12” do relatório [C14 resultados](CICLO14_EV_DECOMPOSTO_RESULTADOS_2026-09-28.md) dizia que a fórmula ainda não havia sido registrada, implementada ou treinada, embora o próprio resultado e seus artefatos descrevessem exatamente esse teste. Essa frase é inconsistente com a evidência primária acima. A leitura correta é: a decomposição foi proposta antes, testada no C14 e rejeitada para a regra C06 sob o cutoff e a janela congelados. Não repetir C14 mudando apenas os mesmos modelos, limites ou calibração nessa janela.

O C14 não aprovou a estratégia: não houve entrada, então EV realizado, payoff, profit factor e acerto continuam indefinidos. O C06 controle continua abaixo da amostra e das oito semanas. O relatório C13 ainda mostra limites oraculares por par abaixo de 1,2% para a política fixa C06. Essa correção documental não altera resultados, modelos, seleção ou protocolo.

## Proveniência

- Ledger C14: `research/EXPERIMENTS.jsonl`, experimento `C14-ev-decomposed-c06-usdm-result-2026-09-28`.
- Scores: `research/results/cycle14_ev_decomposed_2026-09-28/walk_forward_scores.csv`, SHA-256 `06bd156893354aafc79ffe0415169850f692fbfa0e5cb98f2501832f4e6f5506`.
- Relatório JSON: `research/results/cycle14_ev_decomposed_2026-09-28/research.json`, SHA-256 `f2f4325ea72a1ce052fd72e4ab267d1cd28e44fab514cbb7dc2e866d340c0227`.
- Ordens reais: nenhuma.
