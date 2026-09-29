# Handoff para o agente local / Codex — Binance MultiStrategy v0.1

Revisão documental: 2 — 27/09/2026. Versão do código: 0.1.0, inalterada.
Esta revisão atualiza intenção, prioridades e protocolo de evolução. Não registra novo
treinamento, backtest, integração com a Binance nem alteração remota no repositório.

## 1. Decisão atual do usuário — direção de implementação

**Implementar e validar primeiro a v0.1 multiestratégia. Melhorar essa base em ciclos
mensuráveis, buscando lucro líquido razoável e risco controlado. Somente depois avaliar
um Laya especializado ou Jev, para descobrir se realmente melhoram a qualidade das decisões.**

A presença de IA de linguagem não é objetivo nem requisito de sucesso. Laya/Jev são
experimentos posteriores, não dependências da primeira versão e não melhorias presumidas.
Não substituir regras claras por chamadas a modelos. Não adotar o Jev Trader como nova
base nem iniciar fine-tuning de Laya nesta etapa.

O objetivo funcional permanece: Binance Spot e futuros USD-M, análise de candles fechados
de 1 minuto com contexto multitemporal, múltiplas estratégias, entradas/saídas, stop e
trailing stop. Spot compra e encerra inventário; futuros permitem long/short. Não operar
é uma decisão válida. Observar cada minuto não obriga a abrir uma posição a cada minuto.

### Divisão de responsabilidades

| Componente | Direção desta fase |
|---|---|
| Indicadores, gatilhos e regime explícito | Código convencional, causal e auditável. |
| Filtro aprendido das oportunidades | Preservar o classificador/regressor numérico já existente; medir seu ganho contra regras sem ML. |
| Dimensionamento, limites, execução, stop e trailing | Código determinístico; não delegar limites ou proteção a Laya/Jev. |
| Notícias, interpretação textual e especialistas adicionais | Fora da v0.1 prioritária; possíveis experimentos posteriores. |

**Sem Laya/Jev não significa remover o aprendizado de máquina numérico da v0.1.** A
comparação inicial obrigatória é entre regras sem ML e regras com o filtro numérico,
com os mesmos dados, capital, custos e regras de execução. Não presumir que a versão
com ML vence; registrar a conclusão. Se regras forem melhores, preservar essa evidência
e propor a evolução mais simples, sem alterar silenciosamente o comportamento da v0.1.

### O que significa buscar lucro razoável

O usuário ainda não fixou capital nem retorno mínimo mensal/anual. Não inventar uma
meta percentual, renda esperada ou promessa. Isso não impede implementar nem pesquisar:
usar os critérios já configurados como ponto inicial, reportar retorno líquido, risco,
regularidade e frequência de operações e deixar explícito o que foi ou não demonstrado.

A meta original de 70% de trades vencedores permanece registrada e configurada. Ela não
substitui rentabilidade: 70% com prejuízo líquido não é sucesso. Nesta revisão nenhum
limiar foi removido ou relaxado. Preservar os gates atuais, inclusive o intervalo de
confiança, e reportar separadamente resultado econômico e atendimento da meta de acerto.

Os critérios iniciais do pacote incluem pelo menos 200 trades encerrados e não
sobrepostos, oito semanas com operações, profit factor >=1,25, expectativa líquida
positiva, drawdown <=15%, resultado positivo sob custos estressados e win rate >=70%.
O gate também exige, por padrão, limite inferior aproximado de confiança >=70%.
São critérios de pesquisa, não autorização para produção nem garantia de lucro futuro.

Não aumentar risco/alavancagem, usar martingale, ocultar perdas ou reduzir custos
assumidos para fabricar aprovação. Não mudar os critérios depois de observar o teste;
qualquer revisão deve ser explícita, versionada e avaliada em novo experimento.

## 2. O que você recebeu — estado histórico da entrega

Um subprojeto Python executável, oito estratégias e pipeline de treinamento/calibração/
avaliação. O relatório original registra 52 testes de software aprovados, incluindo
exemplos artificiais. Esta revisão documental não reexecutou esses testes. Reproduza-os
no ambiente local e registre o resultado atual.

NÃO foram entregues pesos já treinados com históricos reais da Binance. O ambiente da
entrega original não conseguiu resolver o host para obter os dados. Não há demonstração
de lucro ou 70% de acerto. Nenhuma chave, chamada paga de IA ou ordem real foi utilizada.

O handoff original registrou uma leitura de `XSirch/laya-trader-binance` em 27/09/2026,
com pesquisas Jev e relatórios que já inspecionaram partes de 2025–2026. Esse registro
é histórico: esta revisão não fez nova inspeção remota. Leia main e as instruções atuais
antes de integrar. O nome do repositório não obriga a usar Laya na arquitetura atual.

## 3. Ordem de execução — implementar, medir e evoluir a base

1. Extrair este pacote separado; ler `AGENTS.md`, README, PROTOCOL e SOURCES. Executar
   `uv sync --extra dev`, `uv run pytest -q` e `uv run multitrader --help`. Registrar o
   ambiente e o estado real do código. Não usar métricas artificiais como evidência financeira.
2. Integrar como subprojeto aditivo, por exemplo `research/multistrategy_v01/`, ou planejar
   a migração dos módulos antes de mexer no código atual. Não apagar pesquisas existentes.
   Incorporar a direção deste handoff ao AGENTS/README do local integrado, preservando as
   demais instruções válidas. Informar somente commits/PRs/merges efetivamente realizados.
3. Baixar históricos oficiais com checksum, separadamente para Spot e USD-M. Auditar
   timestamp ms/us, duplicatas, gaps, OHLC, mark e funding. Se faltar arquivo mensal ou
   houver gap, investigar arquivos oficiais diários; não interpolar nem inventar preços.
4. Registrar universo, custos, limites, hipóteses e divisões temporais antes da seleção.
   Começar com poucos símbolos para validar a pipeline; ampliar por critérios de liquidez
   e cobertura conhecidos no período, não escolhendo vencedores retrospectivamente.
5. Executar a referência sem ML e treinar os modelos numéricos separados para Spot/USD-M.
   Publicar todos os resultados, inclusive fracassos. O treinamento atual usa CPU: não
   ocupar a RTX 4070 Ti 12GB com Laya e não consumir providers por decisão de mercado.
6. Rodar walk-forward com janelas de teste sem sobreposição. Tratar períodos históricos
   já vistos como exploratórios. Reservar o dataset final do usuário antes de examiná-lo
   ou ajustar parâmetros. Se a meta falhar, registrar `target_not_demonstrated`; não fazer
   tuning repetido no holdout até conseguir aprovação.
7. Auditar por estratégia, ativo, long/short, regime e custos. O comparador automático
   atual é regras sem ML. Buy-and-hold e caixa com exposição/custos comparáveis são
   extensões pendentes, não funcionalidades que este handoff já implementou.
8. Corrigir defeitos e experimentar melhorias incrementais conforme a seção 4. Medir
   se o filtro numérico agrega valor e quais estratégias ajudam ou prejudicam. Não
   presumir que todas as oito estratégias ou todos os indicadores devem permanecer ativos.
9. Construir coleta contínua, observabilidade e paper portfolio. O `PaperBroker` já trata
   eventos de preço, fechamento e funding, mas não os coleta. `signal` continua sendo
   inferência offline. Paper diagnóstico pode apoiar pesquisa de uma versão reprovada,
   desde que claramente identificado e sem liberar ordens reais.
10. Depois das validações, implementar/testar demo/testnet e reconciliação. Usar demo
    para validar integração, não para afirmar rentabilidade real. Nenhum gate habilita
    dinheiro real automaticamente; produção exige prontidão e autorização explícita.
11. Manter Laya/Jev em backlog posterior. A seção 6 define como compará-los quando houver
    uma base estável e resultado satisfatório demonstrado segundo o protocolo acordado.

## 4. Ciclo de melhoria — não otimizar até o backtest parecer bom

Congelar uma referência reproduzível antes de cada rodada. Formular uma hipótese
específica, implementar uma mudança principal, rodar testes, treinar/selecionar apenas
nos conjuntos permitidos e avaliar temporalmente. Comparar sob o mesmo capital, custos
e regras. Registrar tentativas malsucedidas, não apenas o melhor resultado.

Priorizar qualidade dos dados, paridade do simulador com a execução, custos, regras de
entrada/saída, filtros de regime e seleção de candidatos. Mais indicadores, estratégias
ou modelos não são melhorias por definição. Estudos exploratórios podem orientar a
próxima hipótese, mas não validar a hipótese nos mesmos dados.

Organizar rodadas finitas com hipóteses e orçamento de experimentos registrados. Não
executar busca ilimitada até algum backtest ficar positivo. Se não houver avanço,
relatar o diagnóstico e propor a próxima hipótese; não inventar sucesso nem descartar
perdas. Preservar a referência anterior para comparação e rollback.

### Critérios para comparar versões

Reportar, no mínimo, PnL bruto e líquido, retorno sobre o capital definido, taxas,
slippage, funding, profit factor, expectativa por trade, win rate e sua incerteza,
drawdown, pior período, número de trades, duração/exposição e frequência de operações.
Mostrar estabilidade por janela, estratégia, ativo, direção e regime; informar se os
resultados estão concentrados em poucos trades ou num único período.

Os estados de relatório devem distinguir:
- funcionamento do software e disponibilidade dos dados;
- evidência econômica fora do treino e atendimento ou não dos gates;
- meta de 70% demonstrada ou não; e
- prontidão operacional de paper/demo/produção.

Essa separação é requisito de relatório a implementar onde necessário, não uma nova
funcionalidade já pronta. Um resultado econômico interessante com menos de 70% deve
ser mostrado honestamente, mas não pode ser rotulado como aprovação do gate original.

Usar validação temporal de desenvolvimento para as iterações e reservar confirmação
final. Depois de usado para decisões de projeto, um teste deixa de ser inédito. Novas
versões selecionadas por esse resultado precisam de nova confirmação independente.

## 5. Entregáveis de acompanhamento para o agente

Além dos arquivos já produzidos pelo CLI, criar ou adaptar estes registros no projeto.
Os nomes abaixo são uma proposta de organização, não arquivos funcionais já entregues:

| Registro | Conteúdo mínimo |
|---|---|
| `EXPERIMENTS.jsonl` | ID/parent da rodada, hipótese, alterações, hashes de código/config/dados/modelo, seeds, períodos, custos, tentativas e resultado. |
| `BASELINE_REPORT.md` | Comparação regras vs filtro numérico, tabelas por mercado/regime, limitações, gates e conclusão econômica sem promessa. |
| `NEXT_ITERATION.md` | Próximas hipóteses priorizadas, evidência que as motiva e critérios de manter/rejeitar a mudança. |

Registrar datas exatas e separar resultado de seleção, avaliação exploratória, teste
reservado e observação prospectiva. Não declarar treinamento, download, teste ou merge
sem saída verificável. Não pedir confirmação para cada ajuste local de implementação
ou pesquisa que já esteja neste escopo; preservar, porém, as aprovações necessárias
para custos externos, credenciais e operação real.

Preparar desde já logs reaproveitáveis em pesquisa futura: candle e horário em que a
informação estava disponível, mercado/símbolo, features causais, estratégia, candidato,
decisão/abstenção, versões, custos, proteção e execução. Vincular o resultado só quando
encerrado e conhecido. Separar entradas do modelo de rótulos futuros. Não logar segredos.

Resultados de candidatos rejeitados, quando simulados depois, devem ser marcados como
contrafactuais/simulados; não tratá-los como fills ou lucros efetivamente obtidos.
Não coletar notícias ou contratar provedores textuais apenas para preparar esta fase.

## 6. Fase posterior — Laya/Jev como experimento, não obrigação

### Quando considerar

Depois de existir uma v0.1 evoluída reproduzível, economicamente satisfatória sob
critérios registrados, com avaliação independente e comportamento observado em paper.
Ausência dessa evidência não autoriza pular para Laya/Jev como tentativa de disfarçar
uma base ruim. Primeiro diagnosticar os problemas do núcleo e da execução.

Laya/Jev ficam fora da implementação prioritária deste handoff. No momento da fase
posterior, revalidar disponibilidade, documentação, compatibilidade, custos e licença;
não tratar características discutidas anteriormente como atuais sem verificar.

### Como comparar

Congelar o melhor sistema-base e conduzir experimentos separados:

| Variante | Alteração controlada |
|---|---|
| Base | Regras e filtro numérico conforme a referência escolhida. |
| Base + Laya | Filtro/classificador adicional especializado; pesos e processo de treinamento versionados. |
| Base + Jev | Mesma função decisória limitada, usando serviço externo e custo/latência registrados. |

Começar pela aceitação/rejeição de candidatos; não substituir de uma vez estratégias,
execução e controle de risco. Preservar o direito de abstenção. Se o componente adicional
falhar ou ficar indisponível, aplicar política predefinida de retorno à base ou bloqueio
de novas entradas; a gestão de posições abertas nunca pode depender dele.

Usar a mesma informação disponível no instante da decisão, oportunidades, capital,
custos e simulador nas comparações. As operações executadas podem divergir porque o
filtro muda a seleção; reportar essa diferença e a exposição resultante. Não congelar
artificialmente os mesmos trades se isso anular o comportamento que se pretende testar.

Se adicionar notícias ou outras fontes, separar o ganho dos novos dados do ganho do
modelo: realizar um experimento próprio e, quando viável, uma referência alternativa
com acesso à mesma informação. Nunca atribuir ao Laya/Jev uma vantagem de dados que
não foi fornecida ao comparador.

Treinar Laya somente em informação e resultados permitidos pelo corte temporal. Se
houver rótulos gerados por outra IA, identificá-los e não confundi-los com lucro
comprovado. Calibrar e avaliar previsões; confiança declarada não substitui win rate.

A comparação posterior precisa de novos períodos independentes/prospectivos. Não
reciclar o teste já usado para escolher a base como confirmação final de Laya/Jev.
Executar inicialmente em shadow/paper, sem ordens extras na conta real.

Medir valor incremental líquido, estabilidade, drawdown, cobertura de oportunidades,
calibração quando aplicável, latência (incluindo p95), falhas, custo de inferência e
custo de treinamento/operação. Não contar apenas melhoria de acerto ou respostas bonitas.
Definir previamente critérios de adoção. Se não houver benefício robusto que compense
custo e complexidade, manter a base; sem evidência, registrar resultado inconclusivo.

## 7. Requisitos da futura operação contínua

- WebSocket público, warmup REST, recuperação de lacunas e relógio/ordenação auditáveis.
- Uma decisão por candle fechado, deduplicada por mercado/símbolo/modelo/estratégia/direção.
- Stops reagem a eventos de preço, não aguardam o scheduler de sinais ou um modelo de IA.
- Trailing atual ratcheta no candle fechado. Se mudar para atualização por tick ou trailing
  nativo percentual, alterar o simulador e repetir validação; não assumir equivalência.
- Persistir posições, sinais pendentes, execução, funding e IDs antes de confirmar ações.
- Feed atrasado bloqueia novas entradas. Stops reais devem estar no exchange, pois o
  processo local pode cair. Monitorar rejeição/expiração da proteção, não só a ordem de entrada.
- Reconciliar ordens, fills parciais, posições e saldos após reinício. Timeout de envio não
  significa que a corretora recusou: consultar pelo identificador antes de qualquer reenvio.
- Controlar risco agregado entre Spot e USD-M, perdas diárias, concentração/correlação e
  quantidade de posições; não somar dois orçamentos independentes como se fossem capital novo.
- Reaprender somente com resultados encerrados e observáveis. Não usar teste reservado ou
  posições abertas como rótulos resolvidos. Versionar artefatos e permitir rollback.

## 8. Binance: diferenças que não podem ser ignoradas

As referências abaixo foram preservadas da entrega original, não revalidadas nesta
revisão documental. Consultar de novo a documentação oficial antes de implementar o
adaptador real; a documentação atual prevalece sobre exemplos históricos.

Spot possui trailingDelta em BIPS e limites TRAILING_DELTA por símbolo. As ordens
suportadas e filtros devem ser consultados, não hardcoded. Uma ordem STOP_LOSS_LIMIT
pode não preencher; não vendê-la como garantia de liquidação da posição.

USD-M tem endpoint de ordens condicionais `/fapi/v1/algoOrder`, parâmetros próprios
para stop/trailing, como triggerPrice, activatePrice e callbackRate. Não copiar cegamente
exemplos antigos de `/fapi/v1/order`. Confirmar one-way/hedge, reduceOnly/closePosition,
workingType e cancelamento de proteções órfãs na documentação atual.

Antes de enviar qualquer ordem, validar PRICE_FILTER, LOT_SIZE/MARKET_LOT_SIZE,
notional mínimo, precisão/tick/step e permissões reais da conta. Sinal de venda em Spot
nunca pode criar short. Quantidade vendável deve refletir fills e taxas efetivas.

Não implementar alavancagem com este backtest: faltam margin tiers, liquidação e ADL.
Não solicitar chaves no chat; usar segredo local sem saque habilitado e sem registro
em logs, conforme as permissões necessárias ao ambiente que o usuário autorizar.

## 9. Critério de relatório honesto

Distinguir: código feito; testes de software; downloads efetivamente obtidos; treino real
executado; validação exploratória; teste reservado; paper contínuo; demo; produção.
Entregar os hashes e contagens, taxas assumidas, PnL líquido, intervalo de confiança,
profit factor, drawdown, número de trades e falhas. Não prometer 70% nem lucro futuro.
