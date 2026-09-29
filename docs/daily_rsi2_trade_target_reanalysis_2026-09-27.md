# Reavaliação por operação: RSI2 diário em Spot

## Resultado

Esta análise reagrupa os trades da regra diária RSI2 já pesquisada. Não alterei sinal, parâmetros, universo, datas ou custos. A regra compra quando RSI2 de Wilder <=10 e fechamento > SMA200; sai quando RSI2 >=60 ou fechamento < SMA200. Sinal no fechamento diário e execução na abertura seguinte.

| Janela | Operações base/estresse | Acerto base/estresse | Payoff base/estresse | EV líquido por trade base/estresse | DD de carteira base/estresse |
|---|---:|---:|---:|---:|---:|
| Desenvolvimento, 2024 | 58 / 58 | 63,79% / 62,07% | 0,675 / 0,650 | +0,308% / +0,107% | 15,83% / 16,50% |
| Calibração, H1/2025 | 15 / 15 | 73,33% / 73,33% | 0,708 / 0,629 | +1,040% / +0,837% | 5,35% / 5,49% |
| Validação, H2/2025 | 22 / 22 | 54,55% / 54,55% | 1,163 / 1,075 | +0,851% / +0,650% | 6,84% / 6,94% |
| Confirmação, jan–jul/2026 | 0 / 0 | sem amostra | sem amostra | sem amostra | 0,00% observado |
| Combinado, jan/2025–jul/2026 | 37 / 37 | 62,16% / 62,16% | 0,936 / 0,855 | +0,928% / +0,726% | 8,28% / 8,75% |

Custos por lado: 0,15% base e 0,25% estresse, exatamente os usados no replay Spot original. O EV é retorno líquido dividido pelo notional comprometido na entrada. O DD é a métrica de carteira do ledger diário original; não certifica drawdown intradiário ou fills reais.

## Conclusão contra a meta atual

A regra não passa. No recorte combinado, fica abaixo de 70% de acerto, payoff 1:1 e EV >1,2% em ambos os custos. A confirmação de 2026 não teve entradas. A taxa de acerto combinada foi 23/37 = 62,16%, com intervalo Wilson descritivo de 95% entre 46,10% e 75,94%; portanto, 37 trades também são amostra pequena para afirmar consistência.

A calibração H1/2025 isolada teve 73,33% de acerto, mas só 15 trades, payoff 0,708 e EV de 1,040% no custo base (0,837% no estresse). A validação H2/2025 reverteu: 54,55% de acerto, payoff 1,163 no base (1,075 no estresse) e EV inferior à meta. A regra não deve ser promovida só pela alta taxa de acerto da calibração.

O replay anterior reportou retorno acumulado de +7,73% no custo base e +5,76% no estresse entre janeiro/2025 e julho/2026, com drawdown de carteira inferior a 10%. A confirmação sem operações e o EV por trade abaixo de 1,2% impedem interpretar isso como estratégia consistente sob o alvo vigente. Este histórico já foi examinado e não é um holdout prospectivo.

## Método e proveniência

- Foram carregados os 176 arquivos Spot horários já locais e conferidos; os candles foram agregados em dias completos conforme `extended.daily_bars`.
- A análise usou a mesma máquina de estados RSI2/SMA200 de `strategies.make_signals` e reconstruiu posição, fill na próxima abertura, giro e custo como `backtest.evaluate_window`.
- Métricas por trade foram calculadas depois de taxas de entrada/saída em cada operação; o drawdown agregado veio do relatório anterior, sem replay novo de regra.
- JSON com métricas e ledger individual: [daily_rsi2_trade_reanalysis_20260927.json](../results/daily_rsi2_trade_reanalysis_20260927.json).
- CSV de trades: [daily_rsi2_trade_ledger_20260927.csv](../results/daily_rsi2_trade_ledger_20260927.csv).
- Script de reanálise: [daily_rsi2_trade_reanalysis.py](../src/jev_trader/daily_rsi2_trade_reanalysis.py).
- SHA-256 do relatório fonte: `f091d22062267051130d51efc9c01b3c5404ede788b1faeb40f2c64ece441eaf`.
- SHA-256 do manifesto Binance: `367de91c7b912d18eb01cef7fc8bc9a3597018ee2b00ca9ce5bcc7bbef291912`.
- SHA-256 do script desta análise: `86f5e8a5ee443092f20bfaecc4b926f1530d68e3f2e2f2bec5d28ec3b1096f17`.

Nenhuma ordem real foi enviada. A reanálise não altera o estado da pesquisa ativa nem a execução paper do JEV.
