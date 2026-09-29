# Resultado: ML LONG / IDLE / SHORT a cada minuto

## Decisão

Sem candidata. O HGB foi ajustado em 35.098 estados de treino horários e produziu previsões para cada minuto. Na validação, o único limiar com entradas foi 0,55; gerou 255 estados com probabilidade de ação acima do limiar e 209 operações após posição única/cooldown. Acerto, payoff e EV falharam nos dois custos. Limiares de 0,60 a 0,90 não geraram operações, então não há configuração vencedora.

## Resultado de validação (2025)

| Limiar de probabilidade | Trades | Acerto base/estresse | Payoff base/estresse | EV líquido base/estresse | DD adverso base/estresse |
|---:|---:|---:|---:|---:|---:|
| 0,55 | 209 | 42,58% / 38,28% | 0,808 / 0,792 | -0,259% / -0,359% | 0,14% / 0,19% |
| 0,60–0,90 | 0 em cada limiar | Sem amostra | Sem amostra | Sem amostra | 0% |

Em 2024, os rótulos líquidos foram 12.812 IDLE, 11.365 LONG e 10.921 SHORT. O modelo teve volume de treino suficiente, mas não conseguiu separar entradas de alta qualidade. O gatilho opera em 209 trades; apesar da amostra acima do mínimo de triagem, fica longe de 70% de acerto, payoff 1:1 e EV >1,2%.

## Método e limites

O modelo combina desequilíbrio e retornos de um, cinco, 15 e 60 minutos, volume e número de trades, RSI14, MACD, EMA200, posição Fibonacci de quatro horas, formato do candle e volatilidade. Emite probabilidade para LONG/IDLE/SHORT a cada minuto; a entrada usa a abertura seguinte. Stop fixo de 1,5%, alvo bruto 1,9R, duração máxima 60 minutos, funding incluído, custos de 0,10%/0,15% por lado e alocação fixa de 25% por par, sem alavancagem.

2025 é o único período de seleção. Como não passou, os eventos de 2026 não foram usados para escolher ação, limiar ou parâmetros. O histórico já foi inspecionado em outras granularidades; a confirmação não é um holdout de mercado intocado. Não houve chamada Jev nem ordem real.

- Protocolo congelado: [minute_ml_buy_idle_sell_protocol_2026-09-27.md](minute_ml_buy_idle_sell_protocol_2026-09-27.md).
- Relatório com hashes e todas as métricas: `results/minute_ml_buy_idle_sell_20260927/research.json`.
- SHA-256 do código: `56a3cb12033fe3c515355ef6621d4a4cb609d765e44453900490e32ce603ef53`.
- SHA-256 do protocolo: `abd3bd1344e29535bee31a37f7aefc3c432f008a1f0fdd4a0d373ef659397706`.
