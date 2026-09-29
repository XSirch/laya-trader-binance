# Ciclo 02 — diagnóstico de trajetória das variantes corrigidas

Registro prospectivo do diagnóstico em 28/09/2026, antes de extrair trajetórias. A execução é post hoc na seleção histórica já observada: mede caminhos, não estima edge independente nem aprova estratégia.

## Escopo congelado

- Fonte: relatório corrigido do Ciclo 02, SHA-256 `3d0a1c6a3bf8e2275fd3f4444920a4c1f5a8f776b094283e316b5b20234e680d`, e os dados/labels cujos hashes constam nele.
- Implementação congelada antes da extração: `scripts/cycle02_path_diagnostics.py`, SHA-256 `c05c8fed7f9918976cba27147189e56882b9a08f36ef7ecf24787f1b74168552`; motor de execução `scripts/cycle02_multiframe_research.py`, SHA-256 `6727aa9555d4ed48715c8d632e1a95531bdff28a67e19f106855d6701db5c207`; testes `tests/test_cycle02_path_diagnostics.py`, SHA-256 `fbcb09d404b40e3480c0d61616878897f990e22962dacc7ae1bfa70860413dd4`.
- Universo: BTCUSDT e ETHUSDT, Binance Spot e Binance USD-M perpétuos, tratados separadamente.
- Avaliação: janela já vista `2026-01-02 00:00 UTC` até `2026-09-01 00:00 UTC` exclusiva, 24 variantes fixas (duas famílias, dois horizontes e três saídas por mercado), uma posição global por mercado, mesma regra de entrada, sizing e custos do replay corrigido.
- Cenários: execução-base e execução com taxa/slippage dobrados, extraídas separadamente. Não treinar, ajustar thresholds, selecionar parâmetros ou enviar ordens.
- Para cada operação executada, calcular MFE e MAE em unidades da distância inicial do stop, usando OHLC de preço e o preço de entrada efetivo. Separar excursões até candles completos anteriores à saída das excursões no candle de saída quando a saída intrabar foi por stop/alvo; esse candle permanece ambíguo e não é incorporado à medida de candles completos.
- Saídas `trend_ema21_loss` e `time_stop` ocorrem no fechamento do candle; esse candle é completo no instante da decisão de saída. Relatar MFE/MAE separadamente para esse caminho conhecido.
- Registrar motivo e duração da saída, retorno líquido, custos estimados de taxa/slippage como fração do risco inicial e funding assinado separado. MFE/MAE são diagnósticos futuros, nunca features de entrada.
- Resumir vencedores e perdedores por variante e cenário; não agregar variantes, horizontes, saídas, mercados, cenários ou trades repetidos para cumprir gates.

## Interpretação e limite

O diagnóstico serve apenas para formular uma hipótese de saída ou custo. Não ajustar uma nova regra sobre este mesmo bloco e apresentá-la como validação. Qualquer replay posterior precisa de protocolo próprio, gates Rev02 registrados e classificação retrospectiva explícita. Resultados de P0 anteriores não substituem esta extração porque cobrem outras operações.

## Comando

```powershell
research\.venv\Scripts\python.exe research\scripts\cycle02_path_diagnostics.py `
  --source-report research\results\cycle02_multiframe_corrected_2026-09-28\research.json `
  --expected-source-sha256 3d0a1c6a3bf8e2275fd3f4444920a4c1f5a8f776b094283e316b5b20234e680d `
  --expected-engine-sha256 6727aa9555d4ed48715c8d632e1a95531bdff28a67e19f106855d6701db5c207 `
  --output research\results\cycle02_path_diagnostics_2026-09-28
```
