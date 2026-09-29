# Protocolo: continuação após confirmação do fluxo em futuros de 1 minuto

Hipótese exploratória distinta do replay de absorção: quando desequilíbrio de takers e retorno do preço confirmam a mesma direção, o movimento pode continuar o suficiente para alcançar uma saída limitada por risco. Este teste não altera nem reavalia os sinais de absorção.

## Universo e dados

- Perpétuos USD-M: BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT.
- Velas completas de 1 minuto e funding histórico: janeiro/2024 a agosto/2026.
- Os mesmos arquivos verificados do replay anterior serão reutilizados; nenhuma ordem real ou chamada Jev será feita.
- Os candles já foram examinados no projeto em outras granularidades e na hipótese de absorção. Logo, 2025/2026 servem como avaliação temporal desta nova regra, mas não são holdout de mercado intocado.

## Regra congelada

Em cada fechamento de minuto, medir nas cinco velas encerradas: desequilíbrio de takers `2 * taker_buy_quote / quote_volume - 1`, retorno open-to-close e volume cotado. Exigir volume cotado de cinco minutos pelo menos 1,5 vezes a mediana dos 144 volumes móveis anteriores.

- LONG se desequilíbrio de cinco minutos `>= 0,55` e retorno de cinco minutos for positivo.
- SHORT se desequilíbrio de cinco minutos `<= -0,55` e retorno de cinco minutos for negativo.
- Entrar na abertura seguinte. Stop além da extremidade da faixa de cinco minutos por `0,1 × ATR(14)` de 1m; ignorar stops menores que 0,15% ou maiores que 1,5% do preço de entrada.
- Alvo bruto fixo de `1,8R`, saída temporal após no máximo 60 velas, uma posição por par e cooldown de 30 minutos depois da saída.
- Se stop e alvo ocorrerem na mesma vela, contabilizar o stop primeiro; gaps além do stop usam a abertura como preenchimento adverso.
- Débito/crédito do funding que cair durante a posição.

## ML, seleção e avaliação

Classificador HistGradientBoosting fixo, com as 14 features causais já congeladas no [protocolo de absorção](futures_flow_absorption_protocol_2026-09-27.md): retornos, desequilíbrio taker, múltiplos de volume e trades, faixa/pavios e volatilidade. Hiperparâmetros: `max_iter=100`, `max_leaf_nodes=7`, `learning_rate=0,05`, `l2_regularization=10`, `min_samples_leaf=40`, `random_state=548`. O rótulo é PnL líquido positivo no cenário-base; exigir pelo menos 400 eventos de treino após declustering de 60 minutos.

- Treino: 2024.
- Validação e escolha de um único limiar ML: 2025; testar somente 0,55 a 0,90 em passos de 0,05.
- Confirmação diagnóstica: janeiro a agosto/2026 com limiar congelado após 2025.
- O limiar só passa a triagem se houver pelo menos 30 operações e todos os gates forem atendidos nos dois custos. É necessário haver ao menos 100 operações na validação e na confirmação para discutir consistência inicial.
- Gate conjunto: acerto líquido `>=70%`, payoff líquido `>=1,0` (alvo ideal `1,2–1,5`), EV líquido estritamente `>1,2%` por operação sobre o notional comprometido e drawdown adverso `<=10%`.
- Custos por lado: 0,10% base e 0,15% estresse, incluindo 0,05% de taxa taker presumida e slippage fixo de 0,05%/0,10%. Taxa individual real não foi fornecida; portanto, ambos são cenários, não cotação da conta.

Nenhum limiar será escolhido usando o período de confirmação; se o treino for insuficiente ou a validação falhar, registrar a hipótese sem procurar outro limiar, stop, alvo ou custo nestes dados.
