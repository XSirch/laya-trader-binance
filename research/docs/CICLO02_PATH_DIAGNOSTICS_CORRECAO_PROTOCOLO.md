# Ciclo 02 — correção do diagnóstico de candles de saída

Pré-registro corretivo em 28/09/2026, antes de refazer a extração. A primeira extração, `cycle02_path_diagnostics_2026-09-28`, foi invalidada e seus arquivos são preservados só para auditoria: ela classificou `stop_gap` como candle completo, embora a saída ocorra na abertura e o caminho restante daquele minuto não seja observado. `target_gap` tem a mesma ambiguidade temporal.

## Congelamento da correção

- Reutilizar o mesmo relatório corrigido do Ciclo 02 (SHA-256 `3d0a1c6a3bf8e2275fd3f4444920a4c1f5a8f776b094283e316b5b20234e680d`), datasets/manifests, janela, 24 variantes e cenários base/stress registrados em [CICLO02_PATH_DIAGNOSTICS_PROTOCOLO.md](CICLO02_PATH_DIAGNOSTICS_PROTOCOLO.md).
- Classificar como candle de saída ambíguo todas as causas acionadas por OHLC intraminuto ou abertura: `stop`, `target`, `stop_gap`, `target_gap`. Não incluir seus extremos posteriores entre os candles completos anteriores à saída.
- `trend_ema21_loss` e `time_stop` permanecem saídas no fechamento; seu candle é conhecido no instante da saída.
- Nenhum parâmetro de estratégia, entrada, custo, sizing, janela ou gate muda. Sem treino, ajuste, escolha por EV ou ordens reais.
- Preservar a extração inválida; gravar a repetição em diretório novo `results/cycle02_path_diagnostics_corrected_2026-09-28/`.

O mesmo limite retrospectivo continua valendo: diagnósticos de trajetória formulam hipóteses, não demonstram rentabilidade nem constituem validação prospectiva.

## Comando

```powershell
research\.venv\Scripts\python.exe research\scripts\cycle02_path_diagnostics_corrected.py `
  --source-report research\results\cycle02_multiframe_corrected_2026-09-28\research.json `
  --expected-source-sha256 3d0a1c6a3bf8e2275fd3f4444920a4c1f5a8f776b094283e316b5b20234e680d `
  --expected-engine-sha256 6727aa9555d4ed48715c8d632e1a95531bdff28a67e19f106855d6701db5c207 `
  --output research\results\cycle02_path_diagnostics_corrected_2026-09-28
```
