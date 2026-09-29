# Ciclo 06 — resultados do breakout de um minuto com stop ATR de 15m

Executado em 28/09/2026 conforme o [protocolo congelado](CICLO06_MINUTE_BREAKOUT_STOP15M_PROTOCOLO.md). Resultado: `economics_promising_but_sample_insufficient`; gates de amostra e frequência não passaram.

## Comparação pareada com o Ciclo 05

Scanner, candles, features, corte, modelo mensal, saídas e execução são iguais ao Ciclo 05. Só o ATR do stop inicial mudou de 1m para o último candle completo de 15m.

| Métrica | Ciclo 05: stop ATR 1m | Ciclo 06: stop ATR 15m | Gate Rev02 |
|---|---:|---:|---:|
| Candidatos selecionados / trades-base | 2 / 2 | 19 / 11 | ≥200 trades |
| Semanas ativas | 2 | 6 | ≥8 |
| EV por trade | −0,382% | **+1,262%** | >+1,2% |
| Acerto | 0% | 27,27% | preferência próxima a 70% |
| Payoff | não estimável | 10,17 | ≥1 |
| Profit factor | 0 | 4,35 | ≥1,25 |
| DD máximo | 0,44% | 2,39% | medir, sem teto |
| PnL stress | −US$ 41,88 | **+US$ 380,50** | >0 |

O stop de 15m recuperou EV acima do piso estrito, payoff, profit factor e PnL stress neste replay. Só 11 trades completos em seis semanas não demonstram consistência; `target_not_demonstrated` permanece.

## O que melhorou e o que falta

O Ciclo 06 executou três vencedores e oito perdedores. Os maiores retornos foram +11,144%, +3,956% e +3,709%, todos em long de ETHUSDT e em três episódios de tendência conhecidos. Retirar o maior vencedor reduz o EV para +0,273%; retirar os dois maiores deixa −0,136%. Sob stress, retirar o maior deixa +0,108%; retirar dois deixa −0,297%. O sinal positivo ainda está concentrado, embora apareça em mais de um episódio.

O score geral continuou fraco: R² −0,026, correlação 0,140 e MAE 0,531%, acima do baseline constante de 0,487%. No decil superior, as previsões médias foram +0,569%, mas o retorno médio realizado foi −0,088%. A regra sem filtro também perdeu: 734 trades, EV −0,180%, PF 0,485 e drawdown 52,72%; sob stress, EV −0,397% e PF 0,217. Portanto, manter filtro e controle de amostra é essencial.

## Decisão

Preservar o breakout de 1m com stop ATR de 15m como hipótese promissora, junto do breakout de 15m do Ciclo 04. Rejeitar o stop de 1m do Ciclo 05. No ledger do C06, 19 candidatos selecionados resultaram em 11 entradas; oito foram ignorados porque uma posição já estava aberta. Isso demonstra efeito da regra de posição única, mas não prova que o cooldown de 15 minutos causou a baixa frequência. O Ciclo 07 mede apenas a sensibilidade a esse cooldown, deixando explícita essa incerteza e mantendo os outros parâmetros, inclusive o stop ATR de 15m. Eventos repetidos se sobrepõem e não contam como operações independentes. Apenas trades efetivamente executados, sem posição simultânea, contam para o gate.

O walk-forward usa candles de seleção históricos já examinados; nenhum resultado constitui validação independente ou autorização de paper/ordens reais. Modelos e ledgers estão em [`cycle06_minute_breakout_stop15m_2026-09-28`](../results/cycle06_minute_breakout_stop15m_2026-09-28/).

## Proveniência

- SHA-256 do relatório: registrado em `research/EXPERIMENTS.jsonl` após a execução.
- SHA-256 do script: `467b8e7f48f579f9cbe8083f834c79727786b341a54a252fab92de306ac8f432`.
- SHA-256 do protocolo: `f37ca34dc4371bcd646bba8fe37d697e6d848a02ff5622de0ac0f260b6521948`.
- Oito XGBoost CUDA mensais confirmaram `device=cuda:0` e `tree_method=hist`.
- Nenhuma ordem real foi enviada.
