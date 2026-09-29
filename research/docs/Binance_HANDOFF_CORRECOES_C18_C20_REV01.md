# Handoff para o agente — correções operacionais C18 e C20

**Revisão:** 1 · 29/09/2026  
**Repositório:** `XSirch/laya-trader-binance`  
**Referência da revisão:** `43ee00f948b87c0bedd2749b09c9639b3a514bf8` (`43ee00f`)  
**Objetivo desta tarefa:** corrigir e testar o acompanhamento/contabilidade do paper C18 e a qualificação/temporalidade do coletor C20. Não iniciar outra busca de estratégia ou treinamento.

## 1. Instrução principal

Implemente as correções descritas abaixo no checkout atual, com testes de regressão e relatório verificável. Primeiro confira a `main` atual, as instruções do repositório e eventuais alterações posteriores ao commit de referência. Não faça checkout destrutivo de `43ee00f` nem sobrescreva trabalho posterior. Se um problema já estiver corrigido, confirme com teste e registre a evidência em vez de reintroduzir uma versão antiga.

Este documento consolida as ações da última revisão. Não é uma nova entrega do código v0.1, não substitui a implementação atual e não restaura parâmetros antigos. As especificações de implementação propostas aqui devem ser diferenciadas dos comportamentos observados na revisão.

**Concluir uma correção de software não aprova uma estratégia financeira.** Não alterar parâmetros econômicos, modelos, thresholds ou janelas para fazer resultados passarem. Não chamar Laya/Jev, consumir APIs pagas, treinar novamente, enviar ordens reais ou usar credenciais da Binance nesta tarefa. Preserve experimentos e processos JEV/`forward_paper_v2` que não fazem parte destas correções.

## 2. Estado de referência e limites da evidência

No commit revisado, C20 já possui coletor e testes; deixou de ser apenas uma proposta. O ledger informa 18 testes focados e `compileall` aprovados. Isso é o resultado registrado pelo agente anterior, não uma suíte integral reexecutada para produzir este handoff.

O último registro inspecionado não indicava conexão C20 iniciada. O T0 documental é `2026-09-30T00:00:00Z` e o término máximo exclusivo é `2027-01-20T00:00:00Z` (112 dias). Em São Paulo, o T0 equivale a 29/09/2026 às 21h. Confirme o estado local real; a existência dessa data no documento não prova processo ativo e não autoriza reiniciar ou reprogramar uma série.

C18 tem modelo HGB estático e infraestrutura paper separados. O primeiro sinal elegível documentado é `2026-10-05T01:00:00Z`, equivalente a 04/10/2026 às 22h de São Paulo. Na captura inicial registrada não houve inferência nem trade prospectivo. Não presumir que esse estado continua atual sem ler os artefatos locais.

As duas reproduções anexas usam **métodos transcritos, objetos artificiais e dados sintéticos**, não importam o módulo integral do repositório. Servem como evidência inicial e orientação para testes. Reproduza os problemas no módulo real antes de afirmar que foram corrigidos. Nenhuma reprodução representa um atraso real observado no feed ou uma execução financeira.

## 3. Critérios econômicos que NÃO devem mudar

Aplicar conforme `research/docs/PARAMETROS_VIGENTES.md` e a confirmação do usuário, preservando variantes e mercados separados:

| Critério | Definição vigente |
|---|---|
| EV-base | Média de `net_pnl / nocional_inicial`, estritamente superior a 1,2% por operação (`> 0.012`). Não é retorno mensal nem piso para cada trade individual. |
| Payoff-base | Média dos retornos líquidos positivos dividida pelo módulo da média dos retornos líquidos negativos; mínimo 1,0. |
| Profit factor-base | Soma dos **PnLs monetários** positivos dividida pelo módulo da soma dos PnLs monetários negativos; mínimo 1,25. |
| Amostra | Pelo menos 200 operações/episódios completos, únicos, sem multiplicar fills ou rebalanceamentos. Não somar mercados, variantes, backends ou folds distintos para fabricar a amostra. |
| Cobertura | Pelo menos oito semanas ativas. Não significa 200 trades a cada oito semanas. |
| Stress | PnL agregado positivo com taxa e slippage dobrados, mantendo funding observado em USD-M. EV, payoff e PF de stress continuam diagnósticos, não novos gates. |
| Acerto | Preferência próxima de 70%, não piso obrigatório e não aprovação inferida do score do modelo. |
| Drawdown | Sem teto fixo de aprovação; medir e comparar entre configurações que atendam aos demais critérios. |

Manter alocação fracionária e os limites de cada experimento. Não equiparar risco de 0,25% a percentual alocado, não aumentar nocional/alavancagem para cumprir a meta e não reconfigurar o sizing durante esta correção operacional. Eventuais divergências de sizing em outros estudos devem ser reportadas separadamente, não corrigidas silenciosamente junto com C18/C20.

Não restaurar a meta antiga de 50% CAGR/10% DD, o teto de 15% de DD, acerto obrigatório de 70% ou intervalo inferior de confiança obrigatório. As metas mensais discutidas anteriormente não substituem o gate vigente de EV por operação.

## 4. P0 — C18: acompanhamento frequente sem mudar a decisão semanal

### Evidência da revisão

- `scripts/run_c18_lowvol_hgb_paper_tick.cmd` executa um único `tick` e termina.
- O agendamento documentado é semanal.
- `src/jev_trader/lowvol_hgb_account.py::advance()` rejeita um intervalo superior a 65 minutos quando existem posições abertas (`MAX_GAP_MS`).
- Portanto, se apenas a tarefa semanal estiver ativa, a atualização posterior à abertura de uma posição falhará. Isso é uma consequência do código/agendamento inspecionados, não uma falha observada na máquina do usuário.

### Implementação requerida

1. Inspecionar tarefa, processos, logs e último estado locais. Não presumir que inexiste um coletor intermediário; verificar.
2. Separar explicitamente **observação/contabilização** de **decisão/rebalanceamento**. O modelo e a janela semanal de decisão continuam congelados.
3. Preparar acompanhamento com intervalo inferior a 65 minutos. **Proposta operacional:** a cada 15 minutos, sem inferência ou rebalanceamento fora da janela semanal. Essa cadência é uma proposta de implementação, não uma nova escolha econômica do usuário.
4. Impedir processos concorrentes, execução duplicada da decisão semanal e contabilização duplicada de funding. Uma repetição do tick não pode produzir outra ordem simulada da mesma decisão.
5. Manter o guard de lacuna. Se a máquina suspender ou faltar observação por tempo excessivo com posição aberta, registrar a interrupção e o estado afetado. Não continuar a curva como se a continuidade estivesse provada e não inventar fills históricos.
6. Expor heartbeat/última observação, idade, próxima janela de decisão, posições abertas e motivo de bloqueio. Documentar as dependências de sessão, energia e internet do executor local.
7. Registrar a mudança de orquestração e os hashes sem alterar pesos, features, limiar 0,70, custos ou regra de posição C18. Qualquer ativação/reagendamento deve respeitar a autorização operacional local existente; não criar tarefa duplicada.

### Aceite

- Teste com relógio e transporte artificiais atravessando pelo menos oito dias, com posição aberta e funding: marcações frequentes funcionam, e decisões só ocorrem nas janelas permitidas.
- Intervalos de até 65 minutos e superiores a 65 minutos são testados separadamente; o guard permanece efetivo.
- Reinício, retry e sobreposição de tarefas não duplicam decisões, episódios, fees ou funding.
- Se já houve lacuna real, o relatório a preserva; nenhum replay posterior é apresentado como observação prospectiva contínua.

## 5. P0 — C18: corrigir profit factor monetário

### Evidência da revisão

`src/jev_trader/lowvol_hgb_paper.py::_metrics()` usa `net_return_on_entry_notional` para somar ganhos/perdas no campo `profit_factor` e no gate. Isso diverge da definição monetária em `PARAMETROS_VIGENTES.md` quando os tamanhos das posições variam.

### Implementação requerida

Calcular PF e seu gate de 1,25 a partir de `net_pnl` dos episódios completos. Fazer o mesmo para o PF diagnóstico do stress. Preservar EV e payoff nas unidades registradas:

```text
EV = média(net_pnl / entry_notional)
payoff = média(retornos > 0) / abs(média(retornos < 0))
PF_monetario = soma(net_pnl > 0) / abs(soma(net_pnl < 0))
```

A notação das somas acima significa somar os valores que satisfazem a condição, não contar booleanos. Não descontar novamente taxas/slippage/funding de um `net_pnl` já líquido. Se uma razão de retornos normalizados continuar útil, publicá-la com outro nome e não usá-la como PF monetário.

Tratar ausência de trades, ganhos ou perdas explicitamente, conforme a regra vigente de disponibilidade da métrica. Não transformar divisão por zero ou falta de amostra em aprovação. Verificar que relatório e gate usem exatamente a mesma definição corrigida.

### Aceite

| Exemplo sintético | Resultado obrigatório |
|---|---|
| Trade A: nocional 1.000, PnL +20; trade B: nocional 100, PnL −10 | PF monetário = **2,0**, não 0,2. |
| Mesmo exemplo | EV = **−4%**; a correção do PF não altera o cálculo de EV. |
| Uma perda muito maior em dinheiro, apesar de pequenos percentuais | PF reflete os valores monetários, não uma média de percentuais. |
| Base e stress com custos distintos | Cada conta usa seus PnLs, sem misturar episódios nem descontar custos duas vezes. |
| Zero trades ou amostra insuficiente | Sem aprovação. |

Preservar relatórios antigos. Se já houver episódios C18, recalcular a métrica em relatório corrigido identificado, sem inventar novos fills e sem sobrescrever a evidência anterior.

## 6. P1 — C20: implementar o gate de qualificação dos primeiros 14 dias

### Evidência da revisão

`DailyStore` grava linhas, linhas válidas e hashes. `complete_utc_day` verifica a cobertura estrutural do arquivo, não o gate de qualidade de 99%. No fluxo revisado não foi localizada uma decisão automática acumulada de 13/14 dias nem a interrupção exigida pelo protocolo ao reprovar.

### Implementação requerida

- Separar **arquivo estruturalmente completo**, **qualidade diária** e **qualificação do piloto**. Um dia com 86.400 linhas pode conter muitas lacunas inválidas.
- Considerar os primeiros 14 dias UTC ancorados no T0 registrado; não escolher depois os 14 melhores dias e não excluir dias ruins do denominador.
- Verificar hashes, unicidade/ordem dos segundos e integridade do armazenamento antes de confiar nas contagens.
- Aplicar pelo menos 99% de segundos válidos por dia e pelo menos 13 dias qualificados em 14. Para um dia UTC de 86.400 segundos, 85.536 válidos correspondem exatamente a 99%.
- Exigir também ausência de defeitos inexplicados de parsing, ordenação, armazenamento ou hashes. Uma soma de percentuais não resolve sozinha essa condição: manter pendências identificadas e sua resolução registrada.
- No encerramento do dia 14, emitir decisão persistida. Se reprovar, parar a série conforme o protocolo, preservando os dados e a causa. Não gerar linhas futuras até o término dos 112 dias ao efetuar essa parada antecipada.
- Retomada após a decisão de reprovação não pode ignorar o estado salvo e reativar a série silenciosamente. Uma eventual nova coleta exige registro próprio, não reset do histórico.
- Separar cobertura estrutural, validade de conteúdo e qualificação temporal. O gate de relógio não deve desaparecer dentro de um único booleano de aprovação.

**Proposta de organização, ainda a implementar:** relatório `source_quality_report.json` com estados `pending`, `qualified`, `failed` e `review_required`, anexado ao manifesto sem reescrever dias já finalizados. Os nomes são sugestões, não APIs existentes.

### Aceite

- 13/14 dias com >=99% e nenhuma pendência inexplicada: qualifica a fonte.
- 12/14: reprova e interrompe; 85.535 segundos válidos não atingem 99% de um dia.
- Dia ausente, dia apenas preenchido com lacunas e arquivo completo de baixa qualidade não contam como dias qualificados.
- Reinício reproduz a mesma decisão usando a mesma janela, sem reiniciar a contagem.
- Uma fonte qualificada não cria labels, executa treinamento ou habilita operações.

## 7. P1 — C20: distinguir recebimento recente de evento recente

### Evidência e reprodução

Em `build_sample_row()`, `quote_age_ms` depende do relógio de recebimento. A reprodução anexa usa evento de 60 segundos atrás recebido há 100 ms e relógio declarado qualificado: a versão transcrita produz `sample_valid = 1`.

Esse resultado não demonstra atraso real do stream. Demonstra que a verificação atual pode tratar informação antiga entregue recentemente como cotação fresca. Reproduzir essa situação importando o módulo verdadeiro.

### Implementação requerida

- Preservar separadamente os timestamps recebidos `E`/`T`, UTC de recepção e relógio monotônico. Não substituir timestamps originais por horários ajustados.
- Medir idade de recepção e idade do evento de forma distinta. Considerar offset, incerteza e validade temporal da sonda ao comparar tempo do servidor com tempo local.
- Aplicar o limite de frescor previsto no protocolo (cinco segundos) com semântica explícita. Atribuir a `E` e `T` seus papéis documentados, sem presumir que sejam o mesmo instante.
- Se não for possível determinar a atualidade temporal, registrar **desconhecida/não qualificada**, não “fresca” por default. Preservar dados brutos úteis para inspeção, mas não apresentá-los como elegíveis para execução simulada ou features de latência.
- Proposta de campos versionados: `receipt_fresh`, `event_freshness`, `transport_valid`, `temporal_valid` e `quality_flags`. Não alterar silenciosamente o significado de colunas já gravadas; documentar a equivalência ou diferença em relação ao schema anterior.
- Manter separados os gates de conteúdo e de relógio. Acrescentar diagnóstico temporal não deve relaxar a cobertura original ou reclassificar retroativamente dados já qualificados sem uma correção documentada.
- Garantir que uma cotação recebida depois do fechamento de um segundo não entre naquele segundo retrospectivamente. Uma amostra contendo o último evento do segundo só pode ser usada depois de disponível.

### Relógio

A medição anterior foi offset estimado +342,611 ms, RTT 544,549 ms e incerteza 273,275 ms, com `clock_unqualified`. Isso não é uma medição atual. O código revisado exige `abs(offset) + uncertainty <= 100 ms`; manter o critério sem relaxá-lo para conseguir passar.

Verificar sincronização no host e qualidade das sondas. Corrigir o relógio local não garante incerteza de rede inferior a 100 ms. Não requerer nem alterar privilégios do Windows silenciosamente. Sem qualificação, registrar a limitação e impedir uso indevido de latência. Uma cotação com validade de conteúdo não equivale a uma medição temporal qualificada.

### Aceite

- Evento de 60 s recebido há 100 ms não é classificado como temporalmente fresco.
- Evento e recepção recentes, com relógio qualificado, passam dentro dos limites registrados.
- Testar as fronteiras do limite de cinco segundos e incerteza temporal que cruza a fronteira.
- Sonda expirada, ausente, com horário inconsistente ou offset excessivo não habilita latência.
- Saltos reais do relógio e backlog não se transformam em amostras retroativas válidas.
- IDs não consecutivos continuam sendo registrados; não presumir que cada salto prove perda de pacote.

## 8. P1 — C20: respeitar o término exclusivo e encerrar corretamente

### Evidência e reprodução

`_flush_until()` não limita seu argumento ao término da janela. Na reprodução isolada, avançar dois segundos além de `end_epoch` grava duas linhas fora do intervalo; o flush final até `end_epoch` acusa `wall_clock_regressed_during_capture`, embora não tenha havido regressão real do relógio.

### Implementação requerida

Garantir que toda amostra pertença ao intervalo `[T0, Tend)`. Revalidar término após handshake, `recv`, timeout, backoff e rotação de conexão. Não gravar uma linha cujo segundo seja igual ou posterior a `Tend`.

O encerramento e a finalização de arquivos/manifests devem ser idempotentes e coerentes. Limitar um flush ao fim planejado não deve ser confundido com regressão real de relógio; o detector de regressão verdadeira continua necessário.

Em parada antecipada por reprovação/erro, não preencher o futuro até `Tend`. Em reinício, registrar apenas segundos passados realmente não observados como lacunas explícitas, nunca como cotações. Impedir conexão depois do fim registrado.

### Aceite

- Na reprodução `end_epoch + 2`, nenhuma amostra fora da janela e nenhum falso erro de regressão.
- Handshake, espera de reconexão e recebimento atravessando `Tend` encerram corretamente.
- Repetir finalização não duplica manifesto e não altera arquivo com hash já registrado.
- Reinício antes do fim preserva amostras e evidencia lacunas; reinício após o fim não abre socket.
- A última linha possível é `Tend - 1 segundo`; regressão real de relógio permanece detectável.

## 9. Preservação dos experimentos congelados

Não contornar verificações de hash para permitir as alterações. Conferir quais verificações protegem modelo, treinamento, configuração e código de execução antes de editar.

Registrar emendas corretivas append-only com motivo, arquivos, versões, hashes antigos/novos e comparação de comportamento. O modelo estático C18 e seus dados de treinamento não precisam mudar para corrigir PF ou agendamento; preservá-los.

Se C18/C20 já tiverem dados coletados, manter o schema e os registros antigos. Mudanças de medição devem ter versão e período identificáveis. Não unir segmentos incompatíveis como uma série homogênea, não mover T0 retroativamente e não reconstruir dados que nunca foram capturados. Se a alteração exigir um sucessor de protocolo, explicar o motivo e preservar o original, em vez de invalidar silenciosamente toda a trilha.

Não modificar rotas/modelos de experimentos JEV existentes. Não repetir C14 de EV decomposto, C16 de transferência ou outros estudos financeiros para validar uma correção de infraestrutura.

## 10. Organização e execução dos testes

Ler primeiro:

- `AGENTS.md` onde existir, `research/AGENTS.md` e `research/docs/PARAMETROS_VIGENTES.md`.
- `research/docs/NEXT_ITERATION.md` e `research/EXPERIMENTS.jsonl`.
- Protocolos C18 e C20 e os arquivos de código citados neste handoff.
- Os dois arquivos em `evidencias/` deste pacote.

Executar os testes existentes nas dependências/ambientes previstos pelo checkout. Acrescentar testes que importem código de produção, não apenas cópias de funções. Os casos transcritos anexos continuam identificados como evidência da versão anterior.

Comando conhecido para os testes focados já existentes, a partir de `research/`:

```powershell
uv run pytest -q tests/test_c20_capture.py
```

Adicionar/adaptar testes C18 no pacote correspondente da raiz. Não assumir que o ambiente da raiz e o de `research/` sejam intercambiáveis. Registrar comandos, versão de Python, dependências e contagens realmente executadas; não inventar nomes de testes existentes.

Priorizar testes offline com relógio e transporte artificiais. Não abrir uma coleta de 112 dias ou chamar um `tick` mutante sobre o banco ativo só para fazer um smoke test. Verificações públicas pontuais, quando já autorizadas no fluxo local, devem ser separadas da série prospectiva e nunca usar endpoints de ordens.

Se houver bloqueio de ambiente, dependência ou privilégio, implementar e validar o restante permitido e registrar a limitação exata. Não marcar o item bloqueado como aprovado.

## 11. Documentação e entrega esperada

Atualizar o estado operacional em `NEXT_ITERATION.md` e registrar as correções no ledger. Corrigir o README raiz para encaminhar o agente aos parâmetros atuais, preservando as metas antigas como contexto histórico, não como instrução vigente.

Entregar um relatório único, com caminho sugerido `research/docs/REVISAO_C18_C20_CORRECOES_2026-09-29.md`. Esse arquivo ainda deve ser criado pelo agente, não é um relatório já existente.

O relatório deve conter:

| Item | Evidência mínima |
|---|---|
| C18 acompanhamento | Agendamento/supervisor preparado, cadência real verificada quando autorizado, teste de múltiplos dias e distinção entre observação e decisão. |
| C18 PF | Exemplo monetário testado, mesmo valor no relatório e gate, métricas antigas preservadas quando existirem. |
| C20 qualidade | Gate 13/14, 99%, causas de pendência/reprovação e parada testados. |
| C20 frescor | Evento atrasado não tratado como atual; conteúdo, recepção e relógio separados. |
| C20 término | Zero amostras fora de `[T0,Tend)`, sem falso erro e com retomada/finalização verificadas. |
| Preservação | Hashes/configuração/versões e ausência de mudanças econômicas ou retraining. |
| Validação | Comandos, resultados, testes não executados e limitações. |
| Operação | Não iniciado, preparado, ativo ou bloqueado conforme evidência; processo/heartbeat/último registro quando efetivamente consultados. |

No resumo final, informar commit inicial/final, arquivos alterados, testes antes/depois, falhas pendentes e se houve alteração de agendamento ou captura. Não afirmar “coletando”, “mergeado” ou “corrigido” sem evidência correspondente. Commit/PR/merge seguem as instruções locais do projeto; não descartar branches nem alterações alheias.

**Pronto para esta tarefa** significa correções implementadas e verificadas, com incertezas explicitadas. Não significa fonte já qualificada, estratégia lucrativa, paper completo ou autorização para dinheiro real.

## 12. Base documental e anexos

Este handoff foi elaborado a partir da revisão do commit `43ee00f`, já apresentada na conversa, e dos arquivos abaixo. Não houve nova consulta à `main` durante a redação deste documento; a conferência de alterações posteriores é a primeira ação do agente.

- `research/src/binance_multistrategy/c20_capture.py`
- `research/tests/test_c20_capture.py`
- `research/docs/C20_BOOKTICKER_COLETA_PROSPECTIVA_PREREG_2026-09-29.md`
- `research/docs/BINANCE_USDM_BOOKTICKER_WS_VALIDACAO_FONTES_2026-09-29.md`
- `research/docs/NEXT_ITERATION.md`
- `research/EXPERIMENTS.jsonl`
- `research/docs/PARAMETROS_VIGENTES.md`
- `src/jev_trader/lowvol_hgb_paper.py`
- `src/jev_trader/lowvol_hgb_account.py`
- `scripts/run_c18_lowvol_hgb_paper_tick.cmd`
- `research/docs/CICLO18_PAPER_INICIALIZACAO_2026-09-29.md`

**Anexos no ZIP:**

- `evidencias/reproduce_c20_boundaries.py`: reprodução isolada/transcrita dos dois casos C20. Usa entradas artificiais, não rede; ao ser executada, grava seu JSON ao lado do script.
- `evidencias/isolated_review_results.json`: saída da reprodução anterior, não nova execução deste handoff.
- `MANIFEST.json`: hashes dos arquivos deste pacote. Não é um manifesto de dados de mercado nem evidência de execução dos testes do repositório.

As sugestões de cadência, campos e nomes de relatórios são especificações propostas para a correção, não funcionalidades já prontas. Este pacote não inclui código corrigido do robô nem modelos/datasets; não substitui o checkout atual.
