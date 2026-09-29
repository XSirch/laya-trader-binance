# Ciclo 02 — filtro causal de custo relativo ao stop

Registrado em 28/09/2026, antes do replay. Testa uma única hipótese econômica sugerida na revisão 2 do handoff: a viabilidade de cada sinal depende de quanto a fricção estimada consome do stop inicial.

## Hipótese

Descartar uma entrada se o custo estimado de ida e volta, em cenário-base, exceder 25% da distância percentual até o stop inicial de 1 ATR. Como a distância do stop varia com ATR%, isso pode remover trades nos quais as taxas e o slippage consomem grande parte do risco planejado. O filtro pode reduzir também a frequência; EV, amostra e stress continuam sendo medidos.

## Definição causal congelada

No fechamento completo de 15 minutos que gera o sinal:

```text
stop_fraction_signal = ATR_15m(14) / close_15m
round_trip_cost_rate_base = 2 * (fee_bps_per_side + slippage_bps_per_side) / 10_000
cost_to_stop_ratio = round_trip_cost_rate_base / stop_fraction_signal
accept_signal = cost_to_stop_ratio <= 0.25
```

Custos configurados: Spot 10 bps de taxa e 5 bps de slippage por lado (30 bps ida e volta); USD-M 5 bps e 5 bps por lado (20 bps ida e volta). O mesmo sinal elegível é avaliado em cenário-base e com taxa/slippage dobrados; o cutoff continua baseado nos custos-base e não é recalculado para melhorar o stress.

O ATR e o close são conhecidos no instante do sinal. A regra descarta antes da entrada na próxima abertura de 1 minuto; não usa preço futuro de fill, retorno, MFE/MAE, rótulo nem funding futuro. O simulador continua debitando os custos nos fills uma só vez.

## Universo e avaliação

- Somente BTCUSDT e ETHUSDT em Binance Spot e USD-M, cada mercado separado.
- Manter as 2 famílias, 2 horizontes (6h/24h), 3 saídas, direção, sizing, custos, funding, período e execução do pré-registro do Ciclo 02.
- Rodar regra fixa com o filtro único em 24 combinações mercado/família/horizonte/saída. Comparar cada resultado com a linha de regra sem filtro da reexecução corrigida; não agregar combinações.
- Sem ML, ajuste de threshold ou treino novo nesta etapa. Se o filtro fixo mostrar evidência suficiente para justificar um estágio posterior, registrá-lo separadamente antes de reutilizar os modelos.
- Aplicar todos os gates: EV líquido >1,2%, payoff ≥1, profit factor ≥1,25, pelo menos 200 trades completos em oito semanas ativas, e stress integral positivo com payoff ≥1. Acerto perto de 70% é preferência e drawdown não tem teto.
- A janela de seleção histórica já foi examinada e esta hipótese sucede resultados anteriores; classificar o replay como exploratório, não holdout ou prova prospectiva. Nenhum resultado autoriza paper ou ordem real.
- Se o filtro eliminar todos os sinais, não experimentar outro cutoff nesta janela. Registrar a rejeição.

## Proveniência e saída

Fonte de baseline: relatório corrigido `results/cycle02_multiframe_corrected_2026-09-28/research.json`, SHA-256 `3d0a1c6a3bf8e2275fd3f4444920a4c1f5a8f776b094283e316b5b20234e680d`. Verificar os hashes de dados, o resultado fonte e os hashes distintos dos exits antes de executar.

Salvar fórmula, contagens de sinais elegíveis, métricas base/stress, gates e diferenças pareadas em `results/cycle02_cost_stop_filter_2026-09-28/research.json`. Registrar hashes do protocolo, script, relatório fonte e saída.

## Comando

```powershell
research\.venv\Scripts\python.exe research\scripts\cycle02_cost_stop_filter_research.py --source-report research\results\cycle02_multiframe_corrected_2026-09-28\research.json --expected-source-sha256 3d0a1c6a3bf8e2275fd3f4444920a4c1f5a8f776b094283e316b5b20234e680d --output research\results\cycle02_cost_stop_filter_2026-09-28
```
