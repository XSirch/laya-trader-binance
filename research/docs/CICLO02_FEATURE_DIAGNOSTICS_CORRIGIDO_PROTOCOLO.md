# Ciclo 02 — diagnóstico descritivo de features corrigidas

Registrado em 28/09/2026, antes de extrair importâncias. O objetivo é gerar hipóteses para pesquisa posterior, não medir vantagem financeira nem aprovar uma estratégia.

## Pergunta

Quais features os classificadores XGBoost corrigidos usaram em divisões de árvore, e quais aparecem de forma estável entre as três saídas registradas dentro de cada mercado/família/horizonte?

## Dados e procedimento congelados

- Fonte: relatório corrigido `results/cycle02_multiframe_corrected_2026-09-28/research.json`, SHA-256 `3d0a1c6a3bf8e2275fd3f4444920a4c1f5a8f776b094283e316b5b20234e680d`.
- Inspecionar somente os 24 classificadores XGBoost CUDA já ajustados nos períodos de treino. Não ajustar, calibrar, pontuar, selecionar threshold ou simular trades.
- Verificar cada SHA-256 do artefato de modelo antes de carregá-lo. Recusar fonte invalidada, saídas sem três hashes de labels distintos nos oito grupos ou qualquer modelo com hash divergente.
- Extrair ganho de split do classificador (`importance_type=gain`), ganho normalizado por modelo, ranking, contagem de features usadas, dispositivo e `tree_method`. Preservar métricas por modelo; sumarizar por mercado/família/horizonte, explicitando que as três saídas compartilham sinais candidatos e não são réplicas independentes.
- Interpretar apenas como descrição do ajuste ao treino. Ganho não informa direção do efeito, causalidade, estabilidade futura nem retorno. Features correlacionadas podem dividir ou duplicar importância; não selecionar regra nem alterar thresholds com este diagnóstico.
- Não reutilizar outputs de feature gain da primeira execução invalidada.
- Saída nova: `results/cycle02_corrected_feature_diagnostics_2026-09-28/`. Nenhum treino novo, pesquisa de performance ou ordem real.

## Registro de execução

Registrar hashes do protocolo, relatório, código e 24 modelos, contagem de modelos com divisões e configuração serializada dos boosters. Se aparecer padrão consistente entre os três exits, ele pode motivar uma hipótese separada; essa hipótese precisa de protocolo próprio antes de qualquer replay.

## Comando

```powershell
research\.venv\Scripts\python.exe research\scripts\cycle02_ml_pattern_diagnostics.py --source-report research\results\cycle02_multiframe_corrected_2026-09-28\research.json --expected-source-sha256 3d0a1c6a3bf8e2275fd3f4444920a4c1f5a8f776b094283e316b5b20234e680d --output research\results\cycle02_corrected_feature_diagnostics_2026-09-28
```
