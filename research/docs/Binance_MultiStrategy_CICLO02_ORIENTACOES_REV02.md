# Binance MultiStrategy — orientações para o ciclo 2 — revisão 2

**Data:** 28/09/2026  
**Tipo:** revisão documental; não altera código nem executa treinamento.  
**Fonte principal:** relatório do primeiro treino/walk-forward de 28/09/2026, seguido da confirmação expressa do usuário de que ele alterou os parâmetros.  
**Precedência:** esta revisão substitui `Binance_MultiStrategy_CICLO02_ORIENTACOES.md` e prevalece sobre os critérios incompatíveis do handoff revisão 3. Preserva orientações técnicas anteriores que não conflitem com a decisão atual.

## 0. Estado e limites desta entrega

O relatório recebido informa 57 testes de software aprovados, treinamento XGBoost CUDA, comparação com HistGradientBoosting e nenhum sistema aprovado. Nesta revisão esses resultados não foram reproduzidos: os CSVs, configurações locais atualizadas, pesos e logs do ciclo 1 não foram examinados. Os números abaixo são os relatados, não uma auditoria independente.

Preservar o código local mais recente, incluindo XGBoost/CUDA e recuperação de marks verificados. **Não substituir a implementação atual pelo ZIP antigo da v0.1.** Este complemento deve ser integrado como documentação e backlog. Nenhuma ordem real, treinamento ou alteração no GitHub foi executada por esta entrega.

Manter `target_not_demonstrated` e abstenção operacional. Pesquisa offline e paper diagnóstico podem prosseguir claramente separados de sinais autorizados. Laya/Jev permanecem fora deste ciclo.

## 1. Parâmetros vigentes — alteração confirmada pelo usuário

**O usuário confirmou que mudou os parâmetros. Os critérios informados no relatório do ciclo 1 são intencionais e devem ser adotados. Não são erro ou alteração não autorizada do agente. Não restaurar a política antiga nem exigir nova confirmação para reconhecer esta decisão.**

### Critérios de qualificação

| Item | Critério vigente |
|---|---|
| EV líquido | **Média do retorno líquido por operação sobre seu nocional inicial estritamente maior que 1,2%** (`EV > 0.012`, em representação fracionária). |
| Payoff | **Pelo menos 1:1** (`payoff >= 1.0`), conforme a definição utilizada no relatório e no código atual, explicitada nos artefatos. |
| Taxa de acerto | **Próxima de 70% como preferência**, não um piso obrigatório para aprovação. Reportar o valor e sua incerteza. |
| Drawdown | **Sem teto fixo de aprovação.** Reportar e buscar minimizar entre configurações que cumpram os requisitos obrigatórios. |
| Amostra | **Pelo menos 200 operações**, sem inflar a contagem com saídas parciais ou duplicação dos mesmos trades. |
| Cobertura | **Pelo menos 8 semanas ativas**, sem duplicar períodos sobrepostos. |
| Profit factor | **Pelo menos 1,25**. |
| Custos estressados | **Resultado líquido positivo com taxas e slippage dobrados**, incluindo funding observado quando aplicável. |

EV aqui é uma média da amostra de operações, não a obrigação de cada trade individual ganhar 1,2%, nem um take-profit fixo de 1,2%. Não confundir o gate histórico da estratégia com um corte de previsão por candidato que não tenha sido explicitamente definido na configuração.

**Deixar de exigir:** teto histórico de drawdown de 15%, faixa desejável de 10% como requisito de classificação, win rate obrigatório de 70% e limite inferior do intervalo de confiança >=70%. Intervalos de confiança continuam úteis como diagnóstico, mas não devem reintroduzir silenciosamente um gate revogado.

Não substituir o EV >1,2% por meta mensal de 1% ou 2%. As metas mensais anteriormente discutidas podem permanecer como referências descritivas de planejamento, separadas do gate atual. Não reprovar ou aprovar pelo objetivo mensal como se ele substituísse o critério explícito do relatório. A cobertura anterior de 12 meses também não deve ser acrescentada silenciosamente como gate desta lista: preservar o protocolo efetivamente utilizado e reportar a duração real da avaliação e suas limitações.

Sem teto de drawdown não significa eliminar stop, trailing, alocação fracionária, disponibilidade de saldo ou controles de risco por operação. Preservar a configuração atual desses controles e registrá-la. O relatório não informa o percentual exato de alocação por entrada: não inventar um valor aprovado. A confirmação de mudanças nos gates não autoriza aumentar tamanho, alavancagem ou risco para fabricar aprovação.

### Registro e aplicação

Gerar ou atualizar `PARAMETROS_VIGENTES.md` com a data desta confirmação, tabela acima, unidade de cada métrica, campos efetivos da configuração, versão/hash e funções que aplicam os gates. Isso é documentação da decisão já tomada, **não uma etapa para pedir autorização novamente ou restaurar requisitos antigos**. Atualizar AGENTS, README, protocolo e configurações conflitantes, preservando o código local mais recente e verificando as interfaces reais antes de alterar chaves.

Distinguir:

- gates obrigatórios de qualificação;
- preferências de seleção (acerto próximo de 70% e menor drawdown entre aprovados);
- métricas descritivas do portfólio;
- prontidão de execução, que não é habilitada automaticamente pela aprovação histórica.

Para cada gate, registrar se ele é aplicado por fold, por mercado/modelo ou ao agregado walk-forward. Preservar o escopo efetivamente utilizado no ciclo 1 nos resultados históricos; não mudar o nível de agregação para reclassificar uma reprovação. Para novos experimentos, declarar esse escopo antes da seleção. Não somar trades duplicados de modelos concorrentes para alcançar a amostra mínima de uma estratégia.

Preservar os resultados do ciclo 1 como `target_not_demonstrated`. A confirmação dos critérios não muda os números negativos, não aumenta a amostra e não aprova nenhum modelo.

### Denominadores e unidades

Para uma operação, `r_i = pnl_liquido_i / nocional_inicial_i`; o EV do relatório é `media(r_i)`. Não trocar pela razão entre somas de PnL e nocionais sem identificar que se trata de outra ponderação. Sua contribuição ao patrimônio na entrada, quando isolável, é `pnl_liquido_i / patrimonio_antes_da_entrada_i = f_i * r_i`, com `f_i = nocional_inicial_i / patrimonio_antes_da_entrada_i`.

Manter separadas as métricas de retorno sobre nocional, retorno em R, retorno sobre o patrimônio e eventual retorno sobre margem. A aprovação pelo EV não demonstra, sozinha, retorno mensal específico da carteira. O relatório deve continuar mostrando curva patrimonial, meses positivos/negativos, aportes/retiradas, capital ocioso, exposição e custos. Custos de infraestrutura devem ser discriminados no resultado total do bot, sem alterar silenciosamente a definição do EV de negociação utilizada pelo protocolo atual.

## 2. Leitura técnica do ciclo 1

O baseline de seleção informado é:

| Mercado | Operações | EV com custos | EV sem taxa/slippage, segundo o relatório | Drawdown informado |
|---|---:|---:|---:|---:|
| Spot | 2.013 | -0,289% | +0,011% | 91,8% |
| USD-M | 3.519 | -0,294% | +0,003% | 98,8% |

Confirmar se o cenário chamado “sem custos” ainda aplica funding. Não chamar automaticamente sua métrica de retorno bruto puro antes dessa conferência.

Com os pressupostos usados, o custo aproximado de ida e volta é 30 bp em Spot (0,30%) e 20 bp em USD-M (0,20%, antes de funding), e o estresse é 60/40 bp. Esses valores são hipóteses do experimento; não representam taxas verificadas da conta do usuário. Valores exatos dependem dos nocionais/preços de cada lado.

A média informada no cenário sem taxa/slippage é pequena em comparação com esses custos. Isso motiva investigar horizontes, entradas, saídas e giro antes de aumentar a busca de hiperparâmetros. Não demonstra que toda estratégia individual seja inútil: a média agregada pode esconder heterogeneidade. Também não demonstra que um filtro consiga explorar essa heterogeneidade.

O melhor EV de seleção citado, +0,116% em 13 trades, virou -0,288% em 31 trades de teste. Trata-se de insuficiência de evidência e falha de generalização naquele experimento, não de uma versão quase aprovada. Zero ou um trade em Spot não permitem estimar consistência.

A comparação XGBoost CUDA versus HGB CPU mistura dois algoritmos e dois backends. Não apresentar seus retornos como evidência de que GPU melhora ou piora trading. Para medir aceleração isoladamente, comparar XGBoost CPU/GPU com dados e hiperparâmetros equivalentes, registrando tempo, memória, versões e diferenças numéricas. Esse benchmark é opcional, não prioridade financeira.

## 3. Auditoria P0 — antes de novos treinos extensos

### 3.1 Contabilidade e decomposição de custos

Gerar `ACCOUNTING_AUDIT.md` e ledger por trade com timestamps, IDs, estratégia, direção, quantidade, preços de referência, fills adversos, taxas de entrada/saída, funding, nocional inicial, risco, PnL líquido e marcações de patrimônio.

Se slippage já está nos fills, não subtraí-lo novamente do PnL. Seu impacto pode aparecer como decomposição em relação a preços de referência, sem dupla cobrança. Funding é fluxo observado com sinal correto e timestamp de liquidação; mark price não é necessariamente preço executável.

Reconciliar especificamente a diferença do USD-M: de +0,003% para -0,294% são 29,7 bp, enquanto a aproximação de taxas/slippage declarada é 20 bp. A diferença não prova defeito: os cenários podem executar operações diferentes, usar preços de entrada/saída que alteram stops, ter efeitos de funding ou outras diferenças de ponderação. Identificar a causa, em vez de atribuir todo o desvio a taxas.

Produzir duas comparações distintas:

- **Ledger pareado:** mesmas operações, quantidades e timestamps de referência; decompor contabilmente custos sob convenção explícita. É diagnóstico contrafactual, não estratégia executável certificada.
- **Replay integral:** executar novamente todo o motor com custos alterados, permitindo que capital, fills, proteções e operações mudem; mostrar IDs divergentes e explicar os efeitos.

### 3.2 Drawdown e capital

Auditar a definição: `pico_t = max(equity_0,...,equity_t)`; `drawdown_t = 1 - equity_t / pico_t`; `max_drawdown = max(drawdown_t)`. Queda percentual sobre capital inicial é outra métrica. A frase do relatório “drawdown sobre patrimônio inicial” deve ser esclarecida no código, não presumida correta ou incorreta.

Mostrar curva marcada a mercado, perdas não realizadas, retorno final, pior mês e exposição. Drawdown pequeno de um modelo quase sempre parado não comprova qualidade. Risco de 0,25% por trade também não limita a perda acumulada de uma sequência extensa de trades ruins.

Conferir `max_notional_equity` e qualquer teto novo: a revisão 3 documentava default antigo 1.0, ainda a alterar. O relatório atual não comprova que a limitação fracionária foi implementada. Registrar limite configurado, alocação máxima/média efetiva, reservas, risco inicial e violações. Proibir capital duplicado entre Spot e USD-M num portfólio consolidado.

### 3.3 Funil de abstenção

Exportar `SIGNAL_FUNNEL.csv`, por fold, mercado, ativo, estratégia, direção e regime, com contagens e motivos de rejeição:

```text
candles elegíveis -> candidatos de regra -> filtros de dados/regime
-> corte de probabilidade -> corte do regressor -> viabilidade após custos
-> sizing/saldo -> bloqueio por posição aberta -> simulações executadas
```

Adaptar a ordem ao código real, documentando-a. Registrar rejeições exclusivas de primeira falha e flags de todas as condições, evitando contar a mesma oportunidade várias vezes em totais incompatíveis.

Distinguir `diagnostic_threshold` de um limiar aprovado. Se nenhum parâmetro passa, um “melhor entre reprovados” pode ser avaliado offline, nunca marcado como deployable. Verificar se `target_not_demonstrated` não está zerando inadvertidamente um backtest diagnóstico; não remover esse bloqueio na execução operacional.

### 3.4 Labels e probabilidades

Definir matematicamente o denominador de R e a conversão R/retorno por nocional. Não comparar 1,2%, 1,2 R e probabilidade como unidades intercambiáveis.

Conferir se `stop_fraction` e variáveis de volatilidade usam somente informação disponível na decisão. Stops baseados em ATR do candle do sinal podem ser causais; normalizações com preço futuro de preenchimento precisam de auditoria. Recalcular features usando dados truncados no instante da decisão e testar igualdade.

Avaliar classificador e regressor em seleção temporal: baseline de frequência da classe, calibração, Brier/log loss quando aplicável, cobertura e retorno por faixa de score, e erro do retorno previsto. Accuracy alta de prever sempre perda não é mérito suficiente. Se pesos de classe forem usados, conferir calibração posterior sem vazamento.

## 4. Novo desenho de pesquisa — pequeno e explicável

### Separar observação de duração da operação

Manter ingestão e proteção em 1 minuto; isso não exige sinais e risco baseados em oscilações de 1 minuto. Proposta de experimento: decisões de entrada com candles fechados de 15 minutos e contexto de 1h/4h, preservando execução/monitoramento no fluxo de 1 minuto. Trata-se de hipótese, não de melhoria comprovada.

Começar investigando duas famílias já existentes — retomada de tendência e rompimento/continuação — sem excluir definitivamente reversão nem as outras estratégias. Primeiro publicar decomposição de todas as oito; documentar por que cada família entra ou não no experimento.

### Medir trajetória antes de redesenhar a saída

Gerar `PATH_DIAGNOSTICS.csv` com excursão favorável/adversa máxima (MFE/MAE), horizonte fixo predefinido, duração, causa da saída, distância do stop/alvo, proporção do risco consumida por custos, funding e resultado líquido. Calcular para vencedores e perdedores, não apenas exemplos favoráveis.

Essas medidas usam futuro e são apenas diagnósticos/rótulos, nunca features de entrada. Ao observar trajetórias além da saída original, rotular o resultado como contrafactual, sem contabilizá-lo como ganho capturado. Candles com ordem intraminuto ambígua exigem convenção conservadora ou dados adequados.

Perguntas a responder: o preço chegou a produzir movimento suficiente para pagar os custos? O trailing devolveu ganho após ativação? As saídas ocorreram majoritariamente por time stop, stop ou alvo? O resultado depende de poucas operações?

### Matriz pequena proposta

Depois da auditoria, congelar no conjunto permitido uma matriz com **até 12 variantes por mercado**: duas famílias, dois horizontes máximos (por exemplo 6h e 24h) e três políticas de saída (alvo/stop fixos em ATR, trailing ATR com ativação, saída por perda de tendência com hard stop). Números são hipóteses de pesquisa, não políticas aprovadas de capital.

Definir todos os múltiplos, custos, critérios de tendência/volatilidade e alocação antes de avaliar. Não adicionar um produto cartesiano oculto de dezenas de parâmetros. Toda tentativa conta no orçamento de experimentos. Se a matriz mudar por diagnóstico, criar nova rodada identificada.

Saída mais longa pode melhorar, piorar ou não alterar a expectativa. Não alongar indefinidamente posições perdedoras. Manter stop inicial e horizonte finito. Stop mais distante reduz a quantidade para respeitar risco e alocação; nunca aumentar o risco monetário para compensar menor frequência. USD-M deve carregar funding durante todo o novo horizonte.

### Comparações e ML

Comparar nas mesmas condições regras, regras com filtros causais de regime/custos, e regras com filtro numérico. Examinar grupos de custo relativo, por exemplo `custo_round_trip / distancia_inicial_do_stop`, para testar se o ganho das features de ATR/stop reflete principalmente viabilidade econômica.

Não assumir que basta escolher maior ATR: também avaliar risco, slippage e estabilidade. Importância de ganho em árvore não é vantagem financeira nem causalidade. Usar ablação por grupos correlacionados e, quando apropriado, permutação em blocos temporais como diagnóstico complementar; não interpretar perturbações artificiais como prova causal.

Não exigir baseline agregado positivo como condição lógica para estudar qualquer filtro: um filtro pode, em princípio, selecionar um subconjunto diferente. Exigir evidência causalmente disponível e temporalmente validada para a seleção. Evitar treinos caros repetidos quando nem as regras nem sua estratificação oferecem um mecanismo plausível.

Recriar labels após mudar entradas/saídas, custos ou horizonte. Não reaproveitar pesos, calibração ou respostas antigas como se descrevessem a estratégia nova. Treinar e calibrar exclusivamente nos períodos permitidos. Comparar HGB e XGBoost preservados, sem ampliar o catálogo de modelos nesta rodada.

## 5. Tempo, fronteiras e dados

Período informado: 13/08/2024 00:00 UTC a 01/09/2026 00:00 UTC, fim exclusivo, BTC/ETH, 2.157.120 linhas por mercado. Conferir datas exatas dos folds em `configs/walk_forward.usdm_exploratory.json`; o tamanho total do dataset não é tamanho do teste.

Continuar tratando os períodos históricos já examinados como exploratórios. Não mudar o nome de uma pasta ou os folds para anunciar um novo holdout. Janelas usadas para escolher a versão passam a ser parte do desenvolvimento. Reservar confirmação posterior independente e iniciar paper prospectivo somente com versão/configuração e início registrados; este documento não agenda nem inicia coleta.

Se o horizonte crescer para 24h, a separação de labels deve acompanhá-lo. Auditar purga usando intervalos efetivos `[decisao, fim_do_label]`, sem interseção indevida entre treino, calibração, seleção e avaliação. Qualquer gap/embargo fixo deve ser recalculado para o desenho novo; não manter cegamente os 480 minutos antigos. Lookback causal para aquecimento não autoriza usar labels futuros.

Não interpolar marks ausentes. A questão #483 relata a lacuna de 12/08/2024 10:02–10:03 UTC, mas isso não valida os manifests locais. Para ampliar história no futuro, investigar segmentos oficiais contínuos e reinicialização de indicadores, invalidando trades/labels que cruzam lacunas. Não excluir arbitrariamente períodos difíceis por serem negativos.

## 6. Entregáveis e testes do ciclo 2

Entregar `PARAMETROS_VIGENTES.md`, `ACCOUNTING_AUDIT.md`, `SIGNAL_FUNNEL.csv`, `PATH_DIAGNOSTICS.csv`, configuração congelada dos experimentos, log de todas as tentativas, relatórios por segmento, trades e equity mensais, além de `NEXT_ITERATION.md`. A tarefa anterior de reconciliar uma suposta alteração não autorizada foi substituída: o usuário confirmou os parâmetros.

O relatório deve distinguir: dados/software; EV líquido e atendimento ao piso >1,2%; payoff >=1; profit factor >=1,25; amostra >=200 e semanas ativas >=8; resultado sob estresse; preferência de acerto próxima de 70%; drawdown reportado sem teto; lucro e retorno do portfólio; política de alocação/risco; cobertura temporal; prontidão operacional. Campo ausente ou cálculo indisponível é `not_evaluated`, não aprovado nem zero arbitrário. Para payoff, explicitar se a média de ganhos e perdas usa PnL monetário ou retornos normalizados; não confundir payoff observado com a razão alvo/stop planejada.

Testes mínimos específicos:

1. Separação de R, retorno por nocional, fração alocada, retorno da carteira e margem.
2. Drawdown de 10.000 -> 12.000 -> 10.800 igual a 10%, não 12% sobre capital inicial.
3. Carteira 10.000, nocional 1.000, PnL líquido +50: +5% no trade e +0,5% na carteira.
4. Stop estreito não ultrapassa teto fracionário; stop amplo reduz quantidade; saldo/risco agregado permanecem válidos.
5. Slippage incorporado em fill não debitado outra vez; funding com lado e tempo corretos; ledger reconcilia PnL e equity.
6. Gates de pesquisa, diagnóstico e execução não se confundem; nenhum candidato aprovado preserva abstenção operacional.
7. Horizonte ampliado não permite label cruzar fronteiras; features truncadas não dependem de candles futuros.
8. Sinais em timeframes maiores usam somente candles completos; proteção de posições não espera a próxima decisão de entrada.
9. Mudança de saídas invalida labels/modelos incompatíveis; custos estressados usam as mesmas regras declaradas e funding aplicável.
10. Meses sem trades, posições abertas, aportes/retiradas e capital compartilhado não distorcem retorno.
11. EV exatamente igual a 1,2% não passa no critério estrito; usar precisão completa no gate e arredondamento apenas na apresentação.
12. Win rate inferior a 70% não causa reprovação automática quando todos os gates obrigatórios passam; a preferência continua reportada. O limite inferior de confiança antigo não bloqueia aprovação.
13. Drawdown acima de 15% não causa reprovação por um teto que foi removido; deve aparecer integralmente no relatório e no comparativo entre aprovados.
14. Cumprir uma antiga meta mensal não compensa EV <=1,2%, payoff <1, amostra insuficiente, profit factor <1,25 ou prejuízo sob custos estressados.
15. Não apresentar um limiar de take-profit ou de probabilidade como implementação suficiente do gate de EV médio por operação.

Não inventar comandos CLI para arquivos ainda não implementados. Verificar as interfaces reais, implementar extensões com testes e registrar somente execuções efetivamente realizadas. Os 57 testes relatados são um ponto de partida a reproduzir, não a certificação das novas regras.

## 7. Decisão de encerramento da rodada

O objetivo imediato é pesquisar combinações de sinal, horizonte, saída e custo capazes de atender ao EV líquido >1,2% sobre o nocional por operação, payoff >=1 e demais gates vigentes, sob sizing fracionário. Melhorar de EV negativo para positivo pode ser progresso de pesquisa, mas não é aprovação se o piso de 1,2% ou qualquer outro requisito obrigatório falhar. O retorno da carteira continua sendo medido separadamente.

Aplicar os parâmetros do relatório, cuja alteração foi confirmada pelo usuário. Entre configurações que cumpram os gates obrigatórios, comparar drawdown e preferência de acerto, sem transformar preferências em novas barreiras ocultas. Definir a regra de desempate antes de avaliar novos testes; menor drawdown não aprova um sistema sem trades. Preservar nos relatórios o escopo de avaliação por fold/agregado e a independência temporal, sem somar amostras incompatíveis para fabricar aprovação.

Se a rodada não produzir evidência, publicar as hipóteses rejeitadas e o diagnóstico. Não migrar para Laya/Jev para maquiar a falta de vantagem, não aumentar alavancagem e não executar pesquisa com capital real. A investigação pode continuar com outra hipótese registrada, sem promessa de rentabilidade.

## Referências e proveniência

- Confirmação expressa do usuário em 28/09/2026: ele alterou os parâmetros; considerar as informações do relatório. Fonte de autoridade para os gates vigentes desta revisão.
- Handoff revisão 3 fornecido na conversa: histórico de arquitetura, alocação e estado antigo da v0.1. Seus critérios incompatíveis de EV, acerto e drawdown não prevalecem sobre a decisão atual. Documento distinto do código local atualizado.
- Relatório do ciclo 1 fornecido pelo usuário em 28/09/2026: fonte dos números, caminhos e execuções relatadas. Não reproduzido nesta revisão.
- Referências externas abaixo preservadas da edição anterior, sem nova consulta nesta revisão documental.
- scikit-learn, *Tuning the decision threshold for class prediction*: distinção entre score e decisão, métricas adequadas e cautela ao ajustar o corte. Consulta em 28/09/2026: https://scikit-learn.org/stable/modules/classification_threshold.html
- scikit-learn, *Permutation feature importance*: importância é dependente do modelo, exige avaliação fora do treino e pode ser enganosa com features correlacionadas. Consulta em 28/09/2026: https://scikit-learn.org/stable/modules/permutation_importance.html
- scikit-learn, *Cross-validation: evaluating estimator performance*: ajuste repetido no teste contamina a avaliação; separação temporal deve respeitar dependência temporal. Consulta em 28/09/2026: https://scikit-learn.org/stable/modules/cross_validation.html
- XGBoost, *GPU Support*: backend CUDA de treinamento/inferência; não evidência de rentabilidade. Consulta em 28/09/2026: https://xgboost.readthedocs.io/en/stable/gpu/index.html
- Binance public-data, issue #483: relato de dados faltantes, incluindo 12/08/2024 10:02–10:03 UTC. Consulta em 28/09/2026: https://github.com/binance/binance-public-data/issues/483


## Registro desta revisão documental

Correção principal: reconhecer como autorizadas as alterações dos parâmetros feitas pelo usuário e remover as orientações de restauração dos critérios antigos. Preservados os diagnósticos técnicos, custos e números fornecidos no relatório e o plano de pesquisa incremental, sem Laya/Jev. Nenhum código local, arquivo de configuração executável, resultado histórico, peso treinado ou repositório remoto foi modificado nesta entrega; a integração pelo agente permanece pendente.
