# Próxima hipótese: decisões sensíveis ao custo de transação

Registrado após os resultados das três famílias preditivas. Todo o histórico já examinado permanece retrospectivo.

A hipótese é que ordenar previsões e rebalancear toda semana transforma sinais pequenos em operações sem vantagem líquida. A nova política do script comparará três alternativas em cada decisão: manter a carteira atual, adotar os pesos propostos pelo modelo ou encerrar as posições. O valor de cada alternativa será a soma dos pesos multiplicados pelas previsões semanais, menos o custo unilateral sobre a mudança de pesos em relação à posição atual. Não haverá limiar escolhido depois de observar os resultados.

A comparação usa apenas previsões disponíveis naquele momento. Posições sem previsão corrente não podem ser mantidas pela política; exposição acima do limite deve ser reduzida. Caixa é uma alternativa real, mas não será chamado de estratégia lucrativa se o sistema não demonstrar retorno positivo com atividade suficiente.

Aplicar a mesma política às 18 variantes já registradas, mantendo os modelos, períodos, semente, penalidades, sinais e regras de risco. Comparar contra os replays anteriores sem filtro de custos, sem excluir variantes perdedoras. Seleção apenas pelo desenvolvimento até 2023. Preservar custos de 0,10%, 0,15% e 0,30%, execução às 01:00 UTC e os cenários estrito e condicionado às faixas de liquidação.

Auditar em cada decisão a carteira anterior, a alternativa escolhida, previsão de vantagem, custo previsto, custo contabilizado e limite de exposição. Avaliar tempo em caixa, número de operações, turnover, retorno por janela, concentração por ativo e correção conjunta das comparações disponíveis. Uma melhora retrospectiva exige confirmação adicional; ela não elimina o risco de sobreajuste da pesquisa.

O JEV continua limitado a pontuar aderência caso necessário. A decisão e a contabilização de custos pertencem ao script. Este protocolo ainda não é uma implementação nem um resultado.
