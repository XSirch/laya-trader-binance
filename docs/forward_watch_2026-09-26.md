# Acompanhamento local limitado a 72 horas

O supervisor executa os ciclos da série `forward_paper_v2` a partir de dados públicos e preserva as duas contas fictícias. Não possui acesso a ordens reais nem chama o JEV. O prazo máximo é de 72 horas por inicialização. O processo não instala tarefa agendada, serviço do Windows ou reinício automático após desligamento.

Ele faz uma coleta inicial de verificação e agenda tentativas a partir do minuto 1:05 de cada hora. A janela termina dez segundos antes do minuto 5. Falhas transitórias podem ser repetidas dentro dessa janela; decisões perdidas não são preenchidas depois com preços retrospectivos. O livro contábil determina se uma hora foi processada: código de saída zero, mensagens no console ou aumento do número de cotações não bastam.

Antes da primeira entrada elegível, as capturas não contam como horas de negociação. Com posições abertas, perder uma janela interrompe o supervisor para revisão. Mudança de código fixado, cadeia inconsistente ou interrupção forçada do processo filho também impede continuação automática. Locks remanescentes e dados parciais são preservados para inspeção, sem limpeza que esconda a falha.

## Operação

```powershell
powershell -NoProfile -File scripts/start_forward_watch.ps1 -Series forward_paper_v2 -Hours 72
```

O script abre um processo oculto e retorna o PID do lançador. No Windows, esse PID pode ser diferente do PID do interpretador que escreve o heartbeat. Para confirmar execução, consultar o PID em `results/forward_paper_v2/watch_status.json` e verificar no sistema operacional sua linha de comando e horário de criação. Um arquivo recente sozinho não prova que o processo está vivo.

O status contém prazo final, próximo horário, PID filho, tentativas e horas processadas ou perdidas. Cada tentativa tem logs próprios em `results/forward_paper_v2/watch_runs`. A conta continua sendo simulada: os custos e preenchimentos são premissas, não execuções confirmadas em corretora.

Verificação pontual com evidência versionável:

```powershell
powershell -NoProfile -File scripts/check_forward_watch.ps1 -Series forward_paper_v2
```

O verificador consulta o processo real, confere criação e linha de comando, exige heartbeat recente e compara o hash do supervisor. Ele não inicia processos. Na inicialização de 26/setembro às 19:35 UTC, a coleta de verificação terminou com sucesso e o supervisor entrou em espera. Nenhuma hora de negociação nem operação simulada foi contabilizada até esse checkpoint. O encerramento previsto é 29/setembro às 19:35 UTC, se não houver parada ou falha anterior. O JSON de status registra os horários exatos; esta observação não garante continuidade após o instante verificado.

Para solicitar parada:

```powershell
New-Item -ItemType File -Path results/forward_paper_v2/watch.stop
```

O supervisor observa esse arquivo e não o remove automaticamente. Um pedido de parada durante aquisição pode exigir encerramento do filho e revisão de locks/contabilidade. O vencimento do prazo também encerra o acompanhamento; não simula uma liquidação final de posições usando preços não observados. Se houver posições fictícias abertas, o estado final permanece identificado para revisão.

Este processo só opera enquanto o computador e a sessão o mantiverem em execução e houver conectividade. Não houve configuração para impedir suspensão do computador. A verificação operacional de início e a evidência de rentabilidade são distintas: a primeira pode ser confirmada agora, a segunda depende de operações e observações futuras.

Testes cobrem a janela horária, ausência de backfill, classificação pelo livro, erro após um append válido, encerramento por prazo/pedido de parada e limpeza do filho mesmo quando falha a gravação do heartbeat. O checkpoint de execução usa consulta real ao sistema operacional; não inventa horas processadas ou operações.
