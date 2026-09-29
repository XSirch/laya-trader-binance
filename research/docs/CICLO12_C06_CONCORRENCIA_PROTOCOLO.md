# Ciclo 12 — isolamento do limite de posições do Ciclo 06

## Pergunta

O replay do Ciclo 06 teria retido os mesmos sinais filtrados se aceitasse uma posição simultânea por par (BTCUSDT e ETHUSDT), em vez de bloquear qualquer novo sinal enquanto uma posição global estivesse aberta?

## Evidência que motiva o teste

O Ciclo 06 manteve o breakout, as features e o modelo mensal, mas alterou o stop inicial de ATR 1m para ATR15. Seu replay filtrado obteve EV +1,262% por operação e PnL stress +US$ 380,50, com 11 operações completas em seis semanas; apenas três longs ETH explicaram a maior parte do retorno. De 19 candidatos acima do corte fixo, oito foram ignorados quando uma posição global já estava aberta.

O Ciclo 07 reduziu o cooldown de 15m para 1m, mas treinou novamente sobre uma distribuição diferente e continuou com a posição global única. Portanto, ele não isolou o efeito da trava de concorrência. Esta reanálise corrigirá apenas essa lacuna usando os mesmos scores C06 gravados, sem retreino.

## Protocolo congelado

- Mercado: Binance USD-M; BTCUSDT e ETHUSDT. Sem produtos fora de cripto e sem ordens reais.
- Sinal, features, scanner de 1m, contexto 1h/4h, stop ATR15, saída EMA21/15m, limite de 24h, funding, corte `predicted_net_return > 1,2%`, scores, sizing por operação, dataset e período permanecem iguais ao C06.
- Comparador: reconstruir primeiro a gestão C06 original de uma posição global e exigir reconciliação com trades e métricas publicados.
- Única alteração: permitir até duas posições simultâneas, com no máximo uma por símbolo. A lista de entradas continua ordenada por horário e score como no C06. Uma entrada do mesmo símbolo é ignorada enquanto essa posição estiver aberta.
- O sizing por operação continua igual ao C06; duas posições podem elevar a exposição bruta agregada até duas vezes o limite individual do motor. Essa alteração de capacidade agregada será reportada como risco do teste.
- Sem treino, mudança de threshold, mudança de sizing individual ou pesquisa de outro limite de posições neste ciclo.
- Calcular métricas base e stress, EV por trade, payoff, profit factor, trades, semanas ativas, drawdown marcado minuto a minuto, candidatos ignorados e exposição agregada.

## Decisão e limites

Se a simulação de uma posição não reproduzir o C06, abortar sem interpretar o resultado de duas posições. Se a variante de duas posições piorar EV, stress ou drawdown sem aumentar a amostra de forma material, descartar essa capacidade. Um replay positivo continua exploratório: os mesmos sinais e a mesma janela já foram vistos, a amostra original é baixa e posições simultâneas compartilham risco de mercado. Não usar a execução retrospectiva para autorizar paper ou ordens reais.
