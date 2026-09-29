# Próxima iteração — ciclo 6

Atualizado em 28/09/2026. O estado econômico continua `target_not_demonstrated`; a estratégia ainda não foi encontrada.

## Etapa P0 concluída

A auditoria reproduziu a contabilidade dos 300 registros históricos. O complemento fechou o funil por ativo/estratégia/direção/regime, reconciliou 146 trades pareados com custo dobrado mantendo trajetória e quantidade, e produziu 84 retornos mensais, 12 métricas de portfólio e 300 diagnósticos de caminho. O tratamento de custos, o funil e os resultados estão em [ACCOUNTING_AUDIT.md](ACCOUNTING_AUDIT.md) e [P0_COMPLETION](../results/p0_completion_2026-09-28/p0_completion_summary.json).

Nenhum fold da auditoria P0 cumpre os gates. O estresse integral e o pareado permanecem negativos. Não foi feito novo treino durante aquela auditoria.

## P1 multi-timeframe — reexecutado após correção

Uma auditoria das saídas descobriu que o motor recebeu descrições longas em vez dos modos `fixed`, `trailing` e `trend_loss`. A primeira execução, seu threshold replay e feature gain foram invalidados. A correção e a evidência estão em [CICLO02_CORRECAO_SAIDAS_PROTOCOLO.md](CICLO02_CORRECAO_SAIDAS_PROTOCOLO.md).

Os testes determinísticos e smoke cases confirmaram separadamente alvo fixo, trailing stop e perda da EMA21; também verificam que uma descrição longa seja rejeitada. Os outputs antigos estão preservados e marcados como inválidos. A reexecução corrigida pré-calculou 24 conjuntos de rótulos; os 8 grupos de mercado/família/horizonte tinham 3 hashes distintos cada. Foram treinados 24 HGB CPU e 24 XGBoost CUDA. Todos os 72 comparadores e 480 combinações ML/threshold falharam ao menos um gate; nenhuma combinação alcançou 200 trades (máximo 99). O maior EV observado foi +0,590% em um trade. Detalhes: [resultados do Ciclo 02](CICLO02_RESULTADOS_2026-09-28.md).

## Leitura da sensibilidade corrigida

A análise está em [CICLO02_SENSIBILIDADE_CORRIGIDA_PROTOCOLO.md](CICLO02_SENSIBILIDADE_CORRIGIDA_PROTOCOLO.md) e no [relatório de resultados](CICLO02_RESULTADOS_2026-09-28.md). Reduzir o cutoff elevou a amostra para pelo menos 200 trades em 16/288 combinações, mas o EV base foi negativo em todas as combinações com amostra suficiente e nenhum stress foi positivo. O máximo foi 397 trades com EV −0,254%; o maior EV bruto, +0,106%, usou cinco trades. Não aprovar nenhuma candidata nem repetir a faixa com os modelos corrigidos.

## Filtro causal de custo/stop — testado e rejeitado nesta janela

O filtro `round_trip_cost / stop_fraction <= 0,25`, sugerido pelo handoff, reteve apenas 1/5.871 sinais Spot e 598/11.384 USD-M. Nenhuma das 24 variantes passou; nenhuma teve pelo menos 200 operações, e os poucos EVs positivos não se sustentaram em amostra. O caso Spot de +1,607% base e +1,353% stress é uma só operação, sem payoff ou profit factor estimáveis. Não ajustar outro cutoff nesta janela. Detalhes e hashes: [CICLO02_RESULTADOS_2026-09-28.md](CICLO02_RESULTADOS_2026-09-28.md).

O diagnóstico descritivo dos 24 classificadores corrigidos está em [CICLO02_FEATURE_DIAGNOSTICS_CORRIGIDO_PROTOCOLO.md](CICLO02_FEATURE_DIAGNOSTICS_CORRIGIDO_PROTOCOLO.md). `atr_pct` teve ganho top 3 em todos os 12 modelos de retomada de tendência; `vol_ratio` repetiu top 3 nos seis modelos de rompimento Spot. Isso não informa o sentido do efeito nem mede EV, então não foi convertido diretamente em regra.

### Diagnóstico de trajetória — concluído, sem regra nova

A extração corrigida mediu 40.241 linhas repetidas entre 24 variantes, nos cenários base e stress, com candles de stop/alvo e gaps separados como ambíguos. Os EVs de todas as 24 variantes ficaram negativos: −0,319% a −0,195% base e −0,612% a −0,389% stress. Fricção mediana consumiu 1,11–1,18R em Spot e 0,65–0,69R em USD-M no cenário-base; sob stress, 2,23–2,46R e 1,31–1,43R. MFE dos perdedores antes da barra de saída foi baixa, e a saída por EMA21/trailing não tornou o EV positivo. Os dados apontam para problema de entrada/viabilidade de custo junto com a saída; não justificam um ajuste de trailing ou de stop escolhido nesta janela. Relatório e correção de ambiguidade: [CICLO02_RESULTADOS_2026-09-28.md](CICLO02_RESULTADOS_2026-09-28.md).

### Regressão direta de retorno líquido — concluída, sem candidata

A transferência do regressor `net_return` para os 24 conjuntos de candidatos também falhou: 48 modelos HGB/XGBoost, um único corte congelado `predicted_net_return > 1,2%`, zero gates completos. O melhor caso teve 18 trades e EV +0,788%; 40 modelos não selecionaram nenhum evento. Não reajustar o corte nem repetir a regressão sobre a mesma janela. Detalhes e artefatos: [CICLO03_DIRECT_NET_EV_RESULTADOS_2026-09-28.md](CICLO03_DIRECT_NET_EV_RESULTADOS_2026-09-28.md).

### Próxima ação de pesquisa

Os resultados anteriores permanecem úteis para orientar a próxima mudança. O breakout/continuação USD-M de 24h com saída `trend_loss` fica preservado como hipótese exploratória: os portfólios HGB e XGBoost ficaram positivos, mas a regra sem filtro perdeu e a maior parte do ganho veio de dois episódios de tendência repetidos pelos dois modelos. O regressor XGBoost estático teve calibração fraca, foi treinado até julho de 2025 e selecionou apenas 18 operações na janela; não foi atualizado enquanto o mercado avançava.

O Ciclo 04 manteve o mesmo breakout USD-M de 24h com saída `trend_loss` e reajustou só o XGBoost CUDA mensalmente com rótulos maduros. O EV-base subiu de +0,788% para +2,199% e o PnL stress de +US$ 214 para +US$ 350. Mantemos esse avanço como evidência exploratória: foram apenas 7 trades em 6 semanas, e dois vencedores produziram a maior parte do resultado. O corte de score não deve ser ajustado nessa janela. Detalhes: [CICLO04_ROLLING_REFIT_RESULTADOS_2026-09-28.md](CICLO04_ROLLING_REFIT_RESULTADOS_2026-09-28.md).

O Ciclo 05 avaliou o breakout em candles de 1 minuto com features e stop de 1m. O replay piorou: 1.476 trades sem filtro, win rate 2,17% e EV −0,202%; o XGBoost mensal selecionou duas operações, ambas perdedoras. Rejeitar esta combinação específica, sem descartar o resultado promissor do Ciclo 04. Como a resolução também estreitou o stop, não atribuir a falha somente ao scanner.

O Ciclo 06 isolou o stop intraminuto. Com o scanner, as features e o modelo de 1m mantidos, trocar o stop de ATR de 1m para o último ATR15 completo levou o portfólio filtrado de EV -0,382% no C05 para +1,262%. Payoff 10,17, PF 4,35, drawdown 2,39% e stress +US$ 380,50 passaram os gates econômicos. O limite de amostra continua falhando: 11 trades em seis semanas, abaixo de 200 e oito semanas ativas. Três longs de ETH explicam os ganhos; retirando os dois maiores, EV cai a -0,136%. O score também não se calibrou bem (R² -0,026; MAE pior que baseline). Preservar o stop de 15m como componente promissor, sem alegar consistência. Resultado e hashes: [CICLO06_MINUTE_BREAKOUT_STOP15M_RESULTADOS_2026-09-28.md](CICLO06_MINUTE_BREAKOUT_STOP15M_RESULTADOS_2026-09-28.md).

O Ciclo 07 rejeitou reduzir o cooldown para um minuto: candidatos de seleção cresceram de 1.977 para 4.441 e os rótulos tiveram 78,41% de sobreposição, mas o modelo escolheu 19 sinais e executou 11 trades nos dois ciclos. Só três trades foram iguais, e eram perdas; os grandes ganhos do C06 não se repetiram. No C07, EV-base caiu a -0,232%, PF a 0,51 e stress a -US$ 124,40. A correlação do score caiu de 0,140 para 0,038. Isso mede o efeito combinado do scanner mais denso e da distribuição de treino mais densa; não isola um modelo fixo. Rejeitar essa política e preservar o C06 como hipótese exploratória. Detalhes e hashes: [CICLO07_MINUTE_BREAKOUT_NO_COOLDOWN_RESULTADOS_2026-09-28.md](CICLO07_MINUTE_BREAKOUT_NO_COOLDOWN_RESULTADOS_2026-09-28.md).

O C08 ponderou rótulos por unicidade: a qualidade do score melhorou em MAE/correlação versus C07, mas nenhum evento ultrapassou o cutoff fixo. Preservar o método, sem aprovar o modelo nem baixar o cutoff. O C09 foi não informativo porque seu scanner não mudou os candidatos; seus hashes coincidiram integralmente com C08. O C10 corrigiu a comparação de canal e reduziu os candidatos de 15.410 a 10.694 e a sobreposição de rótulos de 78,41% a 69,08%, mas os scores continuaram abaixo do cutoff e o baseline sem filtro perdeu. Preservar C06 como evidência exploratória de cauda, não como estratégia consistente. Relatórios: [C08](CICLO08_MINUTE_BREAKOUT_UNIQUENESS_WEIGHTS_RESULTADOS_2026-09-28.md), [C09 inválido](CICLO09_MINUTE_BREAKOUT_FIRST_CROSSING_RESULTADOS_2026-09-28.md), [C10](CICLO10_MINUTE_BREAKOUT_FIRST_CROSSING_RESULTADOS_2026-09-28.md).

A próxima ação não será outro ajuste arbitrário nesse breakout. Revisar as pesquisas já feitas para as outras famílias de pares cripto, encontrar a hipótese com melhor evidência econômica e alterar somente o componente cujo relatório mostre falha. Spot e USD-M continuam separados; qualquer candidata precisa satisfazer os gates em janela fora da amostra histórica e depois passar por paper prospectivo congelado.

A combinação C06 já foi selecionada após examinar a mesma janela histórica, portanto C07 também é exploratório e não constitui validação independente. Se os indicadores econômicos se deteriorarem ao elevar a frequência, manteremos o stop de 15m e voltaremos ao gargalo de seleção/calibração, sem reajustar o cutoff nessa janela. As experiências de confluência e classificação BUY/IDLE/SELL por minuto seguem como evidência contrária para a ideia de que apenas aumentar chamadas resolveria a estratégia. Nenhuma ordem real foi enviada.

Se algum candidato passar os gates históricos completos, ainda precisa de paper prospectivo congelado por pelo menos oito semanas ativas e 200 trades completos. Nenhuma análise retrospectiva autoriza ordens reais.

## Critérios de decisão

Aplicar cada gate por variante e mercado, sem agregar folds, backends, mercados ou custos para alcançar amostra:

- EV líquido por operação >1,2% do nocional inicial, payoff mínimo 1:1 e profit factor ≥1,25 no cenário-base.
- Pelo menos 200 trades completos e não duplicados, em pelo menos oito semanas ativas.
- PnL líquido agregado positivo sob taxa e slippage dobrados; funding observado permanece em USD-M. EV, payoff e profit factor do stress são reportados como diagnóstico, sem gates separados.
- Taxa de acerto próxima a 70% é preferência, sem piso obrigatório.
- Sem teto de drawdown; medir e minimizar entre candidatos que passem os demais gates.

A ordem intraminuto continua incerta nos candles de 1m. Nenhum resultado retrospectivo ou paper autoriza ordens reais. Spot e USD-M permanecem separados.

### Resultado do Ciclo 11 — preservar `rank_blend` como evidência, retirar como prioridade

O Ciclo 11 reaplicou, sem mudanças, a regra diária semanal `rank_blend` à extensão de 01/08 a 26/09/2026. Foram 21 episódios em oito semanas. A 0,10% por lado, EV foi −8,233%, payoff 0,430, profit factor 0,322, retorno da carteira −13,856% e drawdown 14,349%. A 0,20% por lado, o custo dobrado, retorno ficou −14,196%. A regra continua documentada como resultado histórico positivo até julho, mas a extensão recente mostra que não é consistente; não ajustar pesos ou limiares nessa janela. Isso é uma estratégia diária, distinta dos sinais intrahora. Detalhes: [Ciclo 11](CICLO11_RANK_BLEND_EXTENSION_RESULTADOS.md).

### Resultado do Ciclo 12 — o limite por par não resolve a baixa frequência

Com os mesmos 19 scores congelados do C06, permitir até duas posições simultâneas — uma por BTC e outra por ETH — manteve exatamente 11 trades, EV-base +1,262%, EV stress +1,092%, PnL stress +US$ 380,50 e DD-base 2,394%. O replay original de uma posição foi reproduzido exatamente. Os oito sinais pulados eram do mesmo ativo ainda aberto; não há evidência para abrir uma segunda posição no outro par. Piramidar no mesmo ativo seria outro desenho de risco e contaria sinais redundantes, portanto não será feito nesta janela. Detalhes: [Ciclo 12](CICLO12_C06_CONCORRENCIA_RESULTADOS.md).

### Próxima mudança justificada

Preservar o stop ATR15m e parar de alterar cooldown e concorrência. A falha visível é o score: R² negativo, correlação baixa e erro médio maior que o baseline; o corte fixo produziu 11 operações, com ganhos concentrados em ETH, enquanto o baseline sem filtro perdeu. C08 melhorou correlação/MAE com pesos por unicidade, mas não gerou scores acima do corte; C10 reduziu sobreposição, mas também não gerou operação. Não baixar cutoff nem mexer nos mesmos limiares históricos. Comparar somente uma nova forma de previsão/ordenação, mantendo o C06 como controle congelado e usando dados posteriores não vistos para avaliação. Até existir amostra fora da janela já examinada, C06 continua exploratório.

`rank_blend` continua registrado como positivo até julho e negativo na extensão de agosto/setembro; o Ciclo 11 documenta essa mudança temporal. Conservar protocolos, ledgers e hipóteses tanto quando positivos quanto negativos. O piso de 200 operações completas e independentes não pode ser cumprido contando rótulos sobrepostos. Nenhum resultado retrospectivo ou paper autoriza ordens reais.

## Atualização após os Ciclos 14–17 — 28/09/2026

O Ciclo 14 treinou os previsores de EV decomposto em CUDA, mas nenhum score superou o corte econômico congelado; não substituir o C06 por essa decomposição. O Ciclo 15 mostrou ordenação retrospectiva do C06 acima de 100 controles aleatórios pareados, mas manteve só 11 operações em seis semanas; isso não confirma capacidade suficiente. O Ciclo 16 rejeitou a transferência do score para BNB/SOL: 14 operações no par novo tiveram EV-base −0,4083%, e o conjunto de quatro contratos ficou em 23 operações e EV +0,4030%; nenhum portfólio passou os gates.

O Ciclo 17 estendeu temporalmente o C06 em BTC/ETH USD-M, com corte e saída congelados e um refit XGBoost CUDA treinado somente em rótulos maduros antes de setembro. Em 01–27/09, pontuou 203 candidatos, selecionou cinco e executou três; acerto 0%, EV-base −0,486%, payoff não definido, profit factor 0 e PnL stress −US$ 54,86. Falhou os gates econômicos e de amostra. A janela é curta e outras pesquisas já haviam examinado o mercado em setembro; não é holdout global independente. Detalhes e proveniência: [protocolo](CICLO17_EXTENSAO_TEMPORAL_C06_SETEMBRO_PROTOCOLO_2026-09-28.md), [resultado](CICLO17_EXTENSAO_TEMPORAL_C06_SETEMBRO_RESULTADOS_2026-09-28.md) e `research/EXPERIMENTS.jsonl`.

**Estado atual:** nenhuma estratégia foi aprovada. Não alterar o corte, o stop ou o universo do C06 com setembro; o C06 permanece reprovado como candidata consistente. A meta só avança com uma hipótese ainda não repetida, regras pré-registradas e evidência futura/paper suficiente por variante e mercado. Nenhuma ordem real foi enviada.

## Auditoria complementar da proposta após o Ciclo 12 — 28/09/2026

O Ciclo 13 concluiu o diagnóstico de capacidade pedido na etapa 1 da proposta: entre 1.977 candidatos C06, a média oracular dos 200 maiores retornos foi +2,029% na base e +1,502% no stress quando BTC e ETH são agrupados. Separados, os tetos ficaram abaixo de 1,2%: +0,850% em BTC e +1,115% em ETH. A seleção agrupada contém 169 eventos sobrepostos e até dez intervalos simultâneos; não prova seleção preditiva nem 200 operações executáveis. Protocolo, relatório, CSV e JSON: [protocolo](OPPORTUNITY_CAPACITY_PROTOCOL_2026-09-28.md), [relatório](OPPORTUNITY_CAPACITY_REPORT_2026-09-28.md), [candidatos](../results/opportunity_capacity_candidates_2026-09-28.csv) e [resultado](../results/opportunity_capacity_2026-09-28.json).

A hipótese de falha de rompimento com retomada de nível descrita na seção 7 da proposta se sobrepõe às experiências anteriores de sweep/reclaim. O estudo intraminuto usou varredura de nível de 60 minutos, confirmação em cinco minutos e fluxo; teve EV de −0,152% em 2025 e −0,497% na confirmação de 2026, a 0,15% de custo por lado. O estudo de sweep da mínima anterior de 24 horas com HGB teve EV de −0,583% e drawdown de 17,93% em 106 operações. As regras e períodos diferem, mas o mecanismo econômico já foi testado em dados históricos que também foram usados por outras pesquisas. Não repetir a família sob novo nome ou com outra granularidade como se fosse hipótese inédita. Referências: [varredura e reclaim](../../docs/futures_liquidity_sweep_research_2026-09-27.md) e [sweep/reclaim com HGB](../../docs/price_action_alpha_research_2026-09-27.md).

O texto final do relatório C13 sugeria a família de retomada como possibilidade ainda não testada; esta revisão do inventário a substitui como recomendação atual. O trabalho seguinte exige uma hipótese econômica distinta e um período de avaliação que ainda não tenha sido usado para escolher eventos, custos ou thresholds. Os Ciclos 13–17 não aprovaram estratégia e nenhuma ordem real foi enviada.

## Registro do Ciclo 18 — 29/09/2026

O C18 pré-registrou uma avaliação paper prospectiva do filtro HGB sobre `low_volatility30_betahedged`, sem repetir o replay histórico. A evidência anterior é promissora em EV e payoff, mas veio de 89 episódios em cerca de 31 meses, com acerto de 62,9%; o candidato foi escolhido após inspeção. A cadência retrospectiva sugere perto de seis anos para acumular 200 episódios, sem garantia. O registro congela um ajuste único com rótulos maduros até 01/08/2026, limiar de 0,70, USD-M e a coorte de 20 contratos formada em janeiro de 2021. O primeiro sinal elegível é 05/10/2026 às 01:00 UTC. Drawdown será medido sem teto fixo e o beta residual será reportado, pois a reequalização do filtro pode perder a neutralidade do fator-base.

O protocolo e os hashes estão em [Ciclo 18](CICLO18_META_FILTRO_HGB_BAIXA_VOLATILIDADE_FORWARD_PROTOCOLO_2026-09-29.md) e `research/EXPERIMENTS.jsonl`. Ainda faltam o runner isolado, o artefato do modelo congelado e a coleta prospectiva; nenhum resultado C18 foi calculado e nenhuma ordem real foi enviada. Emendas append-only corrigem os timestamps dos metadados do registro e fixam o manifesto diário de treino (`bb5ca523…a0fad33`); nenhuma delas altera o método, e todas foram registradas antes de qualquer treino ou observação C18. A primeira ação seguinte é implementar e revisar coletor e contabilidade C18 sem alterar o paper JEV ou `forward_paper_v2`: o coletor atual é amarrado a outra regra e a contabilidade atual usa custos diferentes. Registrar hashes e só então iniciar a coleta simulada.


## Captura inicial do paper C18 — 29/09/2026

O coletor e a contabilidade isolados foram congelados e registrados antes da primeira captura pública. A captura inicial terminou às 01:34:55 UTC, antes da primeira decisão elegível de 05/10/2026 às 01:00 UTC; portanto não houve inferência, trade paper ou resultado econômico. A cadeia local contém quatro registros válidos e 80 recibos públicos com hashes conferidos. Havia 18 contratos ativos da coorte de 20: EOSUSDT não estava no catálogo e MKRUSDT estava `SETTLING`; não houve substituição. Ambas as contas seguem em US$ 10.000, sem posições ou custos. EV, acerto, payoff e profit factor ainda são indefinidos, e o gate amostral continua fechado. O registro completo está em [inicialização paper C18](CICLO18_PAPER_INICIALIZACAO_2026-09-29.md). Esta atualização substitui o status anterior de que ainda faltavam runner e modelo; a avaliação prospectiva e qualquer decisão sobre estratégia continuam pendentes.


Agendamento C18 confirmado no Windows: tarefa `C18-LowVol-HGB-Paper`, semanal aos domingos 22:00 em São Paulo (segunda 01:00 UTC), primeira execução prevista para 04/10/2026 às 22:00 local. Ela roda só com a sessão do usuário conectada, não acorda o computador, não recupera horário perdido e tem limite de dez minutos. O runner pode iniciar na bateria. Ainda não houve execução agendada nem nova observação de mercado; o primeiro sinal elegível continua em 05/10/2026 às 01:00 UTC. Evidência de configuração em `paper/task_definition.xml` e `research/EXPERIMENTS.jsonl`.


Correção de inventário em 29/09: o C14 já treinou em CUDA a decomposição `p × G − (1 − p) × L` sobre candidatos C06 (1.977 scores; zero entradas acima do corte). Uma frase do relatório C14 dizia o contrário; a evidência e a errata estão em [auditoria de correção C14](CICLO14_AUDITORIA_CORRECAO_2026-09-29.md). Não repetir essa hipótese em C06.

## Auditoria de fonte C19 — `bookDepth` histórico

Uma verificação exploratória confirmou arquivos públicos diários `bookDepth` para BTCUSDT USD-M no domínio `data.binance.vision`, apesar de o README consultado não listar essa categoria. Quatro ZIPs entre 31/08 e 26/09/2026 passaram o `.CHECKSUM`; cada um continha 34.560 linhas com bandas a cada 30 segundos. Em 06/09, as bandas ask +0,2% e +1% tinham apenas três e dois valores distintos de preço implícito, enquanto a amostra de 26/09 não mostrava esse congelamento. Corrigir a conclusão de disponibilidade da nota C19, mas não tratar a amostra tardia como prova de correção global: o issue permanece aberto. Antes de treinar qualquer modelo, verificar cobertura diária e qualidade para um único contrato/período, então pré-registrar a ablação baseline versus baseline + `bookDepth`. Detalhes e hashes: [auditoria de cobertura C19](C19_COBERTURA_BOOKDEPTH_AUDITORIA_2026-09-29.md). Nenhum desempenho foi medido; nenhuma estratégia foi aprovada.

**Complemento da auditoria:** os arquivos de BTCUSDT de 01/07 a 25/08/2026 existem em 56/56 datas e todos os checksums conferiram, mas apenas 53/56 passaram a regra de 2.880 timestamps únicos em cada banda. Os dias curtos são 08/07 (12 ausentes por banda), 18/07 (1) e 21/07 (14). Em 19/08, duas amostras marcaram preço médio implícito bid −0,2% acima de ask +0,2%. Esses casos estão detalhados na [auditoria C19](C19_COBERTURA_BOOKDEPTH_AUDITORIA_2026-09-29.md); explicar os gaps e divergências antes de montar features ou treino.

## Atualização de fonte e sequência após a auditoria — 29/09/2026

Esta atualização substitui a recomendação anterior de avançar ao treino após apenas localizar os gaps e as inversões das bandas de agosto. Sob a interpretação UTC, ainda não confirmada, a comparação do snapshot oficial `bookDepth` de 19/05/2025 com o mark-price oficial do mesmo horário produziu diferença de aproximadamente 16,9%–20,2%, embora os dois checksums confiram. Como semântica e fuso continuam sem confirmação e há relatos públicos ainda abertos sobre divergência/timestamp, o `bookDepth` histórico fica excluído de features, replay e treino até revisão futura. Evidência detalhada: [auditoria C19](C19_COBERTURA_BOOKDEPTH_AUDITORIA_2026-09-29.md).

O piloto público do USD-M `bookTicker` conectou pela rota nova `/public` por 30,02 segundos e recebeu 16.364 mensagens, sem regressão de update ID, cotação cruzada ou quantidade negativa. O fluxo bruto projetado é cerca de 7,3 GB/dia; nenhum dado foi salvo. O piloto não mediu desempenho e a incerteza do relógio local impede usar latência. Não iniciar treino nem interpretar esse teste curto como validação de fonte. O próximo protocolo documental é [C20](C20_BOOKTICKER_COLETA_PROSPECTIVA_PREREG_2026-09-29.md), para congelar uma coleta pública agregada por segundo e os critérios de qualidade antes de implementar ou ativar qualquer coletor.

O C18 permanece uma avaliação paper separada, com limiar e modelo congelados; a primeira decisão elegível consta como 05/10/2026 01:00 UTC no protocolo e no ledger. O status de execução do agendador não foi reconsultado nesta atualização, e ainda não há resultado prospectivo registrado. Preservar C18 sem alterações. C14 já treinou em CUDA a decomposição p/G/L e não deve ser repetido no C06; C15 mediu ranking retrospectivo sem superar o limite de frequência e amostra. C13–C17 continuam sem candidata aprovada.

**Próximo gate:** revisar e congelar implementação do agregador C20, validar sincronização do relógio, schema e cadeia de hashes; só então iniciar a coleta. Antes de calcular qualquer rótulo de estratégia, registrar separadamente a família de sinais, entradas, saídas, abstenção, custos, orçamento de busca e bloqueio temporal de oito semanas de desenvolvimento + oito de teste. Os critérios econômicos e de amostra da proposta permanecem inalterados. Nenhuma ordem real foi enviada.
