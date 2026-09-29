# Protocolo: sizing semanal por previsão de cauda

## Hipótese

O estudo anterior usou as mesmas variáveis externas para prever retorno semanal e foi rejeitado: o acréscimo macro piorou o erro e a carteira ficou atrás do controle cripto. Essa decisão não será retreinada. Uma hipótese distinta, apoiada por pesquisa sobre VaR/ES, é que dados macrofinanceiros possam estimar risco de cauda mesmo sem prever a direção do retorno. O estudo publicado de Lawuobahsumo, Algieri e Leccadito estima quantis/ES diários e de cinco dias em cinco ativos entre 2015 e 2021; nossa amostra é menor e o alvo aqui é outro, portanto isso apenas motiva o teste, não antecipa seu resultado.

## Variáveis e previsão

- Manter os mesmos quatro ativos, limites UTC, snapshots ALFRED e limites de frescor do [protocolo macro semanal](macro_external_alpha_protocol_2026-09-27.md). Semanas sem as três séries frescas permanecem sem característica macro.
- Alvo por ativo e semana: menor `low` horário entre a abertura de segunda-feira às 00:00 UTC e a abertura da segunda-feira seguinte, dividido pela abertura inicial, menos um. Assim, o rótulo mede a pior excursão adversa observada dentro da semana. Só pode treinar depois da saída da semana e antes da decisão de domingo seguinte.
- Ajustar expansivamente, separadamente por ativo, um `QuantileRegressor` para o percentil 10 do alvo, com `StandardScaler`, `quantile=0.10`, `alpha=0.01`, solver `highs`, intercepto e no mínimo 52 rótulos completos. Sem grade de hiperparâmetros.
- Comparar `price_only` (retornos próprios de 1, 4 e 12 semanas) a `price_plus_macro` (mesmos lags mais nove variações externas de Nasdaq, VIX e índice amplo do dólar). Treinos de ambos usam exclusivamente rótulos encerrados antes do corte; o treino do modelo macro só contém semanas com todos os recursos frescos.
- Métricas de previsão: perda pinball para quantil 10%, cobertura observada, e os controles zero e quantil 10% empírico do treino. Comparar os dois modelos nas mesmas semanas/ativos, sem interpretar cobertura ou VaR como lucro.

## Regra de exposição fixada

Cada ativo mantém uma conta spot isolada, com saldo inicial igual a 25% do capital. Para previsão `q10`, definir `perda = max(1%, -q10)` e exposição alvo do saldo da conta `min(100%, 4% / perda)`. Isso representa orçamento de cauda de 4% por conta, equivalente a 1% do capital total inicial por ativo antes de diferenças de desempenho. Quando não houver previsão, manter caixa. Rebalancear na abertura semanal para o alvo; liquidar ao fim da amostra.

Comparar duas regras de sizing (`price_only` e `price_plus_macro`) com caixa e buy-and-hold nos custos de 0,15% e 0,30% por lado. Spot long/cash, sem alavancagem. O simulador usa preço de abertura e taxas fixas; spread, impacto, latência, impostos e yield do caixa não são conhecidos por OHLC.

## Avaliação e decisão

Usar o walk-forward comum entre modelos e o holdout fixado em 06/01/2025, liquidando em 31/08/2026. Os preços deste período já foram usados em outras famílias do projeto; chamar esta etapa de teste cronológico do protocolo, não de holdout intocado global. Reportar retorno líquido, CAGR, drawdown nas aberturas, limite adverso intrahorário, exposições, giro, taxas e desempenho por ativo e ano.

A meta local permanece 50% de CAGR líquido e drawdown adverso máximo de 10% nos dois custos e períodos. Um replay retrospectivo favorável não conclui o objetivo de lucratividade consistente: exigiria observação prospectiva em paper com parâmetros congelados. Se falhar, rejeitar esta hipótese e avançar a outra família sem otimizar retrospectivamente.

Não enviar ordens, não chamar JEV e não alterar a carteira paper. Respostas ALFRED brutas ficam no cache local ignorado; resultados versionáveis guardam somente hashes, previsões e métricas agregadas.

### Base documental

Lawuobahsumo, K. K., Algieri, B. e Leccadito, A., “Forecasting cryptocurrencies returns: Do macroeconomic and financial variables improve tail expectation predictions?”, *Quality & Quantity* 58, 2647–2675 (2024), publicado online em 2023. O artigo compara MCQRNN a simulação histórica e ARMA-GARCH, com 1.500 observações diárias e 500 previsões fora da amostra; os resultados de quantis/ES são positivos em geral, mas há exceções e empates. [Artigo original Springer](https://link.springer.com/article/10.1007/s11135-023-01761-1).
