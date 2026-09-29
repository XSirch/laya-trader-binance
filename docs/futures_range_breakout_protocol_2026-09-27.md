# Protocolo: rompimento de faixa horária com fluxo agressor

Esta hipótese combina estrutura de preço e fluxo de takers em futuros de um minuto. Diferencia-se do sweep/reclaim horário, do Supertrend horário e das hipóteses de fluxo que entram diretamente pela direção do imbalance: aqui o gatilho exige fechar além da faixa anterior de 60 minutos e o stop fica no nível rompido.

## Universo e dados

- Perpétuos USD-M: BTCUSDT, ETHUSDT, BNBUSDT e SOLUSDT.
- Velas completas de 1 minuto e funding histórico: janeiro/2024 a agosto/2026; arquivos mensais locais com SHA-256 e CRC verificados.
- Treino 2024, seleção de um limiar ML em 2025 e confirmação diagnóstica janeiro–agosto/2026. O histórico foi pesquisado em outras resoluções; estes cortes não são um holdout de mercado totalmente intocado.
- Sem alavancagem ou ordens reais; funding da posição entra no PnL.

## Sinal e saída fixos

No fechamento de cada minuto `i`, definir a faixa anterior pelos 60 candles encerrados entre `i-64` e `i-5`, excluindo os cinco candles de sinal. Exigir volume financeiro dos últimos cinco minutos pelo menos 1,5 vezes a mediana dos 144 volumes móveis de cinco minutos anteriores.

- LONG quando o fechamento de `i` superar estritamente a máxima da faixa anterior, o retorno dos cinco minutos for positivo e imbalance de taker em cinco minutos for `>= 0,20`.
- SHORT quando o fechamento ficar estritamente abaixo da mínima anterior, o retorno dos cinco minutos for negativo e o imbalance for `<= -0,20`.
- Entrada na abertura seguinte. Stop 0,1 ATR(14) de um minuto para dentro da faixa rompida. Ignorar risco menor que 0,15% ou maior que 1,5% da entrada.
- Alvo bruto fixo de `1,8R`, prazo máximo de 60 minutos, uma posição por par e cooldown de 30 minutos após a saída.
- Stop primeiro se stop e alvo forem tocados na mesma vela; gaps além do stop preenchem na abertura adversa.
- Uma taxa de funding atravessada é debitada ou creditada pelo timestamp histórico.

## Modelo, custos e decisão

Classificador HistGradientBoostingClassifier para probabilidade de PnL líquido positivo no custo-base, usando as 14 features causais do protocolo de fluxo de um minuto. Hiperparâmetros fixos: `max_iter=100`, `max_leaf_nodes=7`, `learning_rate=0,05`, `l2_regularization=10`, `min_samples_leaf=40`, `random_state=548`. Treino exige 400 episódios após declustering de 60 minutos.

- Testar apenas limiares de probabilidade de 0,55 a 0,90 em passos de 0,05; 2025 escolhe no máximo um limiar.
- Custos por lado de 0,10% (0,05% taker assumido + 0,05% slippage) e estresse de 0,15% (0,05% taker + 0,10% slippage).
- O gate conjunto em ambos os custos é: ao menos 30 operações na triagem, acerto líquido `>=70%`, payoff líquido `>=1:1` (alvo ideal `1,2–1,5:1`), EV líquido `>1,2%` do notional comprometido por operação e drawdown adverso `<=10%`. Exigir 100 operações em 2025 e em 2026 para avaliar consistência inicial.
- Se a validação falhar ou o treino for insuficiente, não escolher limiar nem regra olhando 2026; registrar resultado sem ajustar stops, gatilhos ou custos.
