# Binance MultiStrategy — proposta de pesquisa após o Ciclo 12

Data: 28/09/2026.
Status: proposta adicional; nenhum código, treinamento, replay, coleta, ordem ou alteração no repositório foi executado nesta revisão.

## 1. Base e escopo

Esta proposta usa o arquivo `Markdown colado.md` enviado pelo usuário, que consolida resultados até o Ciclo 12. O título do arquivo menciona Ciclo 6, mas as seções finais registram C11 e C12. Os relatórios vinculados, CSVs e códigos locais não foram inspecionados nesta revisão. Os resultados abaixo são os reportados, não uma reprodução independente.

O usuário confirmou que os parâmetros do relatório prevalecem sobre versões antigas dos handoffs. Não restaurar critérios antigos nem exigir Laya/Jev para a próxima etapa.

### Critérios preservados

| Critério | Política vigente |
|---|---|
| EV-base | Média do retorno líquido por trade sobre o nocional inicial estritamente superior a 1,2%. |
| Payoff-base | Pelo menos 1:1. |
| Profit factor-base | Pelo menos 1,25. |
| Amostra | Pelo menos 200 trades completos, não duplicados, em pelo menos oito semanas ativas, por variante e mercado. |
| Stress | PnL agregado positivo com taxas e slippage dobrados; funding observado permanece em USD-M. As demais métricas de stress são diagnósticos. |
| Acerto | Próximo a 70% é preferência, não piso rígido. |
| Drawdown | Sem teto fixo; medir e minimizar entre aprovados. |
| Alocação | Fracionária; preservar os limites de risco/alocação efetivamente autorizados e registrar os valores usados. Não aumentar exposição para atingir metas. |
| Consolidação | Não juntar folds, backends, mercados ou cenários de custos para fabricar as 200 operações. |
| Execução | Nenhuma aprovação histórica ou paper autoriza ordens reais automaticamente. |

Duzentos trades em pelo menos oito semanas não significa duzentos a cada oito semanas. Uma janela mais longa pode ser necessária. Também não significa que 200 trades distintos sejam estatisticamente independentes: reportar dependência por episódio, período e ativo.

## 2. O que não repetir como se fosse novidade

A P0 de contabilidade/custos e o funil já foram concluídos segundo o relatório. Não iniciar outra auditoria genérica sem indício novo.

Foram testados: saídas corrigidas, horizontes multitemporais, cortes de score, custo/stop, regressão direta, refit mensal, scanner de um minuto, stop ATR15m, cooldown, pesos por unicidade, primeiro cruzamento do canal, rank_blend e concorrência entre BTC/ETH.

O C06 permanece apenas como controle exploratório: 11 trades, EV-base +1,262%, payoff 10,17, PF 4,35, drawdown 2,39% e PnL stress +US$ 380,50. Retirar os dois maiores ganhos leva o EV a -0,136%. Isso não aprova o modelo nem estabelece que seu único defeito é a frequência.

C12 reproduziu as mesmas 11 operações ao permitir BTC e ETH simultaneamente. Não insistir nessa alteração para aumentar amostra. C08 melhorou métricas de previsão sem gerar entradas: melhora de MAE não equivale a melhora econômica.

## 3. Primeiro trabalho: teste de capacidade do conjunto de oportunidades

### Pergunta

Antes de outro treinamento, o conjunto de candidatos, com uma política de saída fixa, contém retornos suficientes para sequer comportar EV >1,2% com pelo menos 200 trades?

### Limite superior otimista — diagnóstico retrospectivo, não estratégia

Executar apenas em dados de desenvolvimento já examinados, separadamente por variante, mercado e janela. Não abrir um holdout reservado para fazer este diagnóstico.

1. Reunir todos os candidatos daquela política, inclusive os rejeitados pelo ML, com desfechos maduros e retornos líquidos reproduzíveis.
2. Eliminar cópias idênticas do mesmo evento/política. Não misturar diferentes saídas para escolher a melhor de cada trade retrospectivamente.
3. Se houver menos de 200 candidatos, registrar insuficiência do conjunto; não fabricar amostra com cópias ou sinais sobrepostos.
4. Ordenar os retornos líquidos por nocional do maior para o menor e calcular a média dos 200 maiores.
5. Inicialmente, permitir até candidatos temporalmente incompatíveis. Isso torna o resultado excessivamente favorável e, portanto, um limite superior relaxado, não um portfólio executável.

Para pelo menos 200 retornos fixos e finitos, com todos na mesma unidade:

```python
returns_sorted = sorted(net_returns, reverse=True)
upper_bound_ev_200 = sum(returns_sorted[:200]) / 200
```

Antes do cálculo, validar que há pelo menos 200 observações e que nenhuma é ausente ou não finita. O EV de 1,2% corresponde a 0,012 quando os retornos estão em frações.

Nenhum subconjunto de pelo menos 200 desses retornos fixos pode ter média maior que essa média dos 200 maiores. Impor não sobreposição, oito semanas ativas, saldo e posições só reduz o conjunto de escolhas possíveis.

### Interpretação correta

- Se o limite superior for <=1,2%, nenhum filtro consegue aprovar o gate de EV/amostra com aquele conjunto de retornos fixos. Mudar modelo, seed ou score não resolve esse caso. É preciso mudar oportunidades, dados, horizonte ou política — e tratar isso como novo experimento.
- Se for >1,2%, só foi demonstrado que existe capacidade retrospectiva em uma seleção excessivamente favorável. Não se demonstrou capacidade de prever, executar, diversificar ou passar stress/payoff/PF.
- O diagnóstico não prova impossibilidade em outros períodos, ativos ou estratégias.
- A validade depende de retornos por candidato fixos sob a política avaliada. Se execução, impacto, custos não lineares, saídas ou interações de carteira mudarem o retorno de cada evento, documentar essa limitação e não apresentar o limite como teorema sobre o simulador completo.
- Não usar MFE como retorno capturável, não adotar a melhor saída futura, não preencher rótulos desconhecidos com zero e não apresentar seleção com conhecimento do futuro como trading real.

Saída proposta: `OPPORTUNITY_CAPACITY_REPORT.md` e tabela por variante/mercado/janela, com quantidade total, quantidade deduplicada, limite superior, concentração temporal e limitações.

## 4. Segundo trabalho: distinguir ordenação de calibração

R² negativo indica mau ajuste quadrático em relação à referência constante na amostra, mas não é uma medida direta da qualidade de ordenar oportunidades. A métrica financeira continua sendo o replay líquido executável, não o R².

Antes de trocar o modelo, usar as previsões temporais fora do treino já disponíveis para verificar se scores maiores de fato identificam grupos com retornos líquidos maiores. Os limites dos grupos precisam ser definidos no desenvolvimento/calibração anterior, não escolhidos para maximizar o resultado do teste.

Comparar o seletor a referências sem conhecimento do desfecho: o baseline existente e amostragens aleatórias de candidatos estratificadas por ativo, direção, período e risco ex ante. Executar o mesmo simulador, preservar restrições e registrar a quantidade efetivamente realizada. Não selecionar sementes após olhar lucro e não condicionar os controles à duração ou retorno futuros.

Reportar EV por faixa de score, cobertura, concentração em episódios e incerteza por blocos de calendário compartilhados entre ativos. As faixas são diagnósticas, não autorização para escolher o melhor cutoff retrospectivo.

Retirar grandes vencedores é análise de sensibilidade, não nova regra automática de rejeição: o ponto é saber se há repetição em episódios independentes, não exigir uma distribuição sem ganhos raros.

## 5. Uma alteração de modelo a testar — expectativa decomposta

Se houver capacidade de oportunidades e a evidência justificar testar outro estimador, manter o C06 congelado como controle. Preservar candidatos, features, scanner, cooldown, stop ATR15m, política de saída, custos, alocação e calendário de refit. Modificar inicialmente apenas a forma de previsão.

Alternativa proposta: estimar componentes do retorno em vez de apenas um valor escalar diretamente.

```
r = retorno líquido da operação / nocional inicial
p = P(r > 0 | informações disponíveis)
G = E(r | r > 0, informações disponíveis)
L = E(-r | r <= 0, informações disponíveis)
EV_estimado = p * G - (1 - p) * L
```

Rótulos com retorno zero estão no grupo não positivo e contribuem zero para L. Calcular todos os componentes na mesma unidade e com a mesma política de custos; não descontar taxas duas vezes. O classificador e os estimadores condicionais não são Laya/Jev.

Esta é uma hipótese de modelagem, não uma melhoria presumida. Dividir a amostra pode piorar o ajuste quando existem poucos exemplos de grandes ganhos. Se faltar suporte para estimar um componente, reportar insuficiência em vez de produzir confiança artificial. Não remover automaticamente ganhos grandes da distribuição apenas para melhorar MAE.

Comparar à regressão direta e ao baseline já existentes. Calibrar com dados anteriores separados; preservar o corte econômico acordado. Score calibrado acima de 1,2% não substitui o EV realizado nem os demais gates.

Não chamar essa proposta de primeiro classificador do projeto: a v0.1 já combinava classificação e regressão. A diferença proposta é a decomposição explícita dos tamanhos condicionais de ganhos/perdas em retorno líquido por nocional.

Learning-to-rank pode ser alternativa posterior, não uma segunda grade a executar simultaneamente. Exige grupos de candidatos e interpretação adequada; seu score não é percentual de retorno. Um ranker que sempre escolhe o melhor candidato negativo não resolve o problema. Não comparar seu score bruto a 0,012.

## 6. Ampliar episódios, não multiplicar sinais do mesmo episódio

### Histórico

O primeiro relatório do usuário informou corte anterior a 13/08/2024 devido a dois minutos ausentes de mark. Inventariar blocos oficiais anteriores, caso ainda não tenham sido recuperados, em vez de descartar todo o passado por uma interrupção local. Não afirmar disponibilidade completa sem baixar e auditar.

Usar segmentos contínuos com warmup próprio. Não interpolar marks, atravessar gaps com indicadores como se não existissem, ou encerrar posições favoravelmente no minuto anterior a uma falha só porque o backtest conhece a falha futura. Desfechos que dependam de dados ausentes permanecem não identificados e devem ser contabilizados como tal.

Históricos recuperados servem para treino/desenvolvimento cronológico. Para avaliações antigas, retreinar apenas com dados anteriores ao respectivo corte; um modelo treinado em 2025 não pode ser usado como teste prospectivo de 2022. Não somar segmentos/folds independentes apenas para alcançar o gate de 200 trades. Buscar também um bloco de avaliação longo e contínuo quando houver cobertura.

### Universo multiativo

Uma nova variante pode operar um universo predefinido por critérios de liquidez e cobertura conhecidos na época. Um piloto de 10–20 símbolos é hipótese de engenharia, não escolha aprovada de ativos nem garantia de sinal.

Reconstruir constituintes com informação passada; incluir corretamente listagens/deslistagens e não escolher as moedas com maior lucro retrospectivo. Verificar o histórico de experimentos antes de anunciar algo como não testado.

Implementar uma única política multiativo por mercado com caixa e risco compartilhados, não uma soma de backtests com o mesmo dinheiro duplicado. Sinais simultâneos altamente relacionados não viram episódios independentes só por mudarem de ticker. Reportar concentração por tempo/ativo e preservar alocação fracionária.

Não misturar a ampliação de universo com mudança de score e de saída no mesmo experimento. Atribuir o ganho ao componente efetivamente modificado.

## 7. Uma família alternativa: falha de rompimento com retomada do nível

Caso a capacidade/ordenação não justifique insistir no breakout atual, testar um evento diferente, não outra média móvel.

Hipótese: após ultrapassar um nível previamente conhecido, o preço pode falhar em sustentar o movimento e recuperar o nível; essa recuperação, acompanhada de fluxo observado, pode distinguir reversão de mera continuação. Isso ainda não foi demonstrado como lucrativo neste projeto. O resumo não permite garantir que nunca houve experimento semelhante: verificar o inventário antes de implementar.

Especificação causal inicial:

- Definir nível e normalizadores usando exclusivamente histórico anterior.
- Observar a violação e, depois, um fechamento de confirmação de retorno ao nível.
- Só gerar a entrada depois da confirmação; não marcar como entrada o extremo anterior conhecido retrospectivamente.
- Definir invalidação estrutural e escala de risco, preservando o componente ATR15m apenas como hipótese transferida, não evidência de que serve a toda estratégia.
- Executar no próximo preço disponível, com custos, funding e tratamento conservador de ordem intrabar.
- Spot permite apenas compra e encerramento; USD-M pode testar long/short separadamente.

Não interpretar um pavio como prova de liquidações ou stops de terceiros. Uma reversão baseada em preço é uma hipótese diferente de uma reversão confirmada por dados de liquidação.

### Informação incremental

Priorizar, numa extensão separada, mudanças de open interest, funding conhecido no instante, diferença perpétuo/spot e fluxo agressor. A pergunta é se oferecem informação adicional, não se outro indicador derivado do mesmo candle melhora um ajuste.

Os arquivos oficiais de aggTrades contêm preço, quantidade, timestamp e identificação maker do comprador. A API documentada de histórico de open interest oferece apenas o mês recente; auditar arquivos oficiais e a cobertura disponível antes de prometer histórico longo. Se não houver histórico verificável, coletar prospectivamente ou excluir a feature daquele backtest.

O stream de liquidações é um snapshot que pode omitir outras ordens dentro do mesmo intervalo: a documentação informa a última liquidação por símbolo a cada 1000 ms. Não tratá-lo como total completo de liquidações. Ausência de dados não equivale a zero.

Funding futuro realizado pode entrar no rótulo, mas não na feature anterior ao evento de liquidação. Valores conhecidos/publicados em cada instante devem ter timestamp de disponibilidade. Informações do Spot podem ser features dos futuros sem juntar PnL dos dois mercados.

## 8. Sequência proposta e condição de encerramento de cada pesquisa

| Passo | Entrega | Decisão orientada pela evidência |
|---|---|---|
| 1 | Capacidade otimista por conjunto de candidatos | Se nem o limite relaxado comporta EV/amostra, mudar oportunidades/dados, não o estimador. |
| 2 | Ordenação e referências aleatórias/simples | Distinguir possível seleção útil, calibração ruim e ausência de sinal demonstrado. |
| 3 | Um previsor de expectativa decomposta, com C06 como controle | Manter apenas se agregar evidência temporal; não ajustar cutoff no teste. |
| 4 | Cobertura histórica/universo causal, em experimento separado | Aumentar episódios sem fabricar independência ou duplicar capital. |
| 5 | Uma família de falha de rompimento, se a linha anterior não se justificar | Verificar outra hipótese econômica; não reabrir uma busca ilimitada de combinações. |

O orçamento de tentativas deve ser registrado, mas não vira impedimento permanente para desenvolver novas hipóteses. Não repetir indefinidamente a mesma hipótese e chamar cada ajuste de descoberta.

Uma estratégia-base não precisa ser lucrativa antes do filtro por definição matemática: uma população de candidatos negativa pode conter uma subpopulação positiva. O filtro, porém, precisa identificar essa subpopulação antes dos resultados e de forma replicável. O conjunto escolhido com conhecimento do futuro não demonstra isso.

Nenhuma dessas propostas foi treinada nesta revisão. Não existe promessa de que alguma alcançará os gates. Os resultados negativos anteriores devem permanecer preservados, assim como sinais positivos frágeis.

## 9. Arquivos sugeridos para o agente

- `OPPORTUNITY_CAPACITY_REPORT.md`: limites relaxados, número de candidatos e condições de validade.
- `SCORE_ORDERING_REPORT.md`: faixas, referências, episódios, suporte e incerteza.
- `DATA_COVERAGE_PLAN.md`: cobertura real, gaps, segmentos, universos e testes reservados.
- `NEXT_EXPERIMENT_PROTOCOL.md`: uma mudança principal, hashes, política causal, datas e critérios congelados.
- Atualização do ledger de experimentos: fracassos, invalidações, hipóteses e estados `target_not_demonstrated` preservados.

São nomes propostos; adaptar à estrutura real e não sobrescrever os relatórios atuais.

## 10. Referências verificadas nesta revisão

Fonte interna principal: `Markdown colado.md`, enviado pelo usuário; P0 nas linhas 13–17, saídas corrigidas 25–29, trajetória 57, C06 85, C07–C10 89–93, critérios 113–129, C11–C12 137–145 e próxima mudança 153–157. O primeiro relatório do usuário no histórico da conversa é a fonte do corte de dados em agosto de 2024.

Referências externas primárias, para fundamentos/contratos de dados — não evidência de rentabilidade do nosso bot:

1. scikit-learn, `r2_score`: https://scikit-learn.org/stable/modules/generated/sklearn.metrics.r2_score.html
2. XGBoost, Learning to Rank: https://xgboost.readthedocs.io/en/stable/tutorials/learning_to_rank.html
3. Binance Public Data, formatos e arquivos: https://github.com/binance/binance-public-data
4. Binance USD-M, Market Data / Open Interest Statistics: https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data
5. Binance USD-M, Market Streams / Liquidation Order Streams: https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/market
6. Bailey, Borwein, López de Prado e Zhu, The Probability of Backtest Overfitting: https://escholarship.org/uc/item/4w1110bb

O limite dos 200 melhores retornos e a decomposição de expectativa são argumentos matemáticos desta proposta, não resultados experimentais publicados nem métricas já calculadas sobre os arquivos locais.

## 11. Resultado da verificação após os Ciclos 13–19 — 29/09/2026

Esta seção atualiza o estado da proposta com os artefatos posteriores. Os documentos preservam os resultados negativos e não transformam diagnósticos retrospectivos em validação. O estado econômico geral continua `target_not_demonstrated`.

| Etapa da proposta | Verificação posterior | Decisão |
|---|---|---|
| Capacidade do conjunto (C13) | A média dos 200 maiores retornos foi +2,029% na base e +1,502% no stress quando BTC e ETH foram agrupados. A seleção continha 169 eventos sobrepostos e até dez intervalos simultâneos. Por mercado, o teto foi +0,850% em BTC e +1,115% em ETH. | Diagnóstico concluído; não prova seleção preditiva nem 200 operações executáveis. Não repetir no mesmo conjunto. |
| Ordenação (C15) | O ranking retrospectivo ficou acima de 100 controles aleatórios pareados, mas continuou com apenas 11 operações em seis semanas. | Evidência exploratória; não satisfaz amostra nem independência temporal. Não é uma candidata. |
| Expectativa decomposta com ML/GPU (C14) | A decomposição `p × G − (1 − p) × L` foi treinada em CUDA em 48 modelos sobre 1.977 linhas; zero score ultrapassou o corte fixo de EV previsto. Uma frase contraditória do relatório foi corrigida em [auditoria C14](CICLO14_AUDITORIA_CORRECAO_2026-09-29.md). | Etapa executada e reprovada para C06. Não repetir essa hipótese, os mesmos rótulos ou janela como experimento novo. |
| Cobertura e qualidade de dados (C19) | Os arquivos históricos `bookDepth` existem, mas a auditoria de BTCUSDT encontrou três dias incompletos em 56 e duas inversões de preço médio implícito. Em 19/05/2025, sob a interpretação UTC não confirmada do timestamp no CSV, `notional/depth` ficou cerca de 17%–20% abaixo do mark-price oficial daquele minuto. O checksum confere integridade de transferência, não a semântica econômica nem o fuso do campo. | Histórico `bookDepth` fica fora de treino e replay até semântica, fuso e divergência serem esclarecidos. Não usar o arquivo como fonte quantitativa de profundidade por enquanto. |
| Família alternativa da seção 7 | A falha de rompimento com retomada de nível se sobrepõe aos testes anteriores de sweep/reclaim, que tiveram EV negativo nas janelas examinadas. | Não tratar a mesma família como inédita por mudar a granularidade ou o nome. |
| Candidato prospectivo (C18) | O filtro HGB de baixa volatilidade, treinado em CPU, foi congelado para paper USD-M, com primeira decisão elegível prevista para 05/10/2026 01:00 UTC. O histórico escolhido após inspeção tinha 89 episódios; ainda não existe evidência prospectiva de resultado. | Manter como trilha exploratória independente. O calendário e os parâmetros não autorizam ordens reais nem demonstram ganho de GPU. |

### Próximo passo de dados

Uma captura exploratória de 30 segundos do stream público USD-M `bookTicker` recebeu 16.364 mensagens, sem regressão de `update_id`, cotação cruzada ou quantidade negativa. A taxa observada projeta aproximadamente 7,3 GB/dia de JSON bruto; as mensagens não foram persistidas. O evento mostrou a rota pública `/public` adequada ao tráfego de alta frequência; a Binance aposentou as URLs WebSocket legadas em 23/04/2026 ([aviso oficial](https://www.binance.com/en/support/announcement/detail/ebf9b0aa9eca4ff3804eef6fb09ba32a)). A medição foi apenas de viabilidade e não contém features, sinais ou retornos.

O próximo trabalho autorizado por esta sequência documental é congelar e revisar um coletor público para BTCUSDT USD-M que reduza o fluxo a snapshots de um segundo, registre lacunas e incerteza do relógio e preserve recibos com hashes. O protocolo de captura não autoriza treino: a estratégia, as regras de entrada/saída/abstenção, o orçamento de busca e a separação entre desenvolvimento e teste terão de ser registrados antes de calcular rótulos ou métricas. A série prospectiva não poderá ser apresentada como evidência até acumular amostra executável suficiente e passar todos os gates da seção 1.

**Conclusão da verificação:** a proposta é metodologicamente válida como sequência, mas suas etapas C13–C15 não produziram estratégia, e os dados históricos de `bookDepth` não estão qualificados para novo treino. C18 segue sem resultado. Nenhuma estratégia foi aprovada e nenhuma ordem real foi enviada.
