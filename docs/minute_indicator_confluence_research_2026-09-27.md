# Resultado: confluência de indicadores de um minuto

## Decisão

Sem candidata. O classificador não foi ajustado: após o declustering de 60 minutos restaram 48 eventos de treino, abaixo do mínimo congelado de 400. A regra fixa gerou 52 operações na validação de 2025, mas falhou acerto, payoff e EV nos custos-base e estressado.

## Eventos e resultado da regra fixa

| Período | Custo/lado | Trades | Acerto | Payoff líquido | EV líquido/operação | DD adverso |
|---|---:|---:|---:|---:|---:|---:|
| Validação 2025 | 0,10% | 52 | 40,38% | 0,853 | -0,210% | 3,95% |
| Validação 2025 | 0,15% | 52 | 36,54% | 0,772 | -0,310% | 4,60% |
| Confirmação diagnóstica jan–ago/2026 | 0,10% | 27 | 62,96% | 1,188 | +0,225% | 0,85% |
| Confirmação diagnóstica jan–ago/2026 | 0,15% | 27 | 62,96% | 0,874 | +0,125% | 0,92% |

A confirmação permanece abaixo de 30 operações e não passa os gates de 70% de acerto e EV >1,2%; no custo estressado também falha payoff 1:1. Seu resultado positivo-base não foi usado para alterar 2025. Não é evidência de consistência.

## Regra avaliada e limites

A regra combinou RSI14, MACD(12,26,9), EMA200, faixa Fibonacci de quatro horas, volume e fluxo taker; entrada foi na abertura de minuto seguinte. A amostra de 2025 tinha 58 eventos pré-cooldown e a de 2026, 29. Stop ficou no extremo da faixa de quatro horas; alvo bruto 1,9R; risco permitido 1,5%–2,0%, prazo de 60 minutos. Funding foi incluído, sem alavancagem, chamadas Jev ou ordens reais.

O sinal lembra a ideia de indicadores em confluência, mas esta regra numérica falha na validação. A janela de confirmação foi consultada apenas para diagnóstico; os candles já eram conhecidos em outras granularidades, então nenhum corte representa holdout de mercado totalmente intocado.

- Protocolo congelado: [minute_indicator_confluence_protocol_2026-09-27.md](minute_indicator_confluence_protocol_2026-09-27.md).
- Relatório completo: `results/minute_indicator_confluence_20260927/research.json`.
- SHA-256 do código: `17729a886aeeb45e4ffc164cbe7083caa13125a248958554181ac25b67b1e4bf`.
- SHA-256 do protocolo: `52ff57207bbe1e2d5c032dd40308a2fcdeb8754455b139e78e3ac14eafdc456d`.
