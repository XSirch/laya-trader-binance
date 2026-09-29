# Ciclo 12 — resultados da ablação de concorrência do C06

Executado em 28/09/2026 com as 19 previsões e os scores já gravados pelo Ciclo 06. Não houve retreino. A gestão original de uma posição foi reconstruída antes da comparação; suas métricas reproduziram o C06 e os retornos das operações conferiram com os rótulos salvos.

## Uma posição global versus uma por par

| Custo | Máx. posições | Trades | Acerto | EV/trade | Payoff | PF | PnL da carteira | DD | Semanas ativas |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Base | 1 | 11 | 27,27% | +1,262% | 10,173 | 4,353 | +US$ 575,01 | 2,394% | 6 |
| Base | 2, uma por par | 11 | 27,27% | +1,262% | 10,173 | 4,353 | +US$ 575,01 | 2,394% | 6 |
| Stress | 1 | 11 | 27,27% | +1,092% | 7,852 | 3,297 | +US$ 380,50 | 1,958% | 6 |
| Stress | 2, uma por par | 11 | 27,27% | +1,092% | 7,852 | 3,297 | +US$ 380,50 | 1,958% | 6 |

A alteração não executou nenhuma operação adicional. Os oito sinais que o C06 havia descartado pertenciam a um símbolo que ainda tinha uma posição aberta; eles não eram sinais independentes do outro par. Assim, liberar simultaneidade entre BTC e ETH não resolve o gargalo. Abrir outra operação no mesmo par seria piramidar a mesma exposição, mudaria o risco e não elevaria de forma legítima a amostra de eventos independentes; não faremos esse ajuste usando a mesma janela.

## Aprendizado preservado

- **Manter como hipótese:** stop inicial ATR15m. Na comparação anterior C05→C06, essa única mudança levou o resultado filtrado de EV −0,382% para +1,262% e deixou PnL positivo sob stress.
- **Não mudar cooldown outra vez:** C07 já mostrou que reduzi-lo aumentou muito os candidatos rotulados sem elevar as entradas executadas; o treino também mudou, por isso aquele resultado não isolava o cooldown sozinho.
- **Não relaxar o corte para fabricar trades:** C08 e C10 não produziram score acima de 1,2%, e o baseline bruto do rompimento foi negativo. C06 também teve R² −0,026, correlação 0,140 e MAE pior que o baseline constante.
- **Não aumentar o limite global:** esta ablação reproduziu C06 exatamente, mas confirmou zero ganho ao permitir duas posições em símbolos diferentes.

O C06 permanece uma hipótese de cauda, não uma fórmula consistente. Seu ponto positivo veio de três longs de ETH e só 11 operações em seis semanas; o maior vencedor sozinho responde por grande parte do EV. A fragilidade a corrigir está na qualidade/calibração seletiva do score, sem mexer no stop que melhorou o resultado nem contar sinais sobrepostos como trades independentes.

## Limites e proveniência

É um replay retrospectivo da mesma janela examinada nos Ciclos 06–10. Duas posições poderiam duplicar a exposição bruta agregada, mas a amostra não chegou a usar esse espaço. O motor não adicionou uma simulação de liquidação cruzada. Não houve treino de ML nem ordem real.

Protocolo: [Ciclo 12](CICLO12_C06_CONCORRENCIA_PROTOCOLO.md). Script: [cycle12_c06_concurrent_positions.py](../scripts/cycle12_c06_concurrent_positions.py). Scores e ledger: `research/results/cycle12_c06_concurrent_positions_2026-09-28/`.
