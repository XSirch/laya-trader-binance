# Resultado: stops e alvos no candidato short-only

O replay usa somente as previsões e decisões semanais já gravadas; o HGB não foi retreinado. O controle sem barreiras reproduziu o relatório e o ledger short-only publicados antes do grid. Nenhuma chamada externa ou ordem real foi feita.

O custo base combina 5 bps de taxa e 5 bps de slippage adverso por lado. O stress vigente dobra ambos para 20 bps por lado. O replay de origem usava 15 bps no stress; esse custo foi repetido somente para reconciliar aquele ledger. O motor não modela margem de manutenção, liquidação nem proteção de preço da corretora.

| Período | Regra | N base | Acerto | Payoff | PF | EV/op. base | Retorno base | Retorno stress 2x | DD marcado | Limite adverso | Semanas | Gates numéricos |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| validation_2024 | no_barrier_control | 39 | 51.28% | 1.06 | 0.91 | 0.99% | -2.60% | -3.45% | 21.66% | 22.35% | 53 | fail |
| validation_2024 | stop_4_target_1.2R | 157 | 36.94% | 1.08 | 0.61 | -0.97% | -12.96% | -15.26% | 12.96% | 13.80% | 53 | fail |
| validation_2024 | stop_4_target_1.5R | 156 | 34.62% | 1.37 | 0.68 | -0.76% | -11.17% | -13.49% | 11.17% | 12.03% | 53 | fail |
| validation_2024 | stop_6_target_1.2R | 151 | 53.64% | 1.11 | 1.18 | 0.81% | 7.11% | 4.42% | 5.80% | 6.57% | 53 | fail |
| validation_2024 | stop_6_target_1.5R | 148 | 51.35% | 1.37 | 1.34 | 1.36% | 14.39% | 11.57% | 6.48% | 6.71% | 53 | fail |
| validation_2024 | stop_8_target_1.2R | 143 | 55.94% | 1.09 | 1.28 | 1.41% | 14.02% | 11.29% | 8.99% | 9.24% | 53 | fail |
| validation_2024 | stop_8_target_1.5R | 139 | 53.24% | 1.27 | 1.36 | 1.75% | 18.65% | 15.87% | 8.46% | 9.17% | 53 | fail |
| validation_2024 | stop_10_target_1.2R | 132 | 56.06% | 1.08 | 1.26 | 1.64% | 14.49% | 11.93% | 11.50% | 12.41% | 53 | fail |
| validation_2024 | stop_10_target_1.5R | 123 | 51.22% | 1.33 | 1.29 | 1.89% | 16.24% | 13.79% | 9.90% | 10.68% | 53 | fail |
| calibration_2025h1 | no_barrier_control | 18 | 50.00% | 0.96 | 1.12 | -0.57% | 2.78% | 2.31% | 19.39% | 20.10% | 25 | fail |
| calibration_2025h1 | stop_4_target_1.2R | 64 | 34.38% | 1.08 | 0.52 | -1.20% | -8.22% | -9.37% | 10.47% | 12.72% | 25 | fail |
| calibration_2025h1 | stop_4_target_1.5R | 64 | 31.25% | 1.33 | 0.57 | -1.15% | -7.74% | -8.89% | 11.26% | 13.49% | 25 | fail |
| calibration_2025h1 | stop_6_target_1.2R | 64 | 40.62% | 1.07 | 0.76 | -0.98% | -5.48% | -6.67% | 8.76% | 10.60% | 25 | fail |
| calibration_2025h1 | stop_6_target_1.5R | 64 | 35.94% | 1.32 | 0.79 | -1.03% | -5.08% | -6.27% | 10.38% | 12.19% | 25 | fail |
| calibration_2025h1 | stop_8_target_1.2R | 62 | 38.71% | 1.09 | 0.76 | -1.55% | -7.23% | -8.37% | 14.76% | 16.05% | 25 | fail |
| calibration_2025h1 | stop_8_target_1.5R | 60 | 33.33% | 1.30 | 0.64 | -1.91% | -11.29% | -12.34% | 14.02% | 15.33% | 25 | fail |
| calibration_2025h1 | stop_10_target_1.2R | 56 | 42.86% | 1.04 | 0.70 | -1.26% | -9.90% | -10.92% | 13.53% | 14.96% | 25 | fail |
| calibration_2025h1 | stop_10_target_1.5R | 55 | 43.64% | 1.24 | 0.85 | -0.23% | -4.89% | -5.94% | 11.36% | 14.13% | 25 | fail |
| validation_2025h2 | no_barrier_control | 17 | 82.35% | 1.23 | 6.24 | 13.07% | 20.90% | 20.38% | 8.34% | 9.72% | 26 | fail |
| validation_2025h2 | stop_4_target_1.2R | 66 | 43.94% | 1.09 | 0.86 | -0.34% | -2.13% | -3.40% | 4.47% | 6.58% | 26 | fail |
| validation_2025h2 | stop_4_target_1.5R | 65 | 41.54% | 1.35 | 0.98 | -0.11% | -0.36% | -1.64% | 3.90% | 6.03% | 26 | fail |
| validation_2025h2 | stop_6_target_1.2R | 62 | 51.61% | 1.10 | 1.19 | 0.52% | 3.44% | 2.18% | 4.74% | 6.58% | 26 | fail |
| validation_2025h2 | stop_6_target_1.5R | 59 | 45.76% | 1.36 | 1.15 | 0.48% | 2.91% | 1.70% | 4.73% | 5.54% | 26 | fail |
| validation_2025h2 | stop_8_target_1.2R | 56 | 58.93% | 1.08 | 1.57 | 1.78% | 10.51% | 9.28% | 4.68% | 5.47% | 26 | fail |
| validation_2025h2 | stop_8_target_1.5R | 53 | 54.72% | 1.30 | 1.57 | 2.04% | 10.94% | 9.76% | 4.68% | 5.47% | 26 | fail |
| validation_2025h2 | stop_10_target_1.2R | 53 | 62.26% | 1.03 | 1.66 | 2.54% | 13.07% | 11.87% | 5.71% | 6.27% | 26 | fail |
| validation_2025h2 | stop_10_target_1.5R | 49 | 59.18% | 1.27 | 1.74 | 3.29% | 14.82% | 13.69% | 5.71% | 6.27% | 26 | fail |
| confirmation_2026 | no_barrier_control | 22 | 72.73% | 2.32 | 5.45 | 9.56% | 20.41% | 19.69% | 4.47% | 5.71% | 30 | fail |
| confirmation_2026 | stop_4_target_1.2R | 65 | 36.92% | 1.05 | 0.55 | -1.07% | -8.43% | -9.72% | 9.52% | 10.06% | 29 | fail |
| confirmation_2026 | stop_4_target_1.5R | 65 | 32.31% | 1.28 | 0.54 | -1.15% | -9.17% | -10.46% | 10.84% | 11.20% | 29 | fail |
| confirmation_2026 | stop_6_target_1.2R | 60 | 48.33% | 0.93 | 0.87 | -0.45% | -2.78% | -4.06% | 10.65% | 11.37% | 29 | fail |
| confirmation_2026 | stop_6_target_1.5R | 60 | 46.67% | 1.05 | 0.95 | -0.32% | -1.24% | -2.54% | 10.31% | 11.04% | 29 | fail |
| confirmation_2026 | stop_8_target_1.2R | 52 | 57.69% | 0.99 | 1.45 | 1.17% | 8.18% | 6.94% | 5.53% | 6.13% | 29 | fail |
| confirmation_2026 | stop_8_target_1.5R | 47 | 55.32% | 1.11 | 1.52 | 1.37% | 9.40% | 8.23% | 6.09% | 6.70% | 29 | fail |
| confirmation_2026 | stop_10_target_1.2R | 43 | 67.44% | 0.95 | 2.08 | 2.93% | 15.56% | 14.42% | 5.09% | 5.55% | 29 | fail |
| confirmation_2026 | stop_10_target_1.5R | 40 | 65.00% | 1.16 | 2.31 | 3.77% | 19.34% | 18.25% | 4.59% | 5.04% | 29 | fail |
| combined | no_barrier_control | 88 | 60.23% | 1.20 | 1.75 | 5.78% | 43.08% | 39.92% | 21.66% | 22.48% | 135 | diagnóstico |
| combined | stop_4_target_1.2R | 356 | 37.64% | 1.09 | 0.62 | -0.91% | -28.61% | -33.24% | 29.46% | 29.88% | 134 | diagnóstico |
| combined | stop_4_target_1.5R | 354 | 34.46% | 1.36 | 0.67 | -0.79% | -26.21% | -30.96% | 27.56% | 27.86% | 134 | diagnóstico |
| combined | stop_6_target_1.2R | 341 | 48.97% | 1.09 | 1.01 | 0.15% | 0.65% | -5.59% | 13.76% | 14.47% | 134 | diagnóstico |
| combined | stop_6_target_1.5R | 335 | 45.37% | 1.34 | 1.07 | 0.38% | 8.61% | 1.97% | 12.59% | 13.12% | 134 | diagnóstico |
| combined | stop_8_target_1.2R | 316 | 52.53% | 1.11 | 1.22 | 0.86% | 28.11% | 20.69% | 16.69% | 17.38% | 134 | diagnóstico |
| combined | stop_8_target_1.5R | 300 | 48.00% | 1.32 | 1.21 | 0.92% | 27.46% | 20.38% | 16.73% | 17.42% | 134 | diagnóstico |
| combined | stop_10_target_1.2R | 285 | 54.74% | 1.06 | 1.25 | 1.29% | 33.52% | 26.43% | 17.75% | 18.22% | 134 | diagnóstico |
| combined | stop_10_target_1.5R | 267 | 51.69% | 1.30 | 1.38 | 1.86% | 51.57% | 43.96% | 15.71% | 16.20% | 134 | diagnóstico |

## Leitura

Nenhuma regra passa os gates em uma janela individual. O maior fold tem 157 operações; todas ficam abaixo das 200 exigidas. No combinado, apenas stop_10_target_1.2R, stop_10_target_1.5R satisfaz os números, mas esse agregado é apenas diagnóstico e não pode ser usado para somar folds. A calibração H1/2025 tem EV-base negativo em todas as variantes. A direção e as janelas já foram observadas, então nenhum resultado histórico constitui confirmação independente.

Conclusão: o grid não validou uma estratégia consistente. Os resultados justificam encerrar a seleção retrospectiva e, se a hipótese continuar relevante, congelar uma única regra para coleta prospectiva em paper. Não houve ordem real.

Reconciliação do controle: 10 pares período/custo passaram no relatório e ledger de origem. Protocolo SHA-256 `1c85a69fc7198d4e699e55d81ceb60034bc7dd48f6f579949f22cf79b2423d64`; código `d83ba23017a37684c8e4b3f5b76ffba0d3c6691d2587fbac855db669e05c958e`; ledger de episódios `results/low_volatility_short_brackets_ledger_20260928.csv`.
