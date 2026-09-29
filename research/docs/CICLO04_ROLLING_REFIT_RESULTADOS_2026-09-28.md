# Ciclo 04 — resultados da atualização mensal walk-forward

Executado em 28/09/2026 conforme o [protocolo congelado](CICLO04_ROLLING_REFIT_PROTOCOLO.md). Resultado: `promising_but_insufficient`; nenhum candidato passou todos os gates Rev02.

## Comparação da mesma configuração

O Ciclo 04 manteve USD-M, breakout/continuação de 24h, saída por perda da EMA21, features, alvo, hiperparâmetros XGBoost, corte `predicted_net_return > 1,2%`, custos, funding, sizing e execução. A única alteração foi reajustar o XGBoost no início de cada mês com rótulos já maduros.

| Métrica | XGBoost estático — Ciclo 03 | XGBoost mensal — Ciclo 04 | Gate Rev02 |
|---|---:|---:|---:|
| Candidatos acima do corte | 35 | 14 | diagnóstico |
| Trades-base completos | 18 | 7 | ≥200 |
| Semanas ativas | 14 | 6 | ≥8 |
| EV líquido por trade | +0,788% | **+2,199%** | >+1,2% |
| Acerto | 22,22% | 28,57% | preferência próxima de 70% |
| Payoff | 10,43 | 14,35 | ≥1 |
| Profit factor | 2,78 | 6,28 | ≥1,25 |
| Drawdown máximo | 2,02% | 1,93% | medir, sem teto |
| PnL líquido sob custos dobrados | +US$ 214,06 | **+US$ 349,60** | >0 |
| Trades de stress / semanas ativas | 20 / 14 | 8 / 6 | diagnóstico |

O resultado mensal passou EV, payoff, profit factor e PnL de stress, mas falhou amostra e frequência. A média de sete trades não é estimativa estável de EV e a configuração permanece `target_not_demonstrated`.

## O que melhorou e o que continua falhando

Dos sete trades-base, dois foram vencedores: +12,869% em ETHUSDT no episódio de 19/08 e +5,768% no episódio de 07/04. Os outros cinco perderam entre 0,571% e 0,768%. Retirar o maior vencedor reduz o EV para +0,420%; retirar os dois vencedores deixa −0,650%. O PnL stress também fica negativo ao remover apenas o maior vencedor. Assim, o ganho é compatível com capturar raros rompimentos de tendência, mas depende de dois episódios conhecidos e não demonstra recorrência.

Houve uma melhora pequena nos scores fora do treino: em 1.455 candidatos, a correlação de Pearson foi 0,221 e R² 0,031. O RMSE (1,039%) ficou ligeiramente abaixo do baseline constante (1,055%), mas o MAE (0,535%) foi pior que o baseline (0,488%). No decil superior, a previsão média foi +0,551%, enquanto o retorno realizado médio foi apenas +0,013%, muito abaixo do corte de +1,2%. Portanto, a atualização ajuda a ordenar alguma diferença entre piores e melhores candidatos, mas não calibra o EV em nível suficiente.

A distribuição mensal dos 14 candidatos selecionados foi: jan. 1, fev. 0, mar. 2, abr. 6, mai. 0, jun. 0, jul. 0 e ago. 5. Os sete trades executados ficaram em seis semanas ativas e as duas altas concentraram a maior parte do resultado. O problema restante é a baixa frequência e a concentração temporal, não falta de PnL bruto neste replay.

## Decisão e próxima alteração

Preservar a atualização mensal como uma melhoria exploratória; não descartá-la nem tratá-la como aprovada. O teste sustenta que a atualização merece permanecer no núcleo de pesquisa porque manteve stress positivo e elevou o EV-base, embora os resultados ainda sejam frágeis.

A próxima rodada deve atacar apenas a frequência do sinal, conforme a preferência do usuário por avaliação a cada minuto. A hipótese será converter o scanner do mesmo breakout USD-M para fechar e avaliar candles de 1 minuto, mantendo a saída por EMA21 de 15 minutos, stop inicial de 1 ATR na escala definida antes do teste, modelo mensal, corte de 1,2%, posição única, custos e gates. A resolução de entrada será a única mudança; o protocolo precisa explicar qualquer campo cuja escala mude por consequência direta da frequência de candle. A janela 2026 continua retrospectiva e não poderá escolher threshold ou parâmetros.

Não houve ordens reais. O teste não é independente nem prospectivo e não autoriza paper automaticamente. Artefatos, modelos mensais e scores estão em [`cycle04_rolling_refit_2026-09-28`](../results/cycle04_rolling_refit_2026-09-28/).

## Proveniência

- SHA-256 do relatório: registrado em `research/EXPERIMENTS.jsonl` após a execução.
- SHA-256 do script: `0fd509b7e008bf325025e3031b3f5cebf560241394c02067f1a645eee99ab286`.
- SHA-256 do protocolo: `555911efb3965d8469880aef6b06a3aa04070ea3dcf648854188177f6ec69662`.
- Oito modelos XGBoost CUDA foram treinados; todos registraram `device=cuda:0` e `tree_method=hist`.
- Python 3.13.9, XGBoost 3.4.1, pandas 2.3.3, NumPy 2.5.3, scikit-learn 1.9.1 e SciPy 1.18.1.
