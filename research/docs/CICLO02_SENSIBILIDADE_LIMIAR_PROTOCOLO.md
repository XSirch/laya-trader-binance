# CICLO 02 — sensibilidade pós-hoc do limiar ML

Registrado em 28/09/2026, antes desta análise suplementar. Este estudo sucede ao pré-registro principal e reutiliza modelos treinados e avaliados no mesmo bloco histórico de seleção. Portanto, não é confirmação independente nem substitui paper prospectivo.

## Pergunta

O piso de probabilidade 0,35 do pré-registro principal deixou o classificador sem sinais suficientes? A análise executa os mesmos filtros, custos, sizing, saídas e gates em limiares de 0,05 a 0,35, em passos de 0,05.

## Método congelado para esta sensibilidade

- Reutilizar, sem novo ajuste, os modelos salvos de HGB CPU e XGBoost CUDA do relatório `research/results/cycle02_multiframe_2026-09-28/research.json`.
- Manter o piso de retorno previsto em 0,05R, os mesmos dados, sinais, features, splits cronológicos, custos, funding USD-M, sizing e avaliação de portfólio.
- Reutilizar os rótulos de candidatos já salvos e recomputar scores e replays para cada threshold em 0,05; 0,10; 0,15; 0,20; 0,25; 0,30; 0,35.
- Avaliar BTCUSDT e ETHUSDT separadamente em Spot e USD-M, sem combinar mercados, variantes, backends ou thresholds para cumprir gates.
- Preservar todos os resultados, inclusive thresholds sem trades ou com gates reprovados. O threshold só seria candidato a paper se passar todos os gates; nenhum resultado desta janela autoriza ordens reais.

## Limite da inferência

Esta faixa foi registrada após observar que o bloco de seleção quase não tinha scores acima de 0,35. Assim, qualquer resultado favorável continua sendo exploração retrospectiva e sujeito a seleção adaptativa. Não escolher parâmetros finais com este bloco, não chamá-lo de holdout e não iniciar operação por causa dele. Se algum threshold parecer promissor, congelar modelo, threshold, dados, código, custos e regra antes de coletar uma nova janela prospectiva em paper; manter a regra sem reajustes até cumprir a amostra mínima e as oito semanas ativas.
