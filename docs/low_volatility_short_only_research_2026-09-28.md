# Resultado: carteira short-only de baixa volatilidade

Este teste exploratório usa o mesmo HGB regressor, janela causal, limiar previsto de 1,2% do notional, custos e motor do filtro de EV. Remove as pernas long e aloca até 25% do patrimônio em posições short.

| Período | Custo/lado | Episódios | Acerto | Payoff | EV/trade | DD marcado | Gates |
|---|---:|---:|---:|---:|---:|---:|---|
| validation_2025h2 | 0.10% | 17 | 82.35% | 1.23 | 13.07% | 8.34% | fail |
| validation_2025h2 | 0.15% | 17 | 82.35% | 1.21 | 12.93% | 8.36% | fail |
| confirmation_2026 | 0.10% | 22 | 72.73% | 2.32 | 9.56% | 4.46% | fail |
| confirmation_2026 | 0.15% | 22 | 72.73% | 2.25 | 9.42% | 4.53% | fail |
| combined | 0.10% | 88 | 60.23% | 1.20 | 5.78% | 21.70% | fail |
| combined | 0.15% | 88 | 60.23% | 1.18 | 5.63% | 21.81% | fail |

## Decisão

A carteira short-only não passou todos os gates congelados. As janelas já foram inspecionadas para escolher a direção; mesmo uma aprovação seria somente geração de hipótese.
Nenhuma ordem real ou chamada JEV foi feita.

Protocolo SHA-256 `90bbf2f60d6494e83915463ad9687b7ebe193f298dc93d06c4a30d6635176399`; código `b4b3ececcda147e896dfe14129a8104287a6de2d1b9c52c5051410669862a413`; relatório EV de origem `d2da0b32606284897a3cbfcd46b5255a684714f19cf0f9e1ed747ea011872a9a`.
Ledger de episódios: `results/low_volatility_short_only_ledger_20260928.csv`.
