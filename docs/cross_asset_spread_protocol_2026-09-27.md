# Protocolo: reversão relativa entre pares de futuros cripto

Hipótese nova: desvios extremos da razão de preços entre dois criptoativos perpétuos tendem a convergir em até uma hora. É distinta da convergência Spot/perp do mesmo ativo, dos modelos direcionais de lags horários e dos sinais de tendência/fluxo.

## Universo e spread

Perpétuos USD-M em pares fixos, sem seleção por resultado: BTC/ETH, BTC/BNB, BTC/SOL, ETH/BNB, ETH/SOL e BNB/SOL. Usar velas completas de um minuto e funding histórico de janeiro/2024 a agosto/2026, com arquivos locais SHA-256/CRC verificados.

Para cada par `A/B`, calcular `spread = ln(close_A / close_B)`. Em cada fechamento `i`, a média e o desvio padrão usam exclusivamente os 1.440 spreads anteriores, sem incluir o atual. Gerar sinal somente no cruzamento de entrada: SHORT A/LONG B quando z-score cruza para `>=2,5`; LONG A/SHORT B quando cruza para `<=-2,5`.

- Para z-score positivo, alvo de convergência `+0,5σ` e stop adverso `+3,5σ` relativos à média congelada do sinal.
- Para z-score negativo, alvo `-0,5σ` e stop `-3,5σ`.
- Entrar nas duas pernas na abertura seguinte; considerar alvo/stop atingido apenas quando o fechamento de 1m cruza o nível e executar na abertura subsequente. Se não houver cruzamento, encerrar na abertura após 60 minutos. A abertura real define o preço de saída, inclusive gaps. Para drawdown intratrade, marcar cada minuto pelo extremo combinado adverso das duas pernas.
- Não abrir outro spread se qualquer uma das duas moedas já estiver em posição; cooldown de 30 minutos por moeda após saída. Notional bruto fixo de 25% do capital por spread, dividido igualmente entre pernas; sem alavancagem.
- PnL líquido considera retorno das duas pernas, taxas e slippage nas quatro ordens de entrada/saída, mais funding liquidado em cada perna. EV/payoff são calculados sobre o notional bruto combinado das duas pernas.

## ML, divisão e gates

HGB classifica se o resultado líquido da operação excederá zero no custo-base. Features causais: z-score, mudanças do z-score em 1/5/15 minutos, mudanças e volatilidade do spread, desvio padrão móvel de 24h, correlação de retornos em 60 minutos, retornos de 5/60 minutos, volume relativo e imbalance taker de cada ativo. Par e dados futuros não são features. Hiperparâmetros fixos: `max_iter=100`, `max_leaf_nodes=7`, `learning_rate=0,05`, `l2_regularization=10`, `min_samples_leaf=40`, `random_state=548`. Treino mínimo de 400 eventos após declustering de 60 minutos de eventos que compartilham qualquer ativo.

- Treino 2024; selecionar um único limiar 0,55–0,90 em passos de 0,05 usando apenas 2025; confirmação diagnóstica em janeiro–agosto/2026 com o limiar congelado.
- Custo por ordem executada em cada perna: 0,10% base e 0,15% estresse (0,05% taker presumido mais 0,05%/0,10% de slippage). Com duas pernas de mesmo notional, sobre o notional bruto do spread isso soma respectivamente 0,20% e 0,30% por operação completa, antes do funding.
- Gate conjunto nos dois custos: 30 operações de triagem, acerto líquido `>=70%`, payoff `>=1:1` (ideal 1,2–1,5), EV líquido `>1,2%` sobre notional bruto por operação e drawdown adverso da carteira `<=10%`. Exigir 100 operações na validação e confirmação para discutir consistência inicial.
- Se treino ou validação falhar, não buscar outro z-score, janela, par ou limiar na confirmação; registrar a falha da regra congelada.

Os candles já foram pesquisados em outras resoluções, portanto nenhum período é holdout de mercado intocado. Não enviar ordens reais nem chamadas Jev.
