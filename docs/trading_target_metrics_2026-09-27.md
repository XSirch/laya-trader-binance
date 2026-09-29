# Métricas revisadas da estratégia

## Meta atual

Em 27/09/2026, o usuário substituiu o alvo de 50% anual pelas metas por operação:

- taxa de acerto aproximada de 70%;
- payoff líquido mínimo de 1:1, idealmente entre 1,2:1 e 1,5:1;
- expectativa matemática líquida superior a 1,2% por operação.

O limite anterior de drawdown máximo de 10% continua valendo junto com essas metas. O cálculo de EV assume retorno líquido médio como percentual do capital comprometido antes da entrada, após taxas e slippage. A taxa de acerto conta uma vitória somente quando o PnL realizado líquido é positivo; payoff é a média dos ganhos líquidos dividida pela média absoluta das perdas líquidas.

O paper JEV iniciado antes desta revisão mantém sua configuração e ledger congelados. `src/jev_trader/trade_target_metrics.py` faz uma análise separada desses registros contra os novos critérios, sem alterar a chamada Jev ou o hash de configuração do experimento.

## Compatibilidade aritmética dos alvos

Se `p` é a taxa de acerto, `q` é o payoff entre ganho médio e perda média líquida, e `L` é a perda média como fração do notional comprometido, então:

`EV = (p × q − (1 − p)) × L`

Com `p = 70%`, o EV expresso em unidades da perda média é 0,40R para payoff 1:1, 0,54R para 1,2:1 e 0,75R para 1,5:1. Para atingir EV de 1,2% do notional comprometido, a perda média líquida teria de ser aproximadamente 3,00%, 2,22% ou 1,60% desse notional, respectivamente; para superar 1,2%, seria ligeiramente maior.

Essas perdas estão expressas sobre o notional, portanto não podem ser comparadas diretamente ao drawdown da conta. Com uma posição de 25% do patrimônio, sem alavancagem e sem sobreposição, perdas médias de 3,00%, 2,22% e 1,60% do notional equivalem a aproximadamente 0,75%, 0,56% e 0,40% da conta por operação. O drawdown real depende do tamanho da posição, alavancagem, posições simultâneas, correlação e sequência dos resultados; deve ser calculado na curva de patrimônio da carteira, não inferido apenas das métricas por trade.

Portanto, não se presume que os alvos sejam incompatíveis em toda estratégia, mas precisam ser medidos juntos e líquidos de custos. Nesta pesquisa, EV é percentual do notional comprometido; o limite de drawdown de 10% continua incluído no gate. Para uma futura estratégia de futuros alavancados, distinguir o EV sobre notional do EV sobre margem e calcular o drawdown sobre o patrimônio da conta.

## Como medir

O relatório separa uma triagem preliminar de uma validação. A triagem requer 30 operações completas para evitar tratar poucas operações como evidência; a validação requer ao menos 100, intervalos de incerteza e observação prospectiva. Um resultado de triagem não comprova consistência nem autoriza ordens reais.
