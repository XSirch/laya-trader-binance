# Handoff para o agente local / Codex — Binance MultiStrategy v0.1

Revisão documental: 3 — 28/09/2026. Versão do código: 0.1.0, inalterada.
Esta revisão define metas de retorno e explicita alocação fracionária por operação.
Não executa esses requisitos no código, nem registra novo treinamento, backtest,
integração com a Binance ou alteração remota no repositório.

## 1. Decisão atual do usuário — direção de implementação

**Implementar e validar primeiro a v0.1 multiestratégia, com entradas usando apenas
frações da carteira. Buscar primeiro 1% ao mês equivalente líquido e trabalhar para 2%,
com risco controlado; 5% é um objetivo ambicioso, não obrigação. Somente depois avaliar
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

### Objetivo econômico — atualização da revisão 3

**Primeiro marco: 1% ao mês equivalente líquido. Meta central: 2% ao mês equivalente
líquido. Objetivo ambicioso posterior: 5%, sem ser condição mínima de sucesso.** São metas
de pesquisa, não retornos já obtidos, estimativas comprovadas nem obrigação de ganhar em
cada mês. Nunca aumentar exposição, frequência, risco ou alavancagem para cumprir a meta.

| Critério | Diretriz para implementação e avaliação |
|---|---|
| Primeiro marco econômico | Retorno mensal geométrico equivalente >=1%, com evidência suficiente e os demais critérios reportados. |
| Objetivo central | Retorno mensal geométrico equivalente >=2%, mantendo os limites de risco. |
| Objetivo ambicioso | 5% mensal equivalente, apenas como possibilidade a investigar; não forçar operações para chegar a ele. |
| Denominador principal | Patrimônio total destinado ao bot, em USDT, incluindo caixa/reserva e posições marcadas a mercado, sem duplicação de saldos. |
| Custos | Resultado líquido de taxas, spread/slippage, funding pago/recebido e infraestrutura atribuível; antes de impostos pessoais. |
| Drawdown desejável | Até 10% no período de avaliação, reportando a trajetória e as limitações de marcação. |
| Teto de aprovação histórico | Manter drawdown <=15%; não é garantia de perda máxima futura nem um stop global já implementado. |
| Risco inicial por trade | Preservar `risk_fraction=0.0025` (0,25% do patrimônio) como teto planejado de pesquisa, diferente do percentual alocado. |
| Evidência temporal para a meta econômica | Pelo menos 12 meses fora do treinamento, sem sobreposição de períodos contados, com variação de condições de mercado. |
| Etapas posteriores | Paper prospectivo e demo/reconciliação; piloto real pequeno apenas após autorização explícita e prontidão. |

A carteira destinada ao bot pode ser apenas uma parte do patrimônio do usuário ou dos
saldos na Binance. Não assumir que todos os saldos da conta pertencem a esta estratégia.
Registrar o perímetro de capital; incluir sua parcela ociosa no denominador. Não retirar
caixa da base de cálculo apenas para apresentar um retorno percentual maior.

As operações usarão frações da carteira. **Isso não muda a meta de retorno da carteira
para uma meta sobre o valor de cada ordem.** Mostrar os dois resultados separadamente:
retorno do portfólio e resultado da operação sobre o seu nocional inicial. Em futuros,
retorno sobre margem, quando aplicável numa versão posterior, é outra métrica e não
pode substituir retorno do patrimônio nem ocultar exposição nocional.

Exemplo exclusivamente aritmético, não um default: carteira de 10.000 USDT, entrada de
1.000 USDT (10%) e ganho líquido da operação de 5% produzem 50 USDT, ou 0,5% da carteira,
sem outros resultados ou fluxos. A meta central de 2% sobre essa carteira corresponderia
a 200 USDT líquidos no mês, independentemente de serem feitos poucos ou muitos trades.
**O percentual real por entrada ainda não foi definido pelo usuário.**

Medir pela curva patrimonial marcada a mercado, não apenas por trades encerrados. Não
ocultar perdas mantendo posições abertas. Registrar aportes/retiradas como fluxos, não
como lucro/prejuízo; preferir retorno ponderado pelo tempo com subperíodos delimitados
por esses fluxos. Sem fluxos e com M meses completos:

```text
retorno_mensal_equivalente = (patrimonio_final / patrimonio_inicial) ** (1 / M) - 1
```

Essa fórmula pressupõe patrimônio positivo. Insolvência/interrupção deve ser reportada,
não convertida em percentual válido. Publicar também os retornos de cada mês, meses
negativos, pior mês e drawdown. Incluir meses sem operações e não calcular a meta por
média aritmética dos trades. Não somar taxas mensais/retornos de vários modelos como se
fossem carteiras independentes financiadas pelo mesmo dinheiro.

O simulador atual já considera custos de negociação; infraestrutura e consolidação
completa de carteira exigem extensões. Separar PnL de negociação e líquido total do bot,
sem deduzir o mesmo custo duas vezes. Se custos relevantes não estiverem disponíveis,
registrar hipóteses e sensibilidade, sem afirmar rentabilidade líquida total verificada.

Resultados com menos de 12 meses ou amostra insuficiente são provisórios. Walk-forward
fora do treino pode apoiar pesquisa, mas janelas usadas para escolher a versão não são
confirmação final inédita. Separar pesquisa temporal, teste final reservado e paper;
não somá-los artificialmente para satisfazer a cobertura mínima. O período reservado
não deve voltar a orientar ajustes.

### Taxa de acerto e demais critérios preservados

A meta original de 70% de trades vencedores permanece registrada e configurada. Ela não
substitui rentabilidade: 70% com prejuízo líquido não é sucesso. Nenhum limiar existente
foi removido ou relaxado nesta revisão. Reportar separadamente o resultado econômico,
o marco de 1%, a meta central de 2%, o atendimento dos gates e a meta de acerto.

Os critérios iniciais do pacote incluem pelo menos 200 trades encerrados e não
sobrepostos, oito semanas com operações, profit factor >=1,25, expectativa líquida
positiva, drawdown <=15%, resultado positivo sob custos estressados e win rate >=70%.
O gate também exige, por padrão, limite inferior aproximado de confiança >=70%.
A exigência econômica de 12 meses é adicional: oito semanas com trades não a substituem.
Se um critério não passar, mostrar a falha, sem esconder resultados economicamente úteis.

Não aumentar risco/alavancagem, usar martingale, ocultar perdas ou reduzir custos
assumidos para fabricar aprovação. Não mudar os critérios depois de observar o teste;
qualquer revisão deve ser explícita, versionada e avaliada em novo experimento.
Nenhum resultado histórico habilita dinheiro real automaticamente.

### Alocação por operação — requisito explícito do usuário

**Cada entrada deve usar apenas uma fração configurável da carteira destinada ao bot,
e não automaticamente todo o seu capital.** Alocação, risco no stop e exposição agregada
são limites diferentes, todos aplicáveis simultaneamente. O limite por entrada é um
máximo, não uma obrigação de preencher aquele valor quando o stop permite menos risco.

| Conceito | Regra para o agente |
|---|---|
| Capital de referência | Patrimônio do portfólio do bot, com caixa e posições, reconciliado e sem contagem dupla. |
| Percentual máximo por posição | Parâmetro explícito, maior que zero e menor que 100%. Valor exato ainda pendente; 10% no exemplo não é escolha do usuário. |
| Risco monetário inicial | No máximo o menor entre 0,25% do patrimônio e o orçamento de risco agregado ainda livre. |
| Exposição total | Teto configurável sobre a soma dos nocionais absolutos de todas as posições Spot/USD-M, respeitando no máximo 1x nesta fase sem alavancagem. |
| Saldo disponível e reserva | Respeitar caixa livre, taxas, reservas de ordens pendentes e a reserva mínima configurada; não tratar caixa comprometido como disponível. |
| Posições simultâneas | A v0.1 atual permite uma por modelo/mercado. Não alegar controle global ou múltiplas posições implementados quando não existem. |

Definir o percentual usando **nocional de exposição**, não margem de futuros. Considerar
adições/pyramiding como a mesma posição para o teto, evitando fracionar uma ordem em
várias entradas para contornar o limite. Para risco/exposição agregados, posições long
e short em ativos diferentes não se anulam; reservas devem ser compartilhadas entre
mercados. Não multiplicar o capital disponível pelo número de estratégias ou modelos.

Esboço de dimensionamento, a implementar/validar de forma equivalente no backtest,
paper e adaptador futuro (não é um novo comando ou módulo já pronto):

```text
E = patrimonio do portfólio do bot antes da entrada, marcado a mercado
A = E * percentual_maximo_por_posicao
R = min(E * 0.0025, orcamento_de_risco_agregado_livre)
N_risco = R / (distancia_percentual_ate_stop + provisao_percentual_de_custos)
N = max(0, min(A_restante_na_posicao,
               N_risco,
               limite_de_exposicao_agregada_restante,
               nocional_financiavel_pelo_saldo_livre_apos_reservas_e_taxas))
quantidade = arredondar_para_baixo(N / preco_de_entrada, passo_permitido)
```

`A_restante_na_posicao` desconta nocional já comprometido naquela posição. Para uma
nova posição isolada, vale A. Custos e distâncias são conhecidos ou hipóteses explícitas
no instante da decisão, nunca dados futuros. Revalidar quantidade/risco após fills e
precificação efetiva. Um stop muito próximo não autoriza exceder o teto de alocação.
Se quantidade/notional mínimo inviabilizar a entrada, abster-se; não arredondar para
cima violando o teto. Gaps, slippage e funding podem ultrapassar o risco planejado:
este cálculo não garante a perda máxima realizada.

**Estado real do pacote:** `configs/spot.json` e `configs/usd_m.json` ainda contêm
`max_notional_equity=1.0`. O dimensionamento atual em `simulation.py` e `paper.py` usa o
menor entre esse teto e risco dividido por distância ao stop mais custos. Logo, 0,25%
é o orçamento de risco, não uma alocação de 0,25%, e o teto 1x não equivale a definir
um percentual fracionário específico por entrada. Esta revisão não alterou esses arquivos.

Antes da próxima pesquisa, fixar e registrar um limite fracionário explícito. Para a
v0.1 de uma posição por modelo, `max_notional_equity` pode expressar esse teto numa
configuração de experimento com valor estritamente abaixo de 1.0. Não confundir isso
com o controle de capital compartilhado: a camada agregada Spot/USD-M ainda deve ser
implementada antes de executar os dois mercados sobre o mesmo portfólio.

O agente pode usar uma hipótese provisória de alocação para pesquisa local, claramente
rotulada, escolhida e congelada antes de examinar o teste. Isso não bloqueia testes de
software nem implementação. Não apresentar a hipótese como percentual aprovado pelo
usuário, nem habilitá-la em dinheiro real sem a política e o capital definidos.

Os novos objetivos mensais, a cobertura econômica de 12 meses e os limites consolidados
são requisitos documentados, **não gates já implementados no CLI**. Implementar/testar
sua leitura, cálculo e relatório onde faltarem; não simplesmente adicionar chaves que
`ResearchConfig` ainda não aceita. Não declarar o requisito concluído só por editar Markdown.

Testes de aceitação a acrescentar na implementação:

1. Uma entrada respeita simultaneamente o percentual alocado e o risco, incluindo custos;
   se o teto de alocação limitar o tamanho, aceitar risco efetivo abaixo de 0,25%.
2. Stop muito estreito não leva a usar toda a carteira; stop mais distante reduz a posição.
3. Quantidade mínima, taxas, reserva ou saldo insuficientes provocam abstenção segura.
4. Ordens pendentes, fills parciais e posições entre Spot/USD-M não duplicam capital.
5. O exemplo 10.000/1.000/50 resulta em 0,5% da carteira, sem confundir 5% do trade com 5%
   da carteira; testar também mês sem operações, posições abertas e aportes/retiradas.
6. O relatório distingue amostra insuficiente, lucro líquido, marco de 1%, meta de 2%,
   win rate/gates e prontidão operacional; nenhum desses estados liga ordens reais.

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
4. Registrar universo, custos, capital de referência, percentual máximo por posição,
   limites agregados, hipóteses e divisões temporais antes da seleção. Não rodar a nova
   pesquisa como se `max_notional_equity=1.0` já fosse a política fracionária solicitada.
   Implementar/verificar sizing e métricas da seção 1. Começar com poucos símbolos;
   ampliar por liquidez e cobertura conhecidas no período, não por vencedores posteriores.
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

Reportar, no mínimo, PnL bruto, líquido de negociação e líquido total do bot; patrimônio
e capital de referência; retorno mensal geométrico equivalente e série de meses; taxas,
slippage, funding e infraestrutura; profit factor, expectativa por trade, win rate e sua
incerteza; drawdown, pior período, número de trades, duração/exposição e frequência.
Registrar percentual máximo por posição, alocação efetiva, risco planejado/realizado,
caixa/reserva e exposição agregada. Não substituir retorno do portfólio por retorno do trade.
Mostrar estabilidade por janela, estratégia, ativo, direção e regime; informar se os
resultados estão concentrados em poucos trades ou num único período.

Os estados de relatório devem distinguir:
- funcionamento do software e disponibilidade dos dados;
- evidência econômica fora do treino, cobertura de 12 meses, marco de 1%, meta central
  de 2%, resultado de custos estressados e atendimento ou não dos demais gates;
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
| `BASELINE_REPORT.md` | Comparação regras vs filtro numérico, capital/alocação/risco, meses e retorno equivalente, marcos 1%/2%, mercado/regime, custos, limitações e gates sem promessa. |
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
- Controlar percentual por posição, caixa/reserva, exposição e risco agregados entre Spot
  e USD-M, perdas diárias, concentração/correlação e quantidade de posições. Reservar saldo
  para ordens pendentes e fills parciais; não duplicar o mesmo capital entre modelos.
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
