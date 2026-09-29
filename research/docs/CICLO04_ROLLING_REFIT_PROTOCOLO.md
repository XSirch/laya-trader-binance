# Ciclo 04 — atualização walk-forward mensal do XGBoost

Registrado em 28/09/2026 antes do treino. Status inicial: `preregistered_before_training_or_replay`.

## Pergunta

O regressor estático do Ciclo 03 foi treinado até 01/07/2025. Embora tenha apresentado retorno positivo em uma seleção histórica posterior, a calibração não ordenou bem os resultados e o PnL ficou concentrado em poucos episódios. Este experimento altera somente a data em que o modelo é ajustado: XGBoost USD-M será reestimado no início de cada mês com rótulos já maduros até esse momento. A hipótese é que o modelo consiga acompanhar melhor mudanças de regime. O replay é retrospectivo e não valida essa hipótese para uso futuro.

## Núcleo preservado

- Binance USD-M, BTCUSDT e ETHUSDT.
- Entrada `breakout_continuation`, horizonte máximo de 24 horas.
- Saída `trend_loss`, com stop inicial de 1 ATR e perda da EMA21 conforme motor do Ciclo 02.
- Features, alvo `net_return`, XGBoost CUDA, hiperparâmetros e seed iguais aos do Ciclo 03.
- Um único filtro: `predicted_net_return > 0.012`.
- Tamanho, limite de uma posição por mercado, taxas, slippage, funding e simulação idênticos ao Ciclo 03.

## Única mudança autorizada

O modelo será treinado novamente no primeiro dia UTC de cada mês. Em cada fold, uma linha só poderá entrar no treino se `signal_time < início_do_mês - 24h` e `label_end_time < início_do_mês`. O treino é expansivo, desde o início disponível dos rótulos até a última data madura. Os eventos do mês são previstos uma única vez com o modelo daquele mês. Nenhuma linha com resultado ainda não encerrado poderá treinar o fold; o corte não será recalibrado.

A avaliação cobre o mesmo período de seleção do Ciclo 03, de 02/01/2026 até o limite exclusivo de 01/09/2026. A restrição de encerramento máximo de 24h permanece igual. O portfólio usa posição global única por mercado, e a mesma sequência de candidatos alimenta o cenário-base e o cenário de custos dobrados.

## Comparação e gates

Comparar, sem somar operações, ao XGBoost estático da mesma variante no Ciclo 03 e à regra-base sem filtro já registrada. Reportar EV líquido por nocional inicial, payoff, profit factor, drawdown, trades completos, semanas ativas, acerto, PnL líquido sob custos dobrados e diagnósticos de previsão por mês. Os gates permanecem os da Rev02: EV-base `>1,2%`, payoff `>=1`, PF `>=1,25`, pelo menos 200 trades completos em oito semanas ativas e PnL líquido positivo sob stress. Acerto próximo de 70% é preferência, sem piso; drawdown deve ser medido, sem teto.

O resultado selecionado por threshold não será usado para escolher um threshold, feature, janela ou outro modelo. Métricas por fold e faixas de score são diagnósticos descritivos. Nenhuma combinação será promovida com base em poucos trades ou em um episódio de tendência.

## Integridade, arquivos e limites

- Script: `research/scripts/cycle04_rolling_refit.py`.
- Testes determinísticos: `research/tests/test_cycle04_rolling_refit.py`.
- Pasta de saída prevista e inexistente antes da execução: `research/results/cycle04_rolling_refit_2026-09-28/`.
- Conferir hashes dos dados, labels, relatório do Ciclo 03, motor, script e protocolo antes do replay.
- Confirmar `device=cuda:0` e `tree_method=hist` em cada modelo mensal; encerrar em erro se CUDA não estiver disponível.
- Nenhuma ordem real será enviada.

Esta janela histórica já foi vista em pesquisas anteriores. Mesmo que os gates sejam alcançados, o resultado permanece exploratório, não é holdout independente e não autoriza paper ou ordens reais. Uma candidata ainda precisará de validação independente e paper prospectivo congelado por pelo menos oito semanas ativas e 200 trades completos.
