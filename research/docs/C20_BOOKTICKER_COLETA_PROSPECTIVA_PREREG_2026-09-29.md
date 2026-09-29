# C20 — captura prospectiva de `bookTicker` USD-M

**Registrado em:** 29/09/2026 02:43 UTC  
**Tipo:** protocolo de qualificação de fonte; não é experimento de estratégia  
**Estado:** pré-registrado documentalmente; coletor não implementado e coleta não iniciada  
**Risco:** somente dados públicos, sem credenciais de conta e sem endpoints de ordem

## Pergunta e limite

É possível capturar continuamente o melhor bid/ask de BTCUSDT USD-M com qualidade temporal e de conteúdo suficiente para planejar uma futura avaliação de sinais de microestrutura? C20 mede apenas a fonte e o armazenamento. Não calcula sinais, rótulos, EV, acerto, payoff, drawdown ou qualquer estatística de trading.

O teste exploratório anterior de 30,02 segundos não entra na série. Nenhum payload foi persistido. As mensagens desse teste não podem ser recuperadas para compor treino ou validação.

## Fonte e universo congelados

- Instrumento único: `BTCUSDT` perpétuo USD-M.
- Stream: `btcusdt@bookTicker`, pela rota pública `wss://fstream.binance.com/public/ws/btcusdt@bookTicker`.
- A rota `/public` pertence à arquitetura WebSocket USD-M anunciada pela Binance para tráfego público de alta frequência; as rotas legadas foram retiradas em 23/04/2026. Referência: [aviso oficial da Binance](https://www.binance.com/en/support/announcement/detail/ebf9b0aa9eca4ff3804eef6fb09ba32a).
- Somente leitura pública. O coletor não terá configuração, segredo ou código para enviar, substituir ou cancelar ordens.
- Não combinar Spot, outros contratos ou outros símbolos nesta série.

## Janela proposta e integridade

A coleta começará somente depois que código, ambiente, schema, hashes e relógio forem revisados e registrados. O instante de início `T0` será escrito no ledger antes da primeira conexão. A janela máxima será de 112 dias corridos desde `T0`; não preencher períodos anteriores com dados históricos diferentes. O piloto de 30 segundos foi apenas de viabilidade e não define `T0`.

O coletor manterá a última cotação recebida em cada segundo UTC e produzirá uma linha por segundo, incluindo segundos sem atualização. Isso limita qualquer avaliação posterior a decisões em intervalos de pelo menos um segundo; C20 não permitirá alegações sobre execução intrassegundo ou prioridade na fila. Cada linha ou bloco diário deve permitir distinguir conexão ativa, cotação fresca, atraso, reinício, erro de parse e lacuna. Lacunas não serão interpoladas nem atravessadas em retornos futuros.

Campos mínimos planejados: segundo UTC; tempos `E` e `T` do evento quando presentes; relógio UTC e monotônico de recebimento; `update_id`; bid/quantidade bid; ask/quantidade ask; contagem de mensagens no segundo; spread em pontos-base; mid; desvio do microprice em relação ao mid; desequilíbrio de quantidades; estado de conexão e qualidade do relógio. Valores derivados serão calculados somente depois de preservar os campos recebidos. Cada arquivo diário terá hash SHA-256 e entrará em uma cadeia de manifesto append-only.

O relógio do host será sincronizado antes da captura e seu offset em relação ao horário público da Binance será observado durante a coleta. Se o offset absoluto ultrapassar 100 ms, marcar o intervalo como `clock_unqualified`; não usar latência local como feature. Guardar separadamente tempo de evento e de recebimento. Não inferir que um timestamp negativo de latência seja antecipação real do feed.

## Gates de qualidade da série

Os gates abaixo são para a fonte, não para rentabilidade:

1. Para cada dia UTC, medir as 86.400 amostras esperadas. Uma amostra só conta como válida se a conexão e o parse estiverem íntegros, bid e ask forem positivos, quantidades forem não negativas, `bid <= ask` e a última mensagem tiver no máximo cinco segundos.
2. Um dia só será classificado como completo se pelo menos 99% dos segundos forem válidos. Dias abaixo do corte permanecem no relatório de cobertura como incompletos; não remover silenciosamente os intervalos ruins.
3. Registrar toda regressão, duplicidade ou salto de `update_id`, quote cruzada, mensagem inválida, desconexão, reinício e desvio de relógio. O teste de 30 segundos sem ocorrências não relaxa esses controles.
4. Não gerar retorno ou rótulo em uma janela que cruze segundo inválido, período sem conexão ou intervalo sem relógio qualificado quando a variável depender de latência.
5. O piloto de qualificação será considerado suficiente apenas se pelo menos 13 dos primeiros 14 dias forem completos e nenhum defeito de parse, ordenação, armazenamento ou hash ficar sem explicação. Se falhar, parar o projeto C20 e documentar a causa; não trocar o símbolo ou reduzir o gate dentro da mesma série.

Mesmo após passar a qualificação, a série só demonstra disponibilidade e integridade operacional; não demonstra informação preditiva ou desempenho econômico.

## Separação de pesquisa e condição para ML

Se a coleta continuar após a qualificação, as primeiras oito semanas serão o bloco de desenvolvimento/calibração e as oito semanas seguintes serão reservadas como teste cronológico. Nenhum resultado econômico do bloco final poderá ser usado para escolher variáveis, modelo, threshold, entrada, saída ou abstenção. Falha ou insuficiência de coleta não poderá ser suprida por reamostragem de trades, eventos sobrepostos, outros mercados ou dados sintéticos.

Antes de calcular qualquer rótulo de estratégia, abrir um protocolo sucessor que fixe a regra de oportunidade, os preços de execução bid/ask, saída, horizonte, funding, taxas, slippage, sizing, abstenção e orçamento máximo de modelos/limiares. O uso de GPU/XGBoost ou outro estimador, baseline sem ML e regra de abstenção será registrado nesse protocolo sucessor; C20, isoladamente, não autoriza treinamento.

O teste de estratégia futuro terá de aplicar os critérios vigentes por variante e mercado: EV líquido estritamente maior que 1,2%, payoff ao menos 1:1, profit factor ao menos 1,25, 200 trades completos não duplicados e ao menos oito semanas ativas, PnL agregado positivo com taxas e slippage dobrados e drawdown medido/minimizado sem teto fixo. Aproximar 70% de acerto é preferência. Se qualquer gate não passar, a candidata é reprovada; nenhum resultado de C20 autoriza ordens reais.

## Estado de execução

Na data do registro, não existe implementação, tarefa agendada ou arquivo de captura de C20. Nenhuma coleta foi iniciada nesta execução documental. O próximo passo, antes de abrir o stream, é implementar e revisar o agregador e comparar seu parser com mensagens públicas reais sem persistir uma série de desempenho. C18 deve permanecer sem alteração.
