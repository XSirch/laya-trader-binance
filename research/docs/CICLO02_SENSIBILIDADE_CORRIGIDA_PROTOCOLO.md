# Ciclo 02 — sensibilidade corrigida de threshold

Registrado em 28/09/2026, antes de executar o replay. Esta análise usa os modelos e rótulos do treino corrigido; não é uma nova estratégia nem validação independente.

## Hipótese e motivo

O grid principal corrigido, de 0,35 a 0,80, deixou no máximo 99 trades por modelo/threshold. A faixa de 0,05 a 0,30 pode ampliar a cobertura, mas talvez aumente falsos positivos e custo. A sensibilidade da primeira execução usou saídas ligadas incorretamente e foi invalidada; portanto, ela não constitui evidência repetida válida.

## Protocolo congelado

- Universo: Binance Spot e futuros perpétuos USD-M, BTCUSDT e ETHUSDT, avaliados separadamente.
- Fonte congelada: `results/cycle02_multiframe_corrected_2026-09-28/research.json`, SHA-256 `3d0a1c6a3bf8e2275fd3f4444920a4c1f5a8f776b094283e316b5b20234e680d`.
- Reutilizar os 48 modelos já ajustados, as 24 variantes de rótulos com hash conferido, custos, funding, sizing, filtros, entradas, saídas, cortes temporais e avaliações base/stress. Não treinar nem recalibrar.
- Única mudança: limiar mínimo de probabilidade em `{0.05, 0.10, 0.15, 0.20, 0.25, 0.30}`. O grid principal já cobriu 0,35–0,80; 0,35 não será repetido. `minimum_expected_r=0.05` permanece inalterado.
- Escopo: 48 modelos × 6 thresholds = 288 combinações, com um portfólio separado por mercado/modelo/threshold e sem somar trades concorrentes.
- Aplicar todos os gates registrados: EV líquido >1,2%, payoff ≥1, profit factor ≥1,25, pelo menos 200 trades completos em oito semanas ativas, e stress integral positivo com payoff ≥1. O acerto perto de 70% é preferência; drawdown não tem teto.
- Manter a janela histórica de seleção do relatório corrigido. Os thresholds são pós-hoc nesta mesma janela; qualquer resultado é exploratório, não holdout, paper aprovado ou evidência prospectiva.
- Interromper se o relatório fonte estiver invalidado, hashes de modelos/rótulos divergirem, faltarem variantes/modelos, ou os modos de saída não tiverem três hashes distintos por grupo.
- Saída: `results/cycle02_corrected_threshold_sensitivity_2026-09-28/research.json`. Nenhuma ordem real.

## Registro e critérios de leitura

Registrar SHA-256 do protocolo, código de replay, relatório fonte, modelos, rótulos e resultado. Reportar por mercado/modelo/threshold todas as métricas e gates; usar resultados abaixo do gate apenas para diagnóstico da relação entre cobertura, EV e custos. Não escolher um vencedor retrospectivo para paper.

## Comando

Após adaptar o replay para aceitar explicitamente o relatório corrigido e a pasta de saída nova:

```powershell
research\.venv\Scripts\python.exe research\scripts\cycle02_threshold_sensitivity.py --source-report research\results\cycle02_multiframe_corrected_2026-09-28\research.json --expected-source-sha256 3d0a1c6a3bf8e2275fd3f4444920a4c1f5a8f776b094283e316b5b20234e680d --output research\results\cycle02_corrected_threshold_sensitivity_2026-09-28 --thresholds 0.05,0.10,0.15,0.20,0.25,0.30
```
