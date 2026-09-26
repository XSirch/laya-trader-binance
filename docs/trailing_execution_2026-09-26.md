# Avaliação do trailing stop

O trailing de carteira de 4% é um candidato a controle de risco: melhorou o resultado agregado retrospectivo, mas não impediu perdas e ainda não demonstrou consistência futura. A distância foi fixada depois de comparar nove variantes em dados já estudados; esta rodada manteve essa distância e avaliou somente a sensibilidade da execução.

Na simulação de janeiro/2024 a 26 de setembro/2026, com custo de 0,15% por lado, entrada semanal às 01:00 UTC e execução do stop na abertura horária observada:

| Controle | Retorno acumulado líquido simulado | Queda máxima observada |
| --- | ---: | ---: |
| Sem trailing | +29,16% | 12,49% |
| Trailing de carteira de 4% | +37,57% | 7,43% |

O mecanismo acompanha o maior patrimônio de cada ciclo, encerra todas as posições quando detecta a queda e permite reentrada apenas em um rebalanceamento semanal posterior. Fechar as pernas conjuntamente preserva o tratamento da carteira protegida; stops individuais podem desmontar a proteção. A distância de 4% não é um limite garantido para a perda acumulada: existem saltos de preço, atraso de execução, custos e ciclos sucessivos de perda.

Foram testados 32 cenários com stop e quatro referências sem stop: entradas às 01:00/02:00 UTC, atrasos de 0/1/2/4 horas, custos de 0,15%/0,30% por lado e deslizamento adicional adverso de 0%/0,25% nas saídas por stop. Os atrasos são hipóteses de estresse, não latências medidas. O retorno agregado com trailing ficou entre +24,81% e +37,77%; a queda máxima ficou entre 7,19% e 10,73%. Todos os cenários tiveram queda máxima agregada menor que sua referência com mesmo horário e custo, mas nem todos tiveram retorno maior.

Por exemplo, com entrada às 02:00 UTC, atraso de quatro horas, custo de 0,30% e deslizamento de 0,25%, o trailing retornou +24,81%, com queda máxima de 10,10%; a referência sem stop retornou +26,42%, com queda de 11,01%.

A janela independente de agosto–setembro/2026 continuou negativa em todos os 32 cenários: entre -6,85% e -5,26%. No teste original, o trailing perdeu 6,05%, contra 4,59% sem stop. Portanto, o benefício agregado não se repetiu nessa janela recente. Stops individuais percentuais e por ATR também foram avaliados na rodada anterior; seus resultados constam em `trailing_research_2026-09-26.json`.

O caso sem atraso reproduziu exatamente retorno, queda máxima, custos e número de posições encerradas do experimento fixado, em todos os períodos. Nenhum cenário terminou com stop pendente. A evidência compacta inclui comparações com referências equivalentes e hashes do resultado completo e do código. Os testes automatizados verificam que a ordem de saída pendente persiste após recuperação e que o deslizamento prejudica tanto compras quanto vendas.

O script continua responsável pelas decisões. Esta avaliação não precisou de novas chamadas ao JEV, não consumiu o orçamento da API e não enviou ordens reais. O candidato permanece em pesquisa; a próxima confirmação precisa usar dados cronologicamente novos sem recalibrar a distância a partir de seus resultados.

Reprodução: executar `python -m jev_trader.trailing_execution` e `python scripts/snapshot_trailing_execution.py`, no ambiente do projeto com os dados locais. Evidência: `trailing_execution_2026-09-26.json`; protocolo: `trailing_execution_protocol_2026-09-26.md`.
