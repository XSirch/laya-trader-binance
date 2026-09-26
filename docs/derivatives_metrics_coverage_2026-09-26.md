# Cobertura do arquivo de métricas de derivativos

O catálogo público contém pares ZIP/checksum para todas as **4.896 combinações de ativo e sexta-feira anteriores às respectivas liquidações automáticas**, dentro da janela fixa de 03/12/2021 a 18/09/2026. Isso permite uma aquisição semanal sem escolher datas pela presença dos arquivos. Esta etapa verificou metadados; não baixou ZIPs, validou conteúdo dos CSVs nem executou estratégia.

Foram consultadas 80 páginas do [catálogo público da Binance](https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?prefix=data%2Ffutures%2Fum%2Fdaily%2Fmetrics%2FBTCUSDT%2F&max-keys=1000), entre 21:36:54 e 21:37:50 UTC de 26/09/2026, com até quatro workers. O cohort preserva os 20 ativos históricos de janeiro de 2021. As páginas contêm 69.962 objetos, incluindo as datas de BTC anteriores ao início da janela solicitada.

## Calendários completos

A janela diária de 01/12/2021 a 25/09/2026 contém 1.760 datas por ativo, totalizando 35.200. Foram encontrados 34.525 pares, com 388.468.214 bytes de ZIPs indicados no catálogo. Não há ZIPs sem checksum nem checksums sem ZIP nessa janela. Essa comparação usa todas as datas esperadas, sem estreitar a janela ao primeiro ou último arquivo observado.

A janela de sextas-feiras contém 251 datas por ativo, totalizando 5.020. Há 4.925 pares brutos, cujos ZIPs somam 55.418.709 bytes. Desses, 29 correspondem a datas posteriores à liquidação automática do respectivo contrato. Retiradas essas datas do calendário de pesquisa, restam 4.896 pares em 4.896 datas esperadas. O calendário semanal evita três lacunas diárias, sem alterar sua definição após observar os arquivos.

| Ativo | Pares diários / 1.760 | Pares de sexta / 251 | Sextas posteriores à liquidação |
| --- | ---: | ---: | ---: |
| BTCUSDT | 1.760 | 251 | 0 |
| ETHUSDT | 1.760 | 251 | 0 |
| XRPUSDT | 1.760 | 251 | 0 |
| LINKUSDT | 1.760 | 251 | 0 |
| LTCUSDT | 1.760 | 251 | 0 |
| DOGEUSDT | 1.760 | 251 | 0 |
| DOTUSDT | 1.760 | 251 | 0 |
| BCHUSDT | 1.760 | 251 | 0 |
| XLMUSDT | 1.759 | 251 | 0 |
| ADAUSDT | 1.760 | 251 | 0 |
| EOSUSDT | 1.332 | 190 | 9 |
| UNIUSDT | 1.760 | 251 | 0 |
| SUSHIUSDT | 1.760 | 251 | 0 |
| YFIUSDT | 1.760 | 251 | 0 |
| BNBUSDT | 1.760 | 251 | 0 |
| TRXUSDT | 1.760 | 251 | 0 |
| CRVUSDT | 1.760 | 251 | 0 |
| MKRUSDT | 1.515 | 217 | 20 |
| AAVEUSDT | 1.760 | 251 | 0 |
| GRTUSDT | 1.759 | 251 | 0 |

As três ausências anteriores ou no dia da liquidação são **XLMUSDT em 13/12/2023, GRTUSDT em 16/12/2023 e EOSUSDT em 18/12/2023**. As outras 672 ausências de pares diários estão em datas posteriores aos eventos conhecidos de EOS e MKR. A classificação indica posição no calendário, sem atribuir causa à ausência.

## Arquivos posteriores à liquidação

Há 65 dias pareados de EOS após 21/05/2025 e 137 de MKR após 08/09/2025. O último ZIP de EOS tem data econômica de 05/05/2026, e o de MKR, 23/01/2026. A existência desses objetos não demonstra que os contratos originais continuaram negociáveis nem identifica a natureza das observações. Nenhum desses arquivos deve reativar automaticamente um ativo retirado pela política de ciclo de vida.

Os horários e fontes dos eventos permanecem em [contract_lifecycle_sources_2026-09-26.json](contract_lifecycle_sources_2026-09-26.json). Para separar as ausências, somente datas estritamente posteriores à data UTC da liquidação foram classificadas como posteriores; o próprio dia do evento continua explícito no grupo restante. Como ambos os eventos ocorreram fora de uma sexta-feira, essa convenção não afeta os 4.896 pares semanais anteriores à liquidação. A aquisição e o replay devem também respeitar o momento da decisão, os horários intradiários e a publicação do evento.

## Evidência e reprodução

Cada página XML original foi preservada em `data/binance/metrics_catalog/{SYMBOL}/`, acompanhada de URL completa, instante de consulta, tamanho e SHA-256. O parser verifica prefixo, marcador de paginação, ordem das chaves, metadados e avanço do próximo marcador. Uma retomada verifica os hashes das páginas existentes e busca somente páginas ainda ausentes; arquivos verificados não são sobrescritos. Metadados por objeto preservam `Key`, `Size`, `LastModified` e `ETag`.

O arquivo integral `data/binance/metrics_catalog/coverage.json` possui 5.036.775 bytes e SHA-256:

```text
9ce943cc7d8ca0946ab4938d5931775ddefefb0fac949b0e94f193369eab7444
```

O [JSON versionado](derivatives_metrics_coverage_2026-09-26.json) é uma projeção declarada de 134.956 bytes. Preserva contagens, todas as datas sem pares, referências e hashes das páginas, além do hash do relatório integral. Omite as listas de datas pareadas e os candidatos de download que podem ser reconstruídos dos catálogos locais.

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -p test_metrics_catalog.py -v
.venv\Scripts\python.exe -m jev_trader.metrics_catalog --workers 4
```

`load_catalog(symbol)` entrega o mapa `objects` e suas `raw_sources`. `weekly_candidates(catalog)` entrega as sextas pareadas com `symbol`, `date`, `zip` e `checksum`; a seleção de elegibilidade por ciclo de vida cabe ao consumidor. A segunda execução usa as mesmas páginas verificadas e reproduz os relatórios sem nova consulta de rede.

`LastModified` e `ETag` descrevem a versão atual do objeto. Não comprovam primeira publicação histórica, imutabilidade desde a data econômica, integridade do conteúdo do ZIP ou equivalência dos campos ao REST. Essas limitações permanecem no [inventário das métricas](derivatives_metrics_inventory_2026-09-26.md). A cobertura não demonstra vantagem preditiva nem cumprimento da meta de 50% líquidos ao ano com drawdown de até 10%.
