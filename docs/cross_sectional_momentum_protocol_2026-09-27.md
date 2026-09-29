# Protocolo: momentum cross-sectional em futuros cripto

## Hipótese e gatilho

Hipótese nova e distinta da reversão do spread: entre BTC, ETH, BNB e SOL, o líder de retorno recente pode continuar superando o retardatário na próxima hora. Operar perpétuos USD-M, long no líder e short no retardatário, ambos com notional igual.

A cada 15 minutos UTC, ordenar os quatro contratos pela variação logarítmica dos 60 minutos encerrados no fechamento atual. Gerar sinal somente se o líder teve retorno positivo, o retardatário retorno negativo e a diferença entre os dois retornos for de pelo menos 0,75 ponto percentual. Empates são resolvidos pela ordem fixa BTC, ETH, BNB, SOL. Entrada das duas pernas na abertura de 1 minuto seguinte.

Manter por 60 minutos completos e encerrar as duas pernas na abertura do minuto seguinte. Não há stop ou alvo intraperíodo nesta hipótese. Sinais que compartilham qualquer ativo com uma posição aberta são descartados; cooldown de 30 minutos por ativo após saída. Notional bruto fixo de 25% do capital por operação, metade por perna, sem alavancagem.

PnL usa retorno realizado de cada perna, funding histórico entre entrada e saída e custo de 0,10%/0,15% por ordem em cada perna. Sobre notional bruto combinado, o custo completo de ida e volta é 0,20%/0,30%. EV e payoff são líquidos e expressos sobre o notional bruto combinado.

## ML, validação e gates

HGB prevê PnL líquido positivo no custo-base. Features causais fixas: retornos de 5/15/60/240/1440 minutos do líder e retardatário, dispersão cross-sectional de retorno de 60/240 minutos, gap relativo normalizado, volatilidade realizada de 60 minutos, volume relativo, imbalance taker e diferencial de funding. Ativo específico e informação futura não são features. Hiperparâmetros: `max_iter=100`, `max_leaf_nodes=7`, `learning_rate=0,05`, `l2_regularization=10`, `min_samples_leaf=40`, `random_state=661`.

Treino 2024 após declustering de 60 minutos; seleção de um único threshold entre 0,55 e 0,90 em passos de 0,05 usando apenas 2025; janeiro–agosto/2026 é confirmação diagnóstica somente com threshold congelado. Requer pelo menos 400 eventos independentes no treino, 30 operações para triagem e 100 operações tanto na validação quanto na confirmação.

Passa somente se, em custo base e estresse, todos forem satisfeitos: acerto líquido >=70%, payoff >=1:1 (ideal 1,2–1,5), EV líquido >1,2% por operação e drawdown adverso de carteira <=10%. Se não houver threshold elegível na validação, registrar falha e não escolher parâmetro pela confirmação. Não enviar ordens nem chamar Jev.

Este histórico já foi inspecionado em outras pesquisas e não constitui holdout intocado. Um resultado retrospectivo não demonstra consistência prospectiva nem autoriza negociação real.
