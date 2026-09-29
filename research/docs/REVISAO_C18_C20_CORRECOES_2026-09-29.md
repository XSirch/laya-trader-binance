# Revisão das correções C18/C20 — 29/09/2026

## Escopo e preservação

Checkout verificado em `43ee00f948b87c0bedd2749b09c9639b3a514bf8`; `HEAD`, `main` e `origin/main` estavam nesse mesmo commit antes das alterações, sem commits posteriores que já resolvessem os itens. As reproduções anexas eram versões transcritas e sintéticas. Os novos testes chamam os módulos reais `jev_trader.lowvol_hgb_paper` e `binance_multistrategy.c20_capture`.

Nenhum modelo, parâmetro econômico, threshold, janela de decisão, protocolo congelado ou relatório anterior foi substituído. O banco paper C18 e os arquivos de captura C20 não foram alterados por esta revisão. O ZIP de handoff já aparecia como removido antes do trabalho; a remoção foi preservada. Os três anexos locais do usuário foram preservados sem edição.

## C18 — observação frequente, decisão semanal

- O tick pode observar e contabilizar a cada 15 minutos. A inferência e o rebalanceamento continuam restritos à janela congelada de segunda-feira, 01:00:00–01:04:59 UTC, com primeira decisão elegível em 05/10/2026 às 01:00 UTC.
- Foi acrescentado lock exclusivo entre ticks e reserva única por `feature_cutoff_ms`. Uma repetição da mesma janela não faz nova inferência nem aplica um segundo rebalanceamento. Funding continua sendo processado pela contabilização existente; o teste de oito dias confirma ausência de duplicação.
- O limite de lacuna de 65 minutos foi mantido. Sem posição, intervalos curtos e longos continuam sujeitos ao comportamento contábil existente. Com posição aberta, uma lacuna acima do limite registra `blocked_observation`, preserva a última conta reconciliada e não inventa fills ou continuidade.
- O próximo horário informado nunca precede a primeira decisão congelada.
- O XML de 15 minutos em `research/results/cycle18_lowvol_hgb_forward/paper/task_definition_observation_15m.xml` é uma configuração preparada para a tarefa existente, com `IgnoreNew`; não foi registrada nem ativada. O XML semanal original permanece intacto. As consultas ao Agendador do Windows não permitiram confirmar a tarefa instalada, portanto a cadência efetiva do host não está verificada.

### Profit factor

PF-base e PF de stress agora somam `net_pnl` monetário dos episódios completos, e o gate usa o mesmo PF-base reportado. EV e payoff continuam normalizados pelos retornos líquidos existentes. No exemplo de controle, +US$20 sobre nocional US$1.000 e −US$10 sobre US$100 dão PF monetário 2,0 e EV médio −4%; o stress usa sua própria soma monetária. Ausência de perdas é publicada como `unbounded`, mas não aprova o gate.

### Estado paper consultado sem escrita

`python -m jev_trader.lowvol_hgb_paper status` abriu o SQLite em modo somente leitura e verificou a cadeia de registros e recibos. Na verificação final, o último registro permanece `mark_only`, sequência 4, em 29/09/2026 01:34:55 UTC; posições abertas: nenhuma; operações reais: desabilitadas; candidata: não aprovada; amostra: 0 episódios. O heartbeat estava defasado em 4h31 e não há posição que acione o bloqueio por lacuna. Não foi executado `tick` durante esta tarefa.

O status identificou uma emenda append-only de código pendente no SQLite: hash de código registrado `6057ff19534372bf9bd73cb6d3c0e8e2030f191f0d9dbf24ca80fc1007098267`, hash atual `2aee1f3a4fbf61dbb5f3046e1071b239387cec0b1621214336f02d370022cbf1`. Ela será escrita pelo próximo tick normal; o status de leitura não altera o banco. Hash de configuração registrada e efetiva: `9d92835b4b70b6fe175a9fa88c40d1b2f182e8d978529e398abc7ec0c220a71f`. Hash do modelo congelado: `13c1b2dbd59a56d29ed172a5abb390159da0b6528989993b02641c1e7f9ad606`. Nenhum deles foi alterado.

## C20 — gate fixo dos primeiros 14 dias

O gate avalia os 14 dias ancorados no T0 UTC registrado, sem substituir dias ruins por dados posteriores. Cada dia precisa ter 86.400 linhas ordenadas e únicas, limites e contagem reconciliados com o manifesto e ao menos 85.536 segundos válidos (99%); pelo menos 13 dias devem passar. Defeitos de parsing, ordem, armazenamento, manifesto ou hash sem resolução levam a `review_required`; menos de 13 dias ao fechar a janela leva a `failed` e requer parada. A decisão é persistida em relatório e histórico append-only com hashes, e a mesma janela/decisão é recuperada após reinício.

O CSV histórico preserva seu schema e o significado antigo de `sample_valid`. A versão 2 do manifesto inclui um sidecar diário versionado para diagnóstico temporal; segmentos antigos sem esses dados não são requalificados retroativamente. Recepção monotônica recente, atualidade do evento `E` e do transaction time `T`, qualificação/idade da sonda e elegibilidade de execução são campos separados. Um evento atrasado recebido há 100 ms permanece inadequado temporalmente; estado desconhecido não vira fresco por padrão e nunca habilita execução/features de latência. O gate mantém a qualidade de conteúdo/recepção separada da qualificação temporal.

O fim da captura continua exclusivo: a última amostra possível é `Tend - 1 segundo`. Flush, handshake, recebimento e retomada após Tend foram cobertos; finalização idempotente não cria amostras futuras nem falso erro de regressão. O coletor não recebeu chamada de rede nesta tarefa.

### Estado local da captura

T0 permanece `2026-09-30T00:00:00Z`; Tend permanece `2027-01-20T00:00:00Z`. Na verificação, o processo Python PID 26484 estava vivo, com início em 29/09 às 01:50 no horário local. Em `research/data/c20_bookticker`, os únicos arquivos encontrados eram `runner.stdout.log` e `runner.stderr.log`, ambos com zero bytes; não havia CSV diário, manifesto ou relatório de qualidade. Portanto, a coleta de dados ainda não estava demonstrada e o processo estava antes do T0.

O processo já existia antes das alterações deste trabalho; não foi possível demonstrar que tenha carregado os novos bytes do módulo. As APIs do Windows para processo/agendador foram negadas e `schtasks /Query` não conseguiu localizar o caminho do sistema. O processo não foi parado ou reiniciado, o T0 não foi deslocado e nenhuma tarefa duplicada foi criada. Assim, os testes validam o código no disco, mas a aplicação dessas correções ao processo que aguarda T0 segue pendente.

## Arquivos modificados

- `README.md`: aponta para os critérios econômicos vigentes e mantém a meta histórica antiga identificada como histórica.
- `src/jev_trader/lowvol_hgb_paper.py`: observação/decisão, concorrência, deduplicação semanal, estado operacional, lacuna e PF monetário.
- `tests/test_c18_operational_accounting.py`: teste offline do módulo real, incluindo oito dias, funding, janela semanal, gaps, PF, lock e XML preparado.
- `research/src/binance_multistrategy/c20_capture.py`: gate C20, diagnósticos E/T/recepção/relógio e término exclusivo.
- `research/tests/test_c20_capture.py`: reproduções convertidas em regressões do módulo real, mais reinício e integridade.
- `research/docs/NEXT_ITERATION.md`: emenda de estado atual prependada; o conteúdo histórico abaixo foi preservado.
- `research/EXPERIMENTS.jsonl`: novo registro corretivo append-only.
- `research/docs/REVISAO_C18_C20_CORRECOES_2026-09-29.md`: este relatório.

## Hashes antes/depois

| Artefato | Hash anterior | Hash atual |
|---|---|---|
| `src/jev_trader/lowvol_hgb_paper.py` | `6057ff19534372bf9bd73cb6d3c0e8e2030f191f0d9dbf24ca80fc1007098267` | `2aee1f3a4fbf61dbb5f3046e1071b239387cec0b1621214336f02d370022cbf1` |
| `research/src/binance_multistrategy/c20_capture.py` | `d0756eb2ea9b23e5fe70fa65e08bd3de5674bfc0ed957ba453eb70fa66c60d70` | `b671ce97219bfad1ab70d47d6d2dc1738366cea4fea386bea42536b1c7d494ef` |
| `research/tests/test_c20_capture.py` | `66d307b5d5db13007ee77f5383ebb144a720d547d3146fa5e128ecb368a3cb6d` | `92c969d20d75b343fb29ab6fe1fc1397fb74a45f62bd1835a9ff6ac0ebc2d1da` |
| C18 configuração paper | `9d92835b4b70b6fe175a9fa88c40d1b2f182e8d978529e398abc7ec0c220a71f` | igual, sem alteração |
| C18 modelo congelado | `13c1b2dbd59a56d29ed172a5abb390159da0b6528989993b02641c1e7f9ad606` | igual, sem alteração |
| Protocolo C18 | `8cf48c4b423ffd91026e69fbf19fc68f5da05ce4de37803bfe87181bff7778b4` | igual, sem alteração |
| Protocolo C20 | `8d8a25e916136fa1c6ade6768a24349a62055ca956f98cb384758577f2383533` | igual, sem alteração |

## Validação executada

- `.\.venv-tree\Scripts\python.exe -m pytest -q tests\test_c18_operational_accounting.py` na raiz: **7 passed**.
- `.\.venv\Scripts\python.exe -m pytest -q tests\test_c20_capture.py` em `research/`: **29 passed**.
- Foram usados apenas ambientes locais existentes; não foi executado novo treino, coleta de 112 dias, chamada paga, `tick` paper ou ordem real.
- O registro append-only em `research/EXPERIMENTS.jsonl` inclui hashes dos códigos, testes, documentação e parâmetros preservados.

## Pendências e limite do que foi verificado

O código e os testes estão corrigidos no checkout, mas as rotinas em execução não foram atualizadas. Falta confirmar o Agendador e aplicar a cadência de 15 minutos à tarefa C18 existente sem duplicá-la. Falta iniciar/retomar C20 com os bytes corrigidos antes do T0; o processo pré-T0 existente não foi reiniciado conforme o limite operacional desta revisão. A emenda de código C18 no SQLite será registrada somente no próximo tick normal. Não há resultado de estratégia, paper prospectivo novo, gate C20 decidido ou autorização de ordens reais.
