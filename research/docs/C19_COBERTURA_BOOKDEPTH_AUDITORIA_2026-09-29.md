# Auditoria de cobertura do `bookDepth` — 2026-09-29

**Classificação:** verificação exploratória de disponibilidade e integridade de fonte, feita após a descoberta do arquivo. Não foi pré-registrada como experimento de desempenho; nenhum modelo, sinal ou trade foi calculado.

## Correção do inventário C19

A nota [C19 sobre microestrutura](C19_MICROESTRUTURA_PROFUNDIDADE_FONTES_2026-09-29.md) concluiu que o arquivo público histórico da Binance não documentava profundidade. Essa conclusão precisa de correção: embora o README atual do repositório [Binance Public Data](https://github.com/binance/binance-public-data) não liste `bookDepth`, arquivos diários USD-M estão acessíveis no domínio oficial `data.binance.vision`. O caminho foi localizado pelo relato público [issue #496](https://github.com/binance/binance-public-data/issues/496), que também alerta para uma anomalia nos arquivos. A amostra abaixo foi baixada diretamente do arquivo da Binance, junto com seu `.CHECKSUM`.

Todos os pedidos foram públicos e sem autenticação, para BTCUSDT USD-M. O padrão observado foi `https://data.binance.vision/data/futures/um/daily/bookDepth/BTCUSDT/BTCUSDT-bookDepth-YYYY-MM-DD.zip`. Cada arquivo examinado tinha 34.560 linhas: doze bandas percentuais, com 2.880 snapshots de 30 segundos por banda. As colunas são `timestamp`, `percentage`, `depth` e `notional`; isso é um resumo por bandas, não um feed de eventos por nível com alterações de fila.

| Data | SHA-256 do ZIP | Linhas | Valores distintos de `notional/depth` em +0,2% / +1% | `.CHECKSUM` |
|---|---|---:|---:|---|
| 2026-08-31 | `d2a4c3d4013de92bee8eddc2acf017e7fedcfa7730c915fbac488814b0a432a7` | 34.560 | 2.880 / 2.880 | confere |
| 2026-09-02 | `facd2e2378191fd59cc944de5b9080e95e40b03911b39f9be29d82f5e42485bb` | 34.560 | 2.880 / 2.880 | confere |
| 2026-09-06 | `215fe3b747e0a1cd52597b668c0a0270a9f35fedb4fb645fda0e4ce37694bf99` | 34.560 | 3 / 2 | confere |
| 2026-09-26 | `e8a5401ac1f2110aee2a3de4cf69981342d72fd5d78fcfc30f4aae70d8c9cd50` | 34.560 | 2.880 / 2.880 | confere |

Em 6 de setembro, as bandas ask mais próximas estavam quase congeladas em BTCUSDT, consistente com a anomalia descrita no issue #496; as demais bandas examinadas mantinham 2.880 valores distintos. A amostra de 26 de setembro não mostrou o mesmo congelamento nessas duas bandas. Como o issue ainda está aberto e só quatro dias de BTCUSDT foram medidos, isso não determina a duração nem a correção completa do defeito em todos os símbolos. Checksums conferem integridade de transferência, não validade econômica.

Pedidos `HEAD` adicionais retornaram HTTP 200 em datas selecionadas entre 2025-01-01 e 2026-09-27. Essa amostragem mostra que há arquivos em datas antigas, mas não prova cobertura diária contínua, disponibilidade de todos os pares, semântica completa das bandas ou ausência de outros defeitos. O próximo gate deve inventariar cobertura e validar os arquivos dia a dia para um único contrato/período, detectar bandas congeladas ou cruzadas e excluir qualquer segmento inválido antes de pré-registrar uma comparação de baseline contra baseline + `bookDepth`.

**Conclusão:** há uma fonte histórica pública candidata que não constava no README consultado, portanto coleta prospectiva deixa de ser a única via para estudar profundidade. A fonte é agregada a cada 30 segundos e teve ao menos uma anomalia recente observada; ainda não demonstra edge preditivo, EV líquido, payoff, acerto ou drawdown. Nenhuma estratégia foi treinada ou validada e nenhuma ordem foi enviada.

## Complemento: cobertura contínua e qualidade preliminar

Em nova checagem, os 56 objetos diários de 2026-07-01 a 2026-08-25 retornaram HTTP 200, cobrindo oito semanas corridas de BTCUSDT. Os 56 ZIPs foram baixados e seus `.CHECKSUM` conferiram. A verificação interna foi mais restritiva: 53 dos 56 arquivos tinham exatamente 2.880 timestamps distintos em cada uma das 12 bandas. Os outros três tinham menos linhas, igualmente em todas as bandas e sem timestamps duplicados: 2026-07-08 tinha 2.868 por banda (12 ausentes), 2026-07-18 tinha 2.879 (1 ausente) e 2026-07-21 tinha 2.866 (14 ausentes). Não houve linha com `depth <= 0` ou `notional < 0`, e nenhuma banda/dia teve menos de 1.000 valores distintos de `notional/depth` arredondado a seis casas.

Um teste de consistência marcou dois timestamps em 2026-08-19 em que o preço médio implícito da banda bid −0,2% ficou acima do da banda ask +0,2%: às `13:31:33`, 65.007,8123 contra 64.535,6000; às `15:28:02`, 70.197,4165 contra 69.875,7565. Como esses campos resumem bandas e não são as melhores cotações, isso não prova que o livro real estava cruzado, mas exige explicar a anomalia antes de confiar nas features. Assim, a disponibilidade histórica por oito semanas foi confirmada; a integridade sem ressalvas, não. A próxima etapa deve avaliar o efeito dos timestamps ausentes e esclarecer as duas divergências antes de qualquer protocolo de desempenho ou treinamento.

## Complemento: divergência com mark e decisão de uso — 29/09/2026

A checagem independente do arquivo oficial de 19/05/2025 encontrou uma divergência material sob a interpretação UTC do timestamp `2025-05-19 11:07:31`: `notional/depth` nas bandas publicadas ficou aproximadamente entre 82.098 e 85.498, enquanto os arquivos oficiais de mark-price klines de um minuto mostram fechamentos de 102.922,70 às 11:07 UTC e 102.841,96 às 11:08 UTC. Os dois arquivos passaram seus checksums. A diferença calculada é aproximadamente 16,9%–20,2% em relação ao mark. **O fuso do timestamp de `bookDepth` não foi confirmado**, portanto esse alinhamento não é uma prova temporal conclusiva. A magnitude reproduz o tipo de anomalia descrita por um usuário no [issue #431](https://github.com/binance/binance-public-data/issues/431), que permanece aberto; a issue é um relato de usuário, não uma explicação oficial. A questão sobre a geração e o significado dos campos também permanece sem resposta visível no [issue #447](https://github.com/binance/binance-public-data/issues/447), e a unidade de timestamp foi questionada no [issue #381](https://github.com/binance/binance-public-data/issues/381). Os status foram consultados em 29/09/2026.

Essa evidência muda a recomendação anterior de treinar depois de somente conferir cobertura e as inversões de agosto. Até que semântica, fuso e divergência sejam esclarecidos ou uma reconstrução independente valide esses valores em uma faixa ampla, não usar o `bookDepth` histórico de USD-M para features, rótulos, replay ou treinamento. Não foi demonstrado que todos os dias e bandas sejam incorretos; a fonte como um todo ainda não é confiável o bastante para fundamentar a estratégia. Checksums corretos não resolvem essa dúvida.

### Piloto exploratório do stream `bookTicker`

Em 29/09/2026, uma conexão pública de 30,02 segundos à rota `wss://fstream.binance.com/public/ws/btcusdt@bookTicker` recebeu 16.364 mensagens (545,12/s). O piloto observou zero regressões de `update_id`, zero cotações cruzadas e zero quantidades negativas. A projeção linear do JSON recebido é cerca de 7.331,61 MB/dia. Nenhum payload foi persistido, portanto isso só demonstra viabilidade de conexão e parsing por uma amostra curta; não demonstra continuidade, completude, qualidade econômica ou edge.

O percentil 50 da diferença entre horário de evento e relógio local foi −66 ms e o percentil 95 foi 181 ms. Como o valor negativo pode refletir desvio do relógio local, não usar latência como feature ou alvo até registrar e corrigir a incerteza de sincronização. A Binance anunciou as rotas USD-M separadas `/public`, `/market` e `/private` e a aposentadoria das rotas antigas em 23/04/2026 ([aviso oficial](https://www.binance.com/en/support/announcement/detail/ebf9b0aa9eca4ff3804eef6fb09ba32a)).

Um arquivo histórico diário de `bookTicker` de janeiro de 2024 foi localizado, mas não resolve a falta de histórico recente; uma issue pública também descreve linhas fora de sequência nesse tipo de arquivo ([issue #305](https://github.com/binance/binance-public-data/issues/305)). Não considerar esse arquivo de 2024 um substituto para avaliação prospectiva.

**Estado final de C19:** fonte histórica `bookDepth` disponível, mas desqualificada para uso quantitativo até revisão de semântica. A alternativa BBO ao vivo passou apenas um piloto exploratório de 30 segundos. Nenhum dado desse piloto foi guardado para treino, nenhum retorno foi calculado, nenhum modelo foi treinado e nenhuma ordem foi enviada. Uma coleta prospectiva agregada por segundo depende de protocolo e coletor congelados antes do início.
