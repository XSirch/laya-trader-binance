# Exposição e trailing para a meta de 50% ao ano com queda de 10%

O usuário definiu retorno anual líquido de 50% e drawdown máximo de 10%. Nenhum candidato já validado no histórico atende a essa combinação. O primeiro teste novo mede se mudanças explícitas de exposição e distância do trailing, mantendo a mesma regra de baixa volatilidade e carry protegido, conseguem aproximá-la. É uma análise de viabilidade retrospectiva sobre dados já examinados; não é seleção em amostra nova nem promessa de retorno futuro.

Esta grade fica fixada antes dos resultados. São 48 replays, com os custos de cada cenário incorporados à trajetória inteira. Não multiplicar um retorno pronto pela exposição: taxas, tamanho das posições, funding, reentrada e acionamento dos stops mudam com o patrimônio.

```json
{"schema_version":1,"multipliers":[0.5,1,2,3,4,6],"portfolio_stops":[null,0.01,0.02,0.04],"side_costs":[0.0015,0.003],"start":"2024-01-01","end":"2026-09-26","days":999,"minimum_net_cagr_pct":50,"maximum_drawdown_pct":10}
```

O multiplicador incide sobre os pesos da regra original `blend:low_volatility30+carry30_betahedged`. A exposição bruta alvo original é de até 50% do patrimônio; a maior escala desta grade permite alvo de até 300%, exclusivamente no replay. Manter os mesmos ativos, calendário semanal, preços horários e tratamento conservador de funding do comparativo original. Não mudar a carteira prospectiva nem seus limites. Usar uma nova instância do stop em cada replay.

Carregar uma vez os dados diários e horários verificados e a extensão já disponível. Não alterar arquivos de código congelados. Verificar seus hashes e o hash deste protocolo antes e depois da execução. Os cenários com escala 1 e sem stop ou trailing de 4%, nos dois custos, devem reproduzir retorno, queda, taxas e contagem de stops do relatório original; uma divergência impede usar o resultado novo.

Reportar retorno acumulado e CAGR em colunas separadas. O CAGR usa o período exato de 999 dias e ano de 365 dias. A meta de 50% ao ano equivaleria a cerca de 203% acumulados nesse período, não a 50% acumulados. Reportar também drawdown horário, limite adverso intrahorário, exposição alvo, taxas, funding, tempo em caixa e acionamentos do stop por horário e por perna.

Classificar atendimento nominal somente quando CAGR líquido for pelo menos 50%, drawdown horário no máximo 10% e nenhuma falha de estresse de margem tiver sido registrada. Mostrar separadamente se o limite adverso intrahorário também respeita 10%, além de exigir os dois cenários de custo para qualquer destaque de robustez. Não contar esses cenários como estratégias independentes, calcular significância ou promover automaticamente o melhor resultado da grade.

O limite intrahorário combina extremos adversos simultâneos e não reconstrói uma trajetória negociável. O indicador de margem do motor também é apenas um estresse: não implementa liquidação, faixas de manutenção ou taxa de liquidação da corretora. Aberturas horárias e custo percentual presumido não comprovam liquidez para um capital específico. Insolvência ou falha de execução devem permanecer como cenário falho, sem saldo artificial.

Este experimento pode descartar a amplificação simples como caminho para a meta ou identificar uma hipótese para investigação posterior. Se algum cenário passar, ainda serão necessários análise de desenvolvimento, períodos e ativos, efeitos de seleção, execução e dados novos. Se nenhum passar, relatar isso sem redefinir a meta de 50%/10%. O JEV não é necessário para testar essa hipótese mecânica e não será chamado.
